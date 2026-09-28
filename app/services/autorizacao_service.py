"""Regras de negócio do registro de autorizações.

Todas as validações são refeitas aqui, independentemente do que o frontend
enviou: sessão, vínculo, participação no passeio, prazo e situação atual.
A gravação é atômica: ou todas as respostas da operação são salvas, ou nenhuma.
O PDF só é gerado DEPOIS do commit.
"""
import secrets
from dataclasses import dataclass

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from .. import audit
from ..extensions import db
from ..formatacao import data_br, hora_br, utc_para_local
from ..models import (Autorizacao, AutorizacaoHistorico, Documento, DocumentoItem, Passeio,
                      PasseioAluno, ProtocoloSequencia, Situacao, utcnow)
from ..security import ip_auditoria, ua_auditoria
from . import documento_service
from . import config_service
from .passeio_service import alunos_do_responsavel, estado_passeio, pode_alterar_resposta

MSG_ERRO_GERAL = "Não foi possível registrar a autorização. Nenhuma alteração foi realizada. Tente novamente."


class ErroNegocio(Exception):
    def __init__(self, mensagem: str, status: int = 400):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status = status


@dataclass
class ResultadoRegistro:
    documento: Documento


def _proximo_protocolo(ano: int) -> str:
    seq = db.session.query(ProtocoloSequencia).filter_by(ano=ano).with_for_update().first()
    if seq is None:
        seq = ProtocoloSequencia(ano=ano, ultimo=0)
        db.session.add(seq)
    seq.ultimo += 1
    return f"AUT-{ano}-{seq.ultimo:06d}"


def _novo_codigo_validacao() -> str:
    while True:
        bruto = secrets.token_hex(6).upper()  # 48 bits
        codigo = f"{bruto[0:4]}-{bruto[4:8]}-{bruto[8:12]}"
        if not Documento.query.filter_by(codigo_validacao=codigo).first():
            return codigo


def _snapshot(passeio: Passeio, resp, pares, registro_utc, codigo: str) -> dict:
    local = utc_para_local(registro_utc)
    return {
        "url_validacao": documento_service.url_validacao(codigo),
        "instituicao": config_service.obter("instituicao_nome"),
        "brasao": config_service.obter("brasao"),
        "responsavel": {"nome": resp.nome, "cpf_mascarado": resp.cpf_mascarado},
        "passeio": {
            "nome": passeio.nome, "destino": passeio.destino, "data": data_br(passeio.data),
            "hora_saida": hora_br(passeio.hora_saida), "hora_retorno": hora_br(passeio.hora_retorno),
            "local_saida": passeio.local_saida, "transporte": passeio.transporte or "",
        },
        "alunos": [{
            "nome": aluno.nome, "turma": f"{aluno.turma.ano} - {aluno.turma.nome}",
            "escola": aluno.escola.nome, "matricula": aluno.matricula, "situacao": situacao,
        } for aluno, situacao in pares],
        "declaracao": passeio.texto_declaracao,
        "versao_texto": passeio.versao_texto,
        "registro": {"data": local.strftime("%d/%m/%Y"), "hora": local.strftime("%H:%M:%S")},
    }


def registrar_respostas(resp, passeio_public_id: str, respostas: list, declaracao_aceita: bool,
                        origem: str = "WEB_RESPONSAVEL") -> ResultadoRegistro:
    # 1) Declaração expressa
    if declaracao_aceita is not True:
        raise ErroNegocio("É necessário confirmar a declaração de responsável legal.")

    # 2) Passeio e prazo
    passeio = Passeio.query.filter_by(public_id=passeio_public_id, ativo=True).first()
    if passeio is None:
        raise ErroNegocio("Passeio não encontrado.", 404)
    estado = estado_passeio(passeio)
    if not estado.aberto:
        raise ErroNegocio("O prazo para registrar ou alterar autorizações deste passeio foi encerrado.", 409)

    # 3) Estrutura das respostas
    if not isinstance(respostas, list) or not respostas:
        raise ErroNegocio("Selecione pelo menos um aluno.")
    if len(respostas) > 30:
        raise ErroNegocio("Quantidade de respostas inválida.")
    vistos, pedidos = set(), []
    for r in respostas:
        if not isinstance(r, dict):
            raise ErroNegocio("Requisição inválida.")
        aluno_pid, situacao = str(r.get("aluno_id", "")), r.get("situacao")
        if situacao not in Situacao.PERMITIDAS_RESPONSAVEL:
            raise ErroNegocio("Situação inválida.")
        if aluno_pid in vistos:
            raise ErroNegocio("Aluno repetido na requisição.")
        vistos.add(aluno_pid)
        pedidos.append((aluno_pid, situacao))

    # 4) Vínculo e participação — nunca confiar no ID vindo do frontend
    meus = {a.public_id: a for a in alunos_do_responsavel(resp)}
    pares = []
    for aluno_pid, situacao in pedidos:
        aluno = meus.get(aluno_pid)
        participa = aluno and PasseioAluno.query.filter_by(passeio_id=passeio.id, aluno_id=aluno.id).first()
        if not participa:
            # Mensagem genérica: não revela se o aluno existe.
            raise ErroNegocio("Aluno não encontrado entre os seus vinculados para este passeio.", 403)
        pares.append((aluno, situacao))

    # 5) Situação atual (sem duplicidade; alteração só se permitida)
    atuais = {a.aluno_id: a for a in Autorizacao.query.filter(
        Autorizacao.passeio_id == passeio.id,
        Autorizacao.aluno_id.in_([a.id for a, _ in pares]))}
    for aluno, situacao in pares:
        aut = atuais.get(aluno.id)
        sem_resposta = aut is None or aut.situacao == Situacao.CANCELADO
        if situacao == Situacao.CANCELADO:
            if sem_resposta:
                raise ErroNegocio(f"Não há resposta de {aluno.nome} para cancelar.", 409)
        elif sem_resposta:
            continue
        elif aut.situacao == situacao:
            raise ErroNegocio(f"A resposta para {aluno.nome} já está registrada.", 409)
        if not sem_resposta:
            permitido, motivo = pode_alterar_resposta(passeio, aut)
            if not permitido:
                raise ErroNegocio(f"{aluno.nome}: {motivo}", 409)

    # 6) Gravação atômica
    agora = utcnow()
    ip, ua = ip_auditoria(), ua_auditoria()
    try:
        codigo = _novo_codigo_validacao()
        documento = Documento(
            protocolo=_proximo_protocolo(utc_para_local(agora).year),
            codigo_validacao=codigo,
            passeio_id=passeio.id, responsavel_id=resp.id, data_registro=agora,
            versao_texto=passeio.versao_texto, conteudo=_snapshot(passeio, resp, pares, agora, codigo),
        )
        db.session.add(documento)
        db.session.flush()

        for aluno, situacao in pares:
            aut = atuais.get(aluno.id)
            anterior = aut.situacao if aut else None
            if aut is None:
                aut = Autorizacao(passeio_id=passeio.id, aluno_id=aluno.id)
                db.session.add(aut)
            aut.responsavel_id = resp.id
            aut.situacao = situacao
            aut.data_hora = agora
            aut.versao_texto = passeio.versao_texto
            aut.origem = origem
            aut.ip, aut.user_agent = ip, ua
            aut.documento_id = documento.id
            db.session.flush()

            db.session.add(AutorizacaoHistorico(
                autorizacao_id=aut.id, situacao_anterior=anterior, situacao_nova=situacao,
                data_hora=agora, responsavel_id=resp.id, documento_id=documento.id, ip=ip, user_agent=ua))
            db.session.add(DocumentoItem(documento_id=documento.id, autorizacao_id=aut.id, situacao=situacao))

            if situacao == Situacao.CANCELADO:
                acao = audit.Acao.CANCELAMENTO
            elif anterior in Situacao.RESPOSTAS_RESPONSAVEL:
                acao = audit.Acao.ALTERACAO
            else:
                acao = audit.Acao.AUTORIZACAO if situacao == Situacao.AUTORIZADO else audit.Acao.NEGATIVA
            audit.registrar(acao, "RESPONSAVEL", resp.id, alvo=f"autorizacao:{aut.public_id}",
                            detalhes={"protocolo": documento.protocolo, "de": anterior, "para": situacao},
                            commit=False)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha ao registrar autorizações")
        raise ErroNegocio(MSG_ERRO_GERAL, 500)

    # 7) PDF somente após o commit. Se falhar, poderá ser regenerado no download.
    try:
        documento_service.gerar_e_salvar(documento)
    except Exception:  # noqa: BLE001
        current_app.logger.exception("Falha ao gerar PDF %s", documento.protocolo)

    return ResultadoRegistro(documento)


LIMITE_REVOGACAO_LOTE = 2000


def _validar_motivo(motivo: str) -> str:
    motivo = (motivo or "").strip()[:300]
    if len(motivo) < 5:
        raise ErroNegocio("Informe o motivo da revogação (mínimo de 5 caracteres).")
    return motivo


def revogar_varias(admin, autorizacoes: list, motivo: str) -> int:
    """Revoga (situação CANCELADO) várias autorizações com o MESMO motivo, em uma
    única transação. Cada aluno recebe seu próprio registro de histórico e de auditoria.
    Retorna a quantidade revogada. Autorizações já canceladas são ignoradas."""
    motivo = _validar_motivo(motivo)
    alvo = [a for a in autorizacoes if a.situacao in Situacao.RESPOSTAS_RESPONSAVEL]
    if not alvo:
        raise ErroNegocio("Nenhuma autorização revogável foi selecionada.")
    if len(alvo) > LIMITE_REVOGACAO_LOTE:
        raise ErroNegocio(f"Selecione no máximo {LIMITE_REVOGACAO_LOTE} autorizações por operação.")
    for a in alvo:
        if admin.escola_id and a.aluno.escola_id != admin.escola_id:
            raise ErroNegocio("Há autorizações fora da sua unidade escolar na seleção.", 403)
    agora, ip, ua = utcnow(), ip_auditoria(), ua_auditoria()
    lote = secrets.token_hex(4) if len(alvo) > 1 else None
    try:
        for a in alvo:
            anterior = a.situacao
            a.situacao = Situacao.CANCELADO
            a.data_hora = agora
            db.session.add(AutorizacaoHistorico(
                autorizacao_id=a.id, situacao_anterior=anterior, situacao_nova=Situacao.CANCELADO,
                data_hora=agora, admin_id=admin.id, motivo=motivo, ip=ip, user_agent=ua))
            detalhes = {"acao": "revogar", "de": anterior, "motivo": motivo}
            if lote:
                detalhes["lote"] = lote
            audit.registrar(audit.Acao.ADMIN_ACAO, "ADMIN", admin.id, alvo=f"autorizacao:{a.public_id}",
                            detalhes=detalhes, commit=False)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Falha na revogação em lote")
        raise ErroNegocio("Não foi possível revogar. Nenhuma alteração foi realizada. Tente novamente.", 500)
    return len(alvo)


def cancelar_pela_escola(admin, autorizacao: Autorizacao, motivo: str) -> None:
    if autorizacao.situacao == Situacao.CANCELADO:
        raise ErroNegocio("Esta autorização já está revogada/cancelada.", 409)
    revogar_varias(admin, [autorizacao], motivo)


def status_documento(doc: Documento) -> tuple[bool, str]:
    """(vigente, rótulo). Um documento autêntico pode ter sido substituído
    por uma resposta posterior — nesse caso não comprova mais a situação atual."""
    for item in doc.itens:
        aut = item.autorizacao
        if aut.documento_id != doc.id or aut.situacao != item.situacao:
            return False, "DOCUMENTO SUBSTITUÍDO"
    if all(i.situacao == Situacao.CANCELADO for i in doc.itens):
        return True, "CANCELAMENTO REGISTRADO"
    todos_autorizados = all(i.situacao == Situacao.AUTORIZADO for i in doc.itens)
    return True, "AUTORIZAÇÃO VÁLIDA" if todos_autorizados else "REGISTRO VÁLIDO"
