# Programme↔Department Foundation (DDD Refactor Sub-project 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Relate `Programme` and `Department` via a many-to-many junction, add calendar-shape fields to `Programme`, and build a Programme Management admin module mirroring the existing Departments module.

**Architecture:** Additive-only migration (new columns + new table, no drops/renames). New `services/admin_programme.py` mirrors `services/admin_department.py`'s exact function shapes. New `/admin/programmes` route family and templates mirror `/admin/departments` exactly. `AcademicSession`, `Course`, `RegistrationPeriod`, and eligibility logic are untouched in this sub-project.

**Tech Stack:** Flask, Flask-SQLAlchemy, Flask-Migrate/Alembic, Jinja2, SQLite (dev). No automated test framework — verification is via throwaway `test_client`/`app_context` scripts, run and discarded, never committed (established project convention).

## Global Constraints

- No column drops, no renames of any existing column.
- New `programme_departments` rows only ever created/deleted via `set_programme_departments` (replace-all pattern), never edited in place.
- `programmes.manage` permission granted to exactly Super Administrator and Academic Administrator (the same pair holding `departments.manage`).
- All admin write actions call `log_admin_action(current_user, ...)` — no admin mutation is silent.
- Every route/template mirrors the existing Departments module's structure and inline-style conventions (this app has no separate CSS framework for admin forms — see `templates/admin/department_form.html` for the exact style attributes to replicate).

---

### Task 1: `Programme` columns, `ProgrammeDepartment` model, and migration

**Files:**
- Modify: `models.py:356-364` (the `Programme` class)
- Modify: `models.py` (add new `ProgrammeDepartment` class immediately after `Programme`)
- Create: `migrations/versions/d41f9a3c7b52_programme_department_foundation.py`

**Interfaces:**
- Produces: `Programme.uses_semesters` (bool), `Programme.uses_terms` (bool), `Programme.duration` (str|None); `ProgrammeDepartment(id, programme_id, department_id, created_at)` with relationships `ProgrammeDepartment.programme` → `Programme`, `ProgrammeDepartment.department` → `Department`, and backrefs `Programme.programme_departments`, `Department.programme_departments` (lists of `ProgrammeDepartment` rows).

- [ ] **Step 1: Add the new columns to `Programme` in `models.py`**

Edit the existing class (currently `models.py:356-364`):

```python
class Programme(db.Model):
    __tablename__ = 'programmes'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    program_type = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='active')
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
    uses_semesters = db.Column(db.Boolean, nullable=False, default=True, server_default='1')
    uses_terms = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    duration = db.Column(db.String(50), nullable=True)
```

- [ ] **Step 2: Add `ProgrammeDepartment` immediately after `Programme` in `models.py`**

```python
class ProgrammeDepartment(db.Model):
    __tablename__ = 'programme_departments'
    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey('programmes.id'), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)

    __table_args__ = (db.UniqueConstraint('programme_id', 'department_id'),)

    programme = db.relationship('Programme', backref='programme_departments')
    department = db.relationship('Department', backref='programme_departments')
```

- [ ] **Step 3: Write the migration**

Current head revision is `c95349c0e1ad` (`migrations/versions/c95349c0e1ad_phase3_academic_operations_registration_.py`). Create `migrations/versions/d41f9a3c7b52_programme_department_foundation.py`:

```python
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
```

- [ ] **Step 4: Apply the migration and verify**

Run: `flask db upgrade`

Watch for the `db.create_all()`-vs-Alembic hazard documented in `docs/superpowers/CURRENT_STATE.md`: if `app.py`'s unconditional `db.create_all()` already auto-created `programme_departments` (e.g. because a prior throwaway script imported `app`), `op.create_table` will fail with "table already exists." If that happens: confirm the auto-created table is empty, drop it, temporarily comment out just the `op.create_table(...)` block, run `flask db upgrade`, then revert the migration file via `git checkout -- migrations/versions/d41f9a3c7b52_programme_department_foundation.py` immediately after.

Verify with a throwaway script (run via `python`, then discard — do not commit):
```python
from app import app
from models import Programme, ProgrammeDepartment

with app.app_context():
    for p in Programme.query.all():
        assert p.uses_semesters is True and p.uses_terms is False and p.duration is None, p.code
    print('All programmes have expected defaults.')
    print('programme_departments row count:', ProgrammeDepartment.query.count())
```
Expected: no assertion errors, row count `0` (backfill happens in Task 2).

- [ ] **Step 5: Commit**

```bash
git add models.py migrations/versions/d41f9a3c7b52_programme_department_foundation.py
git commit -m "feat: add Programme calendar fields and ProgrammeDepartment junction table"
```

---

### Task 2: Backfill seeding + service layer

**Files:**
- Modify: `seed_dev_data.py` (add `seed_programme_departments()`, call it from `main()`)
- Create: `services/admin_programme.py`

**Interfaces:**
- Consumes: `Programme`, `ProgrammeDepartment`, `Department`, `User` from `models.py`; `is_department_code_unique`-style pattern from `services/admin_validation.py` for a new `is_programme_code_unique`.
- Produces: `services/admin_programme.py` exposing `list_programmes(search=None, status=None, page=1, per_page=20)`, `get_programme(programme_id)`, `get_programme_detail(programme_id)`, `create_programme(name, code, program_type, description=None, uses_semesters=True, uses_terms=False, duration=None)`, `update_programme(programme_id, name, code, program_type, description=None, uses_semesters=True, uses_terms=False, duration=None)`, `set_programme_status(programme_id, status)`, `get_programme_department_ids(programme_id)`, `set_programme_departments(programme_id, department_ids)`. Also `services/admin_validation.py::is_programme_code_unique(code, exclude_id=None)`.

- [ ] **Step 1: Add `is_programme_code_unique` to `services/admin_validation.py`**

Insert immediately after `is_department_code_unique` (currently `services/admin_validation.py:23-27`):

```python
def is_programme_code_unique(code, exclude_id=None):
    query = Programme.query.filter(Programme.code == code)
    if exclude_id is not None:
        query = query.filter(Programme.id != exclude_id)
    return query.first() is None
```

- [ ] **Step 2: Create `services/admin_programme.py`**

```python
from models import db, Programme, ProgrammeDepartment, Department, User, Course


def list_programmes(search=None, status=None, page=1, per_page=20):
    query = Programme.query
    if search:
        like = f'%{search}%'
        query = query.filter((Programme.name.ilike(like)) | (Programme.code.ilike(like)))
    if status:
        query = query.filter(Programme.status == status)
    query = query.order_by(Programme.name)

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return {'items': items, 'total': total, 'page': page, 'per_page': per_page}


def get_programme(programme_id):
    return Programme.query.get_or_404(programme_id)


def get_programme_detail(programme_id):
    programme = get_programme(programme_id)
    student_count = User.query.filter_by(programme_id=programme_id).count()
    department_ids = get_programme_department_ids(programme_id)
    departments = Department.query.filter(Department.id.in_(department_ids)).order_by(Department.name).all() if department_ids else []
    return {'programme': programme, 'student_count': student_count, 'departments': departments}


def create_programme(name, code, program_type, description=None, uses_semesters=True, uses_terms=False, duration=None):
    programme = Programme(
        name=name, code=code, program_type=program_type, description=description or None,
        uses_semesters=uses_semesters, uses_terms=uses_terms, duration=duration or None,
    )
    db.session.add(programme)
    db.session.commit()
    return programme


def update_programme(programme_id, name, code, program_type, description=None, uses_semesters=True, uses_terms=False, duration=None):
    programme = get_programme(programme_id)
    programme.name = name
    programme.code = code
    programme.program_type = program_type
    programme.description = description or None
    programme.uses_semesters = uses_semesters
    programme.uses_terms = uses_terms
    programme.duration = duration or None
    db.session.commit()
    return programme


def set_programme_status(programme_id, status):
    programme = get_programme(programme_id)
    programme.status = status
    db.session.commit()
    return programme


def get_programme_department_ids(programme_id):
    rows = ProgrammeDepartment.query.filter_by(programme_id=programme_id).all()
    return [row.department_id for row in rows]


def set_programme_departments(programme_id, department_ids):
    ProgrammeDepartment.query.filter_by(programme_id=programme_id).delete()
    for department_id in set(department_ids):
        db.session.add(ProgrammeDepartment(programme_id=programme_id, department_id=department_id))
    db.session.commit()
```

`list_active_programmes()` already exists in `services/admin_student.py` and is reused as-is — do not duplicate it here.

- [ ] **Step 3: Add the backfill function to `seed_dev_data.py`**

Insert a new function after `seed_programmes()` (currently ending at `seed_dev_data.py:417`):

```python
def seed_programme_departments():
    """Best-effort backfill: for every User with both department_id and
    programme_id set, ensure the corresponding ProgrammeDepartment link
    exists. Not exhaustive — most historical data predates the FK
    dual-write — admins complete the rest via the Programme Management UI."""
    pairs = db.session.query(User.programme_id, User.department_id).filter(
        User.programme_id.isnot(None), User.department_id.isnot(None)
    ).distinct().all()
    created = 0
    for programme_id, department_id in pairs:
        exists = ProgrammeDepartment.query.filter_by(
            programme_id=programme_id, department_id=department_id
        ).first()
        if not exists:
            db.session.add(ProgrammeDepartment(programme_id=programme_id, department_id=department_id))
            created += 1
    db.session.commit()
    print(f'Seeded {created} programme_department link(s) from existing student data.')
```

Add the import at the top of `seed_dev_data.py` (currently `seed_dev_data.py:9-14`) — add `ProgrammeDepartment` to the `from models import (...)` block.

Add the call in `main()` immediately after `seed_programmes()` (currently `seed_dev_data.py:77`):

```python
        seed_programmes()
        seed_programme_departments()
```

- [ ] **Step 4: Run and verify**

Run: `python seed_dev_data.py`

Verify with a throwaway script:
```python
from app import app
from models import ProgrammeDepartment, User

with app.app_context():
    expected_pairs = {
        (u.programme_id, u.department_id) for u in User.query.filter(
            User.programme_id.isnot(None), User.department_id.isnot(None)
        ).all()
    }
    actual_pairs = {(pd.programme_id, pd.department_id) for pd in ProgrammeDepartment.query.all()}
    assert expected_pairs.issubset(actual_pairs), (expected_pairs - actual_pairs)
    print(f'OK — {len(actual_pairs)} programme_department link(s), all expected pairs present.')

    from services.admin_programme import create_programme, update_programme, set_programme_status, set_programme_departments, get_programme_department_ids
    from services.admin_validation import is_programme_code_unique
    assert is_programme_code_unique('ND') is False  # seeded programme
    p = create_programme('Test Programme', 'TESTPRG', 'nd', duration='2 years')
    update_programme(p.id, 'Test Programme Updated', 'TESTPRG', 'nd', duration='2 years')
    set_programme_status(p.id, 'archived')
    from models import Department, db
    dept = Department.query.first()
    set_programme_departments(p.id, [dept.id])
    assert get_programme_department_ids(p.id) == [dept.id]
    set_programme_departments(p.id, [])
    assert get_programme_department_ids(p.id) == []
    db.session.delete(p)
    db.session.commit()
    print('Service layer OK.')
```
Expected: both assertions pass, no errors. Clean up the test Programme row as shown (delete before the script ends) so it doesn't linger in the dev DB.

- [ ] **Step 5: Commit**

```bash
git add seed_dev_data.py services/admin_programme.py services/admin_validation.py
git commit -m "feat: add Programme service layer and student-data backfill for programme_departments"
```

---

### Task 3: RBAC permission and admin routes

**Files:**
- Modify: `seed_dev_data.py:353-386` (`seed_admin_rbac`)
- Modify: `app.py` (imports near line 51-55, new routes near line 1240 — immediately after the existing Departments route block)

**Interfaces:**
- Consumes: `list_programmes, get_programme, get_programme_detail, create_programme, update_programme, set_programme_status, get_programme_department_ids, set_programme_departments` from `services/admin_programme.py`; `is_programme_code_unique` from `services/admin_validation.py`; `log_admin_action` from `services/admin_audit.py`; `list_active_departments` from `services/admin_department.py` (already imported in `app.py:71`).
- Produces: Flask endpoints `admin_programmes`, `admin_programme_new`, `admin_programme_detail`, `admin_programme_edit`, `admin_programme_departments`, `admin_programme_activate`, `admin_programme_archive`.

- [ ] **Step 1: Add the `programmes.manage` permission in `seed_dev_data.py`**

In the `permissions` list (currently `seed_dev_data.py:354-363`), add one entry:
```python
        ('programmes.manage', 'Create, edit, and manage programmes'),
```

In the `roles` dict (currently `seed_dev_data.py:377-386`), add `'programmes.manage'` to both role's code lists:
```python
        'Super Administrator': (
            'Complete system access',
            ['dashboard.view', 'sessions.manage', 'students.manage', 'courses.manage', 'registration.manage', 'announcements.manage', 'reports.view', 'departments.manage', 'onboarding.override', 'programmes.manage'],
        ),
        'Academic Administrator': (
            'Course management, registration oversight, and announcements',
            ['dashboard.view', 'students.manage', 'courses.manage', 'registration.manage', 'announcements.manage', 'departments.manage', 'programmes.manage'],
        ),
```

- [ ] **Step 2: Add imports to `app.py`**

Immediately after the existing `from services.admin_department import (...)` block (`app.py:51-54`):
```python
from services.admin_programme import (
    list_programmes, get_programme, get_programme_detail,
    create_programme, update_programme, set_programme_status,
    get_programme_department_ids, set_programme_departments,
)
```

Add `is_programme_code_unique` to the existing admin_validation import line (`app.py:55`):
```python
from services.admin_validation import is_department_code_unique, is_programme_code_unique, validate_credit_range, valid_levels_for_programme
```

- [ ] **Step 3: Add the routes to `app.py`**

Insert immediately after the Departments route block (after `admin_department_archive`, currently ending `app.py:1238`):

```python
@app.route('/admin/programmes')
@permission_required('programmes.manage')
def admin_programmes():
    search = request.args.get('search', '').strip() or None
    status = request.args.get('status', '').strip() or None
    page = request.args.get('page', 1, type=int)
    result = list_programmes(search=search, status=status, page=page)
    return render_template(
        'admin/programmes.html', result=result, search=search or '', status=status or '',
    )


@app.route('/admin/programmes/new', methods=['GET', 'POST'])
@permission_required('programmes.manage')
def admin_programme_new():
    if request.method == 'GET':
        return render_template('admin/programme_form.html', programme=None)

    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip().upper()
    program_type = request.form.get('program_type', '').strip()
    description = request.form.get('description', '').strip()
    uses_semesters = request.form.get('uses_semesters') == 'on'
    uses_terms = request.form.get('uses_terms') == 'on'
    duration = request.form.get('duration', '').strip()

    if not name or not code or not program_type:
        flash('Name, code, and programme type are required.')
        return render_template('admin/programme_form.html', programme=None, form=request.form)
    if not is_programme_code_unique(code):
        flash(f'Programme code "{code}" is already in use.')
        return render_template('admin/programme_form.html', programme=None, form=request.form)

    programme = create_programme(name, code, program_type, description, uses_semesters, uses_terms, duration)
    log_admin_action(current_user, 'programme_created', target_type='programme', target_id=programme.id,
                      details=f'name={name} code={code}', ip_address=request.remote_addr)
    flash(f'Programme "{name}" created.')
    return redirect(url_for('admin_programmes'))


@app.route('/admin/programmes/<int:programme_id>')
@permission_required('programmes.manage')
def admin_programme_detail(programme_id):
    detail = get_programme_detail(programme_id)
    all_departments = list_active_departments()
    linked_ids = set(get_programme_department_ids(programme_id))
    return render_template(
        'admin/programmes.html', detail=detail, result=None,
        all_departments=all_departments, linked_ids=linked_ids,
    )


@app.route('/admin/programmes/<int:programme_id>/edit', methods=['GET', 'POST'])
@permission_required('programmes.manage')
def admin_programme_edit(programme_id):
    programme = get_programme(programme_id)
    if request.method == 'GET':
        return render_template('admin/programme_form.html', programme=programme)

    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip().upper()
    program_type = request.form.get('program_type', '').strip()
    description = request.form.get('description', '').strip()
    uses_semesters = request.form.get('uses_semesters') == 'on'
    uses_terms = request.form.get('uses_terms') == 'on'
    duration = request.form.get('duration', '').strip()

    if not name or not code or not program_type:
        flash('Name, code, and programme type are required.')
        return render_template('admin/programme_form.html', programme=programme, form=request.form)
    if not is_programme_code_unique(code, exclude_id=programme_id):
        flash(f'Programme code "{code}" is already in use.')
        return render_template('admin/programme_form.html', programme=programme, form=request.form)

    update_programme(programme_id, name, code, program_type, description, uses_semesters, uses_terms, duration)
    log_admin_action(current_user, 'programme_updated', target_type='programme', target_id=programme_id,
                      details=f'name={name} code={code}', ip_address=request.remote_addr)
    flash(f'Programme "{name}" updated.')
    return redirect(url_for('admin_programmes'))


@app.route('/admin/programmes/<int:programme_id>/departments', methods=['POST'])
@permission_required('programmes.manage')
def admin_programme_departments(programme_id):
    department_ids = [int(v) for v in request.form.getlist('department_ids')]
    set_programme_departments(programme_id, department_ids)
    log_admin_action(current_user, 'programme_departments_updated', target_type='programme', target_id=programme_id,
                      details=f'department_ids={department_ids}', ip_address=request.remote_addr)
    flash('Programme departments updated.')
    return redirect(url_for('admin_programme_detail', programme_id=programme_id))


@app.route('/admin/programmes/<int:programme_id>/activate', methods=['POST'])
@permission_required('programmes.manage')
def admin_programme_activate(programme_id):
    set_programme_status(programme_id, 'active')
    log_admin_action(current_user, 'programme_status_changed', target_type='programme', target_id=programme_id,
                      details='status=active', ip_address=request.remote_addr)
    flash('Programme activated.')
    return redirect(url_for('admin_programmes'))


@app.route('/admin/programmes/<int:programme_id>/archive', methods=['POST'])
@permission_required('programmes.manage')
def admin_programme_archive(programme_id):
    set_programme_status(programme_id, 'archived')
    log_admin_action(current_user, 'programme_status_changed', target_type='programme', target_id=programme_id,
                      details='status=archived', ip_address=request.remote_addr)
    flash('Programme archived.')
    return redirect(url_for('admin_programmes'))
```

- [ ] **Step 4: Run `python seed_dev_data.py` to seed the new permission, then verify route wiring**

Verify with a throwaway `test_client` script, logging in as the seeded Academic Administrator (`academic.admin@jspict.edu.ng`, password from `DEFAULT_PASSWORD` in `seed_dev_data.py`, currently `Default@123`) via the existing admin login route (`POST /admin/login` with `email`/`password` form fields — confirm the exact field names by checking the existing `admin_login` view in `app.py` before writing this script):
```python
from app import app

with app.test_client() as client:
    client.post('/admin/login', data={'email': 'academic.admin@jspict.edu.ng', 'password': 'Default@123'}, follow_redirects=True)
    resp = client.get('/admin/programmes')
    print(resp.status_code)  # expect 200

with app.test_client() as anon_client:
    resp = anon_client.get('/admin/programmes')
    print(resp.status_code)  # expect 302 (redirect to login), not 200
```
Expected: `/admin/programmes` and `/admin/programmes/new` return 200 for the logged-in Academic Administrator, and 302 for an unauthenticated client.

- [ ] **Step 5: Commit**

```bash
git add app.py seed_dev_data.py
git commit -m "feat: add programmes.manage permission and Programme Management admin routes"
```

---

### Task 4: Admin templates and navigation

**Files:**
- Create: `templates/admin/programmes.html`
- Create: `templates/admin/programme_form.html`
- Modify: `templates/admin/base_admin.html:20` (sidebar nav)

**Interfaces:**
- Consumes: `result` (dict with `items`/`total`/`page`/`per_page`), `search`, `status` (list view); `detail` (dict with `programme`/`student_count`/`departments`), `all_departments`, `linked_ids` (detail view); `programme`, `form` (create/edit form) — all as passed from Task 3's routes.

- [ ] **Step 1: Create `templates/admin/programmes.html`**

Mirrors `templates/admin/departments.html` structure exactly, with a department-assignment block added to the detail branch:

```html
{% extends "admin/base_admin.html" %}

{% block breadcrumbs %}Programmes{% endblock %}

{% block content %}
{% if detail %}
<div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; padding: 1.5rem; margin-bottom: 1.5rem;">
    <h2 style="margin-top:0;">{{ detail.programme.name }} <span style="font-size:0.9rem; color: var(--text-muted);">({{ detail.programme.code }})</span></h2>
    <p style="color: var(--text-muted);">Type: {{ detail.programme.program_type }} &middot; Duration: {{ detail.programme.duration or 'Not set' }} &middot; Status: {{ detail.programme.status }}</p>
    <p style="color: var(--text-muted);">Calendar: {{ 'Semesters' if detail.programme.uses_semesters else '' }}{{ ' & ' if detail.programme.uses_semesters and detail.programme.uses_terms else '' }}{{ 'Terms' if detail.programme.uses_terms else '' }}{{ 'Not configured' if not detail.programme.uses_semesters and not detail.programme.uses_terms else '' }}</p>
    <div style="display:flex; gap:2rem; margin: 1rem 0;">
        <div><div style="font-size:1.6rem; font-weight:700; color: var(--primary-dark);">{{ detail.student_count }}</div><div style="color: var(--text-muted); font-size:0.85rem;">Students</div></div>
        <div><div style="font-size:1.6rem; font-weight:700; color: var(--primary-dark);">{{ detail.departments|length }}</div><div style="color: var(--text-muted); font-size:0.85rem;">Departments</div></div>
    </div>
    <a href="{{ url_for('admin_programme_edit', programme_id=detail.programme.id) }}" style="color: var(--primary-dark); font-weight:600;">Edit</a>
    &nbsp;&middot;&nbsp;
    <a href="{{ url_for('admin_programmes') }}" style="color: var(--text-muted);">Back to Programmes</a>
</div>

<div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; padding: 1.5rem;">
    <h3 style="margin-top:0;">Assigned Departments</h3>
    <form method="POST" action="{{ url_for('admin_programme_departments', programme_id=detail.programme.id) }}">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        {% for dept in all_departments %}
        <label style="display:block; margin-bottom:0.5rem;">
            <input type="checkbox" name="department_ids" value="{{ dept.id }}" {{ 'checked' if dept.id in linked_ids }}>
            {{ dept.name }} ({{ dept.code }})
        </label>
        {% else %}
        <p style="color: var(--text-muted);">No active departments exist yet.</p>
        {% endfor %}
        <button type="submit" style="margin-top:0.5rem; padding:0.6rem 1.2rem; background: var(--primary); color:white; border:none; border-radius:0.5rem; font-weight:600; cursor:pointer;">Save Departments</button>
    </form>
</div>
{% else %}
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem;">
    <form method="GET" style="display:flex; gap:0.6rem;">
        <input type="text" name="search" value="{{ search }}" placeholder="Search name or code" style="padding:0.5rem 0.8rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main);">
        <select name="status" style="padding:0.5rem 0.8rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main);">
            <option value="" {{ 'selected' if not status }}>All statuses</option>
            <option value="active" {{ 'selected' if status == 'active' }}>Active</option>
            <option value="archived" {{ 'selected' if status == 'archived' }}>Archived</option>
        </select>
        <button type="submit" style="padding:0.5rem 1rem; border:none; border-radius:0.5rem; background: var(--primary); color:white; cursor:pointer;">Filter</button>
    </form>
    <a href="{{ url_for('admin_programme_new') }}" style="padding:0.6rem 1.2rem; background: var(--primary); color:white; border-radius:0.5rem; text-decoration:none; font-weight:600;"><i class="fas fa-plus"></i> New Programme</a>
</div>

<div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; overflow:hidden;">
    <table style="width:100%; border-collapse:collapse;">
        <thead>
            <tr style="text-align:left; border-bottom: 1px solid var(--border-color);">
                <th style="padding:0.8rem;">Name</th>
                <th style="padding:0.8rem;">Code</th>
                <th style="padding:0.8rem;">Type</th>
                <th style="padding:0.8rem;">Status</th>
                <th style="padding:0.8rem;"></th>
            </tr>
        </thead>
        <tbody>
            {% for prog in result['items'] %}
            <tr style="border-bottom: 1px solid var(--border-color);">
                <td style="padding:0.8rem;"><a href="{{ url_for('admin_programme_detail', programme_id=prog.id) }}" style="color: var(--text-main); font-weight:600; text-decoration:none;">{{ prog.name }}</a></td>
                <td style="padding:0.8rem; font-family:monospace;">{{ prog.code }}</td>
                <td style="padding:0.8rem; text-transform:capitalize;">{{ prog.program_type }}</td>
                <td style="padding:0.8rem; text-transform:capitalize;">{{ prog.status }}</td>
                <td style="padding:0.8rem; text-align:right;">
                    <a href="{{ url_for('admin_programme_edit', programme_id=prog.id) }}" style="color: var(--primary-dark); margin-right:0.8rem;">Edit</a>
                    {% if prog.status != 'active' %}
                    <form method="POST" action="{{ url_for('admin_programme_activate', programme_id=prog.id) }}" style="display:inline;">
                        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                        <button type="submit" style="background:none; border:none; color: var(--success); cursor:pointer;">Activate</button>
                    </form>
                    {% else %}
                    <form method="POST" action="{{ url_for('admin_programme_archive', programme_id=prog.id) }}" style="display:inline;" onsubmit="return confirm('Archive {{ prog.name }}?');">
                        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                        <button type="submit" style="background:none; border:none; color: var(--danger); cursor:pointer;">Archive</button>
                    </form>
                    {% endif %}
                </td>
            </tr>
            {% else %}
            <tr><td colspan="5" style="padding:2rem; text-align:center; color: var(--text-muted);">No programmes found.</td></tr>
            {% endfor %}
        </tbody>
    </table>
</div>

{% set total_pages = ((result['total'] - 1) // result['per_page']) + 1 if result['total'] else 1 %}
{% if total_pages > 1 %}
<div style="display:flex; gap:0.5rem; justify-content:center; margin-top:1rem;">
    {% for p in range(1, total_pages + 1) %}
    <a href="{{ url_for('admin_programmes', search=search, status=status, page=p) }}"
       style="padding:0.4rem 0.8rem; border-radius:0.4rem; text-decoration:none; {{ 'background: var(--primary); color:white;' if p == result['page'] else 'background: var(--card-bg); color: var(--text-main); border:1px solid var(--border-color);' }}">{{ p }}</a>
    {% endfor %}
</div>
{% endif %}
{% endif %}
{% endblock %}
```

- [ ] **Step 2: Create `templates/admin/programme_form.html`**

Mirrors `templates/admin/department_form.html`, with `program_type` as a select (values: `nd`, `hnd`, `international`, matching `LEVELS_BY_PROGRAM_TYPE`'s keys in `services/admin_validation.py`) and the two calendar checkboxes:

```html
{% extends "admin/base_admin.html" %}

{% block breadcrumbs %}Programmes / {{ 'Edit' if programme else 'New' }}{% endblock %}

{% block content %}
<div style="max-width:520px; background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; padding: 1.5rem;">
    <h2 style="margin-top:0;">{{ 'Edit Programme' if programme else 'New Programme' }}</h2>
    <form method="POST">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <div style="margin-bottom:1rem;">
            <label style="display:block; margin-bottom:0.3rem; font-weight:600;">Name</label>
            <input type="text" name="name" required value="{{ form.name if form else (programme.name if programme else '') }}"
                   style="width:100%; padding:0.6rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main); box-sizing:border-box;">
        </div>
        <div style="margin-bottom:1rem;">
            <label style="display:block; margin-bottom:0.3rem; font-weight:600;">Code</label>
            <input type="text" name="code" required value="{{ form.code if form else (programme.code if programme else '') }}"
                   style="width:100%; padding:0.6rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main); box-sizing:border-box; text-transform:uppercase;">
        </div>
        <div style="margin-bottom:1rem;">
            <label style="display:block; margin-bottom:0.3rem; font-weight:600;">Programme Type</label>
            <select name="program_type" required style="width:100%; padding:0.6rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main); box-sizing:border-box;">
                {% set current_type = form.program_type if form else (programme.program_type if programme else '') %}
                <option value="nd" {{ 'selected' if current_type == 'nd' }}>ND</option>
                <option value="hnd" {{ 'selected' if current_type == 'hnd' }}>HND</option>
                <option value="international" {{ 'selected' if current_type == 'international' }}>International</option>
            </select>
        </div>
        <div style="margin-bottom:1rem;">
            <label style="display:block; margin-bottom:0.3rem; font-weight:600;">Description (optional)</label>
            <input type="text" name="description" value="{{ form.description if form else (programme.description if programme else '') }}"
                   style="width:100%; padding:0.6rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main); box-sizing:border-box;">
        </div>
        <div style="margin-bottom:1rem;">
            <label style="display:block; margin-bottom:0.3rem; font-weight:600;">Duration (optional)</label>
            <input type="text" name="duration" placeholder="e.g. 2 years" value="{{ form.duration if form else (programme.duration if programme else '') }}"
                   style="width:100%; padding:0.6rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main); box-sizing:border-box;">
        </div>
        <div style="margin-bottom:1.5rem;">
            <label style="display:block; margin-bottom:0.3rem; font-weight:600;">Calendar Structure</label>
            {% set us = form.get('uses_semesters') if form else (programme.uses_semesters if programme else True) %}
            {% set ut = form.get('uses_terms') if form else (programme.uses_terms if programme else False) %}
            <label style="display:block;"><input type="checkbox" name="uses_semesters" {{ 'checked' if us }}> Uses Semesters</label>
            <label style="display:block;"><input type="checkbox" name="uses_terms" {{ 'checked' if ut }}> Uses Terms</label>
        </div>
        <button type="submit" style="padding:0.7rem 1.5rem; background: var(--primary); color:white; border:none; border-radius:0.5rem; font-weight:600; cursor:pointer;">Save</button>
        <a href="{{ url_for('admin_programmes') }}" style="margin-left:1rem; color: var(--text-muted);">Cancel</a>
    </form>
</div>
{% endblock %}
```

- [ ] **Step 3: Add the sidebar nav item to `templates/admin/base_admin.html`**

Insert immediately after the Departments `<li>` (currently `templates/admin/base_admin.html:20`):
```html
                <li><a href="{{ url_for('admin_programmes') }}" class="{{ 'active' if request.endpoint and request.endpoint.startswith('admin_programme') }}"><i class="fas fa-graduation-cap"></i> Programmes</a></li>
```

- [ ] **Step 4: Manual verification**

Run the dev server, log in as an Academic Administrator, and click through: Programmes list → New Programme (create one) → detail page → assign/unassign a Department checkbox → Edit → Archive → Activate. Confirm the Departments and Courses admin pages still render correctly (regression check — no shared template was modified except the sidebar).

- [ ] **Step 5: Commit**

```bash
git add templates/admin/programmes.html templates/admin/programme_form.html templates/admin/base_admin.html
git commit -m "feat: add Programme Management admin templates and navigation"
```

---

### Task 5: End-to-end verification and cleanup

**Files:** None (verification only — no code changes expected unless Task 1-4 issues surface).

- [ ] **Step 1: Run the full manual verification pass**

Using a throwaway script plus the running dev server:
1. Confirm migration state: `flask db current` shows `d41f9a3c7b52`.
2. Confirm all 5 seeded Programmes still have `status='active'` and their original `name`/`code`/`program_type` unchanged (dual-write/additive check — nothing pre-existing was mutated except the 3 new columns).
3. Confirm `ProgrammeDepartment` backfill matches expected `(programme_id, department_id)` pairs from seeded students.
4. Walk the full admin UI flow from Task 4 Step 4 again end-to-end.
5. Regression: confirm `/admin/departments`, `/admin/courses`, `/admin/students`, `/admin/sessions` all still load without error for both Super Administrator and Academic Administrator.
6. Regression: confirm the student-facing dashboard and `/registration` pages (untouched by this sub-project) still render correctly for a seeded student.
7. Delete any test Programme/ProgrammeDepartment rows created during verification so the dev DB is left in a clean, representative state (per the lesson in `docs/superpowers/CURRENT_STATE.md` about scripts leaving residual mutated data).

- [ ] **Step 2: Update `docs/superpowers/CURRENT_STATE.md`**

Update Active Worktree, Current Milestone, Last Commit, Completed, In Progress, Next, Notes sections per the established template, recording this sub-project's completion and that sub-project 2 (Academic Calendar) is next in the DDD refactor sequence.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/CURRENT_STATE.md
git commit -m "docs: update CURRENT_STATE.md after Programme<->Department foundation (DDD refactor sub-project 1)"
```
