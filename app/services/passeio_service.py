"""Consultas de passeios e alunos SEMPRE filtradas pelo vínculo do responsável."""
from dataclasses import dataclass
from datetime import timedelta

from ..extensions import db
from ..formatacao import agora_local
from ..models import (Aluno, Autorizacao, Passeio, PasseioAluno, ResponsavelAluno, Situacao, Turma)


def alunos_do_responsavel(resp) -> list[Aluno]:
    """Alunos ativos com vínculo ativo de responsável legal. Única fonte de verdade."""
    return (Aluno.query.join(ResponsavelAluno)
            .filter(ResponsavelAluno.responsavel_id == resp.id,
                    ResponsavelAluno.ativo.is_(True),
                    ResponsavelAluno.responsavel_legal.is_(True),
                    Aluno.ativo.is_(True))
            .order_by(Aluno.nome).all())


def passeios_do_responsavel(resp) -> list[Passeio]:
    ids = [a.id for a in alunos_do_responsavel(resp)]
    if not ids:
        return []
    return (Passeio.query.join(PasseioAluno)
            .filter(Passeio.ativo.is_(True), PasseioAluno.aluno_id.in_(ids))
            .distinct().order_by(Passeio.data.desc()).all())


def passeio_por_public_id(public_id: str, somente_ativo=True) -> Passeio | None:
    q = Passeio.query.filter_by(public_id=public_id)
    if somente_ativo:
        q = q.filter_by(ativo=True)
    return q.first()


@dataclass
class EstadoPasseio:
    encerrado: bool          # data já passou ou passeio inativo
    prazo_encerrado: bool    # após data_limite
    aberto: bool             # aceita novas respostas
    permite_alteracao: bool  # aceita alterar respostas existentes


def estado_passeio(p: Passeio) -> EstadoPasseio:
    agora = agora_local()
    encerrado = (not p.ativo) or agora.date() > p.data
    prazo = agora > p.data_limite
    aberto = not encerrado and not prazo
    return EstadoPasseio(encerrado, prazo, aberto, aberto and p.permite_alteracao)


def limite_alteracao(p: Passeio, aut: Autorizacao):
    """Momento (horário local) até o qual o responsável pode alterar/cancelar a resposta."""
    if p.prazo_alteracao_horas:
        from ..formatacao import utc_para_local
        janela = utc_para_local(aut.data_hora) + timedelta(hours=p.prazo_alteracao_horas)
        return min(janela, p.data_limite)
    return p.data_limite


def pode_alterar_resposta(p: Passeio, aut: Autorizacao) -> tuple[bool, str | None]:
    """(permitido, motivo_se_negado) para alterar ou cancelar uma resposta existente."""
    estado = estado_passeio(p)
    if not estado.aberto:
        return False, "O prazo para alteração desta autorização foi encerrado."
    if not p.permite_alteracao:
        return False, "Este passeio não permite alteração da resposta."
    if agora_local() > limite_alteracao(p, aut):
        return False, "O prazo para alteração desta autorização foi encerrado."
    return True, None


def cancelado_pela_escola(aut: Autorizacao) -> bool:
    ultimo = aut.historico[-1] if aut.historico else None
    return bool(ultimo and ultimo.admin_id)


@dataclass
class ItemAluno:
    aluno: Aluno
    autorizacao: Autorizacao | None
    situacao: str
    pode_responder: bool
    pode_alterar: bool
    aviso: str | None
    respondido_por_outro: bool


def itens_do_responsavel(p: Passeio, resp) -> list[ItemAluno]:
    alunos = [a for a in alunos_do_responsavel(resp)
              if PasseioAluno.query.filter_by(passeio_id=p.id, aluno_id=a.id).first()]
    estado = estado_passeio(p)
    auts = {a.aluno_id: a for a in Autorizacao.query.filter(
        Autorizacao.passeio_id == p.id, Autorizacao.aluno_id.in_([a.id for a in alunos] or [0]))}
    itens = []
    for aluno in alunos:
        aut = auts.get(aluno.id)
        aviso = None
        if aut is None or aut.situacao == Situacao.CANCELADO:
            situacao = aut.situacao if aut else Situacao.AGUARDANDO
            pode_responder = estado.aberto
            pode_alterar = False
            if estado.encerrado and aut is None:
                situacao = Situacao.ENCERRADO
            elif not estado.aberto:
                aviso = "O prazo para registrar a autorização foi encerrado."
            elif aut is not None and cancelado_pela_escola(aut):
                aviso = "A autorização anterior foi revogada pela unidade escolar. Você pode responder novamente."
            elif aut is not None:
                aviso = "A resposta anterior foi cancelada. Você pode responder novamente."
        else:
            situacao = aut.situacao
            pode_responder = False
            pode_alterar, aviso = pode_alterar_resposta(p, aut)
            if pode_alterar and p.prazo_alteracao_horas:
                aviso = (f"Você pode alterar ou cancelar esta resposta até "
                         f"{limite_alteracao(p, aut).strftime('%d/%m/%Y às %H:%M')}.")
        itens.append(ItemAluno(aluno, aut, situacao, pode_responder, pode_alterar, aviso,
                               bool(aut and aut.responsavel_id != resp.id)))
    return itens


def sincronizar_participantes(p: Passeio) -> None:
    """Inclui os alunos ativos das turmas participantes. Remove apenas quem
    não possui resposta registrada (histórico nunca é apagado)."""
    turma_ids = [t.id for t in p.turmas]
    desejados = {a.id for a in Aluno.query.filter(Aluno.turma_id.in_(turma_ids or [0]), Aluno.ativo.is_(True))}
    atuais = {pa.aluno_id: pa for pa in PasseioAluno.query.filter_by(passeio_id=p.id)}
    com_resposta = {a.aluno_id for a in Autorizacao.query.filter_by(passeio_id=p.id)}
    for aluno_id in desejados - atuais.keys():
        db.session.add(PasseioAluno(passeio_id=p.id, aluno_id=aluno_id))
    for aluno_id, pa in atuais.items():
        if aluno_id not in desejados and aluno_id not in com_resposta:
            db.session.delete(pa)


def turmas_por_escola(escola_id=None):
    q = Turma.query
    if escola_id:
        q = q.filter_by(escola_id=escola_id)
    return q.order_by(Turma.escola_id, Turma.ano, Turma.nome).all()
