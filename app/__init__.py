"""Sistema de Autorização Digital de Alunos para Passeios Escolares."""
import os

from flask import Flask, g, jsonify, redirect, render_template, request

from .config import BASE_DIR, Config
from .extensions import db, migrate
from .formatacao import registrar_filtros
from .security import admin_atual, aplicar_cabecalhos, csrf_token, responsavel_atual, verificar_csrf



def create_app(config_object=None) -> Flask:
    app = Flask(__name__, instance_path=str(BASE_DIR / "instance"))
    app.config.from_object(config_object or Config)
    os.makedirs(app.instance_path, exist_ok=True)

    if app.config.get("DEMO_MODE") is False and app.config["SECRET_KEY"].startswith("dev-") and not app.debug:
        app.logger.warning("SECRET_KEY de desenvolvimento em uso. Defina SECRET_KEY e CPF_PEPPER no .env.")

    if os.environ.get("PROXY_FIX", "").lower() in {"1", "true"}:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    migrate.init_app(app, db, directory=str(BASE_DIR / "migrations"))
    registrar_filtros(app)

    from .routes.admin import bp as admin_bp
    from .routes.api import bp as api_bp
    from .routes.public import bp as public_bp
    app.register_blueprint(public_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    @app.before_request
    def _antes():
        # O contexto da aplicação pode ser reaproveitado entre requisições:
        # nunca reutilize o usuário resolvido em uma requisição anterior.
        g.pop("responsavel", None)
        g.pop("admin", None)
        # /saude fica fora do redirecionamento: a verificação da hospedagem chega por HTTP interno.
        if app.config["FORCAR_HTTPS"] and not request.is_secure and request.path != "/saude":
            return redirect(request.url.replace("http://", "https://", 1), code=301)
        verificar_csrf()

    app.after_request(aplicar_cabecalhos)

    @app.context_processor
    def _contexto():
        from .services import config_service
        return {
            "csrf_token": csrf_token,
            "instituicao": config_service.obter("instituicao_nome"),
            "titulo_sistema": config_service.obter("titulo_sistema"),
            "brasao_url": config_service.brasao_url(),
            "imagem_passeio": config_service.imagem_passeio,
            "ILUSTRACOES": config_service.ILUSTRACOES,
            "url_ilustracao": config_service.url_ilustracao,
            "demo_mode": app.config["DEMO_MODE"],
            "responsavel": responsavel_atual(),
            "admin": admin_atual(),
        }

    _registrar_erros(app)

    from .cli import registrar_cli
    registrar_cli(app)
    return app


def _registrar_erros(app: Flask) -> None:
    mensagens = {
        400: ("Requisição inválida", "Não foi possível processar a solicitação. Recarregue a página e tente novamente."),
        403: ("Acesso não permitido", "Você não tem permissão para acessar este conteúdo."),
        404: ("Página não encontrada", "O endereço acessado não existe ou não está mais disponível."),
        405: ("Operação não permitida", "Esta operação não é permitida."),
        429: ("Muitas tentativas", "Aguarde alguns minutos e tente novamente."),
        500: ("Erro interno", "Ocorreu um erro inesperado. Nenhuma alteração foi realizada. Tente novamente."),
    }

    def handler(erro):
        codigo = getattr(erro, "code", 500) or 500
        if codigo == 500:
            db.session.rollback()
        # Respostas JSON já montadas (abort(response)) são repassadas.
        if getattr(erro, "response", None) is not None:
            return erro.response
        titulo, texto = mensagens.get(codigo, mensagens[500])
        if request.path.startswith("/api/"):
            return jsonify(erro=texto), codigo
        return render_template("erro.html", titulo=titulo, texto=texto, codigo=codigo), codigo

    for codigo in mensagens:
        app.register_error_handler(codigo, handler)
