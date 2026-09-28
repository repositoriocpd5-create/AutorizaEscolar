"""rls no postgres (supabase)

Ativa Row Level Security em todas as tabelas quando o banco é PostgreSQL.

No Supabase, tabelas do schema ``public`` ficam acessíveis pela API REST com a
chave publicável (pública por natureza). Com RLS ativo e SEM políticas, essa API
não lê nem grava nada; a aplicação conecta diretamente como dono das tabelas
(usuário ``postgres``), que não é afetado pelo RLS.

Revision ID: 1b0e7f733da3
Revises: 9bfba8258bec
Create Date: 2026-09-28 15:32:23.895460

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '1b0e7f733da3'
down_revision = '9bfba8258bec'
branch_labels = None
depends_on = None

TABELAS = [
    "alembic_version", "escola", "turma", "responsavel", "aluno", "responsavel_aluno",
    "passeio", "passeio_turma", "passeio_aluno", "autorizacao", "autorizacao_historico",
    "documento", "documento_item", "protocolo_sequencia", "admin_usuario", "audit_log",
    "tentativa_acesso", "configuracao", "midia",
]


def upgrade():
    if op.get_context().dialect.name != "postgresql":
        return
    for tabela in TABELAS:
        op.execute(f'ALTER TABLE public."{tabela}" ENABLE ROW LEVEL SECURITY')


def downgrade():
    if op.get_context().dialect.name != "postgresql":
        return
    for tabela in TABELAS:
        op.execute(f'ALTER TABLE public."{tabela}" DISABLE ROW LEVEL SECURITY')
