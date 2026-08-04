# Course → Course + CourseOffering Split (DDD Refactor Sub-project 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the conflated `Course` model into a master `Course` (catalog identity: code/title/credits/course_type/description) and `CourseOffering` (one session/semester's instance of it), moving `CoursePrerequisite`/`CourseCorequisite` to curriculum-level while preserving every existing student-facing behavior and `RegisteredCourse`'s row identities untouched.

**Architecture:** The existing `courses` table is renamed in place to `course_offerings` via `op.rename_table` (same rows, same IDs, nothing dropped) — SQLite automatically updates every sibling table's stored FK text to match. A new master `courses` table is created and backfilled by grouping existing offerings by `code`. `course_offerings.course_id` (new, nullable FK) links each offering to its master. New offerings mirror their master's catalog fields into the offering's own (unchanged) `code`/`title`/`credits`/`course_type`/`description` columns at creation time — dual-write, exactly like every prior sub-project's additive pattern — so every existing template/read-path that reads `offering.code`/`offering.title`/etc. keeps working unchanged. `CoursePrerequisite`/`CourseCorequisite` are rebuilt to FK into the new master `courses` table instead of `course_offerings`; `CourseAssessmentComponent` and `RegisteredCourse` stay FK'd to `course_offerings`, unchanged in scope.

**Tech Stack:** Flask, Flask-SQLAlchemy, Flask-Migrate/Alembic, Jinja2, SQLite (dev). No automated test framework — verification is via throwaway `test_client`/`app_context` scripts, run and discarded, never committed.

## Global Constraints

- No column drops, no renames of any existing column on `course_offerings` (the renamed `courses` table) — every field it has today, it keeps.
- `RegisteredCourse.course_id` semantics are unchanged: it still identifies a `CourseOffering` row by the same ID it always has. No data migration of `registered_courses` rows.
- `CourseAssessmentComponent` stays offering-level — not moved to master, per the confirmed design decision.
- Student-facing registration/eligibility logic (`services/registration.py`, `services/validation.py`) gets a mechanical rename only (`Course` → `CourseOffering`, same field names, same behavior) — no FK-based Programme-aware eligibility rewrite. That is sub-project 4's job.
- The new Course Catalog admin module reuses the existing `courses.manage` permission — no new RBAC permission is introduced.
- Once a master `Course` exists for a code, CSV import never silently overwrites its catalog fields — a mismatch is flagged, not auto-corrected.

---

### Task 1: Migration and `models.py`

**Files:**
- Modify: `models.py:189-225` (`Course` class → renamed `CourseOffering`; `RegisteredCourse` FK/relationship)
- Modify: `models.py:417-424` (`CourseAssessmentComponent` FK/relationship)
- Modify: `models.py:464-487` (`CourseImportJob`/`CourseImportError` — new columns)
- Create: new master `Course` class in `models.py` (placed immediately before the renamed `CourseOffering` class)
- Create: `migrations/versions/a29d6f0c81e5_course_offering_split.py`

**Interfaces:**
- Produces: `Course` (master: `id, code, title, credits, course_type, description, status, created_at`), `CourseOffering` (renamed `Course`, unchanged columns + new `course_id` nullable FK + `course` relationship), `CourseOffering.offerings` backref on `Course` (i.e. `course.offerings` lists its `CourseOffering` rows), `CourseImportJob.mismatched_count`, `CourseImportError.severity`.
- `CoursePrerequisite`/`CourseCorequisite` model code is UNCHANGED — their `db.ForeignKey('courses.id')` and `db.relationship('Course', ...)` string references now correctly resolve to the new master `Course` automatically, since the table name `courses` and class name `Course` are reclaimed by the master. Do not edit `CoursePrerequisite`/`CourseCorequisite` in this task.

- [ ] **Step 1: Add the new master `Course` class to `models.py`**

Insert immediately before the current `Course` class (`models.py:189`):

```python
class Course(db.Model):
    __tablename__ = 'courses'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    credits = db.Column(db.Integer, nullable=False)
    course_type = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='active', server_default='active')
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
```

- [ ] **Step 2: Rename the existing `Course` class to `CourseOffering`**

Replace the current class (`models.py:189-211`, now pushed down by Step 1's insertion):

```python
class CourseOffering(db.Model):
    __tablename__ = 'course_offerings'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    credits = db.Column(db.Integer, nullable=False)
    department = db.Column(db.String(150), nullable=False)
    level = db.Column(db.String(50), nullable=True)
    course_type = db.Column(db.String(20), nullable=False)
    academic_session_id = db.Column(db.Integer, db.ForeignKey('academic_sessions.id'), nullable=False)
    semester_id = db.Column(db.Integer, db.ForeignKey('semesters.id'), nullable=False)
    description = db.Column(db.Text, nullable=True)
    instructor = db.Column(db.String(150), nullable=True)
    schedule = db.Column(db.String(200), nullable=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='active', server_default='active')
    max_capacity = db.Column(db.Integer, nullable=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=True)

    __table_args__ = (db.UniqueConstraint('code', 'academic_session_id', 'semester_id'),)

    academic_session = db.relationship('AcademicSession')
    semester = db.relationship('Semester')
    department_ref = db.relationship('Department', foreign_keys=[department_id])
    course = db.relationship('Course', backref='offerings')
```

Note: every column that existed before (`code`, `title`, `credits`, `department`, `level`, `course_type`, `academic_session_id`, `semester_id`, `description`, `instructor`, `schedule`, `department_id`, `status`, `max_capacity`) is unchanged — only `__tablename__` (was `'courses'`) and the class name changed, plus the new `course_id`/`course` addition.

- [ ] **Step 3: Update `RegisteredCourse`'s FK and relationship**

`RegisteredCourse` (`models.py`, now shifted down by the prior insertions — search for `class RegisteredCourse`) currently has:
```python
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
```
and
```python
    course = db.relationship('Course')
```
Change to:
```python
    course_id = db.Column(db.Integer, db.ForeignKey('course_offerings.id'), nullable=False)
```
and
```python
    course = db.relationship('CourseOffering')
```
This is a Python-model-only change (the underlying FK target table name in the DB is already `course_offerings` after the migration's rename — this just makes the declared model match reality and makes the relationship resolve to the right class). No data changes.

- [ ] **Step 4: Update `CourseAssessmentComponent`'s FK and relationship**

Currently:
```python
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    ...
    course = db.relationship('Course', backref='assessment_components')
```
Change to:
```python
    course_id = db.Column(db.Integer, db.ForeignKey('course_offerings.id'), nullable=False)
    ...
    course = db.relationship('CourseOffering', backref='assessment_components')
```

- [ ] **Step 5: Add new columns to `CourseImportJob`/`CourseImportError`**

In `CourseImportJob`, add immediately after `error_count`:
```python
    mismatched_count = db.Column(db.Integer, nullable=False, default=0, server_default='0')
```

In `CourseImportError`, add immediately after `reason`:
```python
    severity = db.Column(db.String(10), nullable=False, default='error', server_default='error')
```

- [ ] **Step 6: Write the migration**

Current head revision is `b7f4a1de9c63`. Create `migrations/versions/a29d6f0c81e5_course_offering_split.py`:

```python
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
        INSERT INTO course_prerequisites_new (id, course_id, prerequisite_course_id)
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
        INSERT INTO course_corequisites_new (id, course_id, corequisite_course_id)
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
```

- [ ] **Step 7: Apply the migration and verify**

Run: `flask db upgrade`

Watch for the `db.create_all()`-vs-Alembic hazard (documented in `docs/superpowers/CURRENT_STATE.md`) — this migration creates two brand-new tables (`courses`, plus the transient `_new` tables which get renamed away, so only `courses` persists as new) and drops/recreates `course_prerequisites`/`course_corequisites`. If `op.create_table('courses', ...)` fails with "table already exists," follow the documented recovery: confirm it's empty, drop it, let `db.create_all()` recreate it, comment out just that `create_table` block for one run, revert via `git checkout --` immediately after.

Verify with a throwaway script (run via `python`, then discard):
```python
from app import app
from models import Course, CourseOffering, CoursePrerequisite, CourseCorequisite, RegisteredCourse, CourseAssessmentComponent

with app.app_context():
    offerings = CourseOffering.query.order_by(CourseOffering.id).all()
    print(f'{len(offerings)} course_offerings rows, all with original ids/fields intact:')
    for o in offerings:
        print(' ', o.id, o.code, o.title, o.credits, '-> course_id', o.course_id)

    masters = Course.query.order_by(Course.code).all()
    print(f'{len(masters)} master Course rows:')
    for m in masters:
        print(' ', m.id, m.code, m.title, m.credits, '- offerings:', len(m.offerings))

    # Every offering must have a course_id set (no orphans)
    orphans = CourseOffering.query.filter(CourseOffering.course_id.is_(None)).count()
    assert orphans == 0, f'{orphans} offerings have no course_id'
    print('No orphaned offerings.')
```
Expected: no assertion errors; the CSC 212 case (or whatever real duplicate-code case exists) shows one master Course with 2+ offerings.

Then independently verify FK integrity at the SQL level (this migration is high-risk — a table rename plus two full table rebuilds):
```python
import sqlite3
conn = sqlite3.connect('instance/database.db')
cur = conn.cursor()
cur.execute('PRAGMA foreign_key_check')
print('FK violations:', cur.fetchall())
cur.execute('PRAGMA integrity_check')
print('integrity_check:', cur.fetchone())
for t in ['registered_courses', 'course_assessment_components', 'course_prerequisites', 'course_corequisites']:
    cur.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{t}'")
    print(t, '->', cur.fetchone()[0])
```
Expected: zero FK violations, `integrity_check` returns `ok`. `registered_courses`/`course_assessment_components` reference `course_offerings`; `course_prerequisites`/`course_corequisites` reference `courses` (the master).

- [ ] **Step 8: Commit**

```bash
git add models.py migrations/versions/a29d6f0c81e5_course_offering_split.py
git commit -m "feat: split Course into master Course + CourseOffering, repoint prerequisites/corequisites to master"
```

---

### Task 2: Course Catalog service layer

**Files:**
- Create: `services/admin_course_catalog.py`
- Modify: `services/admin_validation.py`

**Interfaces:**
- Consumes: `Course`, `CourseOffering`, `CoursePrerequisite`, `CourseCorequisite`, `db` from `models.py`.
- Produces: `services/admin_course_catalog.py` exposing `list_master_courses(search=None, status=None, page=1, per_page=20)`, `get_master_course(course_id)`, `get_master_course_detail(course_id)`, `create_master_course(code, title, credits, course_type, description=None)`, `update_master_course(course_id, code, title, credits, course_type, description=None)`, `set_master_course_status(course_id, status)`, `list_master_courses_for_picker(exclude_id=None)`, `set_prerequisites(course_id, prerequisite_course_ids)`, `set_corequisites(course_id, corequisite_course_ids)`. Also `is_course_catalog_code_unique(code, exclude_id=None)` in `services/admin_validation.py`.

- [ ] **Step 1: Add `is_course_catalog_code_unique` to `services/admin_validation.py`**

Add `Course` to the top-of-file import (it's already imported for the existing `is_course_code_unique`, which uses `Course` for what is now the OFFERING check against `CourseOffering` — see Task 3, which updates that existing function's model import to `CourseOffering`). Insert this new function immediately after `is_course_code_unique`:

```python
def is_course_catalog_code_unique(code, exclude_id=None):
    query = Course.query.filter(Course.code == code)
    if exclude_id is not None:
        query = query.filter(Course.id != exclude_id)
    return query.first() is None
```

- [ ] **Step 2: Create `services/admin_course_catalog.py`**

```python
from models import db, Course, CourseOffering, CoursePrerequisite, CourseCorequisite


def list_master_courses(search=None, status=None, page=1, per_page=20):
    query = Course.query
    if search:
        like = f'%{search}%'
        query = query.filter((Course.code.ilike(like)) | (Course.title.ilike(like)))
    if status:
        query = query.filter(Course.status == status)
    query = query.order_by(Course.code)

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return {'items': items, 'total': total, 'page': page, 'per_page': per_page}


def get_master_course(course_id):
    return Course.query.get_or_404(course_id)


def get_master_course_detail(course_id):
    course = get_master_course(course_id)
    prerequisites = [cp.prerequisite_course for cp in CoursePrerequisite.query.filter_by(course_id=course_id).all()]
    corequisites = [cc.corequisite_course for cc in CourseCorequisite.query.filter_by(course_id=course_id).all()]
    offerings = CourseOffering.query.filter_by(course_id=course_id).order_by(CourseOffering.id.desc()).all()
    return {
        'course': course, 'prerequisites': prerequisites, 'corequisites': corequisites,
        'offerings': offerings,
    }


def create_master_course(code, title, credits, course_type, description=None):
    course = Course(code=code, title=title, credits=credits, course_type=course_type, description=description or None)
    db.session.add(course)
    db.session.commit()
    return course


def update_master_course(course_id, code, title, credits, course_type, description=None):
    course = get_master_course(course_id)
    course.code = code
    course.title = title
    course.credits = credits
    course.course_type = course_type
    course.description = description or None
    db.session.commit()
    return course


def set_master_course_status(course_id, status):
    course = get_master_course(course_id)
    course.status = status
    db.session.commit()
    return course


def list_master_courses_for_picker(exclude_id=None):
    query = Course.query.filter(Course.status != 'archived')
    if exclude_id:
        query = query.filter(Course.id != exclude_id)
    return query.order_by(Course.code).all()


def set_prerequisites(course_id, prerequisite_course_ids):
    CoursePrerequisite.query.filter_by(course_id=course_id).delete()
    for prereq_id in prerequisite_course_ids:
        if prereq_id != course_id:
            db.session.add(CoursePrerequisite(course_id=course_id, prerequisite_course_id=prereq_id))
    db.session.commit()


def set_corequisites(course_id, corequisite_course_ids):
    CourseCorequisite.query.filter_by(course_id=course_id).delete()
    for coreq_id in corequisite_course_ids:
        if coreq_id != course_id:
            db.session.add(CourseCorequisite(course_id=course_id, corequisite_course_id=coreq_id))
    db.session.commit()
```

Note: `set_prerequisites`/`set_corequisites` are moved here verbatim from `services/admin_course.py` (Task 3 removes them from there) — same replace-all logic, now operating on master `course_id` values instead of offering ids.

- [ ] **Step 3: Run and verify**

Verify with a throwaway script:
```python
from app import app
from models import db, Course
from services.admin_course_catalog import (
    list_master_courses, get_master_course, get_master_course_detail,
    create_master_course, update_master_course, set_master_course_status,
    list_master_courses_for_picker, set_prerequisites, set_corequisites,
)
from services.admin_validation import is_course_catalog_code_unique

with app.app_context():
    assert is_course_catalog_code_unique('CSC 212') is False  # real seeded master course
    c = create_master_course('ZZTEST101', 'Test Course', 3, 'core', description='temp')
    update_master_course(c.id, 'ZZTEST101', 'Test Course Updated', 3, 'core')
    set_master_course_status(c.id, 'archived')
    detail = get_master_course_detail(c.id)
    assert detail['offerings'] == []
    other = Course.query.filter(Course.id != c.id).first()
    set_prerequisites(c.id, [other.id])
    assert get_master_course_detail(c.id)['prerequisites'] == [other]
    set_prerequisites(c.id, [])
    db.session.delete(c)
    db.session.commit()
    print('Course catalog service layer OK.')
```
Expected: no assertion errors, test row cleaned up.

- [ ] **Step 4: Commit**

```bash
git add services/admin_course_catalog.py services/admin_validation.py
git commit -m "feat: add Course Catalog service layer for master course CRUD and prerequisite/corequisite management"
```

---

### Task 3: Offering service layer updates

**Files:**
- Modify: `services/admin_course.py`

**Interfaces:**
- Consumes: `Course`, `CourseOffering`, `Department`, `CourseAssessmentComponent`, `RegisteredCourse`, `db` from `models.py`.
- Produces (replacing the current module's contents): `list_courses(...)` (same signature, now queries `CourseOffering`), `get_course(course_id)`, `get_enrollment_count(course_id)`, `create_course(course_id, department_id, level, academic_session_id, semester_id, instructor=None, schedule=None, max_capacity=None)` (new signature — `course_id` selects the master, catalog fields mirror from it instead of being passed in), `update_course(course_id, **fields)` (offering fields only — `course_id` itself CAN be one of the fields, re-mirroring catalog data if changed), `set_course_status(course_id, status)`, `get_course_detail(course_id)` (now returns only `course` + `assessment_components`, no prerequisites/corequisites), `list_courses_for_picker(exclude_id=None)`, `set_assessment_components(course_id, components)`.

- [ ] **Step 1: Rewrite `services/admin_course.py`**

Replace the entire file:

```python
from models import db, CourseOffering, Course, Department, CourseAssessmentComponent, RegisteredCourse


def list_courses(search=None, department_id=None, level=None, semester_id=None,
                  min_credits=None, max_credits=None, status=None, page=1, per_page=20, sort='code'):
    query = CourseOffering.query
    if search:
        like = f'%{search}%'
        query = query.filter(
            (CourseOffering.code.ilike(like)) | (CourseOffering.title.ilike(like)) | (CourseOffering.description.ilike(like))
        )
    if department_id:
        query = query.filter(CourseOffering.department_id == department_id)
    if level:
        query = query.filter(CourseOffering.level == level)
    if semester_id:
        query = query.filter(CourseOffering.semester_id == semester_id)
    if min_credits is not None:
        query = query.filter(CourseOffering.credits >= min_credits)
    if max_credits is not None:
        query = query.filter(CourseOffering.credits <= max_credits)
    if status:
        query = query.filter(CourseOffering.status == status)

    sort_columns = {'code': CourseOffering.code, 'title': CourseOffering.title, 'credits': CourseOffering.credits, 'status': CourseOffering.status}
    query = query.order_by(sort_columns.get(sort, CourseOffering.code))

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return {'items': items, 'total': total, 'page': page, 'per_page': per_page}


def get_course(course_id):
    return CourseOffering.query.get_or_404(course_id)


def get_enrollment_count(course_id):
    """Current number of students registered for this course offering. A
    one-line duplicate of services/registration.py's get_course_enrollment_count
    — trivial enough that a shared import isn't worth the cross-module coupling."""
    return RegisteredCourse.query.filter_by(course_id=course_id).count()


def create_course(course_id, department_id, level, academic_session_id, semester_id,
                   instructor=None, schedule=None, max_capacity=None):
    """course_id selects the master Course this offering belongs to — its
    code/title/credits/course_type/description are mirrored into this
    offering's own columns at creation time (dual-write), so every existing
    read path that reads offering.code/.title/etc. keeps working unchanged."""
    master = Course.query.get_or_404(course_id)
    department = Department.query.get(department_id)
    offering = CourseOffering(
        code=master.code, title=master.title, credits=master.credits, course_type=master.course_type,
        description=master.description, course_id=master.id,
        department=department.name if department else '', department_id=department_id,
        level=level or None, academic_session_id=academic_session_id, semester_id=semester_id,
        instructor=instructor or None, schedule=schedule or None,
        max_capacity=max_capacity, status='active',
    )
    db.session.add(offering)
    db.session.commit()
    return offering


def update_course(course_id, **fields):
    """fields may include department_id, level, academic_session_id,
    semester_id, instructor, schedule, max_capacity, and optionally
    'master_course_id' to re-link this offering to a different master
    (which re-mirrors code/title/credits/course_type/description from the
    new master)."""
    offering = get_course(course_id)
    if fields.get('department_id'):
        department = Department.query.get(fields['department_id'])
        if department:
            fields['department'] = department.name
    new_master_id = fields.pop('master_course_id', None)
    if new_master_id and new_master_id != offering.course_id:
        master = Course.query.get_or_404(new_master_id)
        offering.course_id = master.id
        offering.code = master.code
        offering.title = master.title
        offering.credits = master.credits
        offering.course_type = master.course_type
        offering.description = master.description
    for key, value in fields.items():
        setattr(offering, key, value)
    db.session.commit()
    return offering


def set_course_status(course_id, status):
    offering = get_course(course_id)
    offering.status = status
    db.session.commit()
    return offering


def get_course_detail(course_id):
    offering = get_course(course_id)
    assessment_components = CourseAssessmentComponent.query.filter_by(course_id=course_id).all()
    return {'course': offering, 'assessment_components': assessment_components}


def list_courses_for_picker(exclude_id=None):
    query = CourseOffering.query.filter(CourseOffering.status != 'archived')
    if exclude_id:
        query = query.filter(CourseOffering.id != exclude_id)
    return query.order_by(CourseOffering.code).all()


def set_assessment_components(course_id, components):
    """components: list of {'name': str, 'weight_percent': int}."""
    CourseAssessmentComponent.query.filter_by(course_id=course_id).delete()
    for comp in components:
        if comp.get('name') and comp.get('weight_percent') is not None:
            db.session.add(CourseAssessmentComponent(
                course_id=course_id, name=comp['name'], weight_percent=comp['weight_percent'],
            ))
    db.session.commit()
```

Note what's REMOVED from this file vs. the pre-split version: `set_prerequisites`/`set_corequisites` (moved to `services/admin_course_catalog.py` in Task 2 — do not leave a duplicate copy here).

- [ ] **Step 2: Update `is_course_code_unique` in `services/admin_validation.py`**

This existing function (checks offering-level code+session+semester uniqueness) currently queries `Course`. Update it to query `CourseOffering`:

```python
def is_course_code_unique(code, academic_session_id, semester_id, exclude_id=None):
    query = CourseOffering.query.filter(
        CourseOffering.code == code,
        CourseOffering.academic_session_id == academic_session_id,
        CourseOffering.semester_id == semester_id,
    )
    if exclude_id is not None:
        query = query.filter(CourseOffering.id != exclude_id)
    return query.first() is None
```

Add `CourseOffering` to the top-of-file import line in `services/admin_validation.py`.

- [ ] **Step 3: Run and verify**

Verify with a throwaway script:
```python
from app import app
from models import db, Course, Department, AcademicSession, Semester
from services.admin_course import list_courses, get_course, create_course, update_course, set_course_status, get_course_detail, list_courses_for_picker, get_enrollment_count

with app.app_context():
    master = Course.query.filter_by(code='CSC 212').first()
    dept = Department.query.first()
    session_obj = AcademicSession.query.first()
    semester = Semester.query.first()

    offering = create_course(master.id, dept.id, 'Year 1', session_obj.id, semester.id)
    assert offering.code == master.code and offering.title == master.title and offering.credits == master.credits
    assert offering.course_id == master.id
    print('create_course mirrors master fields correctly.')

    update_course(offering.id, level='Year 2')
    assert get_course(offering.id).level == 'Year 2'

    detail = get_course_detail(offering.id)
    assert 'prerequisites' not in detail and 'corequisites' not in detail
    assert 'assessment_components' in detail
    print('get_course_detail no longer returns prerequisites/corequisites.')

    assert get_enrollment_count(offering.id) == 0

    db.session.delete(offering)
    db.session.commit()
    print('Offering service layer OK.')
```
Expected: no assertion errors, test row cleaned up.

- [ ] **Step 4: Commit**

```bash
git add services/admin_course.py services/admin_validation.py
git commit -m "feat: update offering service layer to key create/update against a chosen master Course"
```

---

### Task 4: CSV import updates

**Files:**
- Modify: `services/course_import.py`

**Interfaces:**
- Consumes: `Course`, `CourseOffering`, `CourseImportJob`, `CourseImportError`, `db` from `models.py`; `parse_csv`, `create_import_job`, `record_import_error`, `finalize_import_job` from `services/admin_import.py` (unchanged, not modified by this task); `resolve_department`, `resolve_semester` from `services/admin_validation.py`.
- Produces (same public functions, updated internals): `preview_courses_csv(file_storage)`, `import_courses_csv(file_storage, admin_user, academic_session_id)`.

- [ ] **Step 1: Update `services/course_import.py`**

Change the import line (currently `from models import db, Course, CourseImportJob, CourseImportError`) to:
```python
import json

from models import db, Course, CourseOffering, CourseImportJob, CourseImportError
from services.admin_import import parse_csv, create_import_job, record_import_error, finalize_import_job
from services.admin_validation import resolve_department, resolve_semester
```

`_validate_row` and `preview_courses_csv` are UNCHANGED — they don't touch the DB beyond read-only lookups, and the CSV's required/optional columns don't change.

Replace `import_courses_csv` (the loop body starting at `existing = Course.query.filter_by(...)`) with:

```python
def import_courses_csv(file_storage, admin_user, academic_session_id):
    filename = file_storage.filename if file_storage else 'unknown.csv'
    job = create_import_job(CourseImportJob, admin_user, filename)

    rows, parse_error = parse_csv(file_storage, REQUIRED_HEADERS)
    if parse_error:
        record_import_error(CourseImportError, job, 0, {}, parse_error)
        finalize_import_job(job, 0, 0, 0, 0, 1)
        job.status = 'failed'
        db.session.commit()
        return job

    created = updated = skipped = duplicates = errors = mismatched = 0
    seen_dedup_keys = set()

    for row_number, row in enumerate(rows, start=2):
        fields, error, category = _validate_row(row, seen_dedup_keys)
        if error:
            record_import_error(CourseImportError, job, row_number, row, error)
            if category == 'duplicate':
                duplicates += 1
            else:
                errors += 1
            continue
        seen_dedup_keys.add(fields['dedup_key'])

        code, department, semester = fields['code'], fields['department'], fields['semester']
        title, credits, level, course_type = fields['title'], fields['credits'], fields['level'], fields['course_type']
        description, instructor, schedule, max_capacity = fields['description'], fields['instructor'], fields['schedule'], fields['max_capacity']

        master = Course.query.filter_by(code=code).first()
        if master is None:
            master = Course(code=code, title=title, credits=credits, course_type=course_type, description=description or None)
            db.session.add(master)
            db.session.flush()  # assigns master.id without committing yet
        else:
            mismatch = (
                master.title != title or master.credits != credits
                or master.course_type != course_type or (master.description or '') != description
            )
            if mismatch:
                db.session.add(CourseImportError(
                    import_job_id=job.id, row_number=row_number, raw_row=json.dumps(row),
                    reason=f'Row title/credits/course_type/description differs from existing master course "{code}" — master was not changed.',
                    severity='warning',
                ))
                mismatched += 1

        existing = CourseOffering.query.filter_by(
            code=code, academic_session_id=academic_session_id, semester_id=semester.id,
        ).first()
        if existing:
            changed = (
                existing.department_id != department.id or existing.level != (level or None)
                or existing.instructor != (instructor or None) or existing.schedule != (schedule or None)
                or existing.max_capacity != max_capacity
            )
            if changed:
                existing.department_id = department.id
                existing.department = department.name
                existing.level = level or None
                existing.instructor = instructor or None
                existing.schedule = schedule or None
                existing.max_capacity = max_capacity
                updated += 1
            else:
                skipped += 1
            continue

        db.session.add(CourseOffering(
            code=master.code, title=master.title, credits=master.credits, course_type=master.course_type,
            description=master.description, course_id=master.id,
            department=department.name, department_id=department.id,
            level=level or None, academic_session_id=academic_session_id,
            semester_id=semester.id, instructor=instructor or None,
            schedule=schedule or None, max_capacity=max_capacity, status='active',
        ))
        created += 1

    db.session.commit()
    finalize_import_job(job, created, updated, skipped, duplicates, errors)
    job.mismatched_count = mismatched
    db.session.commit()
    return job
```

Note: the offering-level "changed" detection no longer compares `title`/`credits`/`course_type`/`description` (those are the master's job now, handled by the mismatch-warning path above) — only offering-specific fields (`department_id`, `level`, `instructor`, `schedule`, `max_capacity`) trigger an "updated" count.

- [ ] **Step 2: Run and verify**

Verify with a throwaway script that builds an in-memory CSV (using `io.BytesIO` wrapped in a Werkzeug `FileStorage`, matching the pattern any existing import test/verification in this repo would use) covering: (a) a brand-new code creates both master + offering, (b) an existing code with matching fields creates only the offering (no mismatch warning), (c) an existing code with a different title creates the offering AND records a `severity='warning'` `CourseImportError` without mutating the master, (d) `job.mismatched_count` reflects case (c)'s count. Clean up all created rows and the import job afterward.

- [ ] **Step 3: Commit**

```bash
git add services/course_import.py
git commit -m "feat: update CSV course import to find-or-create master courses and flag catalog mismatches"
```

---

### Task 5: Student-facing service updates

**Files:**
- Modify: `services/registration.py`
- Modify: `services/validation.py`

**Interfaces:**
- Mechanical rename only — no behavior change. `services/registration.py`'s `add_course`, `drop_course`, `get_course_enrollment_count` now query `CourseOffering` instead of `Course`. `services/validation.py`'s `validate_course_eligible` reads `course_offering.department`/`.level`/`.academic_session_id`/`.semester_id` (same field names, same values, since these columns are unchanged on the renamed table).

- [ ] **Step 1: Update `services/registration.py`**

Find the import line that includes `Course` (near the top of the file, alongside `RegistrationPeriod`, `DepartmentRegistrationRule`, etc.) and change `Course` to `CourseOffering`.

In `get_course_enrollment_count` (currently `services/registration.py:215-219`), no logic change needed — it only ever used `course_id` against `RegisteredCourse`, not the `Course`/`CourseOffering` model directly. Update its docstring's parenthetical if it names `Course` explicitly (check the actual current text) to say `CourseOffering` instead.

In `add_course` (currently `services/registration.py:222-265`), change:
```python
    course = Course.query.get(course_id)
```
to:
```python
    course = CourseOffering.query.get(course_id)
```
The rest of the function (`validate_course_eligible(course, user, period)`, `get_credit_limits`, `course.max_capacity`, `RegisteredCourse(course_id=course.id)`, etc.) needs no further changes — every attribute access (`course.credits`, `course.code`, `course.max_capacity`) is on a column that still exists, unchanged, on `CourseOffering`.

`drop_course` needs no changes — it never queries `Course`/`CourseOffering` directly, only `RegisteredCourse` by `course_id`.

- [ ] **Step 2: Update `services/validation.py`**

No import changes needed — `validate_course_eligible`'s `course` parameter is just passed in by the caller (`add_course`, which now passes a `CourseOffering` instance). The function body (`course.department`, `course.level`, `course.academic_session_id`, `course.semester_id`) needs zero changes — same attribute names on the renamed model. Update the docstring's reference to "a course" if it's more precise to say "a course offering" — cosmetic, use your judgment, not required.

- [ ] **Step 3: Run and verify**

Verify with a throwaway script exercising the full student registration path end-to-end: create/find a `StudentRegistration` for a seeded student against the active period, call `add_course` with a real `CourseOffering` id matching the student's department/level/session/semester, confirm it succeeds and a `RegisteredCourse` row is created; call `add_course` with a mismatched-department offering, confirm `RegistrationError` is raised with the expected message; call `drop_course`, confirm the `RegisteredCourse` row is removed. Clean up all test data afterward.

- [ ] **Step 4: Commit**

```bash
git add services/registration.py services/validation.py
git commit -m "feat: repoint student-facing registration/eligibility logic from Course to CourseOffering"
```

---

### Task 6: Admin routes

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: everything produced by Tasks 2-4's service layers.
- Produces: new routes `admin_course_catalog` (list), `admin_course_catalog_new`, `admin_course_catalog_detail`, `admin_course_catalog_edit`, `admin_course_catalog_prerequisites`, `admin_course_catalog_corequisites`, `admin_course_catalog_activate`, `admin_course_catalog_archive`. Updated routes: `admin_course_new`, `admin_course_edit` (master picker instead of free-text catalog fields), `admin_course_detail` (no more prerequisite/corequisite context). Removed routes: `admin_course_prerequisites`, `admin_course_corequisites` (moved to the catalog routes above).

- [ ] **Step 1: Update imports**

Change the existing `from services.admin_course import ...` line (`app.py:70`) — remove `set_prerequisites, set_corequisites` (moved), keep the rest:
```python
from services.admin_course import list_courses, get_course, create_course, update_course, set_course_status, get_course_detail, list_courses_for_picker, set_assessment_components, get_enrollment_count
```

Add a new import block immediately after it:
```python
from services.admin_course_catalog import (
    list_master_courses, get_master_course, get_master_course_detail,
    create_master_course, update_master_course, set_master_course_status,
    list_master_courses_for_picker, set_prerequisites, set_corequisites,
)
```

Add `is_course_catalog_code_unique` to the existing `services.admin_validation` import line.

- [ ] **Step 2: Add the Course Catalog routes**

Insert immediately before the existing `@app.route('/admin/courses')` block (currently `app.py:2064`):

```python
@app.route('/admin/course-catalog')
@permission_required('courses.manage')
def admin_course_catalog():
    search = request.args.get('search', '').strip() or None
    status = request.args.get('status', '').strip() or None
    page = request.args.get('page', 1, type=int)
    result = list_master_courses(search=search, status=status, page=page)
    return render_template(
        'admin/course_catalog.html', result=result, search=search or '', status=status or '',
    )


@app.route('/admin/course-catalog/new', methods=['GET', 'POST'])
@permission_required('courses.manage')
def admin_course_catalog_new():
    if request.method == 'GET':
        return render_template('admin/course_catalog_form.html', course=None)

    code = request.form.get('code', '').strip().upper()
    title = request.form.get('title', '').strip()
    credits = request.form.get('credits', type=int)
    course_type = request.form.get('course_type', '').strip()
    description = request.form.get('description', '').strip()

    errors = []
    if not code or not title or not credits or not course_type:
        errors.append('Code, title, credits, and course type are required.')
    elif not is_course_catalog_code_unique(code):
        errors.append(f'Course code "{code}" already exists in the catalog.')
    if errors:
        for e in errors:
            flash(e)
        return render_template('admin/course_catalog_form.html', course=None, form=request.form)

    course = create_master_course(code, title, credits, course_type, description=description)
    log_admin_action(current_user, 'course_catalog_created', target_type='course', target_id=course.id,
                      details=f'code={code}', ip_address=request.remote_addr)
    flash(f'Course "{code}" added to the catalog.')
    return redirect(url_for('admin_course_catalog_detail', course_id=course.id))


@app.route('/admin/course-catalog/<int:course_id>')
@permission_required('courses.manage')
def admin_course_catalog_detail(course_id):
    detail = get_master_course_detail(course_id)
    other_courses = list_master_courses_for_picker(exclude_id=course_id)
    return render_template('admin/course_catalog.html', detail=detail, result=None, other_courses=other_courses)


@app.route('/admin/course-catalog/<int:course_id>/edit', methods=['GET', 'POST'])
@permission_required('courses.manage')
def admin_course_catalog_edit(course_id):
    course = get_master_course(course_id)
    if request.method == 'GET':
        return render_template('admin/course_catalog_form.html', course=course)

    code = request.form.get('code', '').strip().upper()
    title = request.form.get('title', '').strip()
    credits = request.form.get('credits', type=int)
    course_type = request.form.get('course_type', '').strip()
    description = request.form.get('description', '').strip()

    errors = []
    if not code or not title or not credits or not course_type:
        errors.append('Code, title, credits, and course type are required.')
    elif not is_course_catalog_code_unique(code, exclude_id=course_id):
        errors.append(f'Course code "{code}" already exists in the catalog.')
    if errors:
        for e in errors:
            flash(e)
        return render_template('admin/course_catalog_form.html', course=course, form=request.form)

    update_master_course(course_id, code, title, credits, course_type, description=description)
    log_admin_action(current_user, 'course_catalog_updated', target_type='course', target_id=course_id,
                      details=f'code={code}', ip_address=request.remote_addr)
    flash(f'Course "{code}" updated.')
    return redirect(url_for('admin_course_catalog_detail', course_id=course_id))


@app.route('/admin/course-catalog/<int:course_id>/prerequisites', methods=['POST'])
@permission_required('courses.manage')
def admin_course_catalog_prerequisites(course_id):
    prereq_ids = request.form.getlist('prerequisite_ids', type=int)
    set_prerequisites(course_id, prereq_ids)
    log_admin_action(current_user, 'course_catalog_prerequisites_updated', target_type='course', target_id=course_id,
                      details=f'count={len(prereq_ids)}', ip_address=request.remote_addr)
    flash('Prerequisites updated.')
    return redirect(url_for('admin_course_catalog_detail', course_id=course_id))


@app.route('/admin/course-catalog/<int:course_id>/corequisites', methods=['POST'])
@permission_required('courses.manage')
def admin_course_catalog_corequisites(course_id):
    coreq_ids = request.form.getlist('corequisite_ids', type=int)
    set_corequisites(course_id, coreq_ids)
    log_admin_action(current_user, 'course_catalog_corequisites_updated', target_type='course', target_id=course_id,
                      details=f'count={len(coreq_ids)}', ip_address=request.remote_addr)
    flash('Corequisites updated.')
    return redirect(url_for('admin_course_catalog_detail', course_id=course_id))


@app.route('/admin/course-catalog/<int:course_id>/activate', methods=['POST'])
@permission_required('courses.manage')
def admin_course_catalog_activate(course_id):
    set_master_course_status(course_id, 'active')
    log_admin_action(current_user, 'course_catalog_status_changed', target_type='course', target_id=course_id,
                      details='status=active', ip_address=request.remote_addr)
    flash('Course activated.')
    return redirect(url_for('admin_course_catalog_detail', course_id=course_id))


@app.route('/admin/course-catalog/<int:course_id>/archive', methods=['POST'])
@permission_required('courses.manage')
def admin_course_catalog_archive(course_id):
    set_master_course_status(course_id, 'archived')
    log_admin_action(current_user, 'course_catalog_status_changed', target_type='course', target_id=course_id,
                      details='status=archived', ip_address=request.remote_addr)
    flash('Course archived.')
    return redirect(url_for('admin_course_catalog_detail', course_id=course_id))
```

- [ ] **Step 3: Update `admin_course_new` to use the master picker**

Replace the existing route (`app.py:2104-2143`):

```python
@app.route('/admin/courses/new', methods=['GET', 'POST'])
@permission_required('courses.manage')
def admin_course_new():
    departments = list_active_departments()
    sessions = list_sessions()
    semesters = list_semesters()
    master_courses = list_master_courses_for_picker()
    if request.method == 'GET':
        return render_template('admin/course_form.html', course=None, departments=departments, sessions=sessions, semesters=semesters, master_courses=master_courses)

    master_course_id = request.form.get('master_course_id', type=int)
    department_id = request.form.get('department_id', type=int)
    max_capacity = request.form.get('max_capacity', type=int)
    level = request.form.get('level', '').strip()
    academic_session_id = request.form.get('academic_session_id', type=int)
    semester_id = request.form.get('semester_id', type=int)
    instructor = request.form.get('instructor', '').strip()
    schedule = request.form.get('schedule', '').strip()

    errors = []
    if not master_course_id or not department_id or not academic_session_id or not semester_id:
        errors.append('Master course, department, session, and semester are required.')
    else:
        master = get_master_course(master_course_id)
        if not is_course_code_unique(master.code, academic_session_id, semester_id):
            errors.append(f'"{master.code}" already has an offering for that session/semester.')
    if errors:
        for e in errors:
            flash(e)
        return render_template('admin/course_form.html', course=None, departments=departments, sessions=sessions, semesters=semesters, master_courses=master_courses, form=request.form)

    offering = create_course(
        master_course_id, department_id, level, academic_session_id, semester_id,
        instructor=instructor, schedule=schedule, max_capacity=max_capacity,
    )
    log_admin_action(current_user, 'course_created', target_type='course', target_id=offering.id,
                      details=f'code={offering.code} master_course_id={master_course_id}', ip_address=request.remote_addr)
    flash(f'Course offering "{offering.code}" created.')
    return redirect(url_for('admin_course_detail', course_id=offering.id))
```

Note: the Semester dropdown keeps its today's-exact behavior — the full `list_semesters()` list, not filtered by session (unlike the Registration Period form, this offering form has no "session already picked" step before rendering). `list_semesters` is already imported at the top of `app.py` from `services.admin_session` — no new import needed.

- [ ] **Step 4: Update `admin_course_edit` similarly**

Replace the existing route (`app.py:2202-2244`):

```python
@app.route('/admin/courses/<int:course_id>/edit', methods=['GET', 'POST'])
@permission_required('courses.manage')
def admin_course_edit(course_id):
    offering = get_course(course_id)
    departments = list_active_departments()
    sessions = list_sessions()
    semesters = list_semesters()
    master_courses = list_master_courses_for_picker()
    if request.method == 'GET':
        return render_template('admin/course_form.html', course=offering, departments=departments, sessions=sessions, semesters=semesters, master_courses=master_courses)

    master_course_id = request.form.get('master_course_id', type=int)
    department_id = request.form.get('department_id', type=int)
    max_capacity = request.form.get('max_capacity', type=int)
    level = request.form.get('level', '').strip()
    academic_session_id = request.form.get('academic_session_id', type=int)
    semester_id = request.form.get('semester_id', type=int)
    instructor = request.form.get('instructor', '').strip()
    schedule = request.form.get('schedule', '').strip()

    errors = []
    if not master_course_id or not department_id or not academic_session_id or not semester_id:
        errors.append('Master course, department, session, and semester are required.')
    else:
        master = get_master_course(master_course_id)
        if not is_course_code_unique(master.code, academic_session_id, semester_id, exclude_id=course_id):
            errors.append(f'"{master.code}" already has an offering for that session/semester.')
    if errors:
        for e in errors:
            flash(e)
        return render_template('admin/course_form.html', course=offering, departments=departments, sessions=sessions, semesters=semesters, master_courses=master_courses, form=request.form)

    update_course(
        course_id, master_course_id=master_course_id, department_id=department_id,
        level=level or None, academic_session_id=academic_session_id, semester_id=semester_id,
        instructor=instructor or None, schedule=schedule or None, max_capacity=max_capacity,
    )
    log_admin_action(current_user, 'course_updated', target_type='course', target_id=course_id,
                      details=f'master_course_id={master_course_id}', ip_address=request.remote_addr)
    flash('Course offering updated.')
    return redirect(url_for('admin_course_detail', course_id=course_id))
```

Also add `semesters=list_semesters()` to `admin_course_new`'s two `render_template('admin/course_form.html', ...)` calls (GET and the error re-render), for symmetry with `admin_course_edit` — this was omitted from Step 3's listing for brevity; both routes need it.

- [ ] **Step 5: Remove the old prerequisite/corequisite routes**

Delete `admin_course_prerequisites` and `admin_course_corequisites` (currently `app.py:2155-2174`) entirely — their functionality now lives at `admin_course_catalog_prerequisites`/`admin_course_catalog_corequisites` (Step 2).

- [ ] **Step 6: Update `admin_course_detail`**

The route itself (`app.py:2146-2152`) needs no change — `get_course_detail` (Task 3) already returns the right shape. Only the template consuming it changes (Task 7).

- [ ] **Step 7: Add the sidebar nav item**

In `templates/admin/base_admin.html`, insert immediately after the Courses `<li>`:
```html
                <li><a href="{{ url_for('admin_course_catalog') }}" class="{{ 'active' if request.endpoint and request.endpoint.startswith('admin_course_catalog') }}"><i class="fas fa-book-open"></i> Course Catalog</a></li>
```

- [ ] **Step 8: Verify**

Run a throwaway `test_client` script (as Academic Administrator or Super Administrator — check which role has `courses.manage`, matching the pattern established in prior sub-projects' verification scripts): confirm `/admin/course-catalog` and its CRUD routes work end-to-end, confirm `/admin/courses/new` now requires a `master_course_id` and correctly rejects a duplicate session/semester offering for the same master, confirm the old `/admin/courses/<id>/prerequisites` route no longer exists (404) and the new catalog route works instead.

- [ ] **Step 9: Commit**

```bash
git add app.py templates/admin/base_admin.html
git commit -m "feat: add Course Catalog admin routes, rework offering routes to use master course picker"
```

---

### Task 7: Admin templates

**Files:**
- Create: `templates/admin/course_catalog.html`
- Create: `templates/admin/course_catalog_form.html`
- Modify: `templates/admin/course_form.html`
- Modify: `templates/admin/course_detail.html`
- Modify: `templates/admin/course_import_report.html`

**Interfaces:**
- Consumes context variables exactly as passed by Task 6's routes.

- [ ] **Step 1: Create `templates/admin/course_catalog.html`**

Mirrors `templates/admin/departments.html`'s list/detail structure, with prerequisite/corequisite management (moved from `course_detail.html`) added to the detail branch:

```html
{% extends "admin/base_admin.html" %}

{% block breadcrumbs %}Course Catalog{% endblock %}

{% block content %}
{% if detail %}
<div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; padding: 1.5rem; margin-bottom: 1.5rem;">
    <h2 style="margin-top:0;">{{ detail.course.code }} — {{ detail.course.title }}</h2>
    <p style="color: var(--text-muted);">{{ detail.course.credits }} credits &middot; <span style="text-transform:capitalize;">{{ detail.course.course_type }}</span> &middot; <span style="text-transform:capitalize;">{{ detail.course.status }}</span></p>
    {% if detail.course.description %}<p style="margin-top:1rem;">{{ detail.course.description }}</p>{% endif %}
    <a href="{{ url_for('admin_course_catalog_edit', course_id=detail.course.id) }}" style="color: var(--primary-dark); font-weight:600;">Edit</a>
    &nbsp;&middot;&nbsp;
    <a href="{{ url_for('admin_course_catalog') }}" style="color: var(--text-muted);">Back to Course Catalog</a>
</div>

<div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; padding: 1.5rem; margin-bottom:1.5rem;">
    <h3 style="margin-top:0;">Offerings</h3>
    <table style="width:100%; border-collapse:collapse;">
        <thead>
            <tr style="text-align:left; border-bottom: 1px solid var(--border-color);">
                <th style="padding:0.6rem;">Session</th>
                <th style="padding:0.6rem;">Semester</th>
                <th style="padding:0.6rem;">Department</th>
                <th style="padding:0.6rem;">Status</th>
            </tr>
        </thead>
        <tbody>
            {% for o in detail.offerings %}
            <tr style="border-bottom: 1px solid var(--border-color);">
                <td style="padding:0.6rem;"><a href="{{ url_for('admin_course_detail', course_id=o.id) }}" style="color: var(--text-main); text-decoration:none;">{{ o.academic_session.name }}</a></td>
                <td style="padding:0.6rem;">{{ o.semester.name }}</td>
                <td style="padding:0.6rem;">{{ o.department }}</td>
                <td style="padding:0.6rem; text-transform:capitalize;">{{ o.status }}</td>
            </tr>
            {% else %}
            <tr><td colspan="4" style="padding:1.2rem; text-align:center; color: var(--text-muted);">No offerings yet.</td></tr>
            {% endfor %}
        </tbody>
    </table>
</div>

<div style="display:grid; grid-template-columns: 1fr 1fr; gap:1.5rem;">
    <div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; padding: 1.5rem;">
        <h3 style="margin-top:0;">Prerequisites</h3>
        <form method="POST" action="{{ url_for('admin_course_catalog_prerequisites', course_id=detail.course.id) }}">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <select name="prerequisite_ids" multiple size="6" style="width:100%; padding:0.5rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main); margin-bottom:0.8rem;">
                {% set prereq_ids = detail.prerequisites|map(attribute='id')|list %}
                {% for c in other_courses %}
                <option value="{{ c.id }}" {{ 'selected' if c.id in prereq_ids }}>{{ c.code }} — {{ c.title }}</option>
                {% endfor %}
            </select>
            <button type="submit" style="padding:0.5rem 1rem; background: var(--primary); color:white; border:none; border-radius:0.5rem; cursor:pointer;">Save</button>
        </form>
    </div>
    <div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; padding: 1.5rem;">
        <h3 style="margin-top:0;">Corequisites</h3>
        <form method="POST" action="{{ url_for('admin_course_catalog_corequisites', course_id=detail.course.id) }}">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <select name="corequisite_ids" multiple size="6" style="width:100%; padding:0.5rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main); margin-bottom:0.8rem;">
                {% set coreq_ids = detail.corequisites|map(attribute='id')|list %}
                {% for c in other_courses %}
                <option value="{{ c.id }}" {{ 'selected' if c.id in coreq_ids }}>{{ c.code }} — {{ c.title }}</option>
                {% endfor %}
            </select>
            <button type="submit" style="padding:0.5rem 1rem; background: var(--primary); color:white; border:none; border-radius:0.5rem; cursor:pointer;">Save</button>
        </form>
    </div>
</div>
{% else %}
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem;">
    <form method="GET" style="display:flex; gap:0.6rem;">
        <input type="text" name="search" value="{{ search }}" placeholder="Search code or title" style="padding:0.5rem 0.8rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main);">
        <select name="status" style="padding:0.5rem 0.8rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main);">
            <option value="" {{ 'selected' if not status }}>All statuses</option>
            <option value="active" {{ 'selected' if status == 'active' }}>Active</option>
            <option value="archived" {{ 'selected' if status == 'archived' }}>Archived</option>
        </select>
        <button type="submit" style="padding:0.5rem 1rem; border:none; border-radius:0.5rem; background: var(--primary); color:white; cursor:pointer;">Filter</button>
    </form>
    <a href="{{ url_for('admin_course_catalog_new') }}" style="padding:0.6rem 1.2rem; background: var(--primary); color:white; border-radius:0.5rem; text-decoration:none; font-weight:600;"><i class="fas fa-plus"></i> New Catalog Course</a>
</div>

<div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; overflow:hidden;">
    <table style="width:100%; border-collapse:collapse;">
        <thead>
            <tr style="text-align:left; border-bottom: 1px solid var(--border-color);">
                <th style="padding:0.8rem;">Code</th>
                <th style="padding:0.8rem;">Title</th>
                <th style="padding:0.8rem;">Credits</th>
                <th style="padding:0.8rem;">Type</th>
                <th style="padding:0.8rem;">Status</th>
                <th style="padding:0.8rem;"></th>
            </tr>
        </thead>
        <tbody>
            {% for c in result['items'] %}
            <tr style="border-bottom: 1px solid var(--border-color);">
                <td style="padding:0.8rem; font-family:monospace;"><a href="{{ url_for('admin_course_catalog_detail', course_id=c.id) }}" style="color: var(--text-main); font-weight:600; text-decoration:none;">{{ c.code }}</a></td>
                <td style="padding:0.8rem;">{{ c.title }}</td>
                <td style="padding:0.8rem;">{{ c.credits }}</td>
                <td style="padding:0.8rem; text-transform:capitalize;">{{ c.course_type }}</td>
                <td style="padding:0.8rem; text-transform:capitalize;">{{ c.status }}</td>
                <td style="padding:0.8rem; text-align:right;">
                    <a href="{{ url_for('admin_course_catalog_edit', course_id=c.id) }}" style="color: var(--primary-dark); margin-right:0.8rem;">Edit</a>
                    {% if c.status != 'active' %}
                    <form method="POST" action="{{ url_for('admin_course_catalog_activate', course_id=c.id) }}" style="display:inline;">
                        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                        <button type="submit" style="background:none; border:none; color: var(--success); cursor:pointer;">Activate</button>
                    </form>
                    {% else %}
                    <form method="POST" action="{{ url_for('admin_course_catalog_archive', course_id=c.id) }}" style="display:inline;" onsubmit="return confirm('Archive {{ c.code }}?');">
                        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                        <button type="submit" style="background:none; border:none; color: var(--danger); cursor:pointer;">Archive</button>
                    </form>
                    {% endif %}
                </td>
            </tr>
            {% else %}
            <tr><td colspan="6" style="padding:2rem; text-align:center; color: var(--text-muted);">No catalog courses found.</td></tr>
            {% endfor %}
        </tbody>
    </table>
</div>

{% set total_pages = ((result['total'] - 1) // result['per_page']) + 1 if result['total'] else 1 %}
{% if total_pages > 1 %}
<div style="display:flex; gap:0.5rem; justify-content:center; margin-top:1rem;">
    {% for p in range(1, total_pages + 1) %}
    <a href="{{ url_for('admin_course_catalog', search=search, status=status, page=p) }}"
       style="padding:0.4rem 0.8rem; border-radius:0.4rem; text-decoration:none; {{ 'background: var(--primary); color:white;' if p == result['page'] else 'background: var(--card-bg); color: var(--text-main); border:1px solid var(--border-color);' }}">{{ p }}</a>
    {% endfor %}
</div>
{% endif %}
{% endif %}
{% endblock %}
```

- [ ] **Step 2: Create `templates/admin/course_catalog_form.html`**

Mirrors `templates/admin/department_form.html`:

```html
{% extends "admin/base_admin.html" %}

{% block breadcrumbs %}Course Catalog / {{ 'Edit' if course else 'New' }}{% endblock %}

{% block content %}
<div style="max-width:560px; background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; padding: 1.5rem;">
    <h2 style="margin-top:0;">{{ 'Edit Catalog Course' if course else 'New Catalog Course' }}</h2>
    <form method="POST">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <div style="display:flex; gap:1rem; margin-bottom:1rem;">
            <div style="flex:1;">
                <label style="display:block; margin-bottom:0.3rem; font-weight:600;">Course Code</label>
                <input type="text" name="code" required value="{{ form.code if form else (course.code if course else '') }}"
                       style="width:100%; padding:0.6rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main); box-sizing:border-box; text-transform:uppercase;">
            </div>
            <div style="flex:2;">
                <label style="display:block; margin-bottom:0.3rem; font-weight:600;">Title</label>
                <input type="text" name="title" required value="{{ form.title if form else (course.title if course else '') }}"
                       style="width:100%; padding:0.6rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main); box-sizing:border-box;">
            </div>
        </div>
        <div style="display:flex; gap:1rem; margin-bottom:1rem;">
            <div style="flex:1;">
                <label style="display:block; margin-bottom:0.3rem; font-weight:600;">Credits</label>
                <input type="number" name="credits" required value="{{ form.credits if form else (course.credits if course else '') }}"
                       style="width:100%; padding:0.6rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main); box-sizing:border-box;">
            </div>
            <div style="flex:1;">
                <label style="display:block; margin-bottom:0.3rem; font-weight:600;">Course Type</label>
                <select name="course_type" required style="width:100%; padding:0.6rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main);">
                    {% set current_type = form.course_type if form else (course.course_type if course else '') %}
                    {% for value, label in [('core', 'Core'), ('elective', 'Elective'), ('lab', 'Lab')] %}
                    <option value="{{ value }}" {{ 'selected' if current_type == value }}>{{ label }}</option>
                    {% endfor %}
                </select>
            </div>
        </div>
        <div style="margin-bottom:1.5rem;">
            <label style="display:block; margin-bottom:0.3rem; font-weight:600;">Description (optional)</label>
            <textarea name="description" rows="3" style="width:100%; padding:0.6rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main); box-sizing:border-box;">{{ form.description if form else (course.description if course and course.description else '') }}</textarea>
        </div>
        <button type="submit" style="padding:0.7rem 1.5rem; background: var(--primary); color:white; border:none; border-radius:0.5rem; font-weight:600; cursor:pointer;">Save</button>
        <a href="{{ url_for('admin_course_catalog') }}" style="margin-left:1rem; color: var(--text-muted);">Cancel</a>
    </form>
</div>
{% endblock %}
```

- [ ] **Step 3: Update `templates/admin/course_form.html`**

Replace the "Course Code" + "Title" fields block (currently lines 10-21) and the "Description" block (currently lines 22-25) with a single Master Course picker:

```html
        <div style="margin-bottom:1rem;">
            <label style="display:block; margin-bottom:0.3rem; font-weight:600;">Master Course</label>
            <select name="master_course_id" required style="width:100%; padding:0.6rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main);">
                {% set current_master_id = form.master_course_id if form else (course.course_id if course else none) %}
                {% for mc in master_courses %}
                <option value="{{ mc.id }}" {{ 'selected' if current_master_id and current_master_id|int == mc.id }}>{{ mc.code }} — {{ mc.title }} ({{ mc.credits }} credits)</option>
                {% endfor %}
            </select>
            <p style="color: var(--text-muted); font-size:0.8rem; margin-top:0.3rem;">Don't see the course you need? <a href="{{ url_for('admin_course_catalog_new') }}" style="color: var(--primary-dark);">Add it to the Course Catalog</a> first.</p>
        </div>
```

Replace the "Department"/"Credits"/"Max Capacity" field-row (currently lines 26-45) — Credits is removed (it now comes from the master, shown read-only in the picker option text above), Department and Max Capacity stay:

```html
        <div style="display:flex; gap:1rem; margin-bottom:1rem;">
            <div style="flex:1;">
                <label style="display:block; margin-bottom:0.3rem; font-weight:600;">Department</label>
                <select name="department_id" required style="width:100%; padding:0.6rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main);">
                    {% for dept in departments %}
                    <option value="{{ dept.id }}" {{ 'selected' if course and course.department_id == dept.id }}>{{ dept.name }}</option>
                    {% endfor %}
                </select>
            </div>
            <div style="flex:1;">
                <label style="display:block; margin-bottom:0.3rem; font-weight:600;">Max Capacity</label>
                <input type="number" name="max_capacity" value="{{ form.max_capacity if form else (course.max_capacity if course and course.max_capacity else '') }}"
                       style="width:100%; padding:0.6rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main); box-sizing:border-box;">
            </div>
        </div>
```

Replace the "Level"/"Course Type" field-row (currently lines 46-60) — Course Type is removed (it now comes from the master), Level stays:

```html
        <div style="margin-bottom:1rem;">
            <label style="display:block; margin-bottom:0.3rem; font-weight:600;">Level</label>
            <input type="text" name="level" placeholder="e.g. ND1, Year 1" value="{{ form.level if form else (course.level if course and course.level else '') }}"
                   style="width:100%; padding:0.6rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main); box-sizing:border-box;">
        </div>
```

Everything else in the form (Academic Session, Semester, Instructor, Schedule — currently lines 61-90) stays as free-standing offering-specific fields, unchanged. `semesters` is already available to the template since Task 6 Step 3/4 pass `semesters=list_semesters()` from every route that renders this template.

- [ ] **Step 4: Update `templates/admin/course_detail.html`**

Remove the entire Prerequisites/Corequisites grid block (currently lines 41-68) — replace with a single link to the master course's catalog page:

```html
<p style="margin-bottom:1.5rem;"><a href="{{ url_for('admin_course_catalog_detail', course_id=course.course_id) }}" style="color: var(--primary-dark); font-weight:600;"><i class="fas fa-book-open"></i> View in Course Catalog</a> — manage prerequisites, corequisites, and catalog details there.</p>
```

The rest of the template (offering header, enrollment info, Activate/Deactivate/Archive, Assessment Structure section) is unchanged — `course.code`/`course.title`/`course.department`/`course.level`/`course.credits`/`course.status`/`course.instructor`/`course.schedule` are all still valid attribute reads on the (renamed) `CourseOffering` object passed in as `course`.

- [ ] **Step 5: Update `templates/admin/course_import_report.html`**

Add a 6th summary tile immediately after the existing 5 (`Created`/`Updated`/`Skipped`/`Duplicates`/`Errors`, currently lines 9-13):
```html
        <div><div style="font-size:1.4rem; font-weight:700; color: var(--warning);">{{ job.mismatched_count }}</div><div style="color: var(--text-muted); font-size:0.8rem;">Catalog Mismatches</div></div>
```

Split the existing "Row Errors" section (currently `{% if job.errors %}` block, lines 17-39) into two: filter to `severity == 'error'` rows in that section, and add a new section immediately after it for `severity == 'warning'` rows:

```html
{% set warning_rows = job.errors|selectattr('severity', 'equalto', 'warning')|list %}
{% if warning_rows %}
<div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; padding: 1.5rem; margin-top:1.5rem;">
    <h3 style="margin-top:0;">Catalog Mismatches (row still imported)</h3>
    <table style="width:100%; border-collapse:collapse;">
        <thead>
            <tr style="text-align:left; border-bottom: 1px solid var(--border-color);">
                <th style="padding:0.6rem;">Row</th>
                <th style="padding:0.6rem;">Reason</th>
                <th style="padding:0.6rem;">Raw Data</th>
            </tr>
        </thead>
        <tbody>
            {% for err in warning_rows %}
            <tr style="border-bottom: 1px solid var(--border-color);">
                <td style="padding:0.6rem;">{{ err.row_number }}</td>
                <td style="padding:0.6rem; color: var(--warning);">{{ err.reason }}</td>
                <td style="padding:0.6rem; font-family:monospace; font-size:0.75rem;">{{ err.raw_row }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endif %}
```

And change the existing `{% if job.errors %}` condition (the "Row Errors" section) to `{% if job.errors|selectattr('severity', 'equalto', 'error')|list %}` and its `{% for err in job.errors %}` loop to `{% for err in job.errors|selectattr('severity', 'equalto', 'error') %}`, so real errors and mismatch warnings render in their own separate sections.

- [ ] **Step 6: Manual verification**

Run the dev server, log in with a role that has `courses.manage`, and click through: Course Catalog list → New Catalog Course → detail page → prerequisite/corequisite assignment → Edit → Archive/Activate. Then: Courses (offerings) list → New Course (pick a master, fill offering fields) → detail page (confirm "View in Course Catalog" link works, no prerequisite/corequisite UI left here) → Edit. Confirm Departments/Programmes/Sessions admin pages are unaffected.

- [ ] **Step 7: Commit**

```bash
git add templates/admin/course_catalog.html templates/admin/course_catalog_form.html templates/admin/course_form.html templates/admin/course_detail.html templates/admin/course_import_report.html
git commit -m "feat: add Course Catalog admin templates, rework offering form/detail to reference master course"
```

---

### Task 8: End-to-end verification and cleanup

**Files:** None (verification only — no code changes expected unless Tasks 1-7 issues surface).

- [ ] **Step 1: Run the full manual verification pass**

1. Confirm migration state: `flask db current` shows `a29d6f0c81e5`.
2. Confirm every pre-existing course row is intact as a `CourseOffering` with the same id, and correctly linked to a master `Course` — including the real CSC 212 duplicate-code case, which should now show as ONE master with 2 offerings.
3. Confirm `PRAGMA foreign_key_check` is clean and `course_prerequisites`/`course_corequisites` reference the master `courses` table (not `course_offerings`), while `registered_courses`/`course_assessment_components` reference `course_offerings`.
4. Walk the full admin UI flow from Task 7 Step 6 again end-to-end.
5. Walk the full student registration flow (dashboard → registration → add/drop, or whatever the live entry points are) as a seeded student, confirming course listing, add, and drop all work identically to before this sub-project.
6. Run a CSV import covering all three cases from Task 4's verification (new code, matching existing code, mismatched existing code).
7. Regression: confirm `/admin/departments`, `/admin/programmes`, `/admin/sessions`, `/admin/students` all still load without error.
8. Delete any test rows created during verification (master `Course` rows, `CourseOffering` rows, `RegisteredCourse` rows, import jobs) so the dev DB is left in a clean, representative state.

- [ ] **Step 2: Update `docs/superpowers/CURRENT_STATE.md`**

Update Active Worktree, Current Milestone, Last Commit, Completed, In Progress, Next, Notes sections per the established template, recording this sub-project's completion and that sub-project 4 (Student & Registration Programme-awareness) is next in the DDD refactor sequence.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/CURRENT_STATE.md
git commit -m "docs: update CURRENT_STATE.md after Course/CourseOffering split (DDD refactor sub-project 3)"
```
