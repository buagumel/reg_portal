"""course offering split: rename courses to course_offerings, add master courses table, repoint course_prerequisites/course_corequisites, add course_import mismatch tracking

Revision ID: a29d6f0c81e5
Revises: b7f4a1de9c63
Create Date: 2026-08-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a29d6f0c81e5'
down_revision = 'b7f4a1de9c63'
branch_labels = None
depends_on = None


def upgrade():
    # Step A: rename the existing courses table to course_offerings. This is a
    # single, permanent rename with nothing dropped — SQLite safely rewrites
    # every sibling table's stored FK text (course_prerequisites,
    # course_corequisites, course_assessment_components, registered_courses)
    # to reference course_offerings automatically. This is the SAFE case,
    # distinct from the unsafe rename-then-drop pattern documented from
    # sub-project 2's Task 1 fix round.
    op.rename_table('courses', 'course_offerings')

    # Step B: create the new master courses table.
    op.create_table('courses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=20), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('credits', sa.Integer(), nullable=False),
        sa.Column('course_type', sa.String(length=20), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='active', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )

    # Step C: add course_offerings.course_id (nullable FK to the new master table).
    with op.batch_alter_table('course_offerings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('course_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_course_offerings_course_id', 'courses', ['course_id'], ['id'])

    # Step D: backfill the master table — one row per distinct code, using the
    # lowest-id (earliest-created) offering's title/credits/course_type/description
    # as authoritative.
    conn = op.get_bind()
    conn.execute(sa.text('''
        INSERT INTO courses (code, title, credits, course_type, description, status, created_at)
        SELECT code, title, credits, course_type, description, 'active', CURRENT_TIMESTAMP
        FROM (
            SELECT code, title, credits, course_type, description,
                   ROW_NUMBER() OVER (PARTITION BY code ORDER BY id) AS rn
            FROM course_offerings
        ) sub
        WHERE rn = 1
    '''))

    # Step E: backfill course_offerings.course_id from the new master rows.
    conn.execute(sa.text('''
        UPDATE course_offerings
        SET course_id = (SELECT id FROM courses WHERE courses.code = course_offerings.code)
    '''))

    # Step F: flag (print, don't fail) any code where title/credits/course_type/
    # description actually differed across existing offering rows — the master
    # took the earliest row's values; other rows keep their own historical
    # values in their own (unchanged) columns, so nothing is lost, but an
    # admin should know the master might not match every historical offering.
    mismatches = conn.execute(sa.text('''
        SELECT code, COUNT(DISTINCT title || '|' || credits || '|' || course_type || '|' || COALESCE(description, '')) AS variants
        FROM course_offerings
        GROUP BY code
        HAVING variants > 1
    ''')).fetchall()
    for code, variants in mismatches:
        print(f'NOTE: course code "{code}" has {variants} differing title/credits/course_type/description combinations '
              f'across its existing offerings — the master Course now uses the earliest offering\'s values. Review via the Course Catalog admin page.')

    # Step G: rebuild course_prerequisites and course_corequisites to reference
    # the master courses table instead of course_offerings, translating any
    # existing rows' offering-ids to the corresponding master-ids via the
    # course_id mapping just backfilled in Step E.
    op.create_table('course_prerequisites_new',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('prerequisite_course_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
        sa.ForeignKeyConstraint(['prerequisite_course_id'], ['courses.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('course_id', 'prerequisite_course_id'),
    )
    conn.execute(sa.text('''
        INSERT OR IGNORE INTO course_prerequisites_new (id, course_id, prerequisite_course_id)
        SELECT cp.id, co1.course_id, co2.course_id
        FROM course_prerequisites cp
        JOIN course_offerings co1 ON co1.id = cp.course_id
        JOIN course_offerings co2 ON co2.id = cp.prerequisite_course_id
    '''))
    op.drop_table('course_prerequisites')
    op.rename_table('course_prerequisites_new', 'course_prerequisites')

    op.create_table('course_corequisites_new',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('corequisite_course_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
        sa.ForeignKeyConstraint(['corequisite_course_id'], ['courses.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('course_id', 'corequisite_course_id'),
    )
    conn.execute(sa.text('''
        INSERT OR IGNORE INTO course_corequisites_new (id, course_id, corequisite_course_id)
        SELECT cc.id, co1.course_id, co2.course_id
        FROM course_corequisites cc
        JOIN course_offerings co1 ON co1.id = cc.course_id
        JOIN course_offerings co2 ON co2.id = cc.corequisite_course_id
    '''))
    op.drop_table('course_corequisites')
    op.rename_table('course_corequisites_new', 'course_corequisites')

    # Step H: course_import tracking columns.
    with op.batch_alter_table('course_import_jobs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('mismatched_count', sa.Integer(), server_default='0', nullable=False))
    with op.batch_alter_table('course_import_errors', schema=None) as batch_op:
        batch_op.add_column(sa.Column('severity', sa.String(length=10), server_default='error', nullable=False))


def downgrade():
    with op.batch_alter_table('course_import_errors', schema=None) as batch_op:
        batch_op.drop_column('severity')
    with op.batch_alter_table('course_import_jobs', schema=None) as batch_op:
        batch_op.drop_column('mismatched_count')

    # Reverse course_corequisites/course_prerequisites: repoint back to
    # course_offerings by reversing the course_id mapping (find any
    # course_offerings row whose course_id matches, taking the first match
    # per master id — this is a best-effort reversal, matching the same
    # first-match convention used by the forward migration).
    op.create_table('course_corequisites_old',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('corequisite_course_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['course_id'], ['course_offerings.id'], ),
        sa.ForeignKeyConstraint(['corequisite_course_id'], ['course_offerings.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('course_id', 'corequisite_course_id'),
    )
    conn = op.get_bind()
    conn.execute(sa.text('''
        INSERT INTO course_corequisites_old (id, course_id, corequisite_course_id)
        SELECT cc.id,
               (SELECT MIN(id) FROM course_offerings WHERE course_id = cc.course_id),
               (SELECT MIN(id) FROM course_offerings WHERE course_id = cc.corequisite_course_id)
        FROM course_corequisites cc
    '''))
    op.drop_table('course_corequisites')
    op.rename_table('course_corequisites_old', 'course_corequisites')

    op.create_table('course_prerequisites_old',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('prerequisite_course_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['course_id'], ['course_offerings.id'], ),
        sa.ForeignKeyConstraint(['prerequisite_course_id'], ['course_offerings.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('course_id', 'prerequisite_course_id'),
    )
    conn.execute(sa.text('''
        INSERT INTO course_prerequisites_old (id, course_id, prerequisite_course_id)
        SELECT cp.id,
               (SELECT MIN(id) FROM course_offerings WHERE course_id = cp.course_id),
               (SELECT MIN(id) FROM course_offerings WHERE course_id = cp.prerequisite_course_id)
        FROM course_prerequisites cp
    '''))
    op.drop_table('course_prerequisites')
    op.rename_table('course_prerequisites_old', 'course_prerequisites')

    with op.batch_alter_table('course_offerings', schema=None) as batch_op:
        batch_op.drop_constraint('fk_course_offerings_course_id', type_='foreignkey')
        batch_op.drop_column('course_id')

    op.drop_table('courses')
    op.rename_table('course_offerings', 'courses')
