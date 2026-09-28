"""Autenticação do painel administrativo.

Modo Supabase (quando SUPABASE_URL e SUPABASE_PUBLISHABLE_KEY estão definidos):
  e-mail e senha são conferidos pelo Supabase Authentication
  (POST /auth/v1/token?grant_type=password). O sistema NÃO armazena senhas; apenas
  o e-mail precisa estar autorizado em ``admin_usuario`` (ou em ADMIN_EMAILS, que
  cria automaticamente um administrador da rede no primeiro acesso).

Modo local (desenvolvimento/testes): usuário e senha com hash em ``admin_usuario``.
"""
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from flask import current_app
from sqlalchemy import func

from .. import audit
from ..extensions import db
from ..models import AdminUsuario

MSG_INCORRETO = "E-mail ou senha incorretos."
MSG_SEM_PERMISSAO = "Seu usuário não tem permissão de acesso ao painel. Procure a administração da rede."
MSG_INDISPONIVEL = "Não foi possível validar o acesso agora. Tente novamente em instantes."


@dataclass
class Resultado:
    admin: AdminUsuario | None = None
    erro: str | None = None
    falha_credencial: bool = False  # conta para o limite de tentativas


def modo_supabase() -> bool:
    cfg = current_app.config
    return bool(cfg.get("SUPABASE_URL") and cfg.get("SUPABASE_PUBLISHABLE_KEY"))


def _supabase_conferir(email: str, senha: str) -> tuple[str, str] | None:
    """Retorna (e-mail, id) confirmados pelo Supabase, None se a senha estiver incorreta.
    Lança RuntimeError se o serviço estiver indisponível."""
    cfg = current_app.config
    url = f'{cfg["SUPABASE_URL"].rstrip("/")}/auth/v1/token?grant_type=password'
    corpo = json.dumps({"email": email, "password": senha}).encode()
    req = urllib.request.Request(url, data=corpo, method="POST", headers={
        "apikey": cfg["SUPABASE_PUBLISHABLE_KEY"], "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            dados = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 422):
            return None
        raise RuntimeError(f"Supabase respondeu {e.code}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise RuntimeError("Supabase indisponível") from e
    # O token do Supabase não é guardado: a sessão do painel é própria do sistema.
    usuario = dados.get("user") or {}
    email_ok = (usuario.get("email") or "").lower()
    return (email_ok, usuario.get("id") or "") if email_ok else None


def _admin_por_email(email: str) -> AdminUsuario | None:
    adm = AdminUsuario.query.filter(func.lower(AdminUsuario.email) == email).first()
    if adm is None and email in current_app.config["ADMIN_EMAILS"]:
        # Primeiro acesso de um administrador da rede definido em ADMIN_EMAILS.
        adm = AdminUsuario(nome=email.split("@")[0], login=email[:60], email=email, escola_id=None,
                           perfil="ADMIN")
        db.session.add(adm)
        db.session.flush()
        audit.registrar(audit.Acao.ADMIN_ACAO, "SISTEMA", alvo=f"admin:{adm.id}",
                        detalhes={"acao": "criar_admin_via_admin_emails"}, commit=False)
        db.session.commit()
    return adm


def autenticar(identificador: str, senha: str) -> Resultado:
    identificador = (identificador or "").strip()
    if not identificador or not senha:
        return Resultado(erro=MSG_INCORRETO, falha_credencial=True)

    if modo_supabase():
        email = identificador.lower()
        try:
            confirmado = _supabase_conferir(email, senha)
        except RuntimeError:
            current_app.logger.exception("Falha ao consultar o Supabase Auth")
            return Resultado(erro=MSG_INDISPONIVEL)
        if not confirmado:
            return Resultado(erro=MSG_INCORRETO, falha_credencial=True)
        email_ok, uid = confirmado
        adm = _admin_por_email(email_ok)
        if adm is None or not adm.ativo:
            return Resultado(erro=MSG_SEM_PERMISSAO, falha_credencial=True)
        if uid and adm.supabase_id != uid:
            adm.supabase_id = uid
            db.session.commit()
        return Resultado(admin=adm)

    adm = AdminUsuario.query.filter_by(login=identificador, ativo=True).first()
    if adm and adm.conferir_senha(senha):
        return Resultado(admin=adm)
    return Resultado(erro="Usuário ou senha incorretos.", falha_credencial=True)
