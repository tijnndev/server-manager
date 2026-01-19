"""Add Discord integration fields to user_settings

Revision ID: add_discord_settings
Revises: 
Create Date: 2026-01-19

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_discord_settings'
down_revision = None  # Update this with the actual previous revision if needed
branch_labels = None
depends_on = None


def upgrade():
    # Add Discord integration columns to user_settings table
    op.add_column('user_settings', sa.Column('discord_webhook_url', sa.String(500), nullable=True))
    op.add_column('user_settings', sa.Column('discord_enabled', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('user_settings', sa.Column('discord_notify_crashes', sa.Boolean(), nullable=False, server_default='1'))
    op.add_column('user_settings', sa.Column('discord_notify_power_actions', sa.Boolean(), nullable=False, server_default='1'))


def downgrade():
    # Remove Discord integration columns from user_settings table
    op.drop_column('user_settings', 'discord_notify_power_actions')
    op.drop_column('user_settings', 'discord_notify_crashes')
    op.drop_column('user_settings', 'discord_enabled')
    op.drop_column('user_settings', 'discord_webhook_url')
