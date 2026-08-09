"""fee structure: programme/session/semester/department-scoped fee overrides

Revision ID: f3a7c9d21e04
Revises: a29d6f0c81e5
Create Date: 2026-08-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f3a7c9d21e04'
down_revision = 'a29d6f0c81e5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('fee_structures',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('academic_session_id', sa.Integer(), nullable=False),
    sa.Column('semester_id', sa.Integer(), nullable=True),
    sa.Column('department_id', sa.Integer(), nullable=True),
    sa.Column('category_id', sa.Integer(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['academic_session_id'], ['academic_sessions.id'], ),
    sa.ForeignKeyConstraint(['semester_id'], ['semesters.id'], ),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
    sa.ForeignKeyConstraint(['category_id'], ['payment_categories.id'], ),
    sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('fee_structures')
