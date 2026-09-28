"""Registro de eventos de auditoria. Nunca registre senhas, tokens ou CPF em claro."""
from .extensions import db
from .models import AuditLog
from .security import ip_auditoria, ua_auditoria


class Acao:
    LOGIN_RESPONSAVEL = "LOGIN_RESPONSAVEL"
    LOGIN_FALHA = "LOGIN_FALHA"
    LOGIN_BLOQUEADO = "LOGIN_BLOQUEADO"
    LOGOUT = "LOGOUT"
    CONSULTA_ALUNOS = "CONSULTA_ALUNOS"
    AUTORIZACAO = "AUTORIZACAO"
    NEGATIVA = "NEGATIVA"
    ALTERACAO = "ALTERACAO"
    CANCELAMENTO = "CANCELAMENTO"
    PDF_GERADO = "PDF_GERADO"
    PDF_DOWNLOAD = "PDF_DOWNLOAD"
    VALIDACAO_DOCUMENTO = "VALIDACAO_DOCUMENTO"
    ADMIN_LOGIN = "ADMIN_LOGIN"
    ADMIN_LOGIN_FALHA = "ADMIN_LOGIN_FALHA"
    ADMIN_ACAO = "ADMIN_ACAO"
    ADMIN_EXPORTACAO = "ADMIN_EXPORTACAO"


def registrar(acao: str, ator_tipo: str, ator_id=None, alvo=None, detalhes=None, commit=True) -> None:
    db.session.add(AuditLog(
        acao=acao, ator_tipo=ator_tipo, ator_id=ator_id, alvo=alvo,
        detalhes=detalhes or None, ip=ip_auditoria(), user_agent=ua_auditoria(),
    ))
    if commit:
        db.session.commit()
