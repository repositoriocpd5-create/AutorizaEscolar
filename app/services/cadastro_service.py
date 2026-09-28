"""Cadastro de responsáveis (CPF) e alunos pelo painel administrativo.

Regras:
- CPF validado (dígitos verificadores) e único; guardado apenas como HMAC + 2 dígitos finais.
- Data de nascimento do responsável (segundo fator) guardada apenas como HMAC.
- Usuário de escola só vincula/cadastra alunos da própria escola e só enxerga
  responsáveis ligados a alunos dela (ou ainda sem filhos).
- Responsável com autorizações registradas não é apagado (comprovantes e histórico
  precisam ser preservados): é desativado e perde os vínculos.
"""
import re
from datetime import date, datetime

from sqlalchemy import func, or_

from .. import audit
from ..extensions import db
from ..models import (Aluno, Autorizacao, AutorizacaoHistorico, Documento, Escola, Passeio, Responsavel,
                      ResponsavelAluno, Turma)
from ..security import cpf_aceito, hash_cpf, hash_segredo, normalizar_cpf
from .passeio_service import sincronizar_participantes

TIPOS_VINCULO = ["Mãe", "Pai", "Avó", "Avô", "Tutor(a)", "Responsável", "Outro"]


class ErroCadastro(ValueError):
    pass


# ---------------------------------------------------------------------------
# Escopo
# ---------------------------------------------------------------------------
def responsaveis_visiveis(adm):
    q = Responsavel.query
    if adm.escola_id:
        com_aluno_da_escola = (db.session.query(ResponsavelAluno.responsavel_id).join(Aluno)
                               .filter(Aluno.escola_id == adm.escola_id))
        sem_vinculo = ~Responsavel.id.in_(db.session.query(ResponsavelAluno.responsavel_id))
        q = q.filter(or_(Responsavel.id.in_(com_aluno_da_escola), sem_vinculo))
    return q


def responsavel_no_escopo(adm, public_id) -> Responsavel | None:
    return responsaveis_visiveis(adm).filter(Responsavel.public_id == public_id).first()


def alunos_visiveis(adm):
    q = Aluno.query
    if adm.escola_id:
        q = q.filter(Aluno.escola_id == adm.escola_id)
    return q


def pesquisar(adm, termo: str, escola_id: str = ""):
    q = responsaveis_visiveis(adm)
    termo = (termo or "").strip()
    digitos = normalizar_cpf(termo)
    if len(digitos) == 11:
        q = q.filter(Responsavel.cpf_hash == hash_cpf(digitos))
    elif termo:
        like = f"%{termo.lower()}%"
        filhos = (db.session.query(ResponsavelAluno.responsavel_id).join(Aluno)
                  .filter(or_(func.lower(Aluno.nome).like(like), Aluno.matricula == termo)))
        q = q.filter(or_(func.lower(Responsavel.nome).like(like), Responsavel.id.in_(filhos)))
    if escola_id.isdigit():
        q = q.filter(Responsavel.id.in_(db.session.query(ResponsavelAluno.responsavel_id).join(Aluno)
                                        .filter(Aluno.escola_id == int(escola_id))))
    return q.order_by(Responsavel.nome)


# ---------------------------------------------------------------------------
# Responsável
# ---------------------------------------------------------------------------
def _data(valor: str) -> date | None:
    valor = (valor or "").strip()
    if not valor:
        return None
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date()
    except ValueError:
        raise ErroCadastro("Data inválida.")


def salvar_responsavel(adm, resp: Responsavel | None, form) -> Responsavel:
    novo = resp is None
    nome = (form.get("nome") or "").strip()[:160]
    if len(nome) < 3:
        raise ErroCadastro("Informe o nome completo do responsável.")
    cpf = normalizar_cpf(form.get("cpf", ""))
    if novo and not cpf:
        raise ErroCadastro("Informe o CPF.")
    if cpf:
        if not cpf_aceito(cpf):
            raise ErroCadastro("CPF inválido. Verifique os números informados.")
        existente = Responsavel.query.filter_by(cpf_hash=hash_cpf(cpf)).first()
        if existente and (novo or existente.id != resp.id):
            raise ErroCadastro("Este CPF já está cadastrado para outro responsável.")
    email = (form.get("email") or "").strip()[:160]
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise ErroCadastro("E-mail inválido.")
    nascimento = _data(form.get("data_nascimento"))
    if nascimento and not (1900 <= nascimento.year <= date.today().year - 14):
        raise ErroCadastro("Data de nascimento do responsável inválida.")

    if novo:
        resp = Responsavel(nome=nome, cpf_hash=hash_cpf(cpf), cpf_final=cpf[-2:])
        db.session.add(resp)
    else:
        resp.nome = nome
        if cpf:
            resp.cpf_hash, resp.cpf_final = hash_cpf(cpf), cpf[-2:]
    resp.email = email or None
    resp.telefone = re.sub(r"[^\d()+\- ]", "", form.get("telefone", ""))[:30] or None
    if nascimento:
        resp.data_nascimento_hash = hash_segredo(nascimento.isoformat())
    elif form.get("limpar_nascimento") == "1":
        resp.data_nascimento_hash = None
    resp.ativo = form.get("ativo", "1") == "1"
    db.session.flush()
    audit.registrar(audit.Acao.ADMIN_ACAO, "ADMIN", adm.id, alvo=f"responsavel:{resp.public_id}",
                    detalhes={"acao": "criar_responsavel" if novo else "editar_responsavel",
                              "cpf_alterado": bool(cpf and not novo)}, commit=False)
    return resp


def possui_historico(resp: Responsavel) -> bool:
    return any(q.first() is not None for q in (
        Autorizacao.query.filter_by(responsavel_id=resp.id),
        AutorizacaoHistorico.query.filter_by(responsavel_id=resp.id),
        Documento.query.filter_by(responsavel_id=resp.id),
    ))


def excluir_responsavel(adm, resp: Responsavel) -> str:
    """Exclui de fato se não houver histórico; senão desativa e remove vínculos."""
    if adm.escola_id and any(v.aluno.escola_id != adm.escola_id for v in resp.vinculos):
        raise ErroCadastro("Este responsável tem filhos em outra unidade escolar; peça à rede para excluí-lo.")
    alvo = f"responsavel:{resp.public_id}"
    ResponsavelAluno.query.filter_by(responsavel_id=resp.id).delete()
    if possui_historico(resp):
        resp.ativo = False
        audit.registrar(audit.Acao.ADMIN_ACAO, "ADMIN", adm.id, alvo=alvo,
                        detalhes={"acao": "desativar_responsavel_com_historico"}, commit=False)
        return "desativado"
    db.session.delete(resp)
    audit.registrar(audit.Acao.ADMIN_ACAO, "ADMIN", adm.id, alvo=alvo,
                    detalhes={"acao": "excluir_responsavel"}, commit=False)
    return "excluido"


# ---------------------------------------------------------------------------
# Alunos e vínculos
# ---------------------------------------------------------------------------
def _sincronizar_passeios_da_turma(turma_id: int) -> None:
    for p in Passeio.query.filter(Passeio.turmas.any(Turma.id == turma_id)).all():
        sincronizar_participantes(p)


def salvar_aluno(adm, aluno: Aluno | None, form) -> Aluno:
    novo = aluno is None
    nome = (form.get("aluno_nome") or "").strip()[:160]
    matricula = re.sub(r"\s", "", form.get("matricula") or "")[:30]
    if len(nome) < 3:
        raise ErroCadastro("Informe o nome do aluno.")
    if not matricula:
        raise ErroCadastro("Informe a matrícula do aluno.")
    outra = Aluno.query.filter_by(matricula=matricula).first()
    if outra and (novo or outra.id != aluno.id):
        raise ErroCadastro(f"A matrícula {matricula} já pertence a outro aluno.")
    turma_id = form.get("turma_id", "")
    turma = db.session.get(Turma, int(turma_id)) if turma_id.isdigit() else None
    if turma is None:
        raise ErroCadastro("Selecione a escola e a turma do aluno.")
    if adm.escola_id and turma.escola_id != adm.escola_id:
        raise ErroCadastro("Você só pode cadastrar alunos da sua unidade escolar.")
    sexo = form.get("sexo") if form.get("sexo") in ("M", "F") else None
    nascimento = _data(form.get("aluno_nascimento"))
    turma_anterior = None if novo else aluno.turma_id
    if novo:
        aluno = Aluno(nome=nome, matricula=matricula, escola_id=turma.escola_id, turma_id=turma.id)
        db.session.add(aluno)
    aluno.nome, aluno.matricula, aluno.sexo, aluno.data_nascimento = nome, matricula, sexo, nascimento
    aluno.escola_id, aluno.turma_id = turma.escola_id, turma.id
    if "aluno_ativo" in form or not novo:
        aluno.ativo = form.get("aluno_ativo", "1") == "1"
    db.session.flush()
    # Aluno novo (ou que mudou de turma) entra nos passeios dessa turma.
    _sincronizar_passeios_da_turma(turma.id)
    if turma_anterior and turma_anterior != turma.id:
        _sincronizar_passeios_da_turma(turma_anterior)
    audit.registrar(audit.Acao.ADMIN_ACAO, "ADMIN", adm.id, alvo=f"aluno:{aluno.public_id}",
                    detalhes={"acao": "criar_aluno" if novo else "editar_aluno"}, commit=False)
    return aluno


def vincular(adm, resp: Responsavel, aluno: Aluno, tipo: str, legal: bool) -> None:
    if adm.escola_id and aluno.escola_id != adm.escola_id:
        raise ErroCadastro("Você só pode vincular alunos da sua unidade escolar.")
    tipo = tipo if tipo in TIPOS_VINCULO else "Responsável"
    v = ResponsavelAluno.query.filter_by(responsavel_id=resp.id, aluno_id=aluno.id).first()
    if v is None:
        v = ResponsavelAluno(responsavel_id=resp.id, aluno_id=aluno.id)
        db.session.add(v)
    v.tipo_vinculo, v.responsavel_legal, v.ativo = tipo, legal, True
    audit.registrar(audit.Acao.ADMIN_ACAO, "ADMIN", adm.id, alvo=f"responsavel:{resp.public_id}",
                    detalhes={"acao": "vincular_aluno", "aluno": aluno.public_id, "tipo": tipo,
                              "pode_autorizar": legal}, commit=False)


def desvincular(adm, resp: Responsavel, vinculo_id: int) -> None:
    v = ResponsavelAluno.query.filter_by(id=vinculo_id, responsavel_id=resp.id).first()
    if v is None:
        raise ErroCadastro("Vínculo não encontrado.")
    if adm.escola_id and v.aluno.escola_id != adm.escola_id:
        raise ErroCadastro("Você só pode alterar vínculos de alunos da sua unidade escolar.")
    audit.registrar(audit.Acao.ADMIN_ACAO, "ADMIN", adm.id, alvo=f"responsavel:{resp.public_id}",
                    detalhes={"acao": "desvincular_aluno", "aluno": v.aluno.public_id}, commit=False)
    db.session.delete(v)


def aluno_por_referencia(adm, ref: str) -> Aluno | None:
    """Localiza aluno pela matrícula (ou 'matrícula — nome' vindo da lista de sugestões)."""
    matricula = (ref or "").split("—")[0].strip()
    if not matricula:
        return None
    return alunos_visiveis(adm).filter(Aluno.matricula == matricula).first()


def turmas_do_escopo(adm):
    q = Turma.query.join(Escola)
    if adm.escola_id:
        q = q.filter(Turma.escola_id == adm.escola_id)
    return q.order_by(Escola.nome, Turma.ano, Turma.nome).all()


def escolas_do_escopo(adm):
    q = Escola.query
    if adm.escola_id:
        q = q.filter_by(id=adm.escola_id)
    return q.order_by(Escola.nome).all()

