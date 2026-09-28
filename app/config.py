"""Configuração da aplicação.

Todos os valores sensíveis vêm de variáveis de ambiente (ver .env.example).
"""
import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "sim", "yes", "on"}


def _url_banco(url: str) -> str:
    """Provedores (Render, Heroku) entregam 'postgres://'; o SQLAlchemy usa o driver psycopg 3."""
    for prefixo in ("postgres://", "postgresql://"):
        if url.startswith(prefixo):
            return "postgresql+psycopg://" + url[len(prefixo):]
    return url


class Config:
    # --- Segredos -----------------------------------------------------------
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-inseguro-troque-em-producao")
    # "Pepper" usado no HMAC do CPF. NUNCA altere depois de popular o banco:
    # os CPFs são localizados apenas pelo hash.
    CPF_PEPPER = os.environ.get("CPF_PEPPER", "dev-pepper-troque-em-producao")

    # --- Banco de dados -----------------------------------------------------
    SQLALCHEMY_DATABASE_URI = _url_banco(
        os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'instance' / 'passeios.db'}"))
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- Armazenamento dos PDFs --------------------------------------------
    DOCUMENTOS_DIR = os.environ.get("DOCUMENTOS_DIR", str(BASE_DIR / "instance" / "documentos"))

    # --- Instituição ------------------------------------------------------
    INSTITUICAO_NOME = os.environ.get("INSTITUICAO_NOME", "Secretaria Municipal de Educação")
    TIMEZONE = os.environ.get("TIMEZONE", "America/Sao_Paulo")
    # URL pública usada no QR Code. Se vazio, usa o host da requisição.
    # No Render, RENDER_EXTERNAL_URL é definida automaticamente.
    PUBLIC_BASE_URL = (os.environ.get("PUBLIC_BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL", "")).rstrip("/")

    # --- Modo demonstração -----------------------------------------------
    # Em demonstração o CPF 000.000.000-00 (inválido pelo dígito verificador)
    # é aceito apenas para os responsáveis fictícios do seed.
    DEMO_MODE = _bool("DEMO_MODE", False)
    DEMO_CPFS = {c.strip() for c in os.environ.get("DEMO_CPFS", "00000000000").split(",") if c.strip()}

    # --- Autenticação do responsável -------------------------------------
    # "nenhum"          -> somente CPF (apenas protótipo/demonstração)
    # "data_nascimento" -> CPF + data de nascimento do responsável
    # Outros provedores (sms, email, govbr) podem ser plugados em
    # app/services/auth_service.py sem alterar as rotas.
    AUTH_SEGUNDO_FATOR = os.environ.get("AUTH_SEGUNDO_FATOR", "nenhum")
    SESSAO_MINUTOS = int(os.environ.get("SESSAO_MINUTOS", "30"))
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=SESSAO_MINUTOS)

    # --- Limites contra força bruta/enumeração ---------------------------
    LIMITE_TENTATIVAS_IP = int(os.environ.get("LIMITE_TENTATIVAS_IP", "10"))
    LIMITE_TENTATIVAS_CPF = int(os.environ.get("LIMITE_TENTATIVAS_CPF", "5"))
    LIMITE_JANELA_MINUTOS = int(os.environ.get("LIMITE_JANELA_MINUTOS", "15"))
    LIMITE_VALIDACAO_IP = int(os.environ.get("LIMITE_VALIDACAO_IP", "30"))

    # --- Auditoria / LGPD -------------------------------------------------
    REGISTRAR_IP = _bool("REGISTRAR_IP", True)
    REGISTRAR_USER_AGENT = _bool("REGISTRAR_USER_AGENT", True)

    # --- Cookies ----------------------------------------------------------
    SESSION_COOKIE_NAME = "passeio_sessao"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    FORCAR_HTTPS = _bool("FORCAR_HTTPS", False)

    JSON_SORT_KEYS = False


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    DEMO_MODE = True
    SECRET_KEY = "teste"
    CPF_PEPPER = "teste"
