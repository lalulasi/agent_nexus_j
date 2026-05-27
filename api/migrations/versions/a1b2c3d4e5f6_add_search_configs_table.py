"""add search_configs table

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-05-27
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "a1b2c3d4e5f6"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_configs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(20), nullable=False, server_default="ddgs"),
        sa.Column("api_key", sa.Text, nullable=True),
        sa.Column("max_results", sa.Integer, nullable=False, server_default="5"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("search_configs")
