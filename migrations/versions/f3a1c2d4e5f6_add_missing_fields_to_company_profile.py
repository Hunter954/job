"""Add missing fields to company_profile

Revision ID: f3a1c2d4e5f6
Revises: 233268a8b6ef
Create Date: 2026-03-05 15:56:38.547223

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f3a1c2d4e5f6'
down_revision = '233268a8b6ef'
branch_labels = None
depends_on = None


def upgrade():
    # Address + extra company fields (added to model after initial migration)
    op.add_column('company_profile', sa.Column('cep', sa.String(length=20), nullable=True))
    op.add_column('company_profile', sa.Column('state', sa.String(length=30), nullable=True))
    op.add_column('company_profile', sa.Column('neighborhood', sa.String(length=120), nullable=True))
    op.add_column('company_profile', sa.Column('house_number', sa.String(length=30), nullable=True))

    op.add_column('company_profile', sa.Column('segment', sa.String(length=120), nullable=True))
    op.add_column('company_profile', sa.Column('company_size', sa.String(length=60), nullable=True))
    op.add_column('company_profile', sa.Column('founded_year', sa.Integer(), nullable=True))

    # Admin approval flag exists in the model; keep it for back-compat, but default to false
    op.add_column('company_profile', sa.Column('is_approved', sa.Boolean(), nullable=False, server_default=sa.text('false')))

    # remove server default (keeps existing values)
    op.alter_column('company_profile', 'is_approved', server_default=None)


def downgrade():
    op.drop_column('company_profile', 'is_approved')
    op.drop_column('company_profile', 'founded_year')
    op.drop_column('company_profile', 'company_size')
    op.drop_column('company_profile', 'segment')
    op.drop_column('company_profile', 'house_number')
    op.drop_column('company_profile', 'neighborhood')
    op.drop_column('company_profile', 'state')
    op.drop_column('company_profile', 'cep')
