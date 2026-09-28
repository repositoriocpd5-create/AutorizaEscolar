"""Comandos de linha de comando (flask <comando>)."""
import getpass

import click
from flask import current_app

from .extensions import db
from .models import AdminUsuario, Escola
from .security import limpar_tentativas_antigas


def registrar_cli(app):
    @app.cli.command("seed-demo")
    @click.option("--reset", is_flag=True, help="Apaga e recria todas as tabelas antes (somente demonstração).")
    def seed_demo(reset):
        """Popula o banco com dados FICTÍCIOS de demonstração."""
        if not current_app.config["DEMO_MODE"]:
            raise click.ClickException(
                "Recusado: DEMO_MODE está desligado. Dados fictícios não devem ser misturados à produção.")
        from seeds.demo import popular
        if reset:
            db.drop_all()
            db.create_all()
        popular()
        click.echo("Dados de demonstração criados.")

    @app.cli.command("criar-admin")
    @click.option("--nome", prompt=True)
    @click.option("--email", default="", help="E-mail do Supabase Authentication (modo Supabase: sem senha local).")
    @click.option("--login", default="", help="Login local (somente sem Supabase).")
    @click.option("--escola", default="", help="Código da escola (vazio = acesso a toda a rede).")
    def criar_admin(nome, email, login, escola):
        """Autoriza um usuário no painel administrativo."""
        from .services.admin_auth_service import modo_supabase
        esc = Escola.query.filter_by(codigo=escola).first() if escola else None
        if escola and esc is None:
            raise click.ClickException("Escola não encontrada.")
        if modo_supabase():
            if not email:
                raise click.ClickException("Informe --email (a senha é gerenciada no Supabase Authentication).")
            adm = AdminUsuario(login=email.lower()[:60], email=email.lower(), nome=nome,
                               escola_id=esc.id if esc else None)
        else:
            if not login:
                raise click.ClickException("Informe --login.")
            senha = getpass.getpass("Senha (mín. 10 caracteres): ")
            if len(senha) < 10:
                raise click.ClickException("Senha muito curta.")
            adm = AdminUsuario(login=login, nome=nome, escola_id=esc.id if esc else None)
            adm.definir_senha(senha)
        db.session.add(adm)
        db.session.commit()
        click.echo("Administrador autorizado.")

    @app.cli.command("limpar-tentativas")
    def limpar():
        """Remove registros antigos de tentativas de acesso (agende diariamente)."""
        limpar_tentativas_antigas()
        click.echo("Ok.")
