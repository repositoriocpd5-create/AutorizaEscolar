"""Gera docs/supabase/schema.sql INCREMENTAL e reexecutável para o SQL Editor do Supabase.

Cada migration vira um bloco ``DO`` que só é aplicado se o banco estiver exatamente
na revisão anterior (lida de ``alembic_version``). Assim o mesmo arquivo serve para
um banco vazio e para um banco que já recebeu versões anteriores do script, e pode
ser executado várias vezes sem erro.

Uso:  .venv\\Scripts\\python scripts\\gerar_sql_supabase.py
"""
import os
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "docs" / "supabase" / "schema.sql"
FLASK = RAIZ / ".venv" / ("Scripts/flask.exe" if os.name == "nt" else "bin/flask")

sys.path.insert(0, str(RAIZ))


def cadeia_de_revisoes() -> list[tuple[str | None, str]]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config()
    cfg.set_main_option("script_location", str(RAIZ / "migrations"))
    scripts = ScriptDirectory.from_config(cfg)
    revs = list(scripts.walk_revisions("base", "heads"))
    revs.reverse()  # da mais antiga para a mais nova
    return [(r.down_revision, r.revision) for r in revs]


def sql_offline(intervalo: str) -> str:
    env = dict(os.environ, DATABASE_URL="postgresql://offline:offline@localhost:5432/offline",
               PYTHONIOENCODING="utf-8", PYTHONUTF8="1", SUPABASE_URL="")
    r = subprocess.run([str(FLASK), "--app", "wsgi", "db", "upgrade", intervalo, "--sql"], cwd=RAIZ, env=env,
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit(r.stderr)
    linhas = [l for l in r.stdout.splitlines() if l.strip() not in ("BEGIN;", "COMMIT;")]
    # Dentro de um bloco PL/pgSQL, INSERT ... RETURNING exigiria uma variável de destino.
    return re.sub(r"\s+RETURNING\s+[\w.]+;", ";", "\n".join(linhas)).strip()


def main():
    blocos = []
    for anterior, revisao in cadeia_de_revisoes():
        if anterior is None:
            corpo = sql_offline(revisao)
            condicao = "to_regclass('public.alembic_version') IS NULL"
        else:
            corpo = sql_offline(f"{anterior}:{revisao}")
            condicao = (f"to_regclass('public.alembic_version') IS NOT NULL AND EXISTS "
                        f"(SELECT 1 FROM alembic_version WHERE version_num = '{anterior}')")
        assert "$mig$" not in corpo
        blocos.append(f"-- Migration {revisao}\nDO $mig$\nBEGIN\n  IF {condicao} THEN\n"
                      + "\n".join("    " + l for l in corpo.splitlines()) +
                      "\n  END IF;\nEND\n$mig$;\n")
    cabecalho = """-- =====================================================================
-- Autoriza Escolar — criação/ATUALIZAÇÃO das tabelas no Supabase (PostgreSQL)
--
-- Como usar: Supabase → SQL Editor → New query → cole este arquivo → Run.
-- Pode ser executado QUANTAS VEZES QUISER: cada bloco só é aplicado se o banco
-- estiver na versão anterior a ele (tabela alembic_version). Serve tanto para um
-- banco vazio quanto para atualizar um banco criado com versões anteriores.
--
-- Segurança: RLS é ativado em TODAS as tabelas, sem políticas. A API REST do
-- Supabase (chave publicável) não acessa nenhum dado; o sistema conecta
-- diretamente ao banco.
-- =====================================================================

BEGIN;

"""
    rodape = "\nCOMMIT;\n\n-- Versão final esperada:\nSELECT version_num AS versao_do_banco FROM alembic_version;\n"
    SAIDA.write_text(cabecalho + "\n".join(blocos) + rodape, encoding="utf-8")
    print(f"{len(blocos)} migrations -> {SAIDA}")


if __name__ == "__main__":
    main()
