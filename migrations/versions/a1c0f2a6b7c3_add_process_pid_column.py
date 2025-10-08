"""add process pid column

Revision ID: a1c0f2a6b7c3
Revises: 868467c55166
Create Date: 2025-10-08 09:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1c0f2a6b7c3'
down_revision = '868467c55166'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('processes', sa.Column('process_pid', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('processes', 'process_pid')
