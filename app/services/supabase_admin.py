"""Chamadas administrativas ao Supabase Authentication (GoTrue).

Criar/convidar usuários, definir senha e bloquear exigem a CHAVE SECRETA
(SUPABASE_SECRET_KEY, formato ``sb_secret_...`` ou a antiga ``service_role``).
Ela fica SOMENTE no servidor (variável de ambiente) e nunca vai para o navegador.
O envio do link de redefinição de senha usa apenas a chave publicável.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from flask import current_app, url_for

BANIMENTO = "876000h"  # ~100 anos: bloqueio até ser reativado


class ErroSupabase(Exception):
    pass


def disponivel() -> bool:
    """Operações administrativas (criar, convidar, senha, bloquear) habilitadas?"""
    cfg = current_app.config
    return bool(cfg.get("SUPABASE_URL") and cfg.get("SUPABASE_SECRET_KEY"))


def _cabecalhos(chave: str) -> dict:
    h = {"apikey": chave, "Content-Type": "application/json"}
    # Chaves antigas (JWT service_role) também vão no Authorization;
    # as novas (sb_secret_...) só no apikey.
    if not chave.startswith("sb_"):
        h["Authorization"] = f"Bearer {chave}"
    return h


def _chamar(metodo: str, caminho: str, corpo: dict | None = None, secreta: bool = True) -> dict:
    cfg = current_app.config
    chave = cfg["SUPABASE_SECRET_KEY"] if secreta else cfg["SUPABASE_PUBLISHABLE_KEY"]
    if not chave:
        raise ErroSupabase("Chave do Supabase não configurada.")
    req = urllib.request.Request(
        f'{cfg["SUPABASE_URL"].rstrip("/")}{caminho}', method=metodo, headers=_cabecalhos(chave),
        data=json.dumps(corpo).encode() if corpo is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            bruto = resp.read().decode() or "{}"
            return json.loads(bruto)
    except urllib.error.HTTPError as e:
        try:
            detalhe = json.loads(e.read().decode() or "{}")
        except (ValueError, OSError):
            detalhe = {}
        msg = detalhe.get("msg") or detalhe.get("message") or detalhe.get("error_description") or ""
        codigo = detalhe.get("error_code") or detalhe.get("code") or ""
        current_app.logger.warning("Supabase %s %s -> %s %s", metodo, caminho, e.code, codigo)
        if e.code == 422 and ("already" in msg.lower() or codigo == "email_exists"):
            raise ErroSupabase("Já existe um usuário com este e-mail no Supabase.") from e
        if e.code in (401, 403):
            raise ErroSupabase("Chave secreta do Supabase inválida ou sem permissão.") from e
        if e.code == 429:
            raise ErroSupabase("Limite de envio de e-mails do Supabase atingido. Tente mais tarde.") from e
        raise ErroSupabase(f"O Supabase recusou a operação ({e.code}). {msg}".strip()) from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise ErroSupabase("Não foi possível conectar ao Supabase.") from e


def url_definir_senha() -> str:
    base = current_app.config.get("PUBLIC_BASE_URL")
    caminho = url_for("admin.definir_senha")
    return f"{base}{caminho}" if base else url_for("admin.definir_senha", _external=True)


def criar_usuario(email: str, senha: str, nome: str) -> str:
    dados = _chamar("POST", "/auth/v1/admin/users", {
        "email": email, "password": senha, "email_confirm": True, "user_metadata": {"nome": nome}})
    return dados.get("id") or (dados.get("user") or {}).get("id", "")


def convidar(email: str, nome: str) -> str:
    alvo = urllib.parse.quote(url_definir_senha(), safe="")
    dados = _chamar("POST", f"/auth/v1/invite?redirect_to={alvo}", {"email": email, "data": {"nome": nome}})
    return dados.get("id") or (dados.get("user") or {}).get("id", "")


def definir_senha(uid: str, senha: str) -> None:
    _chamar("PUT", f"/auth/v1/admin/users/{uid}", {"password": senha})


def bloquear(uid: str, bloqueado: bool) -> None:
    _chamar("PUT", f"/auth/v1/admin/users/{uid}", {"ban_duration": BANIMENTO if bloqueado else "none"})


def buscar_id(email: str) -> str | None:
    """Localiza o id de um usuário existente pelo e-mail (varre as páginas da listagem)."""
    email = email.lower()
    for pagina in range(1, 51):
        dados = _chamar("GET", f"/auth/v1/admin/users?page={pagina}&per_page=200")
        usuarios = dados.get("users", [])
        for u in usuarios:
            if (u.get("email") or "").lower() == email:
                return u.get("id")
        if len(usuarios) < 200:
            return None
    return None


def enviar_redefinicao(email: str) -> None:
    """Envia o e-mail de redefinição de senha (funciona só com a chave publicável)."""
    alvo = urllib.parse.quote(url_definir_senha(), safe="")
    _chamar("POST", f"/auth/v1/recover?redirect_to={alvo}", {"email": email}, secreta=False)

