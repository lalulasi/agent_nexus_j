"""add thinking_enabled and thinking_budget to llm_configs

Revision ID: f1a2b3c4d5e6
Revises: e3f8a2b9c1d5
Create Date: 2026-05-27

"""
from alembic import op
import sqlalchemy as sa

revision = "f1a2b3c4d5e6"
down_revision = "e3f8a2b9c1d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_configs",
        sa.Column("thinking_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "llm_configs",
        sa.Column("thinking_budget", sa.Integer(), nullable=False, server_default="8000"),
    )


def downgrade() -> None:
    op.drop_column("llm_configs", "thinking_budget")
    op.drop_column("llm_configs", "thinking_enabled")
