"""add_mcp_servers_table

Revision ID: e3f8a2b9c1d5
Revises: d6c027bbcd17
Create Date: 2026-05-27 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e3f8a2b9c1d5'
down_revision: Union[str, None] = 'd6c027bbcd17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'mcp_servers',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('auth_header', sa.Text(), nullable=True),
        sa.Column('mode', sa.String(length=32), nullable=False, server_default='tool_provider'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('discovered_tools', sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )


def downgrade() -> None:
    op.drop_table('mcp_servers')
