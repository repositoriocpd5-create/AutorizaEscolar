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
    @click.option("--login", prompt=True)
    @click.option("--nome", prompt=True)
    @click.option("--escola", default="", help="Código da escola (vazio = acesso a toda a rede).")
    def criar_admin(login, nome, escola):
        """Cria um usuário administrativo."""
        senha = getpass.getpass("Senha (mín. 10 caracteres): ")
        if len(senha) < 10:
            raise click.ClickException("Senha muito curta.")
        esc = Escola.query.filter_by(codigo=escola).first() if escola else None
        if escola and esc is None:
            raise click.ClickException("Escola não encontrada.")
        adm = AdminUsuario(login=login, nome=nome, escola_id=esc.id if esc else None)
        adm.definir_senha(senha)
        db.session.add(adm)
        db.session.commit()
        click.echo("Administrador criado.")

    @app.cli.command("limpar-tentativas")
    def limpar():
        """Remove registros antigos de tentativas de acesso (agende diariamente)."""
        limpar_tentativas_antigas()
        click.echo("Ok.")
