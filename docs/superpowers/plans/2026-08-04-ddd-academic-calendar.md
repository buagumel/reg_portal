# Academic Calendar (DDD Refactor Sub-project 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `AcademicSession` (and transitively `RegistrationPeriod`) an optional Programme scope, and enable term-based academic cycles by reusing `Semester` with a `period_type` discriminator — without changing any live, student-facing registration behavior.

**Architecture:** Additive-only migration. `AcademicSession.name` uniqueness changes from global to per-`(name, programme_id)` — since this table predates Alembic tracking in this repo (created via `db.create_all()` before Flask-Migrate was introduced, confirmed by inspecting `sqlite_master`: `academic_sessions` has an inline `UNIQUE (name)` table constraint with no discoverable name, backed by SQLite's auto-generated `sqlite_autoindex_academic_sessions_1`), the migration rebuilds this one table explicitly via raw SQL rather than relying on Alembic batch-mode's constraint reflection, which cannot reliably target an unnamed constraint. `Semester` gains a `period_type` column; no new Term model. `RegistrationPeriod` gets no new column — its Programme is always inherited from `academic_session_id`. `get_active_period()`/`activate_period()` are explicitly untouched.

**Tech Stack:** Flask, Flask-SQLAlchemy, Flask-Migrate/Alembic, Jinja2, SQLite (dev). No automated test framework — verification is via throwaway `test_client`/`app_context` scripts, run and discarded, never committed.

## Global Constraints

- No column drops, no renames of any existing column.
- `get_active_period()`, `activate_period()`, and all student-facing registration/eligibility logic are untouched in this sub-project — deferred to sub-project 4.
- `RegistrationPeriod` does not get its own `programme_id` column — its Programme is always derived from `academic_session_id`.
- Every existing caller of `create_session`/`update_session`/`list_sessions` (which pass no `programme_id`) must keep working unchanged — the new parameter is optional, default `None`.
- Reference-data seeding (the 3 new Term `Semester` rows) goes in `seed_dev_data.py`, not the migration — matching this repo's own established convention (the 5 `Programme` rows are seeded the same way, in `seed_programmes()`, not in a migration).

---

### Task 1: Data model — `AcademicSession.programme_id`, `Semester.period_type`, migration

**Files:**
- Modify: `models.py:106-121` (`AcademicSession` and `Semester` classes)
- Modify: `models.py:123-144` (`RegistrationPeriod` class — add `programme` property)
- Create: `migrations/versions/b7f4a1de9c63_academic_calendar_programme_scope.py`

**Interfaces:**
- Produces: `AcademicSession.programme_id` (nullable FK), `AcademicSession.programme` (relationship), unique constraint on `(name, programme_id)`; `Semester.period_type` (String, default `'semester'`); `RegistrationPeriod.programme` (read-only property, not a column).

- [ ] **Step 1: Update `AcademicSession` in `models.py`**

Replace the current class (`models.py:106-113`):

```python
class AcademicSession(db.Model):
    __tablename__ = 'academic_sessions'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(20), nullable=False)
    is_current = db.Column(db.Boolean, default=False, nullable=False)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='draft', server_default='draft')
    programme_id = db.Column(db.Integer, db.ForeignKey('programmes.id'), nullable=True)

    __table_args__ = (db.UniqueConstraint('name', 'programme_id'),)

    programme = db.relationship('Programme')
```

Note: `name`'s column-level `unique=True` is removed (it's replaced by the table-level `UniqueConstraint('name', 'programme_id')`).

- [ ] **Step 2: Update `Semester` in `models.py`**

Replace the current class (`models.py:116-121`):

```python
class Semester(db.Model):
    __tablename__ = 'semesters'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    order = db.Column(db.Integer, nullable=False)
    period_type = db.Column(db.String(20), nullable=False, default='semester', server_default='semester')
```

- [ ] **Step 3: Add a `programme` property to `RegistrationPeriod` in `models.py`**

`RegistrationPeriod` currently ends with its two relationships (`models.py:143-144`, `academic_session` and `semester`). Add immediately after:

```python
    @property
    def programme(self):
        return self.academic_session.programme if self.academic_session else None
```

- [ ] **Step 4: Write the migration**

Current head revision is `d41f9a3c7b52` (`migrations/versions/d41f9a3c7b52_programme_department_foundation.py`). Create `migrations/versions/b7f4a1de9c63_academic_calendar_programme_scope.py`:

```python
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
```

- [ ] **Step 5: Apply the migration and verify**

Run: `flask db upgrade`

Watch for the `db.create_all()`-vs-Alembic hazard documented in `docs/superpowers/CURRENT_STATE.md` (it has hit on every schema-adding sub-project so far). If `op.create_table('academic_sessions', ...)` fails with "table already exists": this means `academic_sessions` was auto-created fresh by `db.create_all()` (unlikely here since it already existed pre-migration with data — if this happens, STOP and report BLOCKED rather than guessing, since dropping `academic_sessions` would be destructive to real seeded data, unlike the empty brand-new tables this hazard normally involves).

Verify with a throwaway script (run via `python`, then discard — do not commit):
```python
from app import app
from models import AcademicSession, Semester, Programme, db

with app.app_context():
    # Existing sessions preserved, programme_id NULL
    for s in AcademicSession.query.all():
        assert s.programme_id is None, s.name
    print('Existing sessions preserved with programme_id=None.')

    # Existing semesters backfilled to period_type='semester'
    for sem in Semester.query.all():
        assert sem.period_type == 'semester', sem.name
    print('Existing semesters backfilled to period_type=semester.')

    # New composite uniqueness: same name under two different programmes both succeed
    p1 = Programme.query.first()
    p2 = Programme.query.filter(Programme.id != p1.id).first()
    s1 = AcademicSession(name='ZZTEST-2099/2100', start_date=None, end_date=None, status='draft', programme_id=p1.id)
    s2 = AcademicSession(name='ZZTEST-2099/2100', start_date=None, end_date=None, status='draft', programme_id=p2.id)
    db.session.add_all([s1, s2])
    db.session.commit()
    print('Same name under two different programmes: both created OK.')

    # Same name + same programme must still fail
    s3 = AcademicSession(name='ZZTEST-2099/2100', start_date=None, end_date=None, status='draft', programme_id=p1.id)
    db.session.add(s3)
    try:
        db.session.commit()
        print('FAIL: duplicate (name, programme_id) was allowed')
    except Exception as e:
        db.session.rollback()
        print('OK: duplicate (name, programme_id) correctly rejected:', type(e).__name__)

    # Cleanup
    AcademicSession.query.filter(AcademicSession.name == 'ZZTEST-2099/2100').delete()
    db.session.commit()
    print('Cleaned up test rows.')
```
Expected: all assertions pass, both success/failure cases print "OK".

- [ ] **Step 6: Commit**

```bash
git add models.py migrations/versions/b7f4a1de9c63_academic_calendar_programme_scope.py
git commit -m "feat: add Programme scope to AcademicSession and period_type to Semester"
```

---

### Task 2: Service layer and Term seed data

**Files:**
- Modify: `services/admin_session.py`
- Modify: `services/admin_validation.py`
- Modify: `seed_dev_data.py`

**Interfaces:**
- Consumes: `Programme` from `models.py` (already imported where needed).
- Produces: `create_session(name, start_date, end_date, programme_id=None)`, `update_session(session_id, name, start_date, end_date, programme_id=None)`, `list_sessions(programme_id=None)`, `list_semesters_for_programme(programme)` — all in `services/admin_session.py`. `is_session_name_unique(name, programme_id, exclude_id=None)` in `services/admin_validation.py`.

- [ ] **Step 1: Add `is_session_name_unique` to `services/admin_validation.py`**

Insert immediately after `is_programme_code_unique` (added in sub-project 1):

```python
def is_session_name_unique(name, programme_id, exclude_id=None):
    query = AcademicSession.query.filter(
        AcademicSession.name == name, AcademicSession.programme_id == programme_id
    )
    if exclude_id is not None:
        query = query.filter(AcademicSession.id != exclude_id)
    return query.first() is None
```

Add `AcademicSession` to the top-of-file import line (`from models import Department, Programme, Course, Semester` becomes `from models import Department, Programme, Course, Semester, AcademicSession`).

- [ ] **Step 2: Update `services/admin_session.py`**

Replace `list_sessions`, `create_session`, `update_session` (currently `services/admin_session.py:4-25`):

```python
def list_sessions(programme_id=None):
    query = AcademicSession.query
    if programme_id is not None:
        query = query.filter(AcademicSession.programme_id == programme_id)
    return query.order_by(AcademicSession.start_date.desc().nullslast(), AcademicSession.id.desc()).all()


def get_session(session_id):
    return AcademicSession.query.get_or_404(session_id)


def create_session(name, start_date, end_date, programme_id=None):
    session_obj = AcademicSession(name=name, start_date=start_date, end_date=end_date, status='draft', programme_id=programme_id)
    db.session.add(session_obj)
    db.session.commit()
    return session_obj


def update_session(session_id, name, start_date, end_date, programme_id=None):
    session_obj = get_session(session_id)
    session_obj.name = name
    session_obj.start_date = start_date
    session_obj.end_date = end_date
    session_obj.programme_id = programme_id
    db.session.commit()
    return session_obj
```

In `clone_session` (currently `services/admin_session.py:37-78`), update the `new_session = AcademicSession(...)` line (currently line 45) to preserve the source session's Programme scope:

```python
    new_session = AcademicSession(name=new_name, start_date=new_start_date, end_date=new_end_date, status='draft', programme_id=source.programme_id)
```

Add `list_semesters_for_programme` immediately after `list_semesters` (currently `services/admin_session.py:81-82`):

```python
def list_semesters_for_programme(programme):
    """Filter Semester rows by the programme's calendar shape. Returns every
    Semester row if programme is None or has neither uses_semesters nor
    uses_terms set — the same 'show everything' behavior as an unscoped
    session has always had."""
    if programme is None:
        return list_semesters()
    types = []
    if programme.uses_semesters:
        types.append('semester')
    if programme.uses_terms:
        types.append('term')
    if not types:
        return list_semesters()
    return Semester.query.filter(Semester.period_type.in_(types)).order_by(Semester.order).all()
```

- [ ] **Step 3: Seed the 3 new Term `Semester` rows in `seed_dev_data.py`**

Add a new function, placed immediately after `seed_programmes()` (currently ending `seed_dev_data.py:417`, right before the `seed_programme_departments` function added in sub-project 1):

```python
def seed_term_semesters():
    terms = [('Term 1', 1), ('Term 2', 2), ('Term 3', 3)]
    for name, order in terms:
        if Semester.query.filter_by(name=name).first():
            print(f'Skipping semester {name} (already exists)')
            continue
        db.session.add(Semester(name=name, order=order, period_type='term'))
        db.session.commit()
        print(f'Seeded term: {name}')
```

Add the call in `main()`'s `seed()` function immediately before `seed_programmes()` (so semesters exist before anything that might reference them):

```python
        seed_term_semesters()
        seed_programmes()
```

`Semester` must already be importable — confirm it's in the existing `from models import (...)` block at the top of `seed_dev_data.py` (it is, per `models.py` imports already listed there for `DepartmentRegistrationRule` etc. — add `Semester` to that import line if not already present).

- [ ] **Step 4: Run and verify**

Run: `python seed_dev_data.py`

Verify with a throwaway script:
```python
from app import app
from models import Semester
from services.admin_session import list_semesters_for_programme
from services.admin_validation import is_session_name_unique
from models import Programme

with app.app_context():
    terms = Semester.query.filter_by(period_type='term').order_by(Semester.order).all()
    assert [t.name for t in terms] == ['Term 1', 'Term 2', 'Term 3'], [t.name for t in terms]
    print('3 term semesters seeded correctly.')

    hnd = Programme.query.filter_by(code='HND').first()
    hnd.uses_semesters, hnd.uses_terms = True, False
    intl = Programme.query.filter_by(code='INTLDIP').first()
    intl.uses_semesters, intl.uses_terms = False, True
    from models import db
    db.session.commit()

    hnd_semesters = list_semesters_for_programme(hnd)
    assert all(s.period_type == 'semester' for s in hnd_semesters), hnd_semesters
    intl_semesters = list_semesters_for_programme(intl)
    assert all(s.period_type == 'term' for s in intl_semesters), intl_semesters
    assert list_semesters_for_programme(None) == list_semesters_for_programme(None)  # no error on None
    print('list_semesters_for_programme filters correctly by programme calendar shape.')

    assert is_session_name_unique('2025/2026', None) is False  # '2025/2026' is a real seeded legacy session (programme_id=None) as of this plan's writing
    assert is_session_name_unique('2025/2026', hnd.id) is True  # same name, but scoped to HND specifically — no collision
    print('is_session_name_unique behaves as expected.')
```
Expected: no assertion errors. (Revert the `hnd`/`intl` flag changes made for this test if they weren't already at those values — check with `git diff`-equivalent reasoning: these are dev-seed Programmes with `uses_semesters=True, uses_terms=False` from sub-project 1's migration defaults, so setting `intl.uses_terms=True` is a real mutation — restore both to their pre-test values after the assertions pass, or note in your report that this was left changed if it seems reasonable to leave International Diploma correctly flagged as term-based. Use your judgment and document what you did.)

- [ ] **Step 5: Commit**

```bash
git add services/admin_session.py services/admin_validation.py seed_dev_data.py
git commit -m "feat: add Programme-scoped session service layer and term semester seed data"
```

---

### Task 3: Admin routes

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: `list_sessions`, `create_session`, `update_session`, `list_semesters_for_programme` from `services/admin_session.py` (already imported at `app.py:65-69` for the first three — add `list_semesters_for_programme`); `is_session_name_unique` from `services/admin_validation.py`; `list_active_programmes` (already imported at `app.py:85`).

- [ ] **Step 1: Update the `services.admin_session` import in `app.py`**

Find the existing import block (`app.py:65-69`):
```python
from services.admin_session import (
    list_sessions, get_session, create_session, update_session, archive_session, clone_session,
    list_semesters, list_periods, get_period, create_period, update_period, activate_period,
    list_holidays, create_holiday, list_inactive_periods,
)
```
Add `list_semesters_for_programme` to this import list.

Add `is_session_name_unique` to the existing `services.admin_validation` import line (which after sub-project 1 reads `from services.admin_validation import is_department_code_unique, is_programme_code_unique, validate_credit_range, valid_levels_for_programme`).

- [ ] **Step 2: Update `admin_sessions` (list route, `app.py:1372-1376`)**

```python
@app.route('/admin/sessions')
@permission_required('sessions.manage')
def admin_sessions():
    programme_id = request.args.get('programme_id', type=int)
    sessions = list_sessions(programme_id=programme_id)
    return render_template(
        'admin/sessions.html', sessions=sessions,
        programmes=list_active_programmes(), selected_programme_id=programme_id,
    )
```

- [ ] **Step 3: Update `admin_sessions_new` (`app.py:1379-1400`)**

```python
@app.route('/admin/sessions/new', methods=['GET', 'POST'])
@permission_required('sessions.manage')
def admin_sessions_new():
    if request.method == 'GET':
        return render_template('admin/session_form.html', session=None, programmes=list_active_programmes())

    name = request.form.get('name', '').strip()
    start_date = request.form.get('start_date') or None
    end_date = request.form.get('end_date') or None
    programme_id = request.form.get('programme_id', type=int) or None
    if not name:
        flash('Session name is required.')
        return render_template('admin/session_form.html', session=None, form=request.form, programmes=list_active_programmes())
    if not is_session_name_unique(name, programme_id):
        flash(f'A session named "{name}" already exists for this programme.')
        return render_template('admin/session_form.html', session=None, form=request.form, programmes=list_active_programmes())

    from datetime import date
    start_date = date.fromisoformat(start_date) if start_date else None
    end_date = date.fromisoformat(end_date) if end_date else None

    session_obj = create_session(name, start_date, end_date, programme_id=programme_id)
    log_admin_action(current_user, 'session_created', target_type='academic_session', target_id=session_obj.id,
                      details=f'name={name} programme_id={programme_id}', ip_address=request.remote_addr)
    flash(f'Session "{name}" created.')
    return redirect(url_for('admin_session_edit', session_id=session_obj.id))
```

- [ ] **Step 4: Update `admin_session_edit` (`app.py:1403-1428`)**

```python
@app.route('/admin/sessions/<int:session_id>/edit', methods=['GET', 'POST'])
@permission_required('sessions.manage')
def admin_session_edit(session_id):
    session_obj = get_session(session_id)
    if request.method == 'GET':
        return render_template(
            'admin/session_form.html', session=session_obj, programmes=list_active_programmes(),
            periods=list_periods(session_id), holidays=list_holidays(session_id),
        )

    name = request.form.get('name', '').strip()
    start_date = request.form.get('start_date') or None
    end_date = request.form.get('end_date') or None
    programme_id = request.form.get('programme_id', type=int) or None
    if not name:
        flash('Session name is required.')
        return render_template('admin/session_form.html', session=session_obj, form=request.form, programmes=list_active_programmes())
    if not is_session_name_unique(name, programme_id, exclude_id=session_id):
        flash(f'A session named "{name}" already exists for this programme.')
        return render_template('admin/session_form.html', session=session_obj, form=request.form, programmes=list_active_programmes())

    from datetime import date
    start_date = date.fromisoformat(start_date) if start_date else None
    end_date = date.fromisoformat(end_date) if end_date else None

    update_session(session_id, name, start_date, end_date, programme_id=programme_id)
    log_admin_action(current_user, 'session_updated', target_type='academic_session', target_id=session_id,
                      details=f'name={name} programme_id={programme_id}', ip_address=request.remote_addr)
    flash(f'Session "{name}" updated.')
    return redirect(url_for('admin_sessions'))
```

- [ ] **Step 5: Update `admin_period_new` and `admin_period_edit` to use `list_semesters_for_programme`**

In `admin_period_new` (`app.py:2291-2295`), change:
```python
    session_obj = get_session(session_id)
    semesters = list_semesters()
```
to:
```python
    session_obj = get_session(session_id)
    semesters = list_semesters_for_programme(session_obj.programme)
```
Leave the rest of `admin_period_new` unchanged — every other reference to `semesters` in that function already uses the local variable.

In `admin_period_edit` (`app.py:2335-2340`), make the identical change:
```python
    session_obj = get_session(session_id)
    period = get_period(period_id)
    semesters = list_semesters_for_programme(session_obj.programme)
```

- [ ] **Step 6: Verify**

Run a throwaway `test_client` script: log in as Academic Administrator (`academic.admin@jspict.edu.ng` / `Default@123`, handling the CSRF/first-login considerations noted in prior sub-project verification scripts), then:
- `GET /admin/sessions` → 200, contains a Programme filter control.
- `POST /admin/sessions/new` with a `programme_id` set → 302, new session has that `programme_id`.
- `POST /admin/sessions/new` again with the same name and same `programme_id` → flashes the duplicate error, does not create a second row.
- `POST /admin/sessions/new` with the same name but a *different* `programme_id` → succeeds.
- `GET /admin/sessions/<id>/periods/new` for a session scoped to a `uses_terms=True` Programme → the semester `<select>` options are limited to Term rows (check the response body contains "Term 1" and does NOT contain "First Semester" or "Second Semester" — the two existing seeded Semester rows).
- Clean up all test data created.

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "feat: wire Programme scoping into session and registration period admin routes"
```

---

### Task 4: Admin templates

**Files:**
- Modify: `templates/admin/session_form.html`
- Modify: `templates/admin/sessions.html`
- Modify: `templates/admin/period_form.html`

**Interfaces:**
- Consumes: `programmes` (list of active `Programme` objects, from Task 3's routes) in `session_form.html` and `sessions.html`; `selected_programme_id` in `sessions.html`; `session.programme` (already available via the model relationship, no new context variable needed) in `period_form.html`.

- [ ] **Step 1: Add the Programme selector to `templates/admin/session_form.html`**

Insert immediately after the "Academic Year" field block (currently `templates/admin/session_form.html:10-14`):

```html
        <div style="margin-bottom:1rem;">
            <label style="display:block; margin-bottom:0.3rem; font-weight:600;">Programme (optional — leave blank for a shared/legacy session)</label>
            <select name="programme_id" style="width:100%; padding:0.6rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main);">
                <option value="">— Shared / Legacy —</option>
                {% set current_programme_id = form.get('programme_id', type=int) if form else (session.programme_id if session else none) %}
                {% for prog in programmes %}
                <option value="{{ prog.id }}" {{ 'selected' if current_programme_id == prog.id }}>{{ prog.name }} ({{ prog.code }})</option>
                {% endfor %}
            </select>
        </div>
```

- [ ] **Step 2: Add a Programme column and filter to `templates/admin/sessions.html`**

Add the filter form before the existing "New Session" button block (currently `templates/admin/sessions.html:5-8`):

```html
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem;">
    <form method="GET" style="display:flex; gap:0.6rem;">
        <select name="programme_id" onchange="this.form.submit()" style="padding:0.5rem 0.8rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main);">
            <option value="">All Programmes</option>
            {% for prog in programmes %}
            <option value="{{ prog.id }}" {{ 'selected' if selected_programme_id == prog.id }}>{{ prog.name }} ({{ prog.code }})</option>
            {% endfor %}
        </select>
    </form>
    <a href="{{ url_for('admin_sessions_new') }}" style="padding:0.6rem 1.2rem; background: var(--primary); color:white; border-radius:0.5rem; text-decoration:none; font-weight:600;"><i class="fas fa-plus"></i> New Session</a>
</div>
```
(This replaces the existing `<div style="display:flex; justify-content:flex-end; margin-bottom:1rem;">...New Session...</div>` block — the New Session link moves inside the new flex container alongside the filter.)

Add a "Programme" column to the table header (currently `templates/admin/sessions.html:12-20`, insert after the "Session" `<th>`):
```html
                <th style="padding:0.8rem;">Programme</th>
```

Add the corresponding cell in the table body (currently `templates/admin/sessions.html:24-25`, insert after the Session name `<td>`):
```html
                <td style="padding:0.8rem;">{{ s.programme.name if s.programme else '—' }}</td>
```

Update the `colspan` on the empty-state row (currently `colspan="6"`) to `colspan="7"` to account for the new column.

- [ ] **Step 3: Add a read-only Programme display to `templates/admin/period_form.html`**

Insert immediately after the `<h2>` heading (currently `templates/admin/period_form.html:7`):
```html
        <p style="color: var(--text-muted); font-size:0.85rem; margin-top:-0.5rem; margin-bottom:1rem;">Programme: {{ session.programme.name if session.programme else 'Shared / Legacy (all programmes)' }}</p>
```

- [ ] **Step 4: Manual verification**

Run the dev server, log in as Academic Administrator, and click through: Sessions list (confirm Programme column and filter work) → New Session (assign a Programme) → session detail → Add Period (confirm the Programme line displays and the Semester dropdown reflects the session's Programme's calendar shape). Confirm the Departments, Courses, and Programmes admin pages are unaffected.

- [ ] **Step 5: Commit**

```bash
git add templates/admin/session_form.html templates/admin/sessions.html templates/admin/period_form.html
git commit -m "feat: add Programme scoping UI to session and registration period admin templates"
```

---

### Task 5: End-to-end verification and cleanup

**Files:** None (verification only — no code changes expected unless Task 1-4 issues surface).

- [ ] **Step 1: Run the full manual verification pass**

1. Confirm migration state: `flask db current` shows `b7f4a1de9c63`.
2. Confirm every pre-existing `AcademicSession` row still has its original `name`/`start_date`/`end_date`/`status`/`is_current` unchanged, with `programme_id=None`.
3. Confirm every pre-existing `Semester` row has `period_type='semester'`, and the 3 new rows ("Term 1/2/3") exist with `period_type='term'`.
4. Confirm `activate_period()`/`get_active_period()` behavior is completely unchanged — activate a period, confirm exactly one `RegistrationPeriod.is_active=True` and exactly one `AcademicSession.is_current=True` institution-wide, exactly as before this sub-project.
5. Walk the full admin UI flow from Task 4 Step 4 again end-to-end.
6. Regression: confirm `/admin/departments`, `/admin/courses`, `/admin/programmes`, `/admin/students` all still load without error.
7. Regression: confirm the student-facing dashboard and `/registration` pages render correctly for a seeded student and are entirely unaffected by this sub-project (they should be — nothing in `services/registration.py` was touched).
8. Delete any test `AcademicSession`/`RegistrationPeriod` rows created during verification so the dev DB is left in a clean, representative state.

- [ ] **Step 2: Update `docs/superpowers/CURRENT_STATE.md`**

Update Active Worktree, Current Milestone, Last Commit, Completed, In Progress, Next, Notes sections per the established template, recording this sub-project's completion and that sub-project 3 (Course → Course + CourseOffering split) is next in the DDD refactor sequence.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/CURRENT_STATE.md
git commit -m "docs: update CURRENT_STATE.md after Academic Calendar (DDD refactor sub-project 2)"
```
