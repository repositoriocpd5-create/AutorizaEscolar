"""Utilitários de segurança: CPF, CSRF, limitação de tentativas, sessão e cabeçalhos."""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import abort, current_app, g, jsonify, redirect, request, session, url_for

from .extensions import db
from .models import AdminUsuario, Responsavel, TentativaAcesso, utcnow


# ---------------------------------------------------------------------------
# CPF
# ---------------------------------------------------------------------------
def normalizar_cpf(valor: str) -> str:
    """Remove tudo que não for dígito."""
    return re.sub(r"\D", "", valor or "")


def cpf_valido(cpf: str) -> bool:
    """Valida os dígitos verificadores (recebe CPF já normalizado)."""
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for tamanho in (9, 10):
        soma = sum(int(cpf[i]) * (tamanho + 1 - i) for i in range(tamanho))
        digito = (soma * 10 % 11) % 10
        if digito != int(cpf[tamanho]):
            return False
    return True


def cpf_aceito(cpf: str) -> bool:
    """CPF válido, ou CPF fictício permitido somente em modo demonstração."""
    if cpf_valido(cpf):
        return True
    return bool(current_app.config["DEMO_MODE"] and cpf in current_app.config["DEMO_CPFS"])


def hash_cpf(cpf: str, pepper: str | None = None) -> str:
    pepper = pepper or current_app.config["CPF_PEPPER"]
    return hmac.new(pepper.encode(), normalizar_cpf(cpf).encode(), hashlib.sha256).hexdigest()


def hash_segredo(valor: str, pepper: str | None = None) -> str:
    """HMAC genérico para segundos fatores (ex.: data de nascimento AAAA-MM-DD)."""
    pepper = pepper or current_app.config["CPF_PEPPER"]
    return hmac.new(pepper.encode(), ("2f:" + valor).encode(), hashlib.sha256).hexdigest()


def mascarar_cpf(cpf: str) -> str:
    return f"***.***.***-{normalizar_cpf(cpf)[-2:]}"


# ---------------------------------------------------------------------------
# Rede
# ---------------------------------------------------------------------------
def client_ip() -> str:
    # Atrás de proxy reverso, configure ProxyFix (ver README) em vez de ler
    # X-Forwarded-For manualmente — o cabeçalho pode ser forjado.
    return request.remote_addr or "0.0.0.0"


def client_ua() -> str:
    return (request.headers.get("User-Agent") or "")[:300]


def ip_auditoria():
    return client_ip() if current_app.config["REGISTRAR_IP"] else None


def ua_auditoria():
    return client_ua() if current_app.config["REGISTRAR_USER_AGENT"] else None


# ---------------------------------------------------------------------------
# Limitação de tentativas (proteção contra força bruta e enumeração)
# ---------------------------------------------------------------------------
def _janela() -> datetime:
    return utcnow() - timedelta(minutes=current_app.config["LIMITE_JANELA_MINUTOS"])


def falhas_recentes(chave: str) -> int:
    return TentativaAcesso.query.filter(
        TentativaAcesso.chave == chave,
        TentativaAcesso.sucesso.is_(False),
        TentativaAcesso.data_hora >= _janela(),
    ).count()


def excedeu_limite(chave: str, limite: int) -> bool:
    return falhas_recentes(chave) >= limite


def registrar_tentativa(chave: str, sucesso: bool) -> None:
    db.session.add(TentativaAcesso(chave=chave, sucesso=sucesso))
    db.session.commit()


def limpar_tentativas_antigas() -> None:
    TentativaAcesso.query.filter(TentativaAcesso.data_hora < utcnow() - timedelta(days=1)).delete()
    db.session.commit()


# ---------------------------------------------------------------------------
# CSRF (token por sessão, conferido em todo POST/PUT/PATCH/DELETE)
# ---------------------------------------------------------------------------
def csrf_token() -> str:
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def verificar_csrf() -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if current_app.config.get("TESTING") and current_app.config.get("CSRF_DESABILITADO"):
        return
    enviado = request.headers.get("X-CSRF-Token") or request.form.get("_csrf", "")
    esperado = session.get("_csrf", "")
    if not esperado or not hmac.compare_digest(enviado, esperado):
        if request.path.startswith("/api/"):
            response = jsonify(erro="Sessão expirada. Recarregue a página e tente novamente.")
            response.status_code = 400
            abort(response)
        abort(400)


# ---------------------------------------------------------------------------
# Sessão do responsável e do administrador
# ---------------------------------------------------------------------------
def iniciar_sessao_responsavel(resp: Responsavel) -> None:
    session.clear()
    session.permanent = True
    session["resp_id"] = resp.id
    session["resp_auth"] = utcnow().isoformat()
    csrf_token()


def responsavel_atual() -> Responsavel | None:
    if "responsavel" in g:
        return g.responsavel
    resp = None
    rid = session.get("resp_id")
    if rid:
        resp = db.session.get(Responsavel, rid)
        if resp is not None and not resp.ativo:
            resp = None
    g.responsavel = resp
    return resp


def responsavel_obrigatorio(api: bool = False):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if responsavel_atual() is None:
                if api:
                    return jsonify(erro="Sessão expirada. Informe o CPF novamente."), 401
                return redirect(url_for("public.login"))
            return fn(*args, **kwargs)
        return wrapper
    return deco


def admin_atual() -> AdminUsuario | None:
    if "admin" in g:
        return g.admin
    adm = None
    aid = session.get("admin_id")
    if aid:
        adm = db.session.get(AdminUsuario, aid)
        if adm is not None and not adm.ativo:
            adm = None
    g.admin = adm
    return adm


def admin_obrigatorio(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if admin_atual() is None:
            return redirect(url_for("admin.login", proximo=request.path))
        return fn(*args, **kwargs)
    return wrapper


def permissao_obrigatoria(permissao: str):
    """Exige admin logado com a permissão (ver models.PERMISSOES). Caso contrário, 403."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            adm = admin_atual()
            if adm is None:
                return redirect(url_for("admin.login", proximo=request.path))
            if not adm.pode(permissao):
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return deco


# ---------------------------------------------------------------------------
# Cabeçalhos de segurança
# ---------------------------------------------------------------------------
def aplicar_cabecalhos(response):
    supabase = current_app.config.get("SUPABASE_URL", "")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
        f"connect-src 'self' {supabase}".rstrip() + "; "
        "object-src 'self'; frame-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'",
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if current_app.config["FORCAR_HTTPS"]:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    # Páginas com dados pessoais não devem ficar em cache compartilhado.
    if session.get("resp_id") or session.get("admin_id"):
        response.headers["Cache-Control"] = "no-store"
    return response
