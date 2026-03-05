"""add company profile business fields

Revision ID: 2f3a9b1c4d11
Revises: e7c267d2ab82
Create Date: 2026-03-05 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2f3a9b1c4d11"
down_revision = "e7c267d2ab82"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("company_profile", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cep", sa.String(length=9), nullable=True))
        batch_op.add_column(sa.Column("state", sa.String(length=2), nullable=True))
        batch_op.add_column(sa.Column("neighborhood", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("house_number", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("segment", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("company_size", sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column("founded_year", sa.String(length=10), nullable=True))


def downgrade():
    with op.batch_alter_table("company_profile", schema=None) as batch_op:
        batch_op.drop_column("founded_year")
        batch_op.drop_column("company_size")
        batch_op.drop_column("segment")
        batch_op.drop_column("house_number")
        batch_op.drop_column("neighborhood")
        batch_op.drop_column("state")
        batch_op.drop_column("cep")
