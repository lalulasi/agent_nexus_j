"""flex_embedding_dim_drop_ivfflat

Revision ID: d6c027bbcd17
Revises: d0f4e6ebc4f0
Create Date: 2026-05-26 20:30:24.822772

"""
from typing import Sequence, Union

import pgvector.sqlalchemy
from alembic import op
import sqlalchemy as sa


revision: str = 'd6c027bbcd17'
down_revision: Union[str, None] = 'd0f4e6ebc4f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IVFFlat index requires a fixed-dimension column; drop it before altering type
    op.drop_index('ix_knowledge_chunks_embedding', table_name='knowledge_chunks',
                  postgresql_using='ivfflat')
    # Change from vector(1536) to vector (no fixed dim) to support any embedding model
    op.execute("ALTER TABLE knowledge_chunks ALTER COLUMN embedding TYPE vector USING embedding::vector")


def downgrade() -> None:
    op.execute("ALTER TABLE knowledge_chunks ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)")
    op.create_index('ix_knowledge_chunks_embedding', 'knowledge_chunks', ['embedding'],
                    unique=False, postgresql_using='ivfflat',
                    postgresql_with={'lists': 100},
                    postgresql_ops={'embedding': 'vector_cosine_ops'})
