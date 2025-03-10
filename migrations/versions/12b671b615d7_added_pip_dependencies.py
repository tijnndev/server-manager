"""Added pip dependencies

Revision ID: 12b671b615d7
Revises: 397a5577e0a6
Create Date: 2024-12-17 00:12:36.131085

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '12b671b615d7'
down_revision = '397a5577e0a6'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('processes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('dependencies', sa.JSON(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('processes', schema=None) as batch_op:
        batch_op.drop_column('dependencies')

    # ### end Alembic commands ###
