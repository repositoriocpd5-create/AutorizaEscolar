"""catalogo reutilizavel de destinos

Revision ID: c2a9d4f6e812
Revises: f7e85f89f1b6
Create Date: 2026-09-29
"""
from alembic import op
import sqlalchemy as sa


revision = "c2a9d4f6e812"
down_revision = "f7e85f89f1b6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "destino_salvo",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(length=200), nullable=False),
        sa.Column("nome_normalizado", sa.String(length=200), nullable=False, unique=True),
        sa.Column("usos", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("criado_em", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_destino_salvo_nome_normalizado", "destino_salvo", ["nome_normalizado"])

    # Preserva os destinos dos passeios já cadastrados, agrupando diferenças só de caixa.
    op.execute("""
        INSERT INTO destino_salvo (nome, nome_normalizado, usos, criado_em, atualizado_em)
        SELECT MIN(TRIM(destino)), LOWER(TRIM(destino)), COUNT(*), CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM passeio
        WHERE TRIM(destino) <> ''
        GROUP BY LOWER(TRIM(destino))
    """)


def downgrade():
    op.drop_index("ix_destino_salvo_nome_normalizado", table_name="destino_salvo")
    op.drop_table("destino_salvo")
