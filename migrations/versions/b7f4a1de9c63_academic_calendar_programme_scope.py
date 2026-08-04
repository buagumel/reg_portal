"""academic calendar programme scope: programme_id + composite unique on academic_sessions, period_type on semesters

Revision ID: b7f4a1de9c63
Revises: d41f9a3c7b52
Create Date: 2026-08-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7f4a1de9c63'
down_revision = 'd41f9a3c7b52'
branch_labels = None
depends_on = None


def upgrade():
    # academic_sessions predates Alembic tracking in this repo (originally created via
    # db.create_all()) and has an unnamed inline `UNIQUE (name)` table constraint that
    # Alembic batch mode cannot reliably target for removal. Rebuild the table explicitly
    # via raw SQL instead of batch_alter_table, so the new composite constraint is the
    # only one governing `name` going forward.
    op.execute('ALTER TABLE academic_sessions RENAME TO academic_sessions_old')
    op.create_table('academic_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=20), nullable=False),
        sa.Column('is_current', sa.Boolean(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='draft', nullable=False),
        sa.Column('programme_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['programme_id'], ['programmes.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', 'programme_id', name='uq_academic_sessions_name_programme_id'),
    )
    op.execute('''
        INSERT INTO academic_sessions (id, name, is_current, start_date, end_date, status, programme_id)
        SELECT id, name, is_current, start_date, end_date, status, NULL FROM academic_sessions_old
    ''')
    op.execute('DROP TABLE academic_sessions_old')

    with op.batch_alter_table('semesters', schema=None) as batch_op:
        batch_op.add_column(sa.Column('period_type', sa.String(length=20), server_default='semester', nullable=False))


def downgrade():
    with op.batch_alter_table('semesters', schema=None) as batch_op:
        batch_op.drop_column('period_type')

    op.execute('ALTER TABLE academic_sessions RENAME TO academic_sessions_new')
    op.create_table('academic_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=20), nullable=False),
        sa.Column('is_current', sa.Boolean(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='draft', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.execute('''
        INSERT INTO academic_sessions (id, name, is_current, start_date, end_date, status)
        SELECT id, name, is_current, start_date, end_date, status FROM academic_sessions_new
    ''')
    op.execute('DROP TABLE academic_sessions_new')
