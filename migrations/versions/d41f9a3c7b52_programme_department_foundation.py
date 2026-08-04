"""programme department foundation: uses_semesters/uses_terms/duration on programmes, programme_departments junction table

Revision ID: d41f9a3c7b52
Revises: c95349c0e1ad
Create Date: 2026-08-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd41f9a3c7b52'
down_revision = 'c95349c0e1ad'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('programme_departments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('programme_id', sa.Integer(), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
    sa.ForeignKeyConstraint(['programme_id'], ['programmes.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('programme_id', 'department_id')
    )
    with op.batch_alter_table('programmes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('uses_semesters', sa.Boolean(), server_default='1', nullable=False))
        batch_op.add_column(sa.Column('uses_terms', sa.Boolean(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('duration', sa.String(length=50), nullable=True))


def downgrade():
    with op.batch_alter_table('programmes', schema=None) as batch_op:
        batch_op.drop_column('duration')
        batch_op.drop_column('uses_terms')
        batch_op.drop_column('uses_semesters')

    op.drop_table('programme_departments')
