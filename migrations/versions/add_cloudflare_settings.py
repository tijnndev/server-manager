"""add cloudflare api token to user_settings

Revision ID: add_cloudflare_settings
Revises: add_discord_settings
Create Date: 2026-02-11
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_cloudflare_settings'
down_revision = 'add_discord_settings'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user_settings', sa.Column('cloudflare_api_token', sa.String(length=255), nullable=True))


def downgrade():
    op.drop_column('user_settings', 'cloudflare_api_token')
