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

    @app.cli.command("importar-escolas")
    @click.argument("arquivo", type=click.Path(exists=True, dir_okay=False))
    def importar_escolas(arquivo):
        """Importa/atualiza escolas a partir do JSON da rede (idempotente, pelo INEP)."""
        from .services import escola_service
        with open(arquivo, "rb") as f:
            rel = escola_service.importar_arquivo(f.read())
        db.session.commit()
        click.echo(f"Criadas: {rel.criadas} · Atualizadas: {rel.atualizadas}")
        for aviso in rel.avisos:
            click.echo(f"  AVISO: {aviso}")

    @app.cli.command("sql-escolas")
    @click.argument("arquivo", type=click.Path(exists=True, dir_okay=False))
    @click.argument("saida", type=click.Path(dir_okay=False))
    def sql_escolas(arquivo, saida):
        """Gera SQL (INSERT ... ON CONFLICT) das escolas para o SQL Editor do Supabase."""
        import json
        from .services import escola_service
        with open(arquivo, encoding="utf-8-sig") as f:
            dados = json.load(f)
        with open(saida, "w", encoding="utf-8") as f:
            f.write(escola_service.sql_supabase(dados))
        click.echo(f"SQL gravado em {saida}")

    @app.cli.command("sql-alunos")
    @click.argument("arquivo", type=click.Path(exists=True, dir_okay=False))
    @click.argument("saida", type=click.Path(dir_okay=False))
    @click.option("--inep", default=None, help="Já preenche o INEP da escola.")
    @click.option("--pepper-de", "pepper_de", default=None, type=click.Path(exists=True, dir_okay=False),
                  help="Arquivo .env de onde ler CPF_PEPPER (o valor não é exibido).")
    @click.option("--substituir", is_flag=True,
                  help="Substitui alunos, responsáveis, turmas e vínculos da escola indicada.")
    def sql_alunos(arquivo, saida, inep, pepper_de, substituir):
        """Gera SQL de alunos + responsáveis (pai/mãe) para o SQL Editor do Supabase.
        Sem --inep/--pepper-de, preencha as linhas 4 e 5 do arquivo antes de rodar."""
        from dotenv import dotenv_values
        from .services import importacao_alunos as imp
        pepper = dotenv_values(pepper_de).get("CPF_PEPPER") if pepper_de else None
        if pepper_de and not pepper:
            raise click.ClickException("CPF_PEPPER não encontrado no arquivo informado.")
        leitura = imp.ler_arquivo(arquivo)
        with open(saida, "w", encoding="utf-8") as f:
            f.write(imp.gerar_sql(leitura, inep=inep, pepper=pepper, substituir=substituir))
        click.echo(f"{len(leitura.linhas)} alunos -> {saida} ({len(leitura.avisos)} aviso(s))")
        for a in leitura.avisos:
            click.echo(f"  AVISO: {a}")

    @app.cli.command("importar-alunos")
    @click.argument("arquivo", type=click.Path(exists=True, dir_okay=False))
    @click.option("--inep", required=True, help="INEP da escola destes alunos.")
    def importar_alunos(arquivo, inep):
        """Importa alunos + responsáveis direto no banco configurado (DATABASE_URL)."""
        from .services import importacao_alunos as imp
        leitura = imp.ler_arquivo(arquivo)
        with current_app.test_request_context():
            res = imp.importar_local(leitura, inep)
            db.session.commit()
        click.echo(f"Importados: {res['alunos']} alunos ({res['ativos']} ativos); {len(leitura.avisos)} aviso(s).")

    @app.cli.command("limpar-tentativas")
    def limpar():
        """Remove registros antigos de tentativas de acesso (agende diariamente)."""
        limpar_tentativas_antigas()
        click.echo("Ok.")
