# DDD Refactor Sub-project 5 (FeeStructure) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Programme/Session/Semester/Department-scoped `FeeStructure` override layer on top of the existing flat `PaymentCategory` catalog, so the general payment page (`/payment/create`) can charge different amounts to different students for the same fee category, with a minimal admin UI to manage the overrides.

**Architecture:** One new additive model (`FeeStructure`, no changes to any existing table), one new resolution service (`services/fee_structure.py`) that layers scoped lookups over `PaymentCategory.default_amount`, one new admin CRUD surface (service + routes + templates), and a two-line rewire of the existing `/payment/create` GET/POST routes to call the new resolver instead of reading `category.default_amount` directly.

**Tech Stack:** Flask, Flask-SQLAlchemy, Flask-Migrate/Alembic, Jinja2, SQLite (dev). No automated test framework — manual `test_client`/`app_context` throwaway verification scripts (established convention, never committed).

## Global Constraints

- **Additive only.** No changes to `PaymentCategory`, `PaymentItem`, `Payment`, `PaymentReceipt`, `GatewayResponse`, `DepartmentRegistrationRule`, or any payment-gateway code. `FeeStructure` is a brand-new table; every other change in this plan is either brand-new code or a two-line swap of one function call for another.
- **`FeeStructure.category_id`** references the existing `PaymentCategory` table — no new category concept.
- **`semester_id` and `department_id` are both nullable** on `FeeStructure`. `NULL` means "applies to every value of that axis within this session." An exact match on either axis outranks its `NULL` counterpart during resolution.
- **No DB-level uniqueness constraint** on `FeeStructure`'s scope (SQLite treats `NULL` as distinct in composite unique indexes, so it wouldn't actually work) — uniqueness is enforced in the service layer via `is_fee_structure_scope_unique`, mirroring `services/admin_validation.py::is_session_name_unique`.
- **Admin UI reuses the `sessions.manage` permission** — no new permission code. Confirmed only the Super Administrator role has it today (Academic Administrator does not); that's the correct blast radius for fee-amount configuration.
- **Current migration head is `a29d6f0c81e5`** (confirmed via `flask db current`). The new migration's `down_revision` must be exactly that.
- Server-side amount resolution (`resolve_amount`) is always authoritative — the client never supplies an amount that gets trusted (already true today for `/payment/create`, must remain true).

---

### Task 1: `FeeStructure` model + migration

**Files:**
- Modify: `models.py:308-311` (insert the new class between `GatewayResponse` and `Permission`)
- Create: `migrations/versions/f3a7c9d21e04_fee_structure.py`

**Interfaces:**
- Produces: `FeeStructure` model with columns `id, academic_session_id, semester_id (nullable), department_id (nullable), category_id, amount (Numeric(10,2)), created_at`, relationships `academic_session, semester, department, category`, and a `programme` property. Table name `fee_structures`.

- [ ] **Step 1: Add the `FeeStructure` model to `models.py`**

Insert immediately after `GatewayResponse` (currently ends at `models.py:308`) and before `class Permission(db.Model):` (currently `models.py:311`):

```python
class FeeStructure(db.Model):
    __tablename__ = 'fee_structures'
    id = db.Column(db.Integer, primary_key=True)
    academic_session_id = db.Column(db.Integer, db.ForeignKey('academic_sessions.id'), nullable=False)
    semester_id = db.Column(db.Integer, db.ForeignKey('semesters.id'), nullable=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey('payment_categories.id'), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)

    academic_session = db.relationship('AcademicSession')
    semester = db.relationship('Semester')
    department = db.relationship('Department')
    category = db.relationship('PaymentCategory')

    @property
    def programme(self):
        return self.academic_session.programme if self.academic_session else None
```

- [ ] **Step 2: Write the migration**

Create `migrations/versions/f3a7c9d21e04_fee_structure.py`:

```python
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
```

- [ ] **Step 3: Run the migration**

Run: `flask db upgrade`
Expected: `INFO [alembic.runtime.migration] Running upgrade a29d6f0c81e5 -> f3a7c9d21e04, fee structure: ...`. Then `flask db current` shows `f3a7c9d21e04 (head)`.

**If `op.create_table` fails with "table already exists"** (the `db.create_all()`-vs-Alembic hazard documented in `docs/superpowers/CURRENT_STATE.md` — a throwaway script that imported `app` may have auto-created `fee_structures` from the model definition before the migration ran): confirm the auto-created table is empty (`SELECT COUNT(*) FROM fee_structures;` via a throwaway script — must be 0), drop it (`DROP TABLE fee_structures;`), then re-run `flask db upgrade`.

- [ ] **Step 4: Verify the model round-trips**

Throwaway script (do not commit):
```python
from decimal import Decimal
from app import app
from models import db, FeeStructure, AcademicSession, PaymentCategory
with app.app_context():
    session = AcademicSession.query.first()
    category = PaymentCategory.query.first()
    fs = FeeStructure(academic_session_id=session.id, category_id=category.id, amount=Decimal('1234.56'))
    db.session.add(fs)
    db.session.commit()
    fetched = FeeStructure.query.get(fs.id)
    assert fetched.semester_id is None
    assert fetched.department_id is None
    # Compare via Decimal, not a float literal — Decimal('1234.56') == 1234.56
    # is False in Python (binary float can't represent 1234.56 exactly).
    assert fetched.amount == Decimal('1234.56')
    assert fetched.programme == session.programme
    db.session.delete(fetched)
    db.session.commit()
    print('OK')
```
Expected: prints `OK` with no assertion errors. Delete the script after running it.

- [ ] **Step 5: Commit**

```bash
git add models.py migrations/versions/f3a7c9d21e04_fee_structure.py
git commit -m "feat: add FeeStructure model and migration"
```

---

### Task 2: `services/fee_structure.py` — resolution logic

**Files:**
- Create: `services/fee_structure.py`

**Interfaces:**
- Consumes: `FeeStructure`, `AcademicSession`, `PaymentCategory` (from `models.py`, Task 1); `get_active_period` (from `services/registration.py`, already exists — signature `get_active_period(user=None) -> RegistrationPeriod | None`).
- Produces: `get_current_session(user=None) -> AcademicSession | None`, `resolve_fee_context(user) -> (AcademicSession | None, int | None)`, `resolve_amount(user, category) -> Decimal | None`, `get_payable_categories(user) -> list[(PaymentCategory, Decimal)]`. Task 4 (admin routes) and Task 5 (payment routes) both import from this module.

- [ ] **Step 1: Write `services/fee_structure.py`**

```python
from models import db, AcademicSession, PaymentCategory, FeeStructure
from services.registration import get_active_period


def get_current_session(user=None):
    """AcademicSession-level analog of get_active_period(): returns the
    is_current=True session in user's Programme's scope group, falling
    back to the shared/legacy is_current session if the user has no
    programme_id or their Programme has no current session of its own.
    user=None (or a user whose scope group and the legacy group both lack
    a current session) returns the shared/legacy current session, or None
    if even that doesn't exist."""
    if user is not None and user.programme_id is not None:
        programme_session = AcademicSession.query.filter(
            AcademicSession.is_current == True,
            AcademicSession.programme_id == user.programme_id,
        ).order_by(AcademicSession.id.desc()).first()
        if programme_session is not None:
            return programme_session

    return AcademicSession.query.filter(
        AcademicSession.is_current == True,
        AcademicSession.programme_id.is_(None),
    ).order_by(AcademicSession.id.desc()).first()


def resolve_fee_context(user):
    """Returns (session, semester_id). session is always
    get_current_session(user) — independent of whether a registration
    period is currently open, since general fee payment isn't gated on
    registration. semester_id comes from get_active_period(user) only
    when that period's academic_session_id matches the resolved session
    (so a period active in a DIFFERENT scope group's session never leaks
    its semester into this one); otherwise None (session-wide)."""
    session = get_current_session(user)
    semester_id = None
    if session is not None:
        period = get_active_period(user)
        if period is not None and period.academic_session_id == session.id:
            semester_id = period.semester_id
    return session, semester_id


def resolve_amount(user, category):
    """Returns the Decimal amount to charge `user` for `category`: the
    most specific matching FeeStructure row, tried in order
    (session, semester, dept) -> (session, semester, NULL) ->
    (session, NULL, dept) -> (session, NULL, NULL), falling back to
    category.default_amount when no row matches (or the user has no
    resolvable current session at all). A user with no department_id can
    only match NULL-department rows — never silently charged a
    department-specific amount without a resolved department."""
    session, semester_id = resolve_fee_context(user)
    if session is not None:
        department_id = user.department_id
        candidates = [(semester_id, department_id), (semester_id, None)]
        if department_id is not None:
            candidates.append((None, department_id))
        candidates.append((None, None))
        seen = set()
        for sem, dept in candidates:
            key = (sem, dept)
            if key in seen:
                continue
            seen.add(key)
            row = FeeStructure.query.filter_by(
                academic_session_id=session.id, semester_id=sem,
                department_id=dept, category_id=category.id,
            ).first()
            if row is not None:
                return row.amount
    return category.default_amount


def get_payable_categories(user):
    """Returns [(category, amount), ...] for every active PaymentCategory
    with a resolvable, non-None amount for this user — powers
    /payment/create. A category with neither a default_amount nor a
    matching FeeStructure row (e.g. registration_fee, handled by
    DepartmentRegistrationRule instead) is excluded, exactly matching the
    pre-existing `if category.default_amount is not None` filter."""
    result = []
    for category in PaymentCategory.query.filter_by(is_active=True).order_by(PaymentCategory.name).all():
        amount = resolve_amount(user, category)
        if amount is not None:
            result.append((category, amount))
    return result
```

- [ ] **Step 2: Verify against real dev data**

Throwaway script (do not commit) — run against the current dev DB, no test rows created yet so this should exactly reproduce today's flat behavior:
```python
from app import app
from models import User, PaymentCategory
from services.fee_structure import get_current_session, resolve_fee_context, resolve_amount, get_payable_categories

with app.app_context():
    student = User.query.filter(User.department_id.isnot(None)).first()
    session = get_current_session(student)
    print('current session:', session.name if session else None, session.programme_id if session else None)

    ctx_session, semester_id = resolve_fee_context(student)
    print('fee context:', ctx_session.id if ctx_session else None, semester_id)

    for category in PaymentCategory.query.filter_by(is_active=True).all():
        amount = resolve_amount(student, category)
        assert amount == category.default_amount, f'{category.code}: expected fallback to default_amount, got {amount}'
    print('all categories fall back to default_amount with zero FeeStructure rows: OK')

    payable = get_payable_categories(student)
    payable_codes = {c.code for c, _ in payable}
    assert 'registration_fee' not in payable_codes, 'registration_fee (no default_amount) must stay excluded'
    assert len(payable) == PaymentCategory.query.filter(
        PaymentCategory.is_active == True, PaymentCategory.default_amount.isnot(None)
    ).count()
    print('get_payable_categories matches pre-existing filter: OK')
```
Expected: both `OK` lines print, no assertion errors.

- [ ] **Step 3: Commit**

```bash
git add services/fee_structure.py
git commit -m "feat: add FeeStructure resolution service (get_current_session, resolve_amount, get_payable_categories)"
```

---

### Task 3: Admin service layer — `is_fee_structure_scope_unique` + `services/admin_fee_structure.py`

**Files:**
- Modify: `services/admin_validation.py` (append `is_fee_structure_scope_unique`)
- Create: `services/admin_fee_structure.py`

**Interfaces:**
- Consumes: `FeeStructure` (Task 1).
- Produces: `is_fee_structure_scope_unique(academic_session_id, semester_id, department_id, category_id, exclude_id=None) -> bool`; `list_fee_structures(session_id=None) -> list[FeeStructure]`, `get_fee_structure(id) -> FeeStructure`, `create_fee_structure(academic_session_id, semester_id, department_id, category_id, amount) -> FeeStructure`, `update_fee_structure(id, semester_id, department_id, category_id, amount) -> FeeStructure`, `delete_fee_structure(id) -> None`. Task 4 (admin routes) is the consumer.

- [ ] **Step 1: Add `is_fee_structure_scope_unique` to `services/admin_validation.py`**

Append at the end of the file (after `is_course_catalog_code_unique` and any other existing validators):

```python
def is_fee_structure_scope_unique(academic_session_id, semester_id, department_id, category_id, exclude_id=None):
    query = FeeStructure.query.filter(
        FeeStructure.academic_session_id == academic_session_id,
        FeeStructure.semester_id == semester_id,
        FeeStructure.department_id == department_id,
        FeeStructure.category_id == category_id,
    )
    if exclude_id is not None:
        query = query.filter(FeeStructure.id != exclude_id)
    return query.first() is None
```

Add `FeeStructure` to the `from models import ...` line at the top of `services/admin_validation.py` (currently `from models import Department, Programme, Course, CourseOffering, Semester, AcademicSession`).

- [ ] **Step 2: Write `services/admin_fee_structure.py`**

```python
from models import db, FeeStructure, AcademicSession


def list_fee_structures(session_id=None):
    query = FeeStructure.query
    if session_id is not None:
        query = query.filter(FeeStructure.academic_session_id == session_id)
    return query.join(AcademicSession).order_by(
        AcademicSession.start_date.desc().nullslast(), FeeStructure.category_id
    ).all()


def get_fee_structure(fee_structure_id):
    return FeeStructure.query.get_or_404(fee_structure_id)


def create_fee_structure(academic_session_id, semester_id, department_id, category_id, amount):
    row = FeeStructure(
        academic_session_id=academic_session_id, semester_id=semester_id,
        department_id=department_id, category_id=category_id, amount=amount,
    )
    db.session.add(row)
    db.session.commit()
    return row


def update_fee_structure(fee_structure_id, semester_id, department_id, category_id, amount):
    row = get_fee_structure(fee_structure_id)
    row.semester_id = semester_id
    row.department_id = department_id
    row.category_id = category_id
    row.amount = amount
    db.session.commit()
    return row


def delete_fee_structure(fee_structure_id):
    row = get_fee_structure(fee_structure_id)
    db.session.delete(row)
    db.session.commit()
```

- [ ] **Step 3: Verify uniqueness and CRUD behavior**

Throwaway script (do not commit):
```python
from app import app
from models import AcademicSession, PaymentCategory
from services.admin_validation import is_fee_structure_scope_unique
from services.admin_fee_structure import create_fee_structure, update_fee_structure, delete_fee_structure, list_fee_structures

with app.app_context():
    session = AcademicSession.query.first()
    category = PaymentCategory.query.first()

    assert is_fee_structure_scope_unique(session.id, None, None, category.id) is True

    row = create_fee_structure(session.id, None, None, category.id, 9999.00)
    assert is_fee_structure_scope_unique(session.id, None, None, category.id) is False
    assert is_fee_structure_scope_unique(session.id, None, None, category.id, exclude_id=row.id) is True

    before = len(list_fee_structures(session.id))
    update_fee_structure(row.id, None, None, category.id, 8888.00)
    assert row.amount == 8888.00
    after = len(list_fee_structures(session.id))
    assert before == after

    delete_fee_structure(row.id)
    assert is_fee_structure_scope_unique(session.id, None, None, category.id) is True
    print('OK')
```
Expected: prints `OK` with no assertion errors.

- [ ] **Step 4: Commit**

```bash
git add services/admin_validation.py services/admin_fee_structure.py
git commit -m "feat: add FeeStructure admin CRUD service + uniqueness validator"
```

---

### Task 4: Admin routes + templates + nav link

**Files:**
- Modify: `app.py` (add imports + 4 new routes)
- Modify: `templates/admin/base_admin.html` (add nav link)
- Create: `templates/admin/fee_structures.html`
- Create: `templates/admin/fee_structure_form.html`

**Interfaces:**
- Consumes: `list_fee_structures, get_fee_structure, create_fee_structure, update_fee_structure, delete_fee_structure` (Task 3); `is_fee_structure_scope_unique` (Task 3); `list_sessions, get_session, list_semesters_for_programme` (`services/admin_session.py`, already exist); `list_active_departments` (`services/admin_department.py`, already exists); `permission_required('sessions.manage')`, `log_admin_action` (already exist and are already imported/used elsewhere in `app.py`).
- Produces: routes `admin_fee_structures` (GET `/admin/fee-structure`), `admin_fee_structure_new` (GET/POST `/admin/fee-structure/new`), `admin_fee_structure_edit` (GET/POST `/admin/fee-structure/<int:fee_structure_id>/edit`), `admin_fee_structure_delete` (POST `/admin/fee-structure/<int:fee_structure_id>/delete`).

- [ ] **Step 1: Add imports to `app.py`**

`get_session`, `list_semesters_for_programme`, and `list_sessions` are already imported at `app.py:65-69` (`from services.admin_session import (...)`); `list_active_departments` is already imported at `app.py:85`; `PaymentCategory` is already imported at `app.py:10`. Nothing to add for any of those.

Add `is_fee_structure_scope_unique` to the existing `from services.admin_validation import (...)` block at `app.py:61-64` (append it to that import list rather than adding a second import line for the same module).

Add two new import lines, near the existing `from services.payment import (...)` block:
```python
from services.fee_structure import get_payable_categories, resolve_amount
from services.admin_fee_structure import (
    list_fee_structures, get_fee_structure, create_fee_structure,
    update_fee_structure, delete_fee_structure,
)
```

- [ ] **Step 2: Add the 4 routes to `app.py`**

Place these near the existing `/admin/sessions...` routes (e.g. right after the last `/admin/sessions/<int:session_id>/holidays` route, before the course-catalog routes):

```python
@app.route('/admin/fee-structure')
@permission_required('sessions.manage')
def admin_fee_structures():
    session_id = request.args.get('session_id', type=int)
    rows = list_fee_structures(session_id=session_id)
    return render_template(
        'admin/fee_structures.html', rows=rows,
        sessions=list_sessions(), selected_session_id=session_id,
    )


@app.route('/admin/fee-structure/new', methods=['GET', 'POST'])
@permission_required('sessions.manage')
def admin_fee_structure_new():
    sessions = list_sessions()
    session_id = request.args.get('session_id', type=int) or request.form.get('academic_session_id', type=int)
    selected_session = get_session(session_id) if session_id else None
    semesters = list_semesters_for_programme(selected_session.programme) if selected_session else []
    departments = list_active_departments()
    categories = PaymentCategory.query.filter_by(is_active=True).order_by(PaymentCategory.name).all()

    if request.method == 'GET' or selected_session is None:
        return render_template(
            'admin/fee_structure_form.html', row=None, sessions=sessions,
            selected_session=selected_session, semesters=semesters,
            departments=departments, categories=categories,
        )

    semester_id = request.form.get('semester_id', type=int) or None
    department_id = request.form.get('department_id', type=int) or None
    category_id = request.form.get('category_id', type=int)
    amount = request.form.get('amount', type=float)

    if not category_id or amount is None:
        flash('Category and amount are required.')
        return render_template(
            'admin/fee_structure_form.html', row=None, sessions=sessions,
            selected_session=selected_session, semesters=semesters,
            departments=departments, categories=categories, form=request.form,
        )
    if not is_fee_structure_scope_unique(selected_session.id, semester_id, department_id, category_id):
        flash('A fee structure row for this exact session/semester/department/category combination already exists.')
        return render_template(
            'admin/fee_structure_form.html', row=None, sessions=sessions,
            selected_session=selected_session, semesters=semesters,
            departments=departments, categories=categories, form=request.form,
        )

    row = create_fee_structure(selected_session.id, semester_id, department_id, category_id, amount)
    log_admin_action(current_user, 'fee_structure_created', target_type='fee_structure', target_id=row.id,
                      details=f'session_id={selected_session.id} semester_id={semester_id} department_id={department_id} category_id={category_id} amount={amount}',
                      ip_address=request.remote_addr)
    flash('Fee structure row created.')
    return redirect(url_for('admin_fee_structures', session_id=selected_session.id))


@app.route('/admin/fee-structure/<int:fee_structure_id>/edit', methods=['GET', 'POST'])
@permission_required('sessions.manage')
def admin_fee_structure_edit(fee_structure_id):
    row = get_fee_structure(fee_structure_id)
    semesters = list_semesters_for_programme(row.academic_session.programme)
    departments = list_active_departments()
    categories = PaymentCategory.query.filter_by(is_active=True).order_by(PaymentCategory.name).all()

    if request.method == 'GET':
        return render_template(
            'admin/fee_structure_form.html', row=row, sessions=None,
            selected_session=row.academic_session, semesters=semesters,
            departments=departments, categories=categories,
        )

    semester_id = request.form.get('semester_id', type=int) or None
    department_id = request.form.get('department_id', type=int) or None
    category_id = request.form.get('category_id', type=int)
    amount = request.form.get('amount', type=float)

    if not category_id or amount is None:
        flash('Category and amount are required.')
        return render_template(
            'admin/fee_structure_form.html', row=row, sessions=None,
            selected_session=row.academic_session, semesters=semesters,
            departments=departments, categories=categories, form=request.form,
        )
    if not is_fee_structure_scope_unique(row.academic_session_id, semester_id, department_id, category_id, exclude_id=row.id):
        flash('A fee structure row for this exact session/semester/department/category combination already exists.')
        return render_template(
            'admin/fee_structure_form.html', row=row, sessions=None,
            selected_session=row.academic_session, semesters=semesters,
            departments=departments, categories=categories, form=request.form,
        )

    update_fee_structure(fee_structure_id, semester_id, department_id, category_id, amount)
    log_admin_action(current_user, 'fee_structure_updated', target_type='fee_structure', target_id=fee_structure_id,
                      details=f'semester_id={semester_id} department_id={department_id} category_id={category_id} amount={amount}',
                      ip_address=request.remote_addr)
    flash('Fee structure row updated.')
    return redirect(url_for('admin_fee_structures', session_id=row.academic_session_id))


@app.route('/admin/fee-structure/<int:fee_structure_id>/delete', methods=['POST'])
@permission_required('sessions.manage')
def admin_fee_structure_delete(fee_structure_id):
    row = get_fee_structure(fee_structure_id)
    session_id = row.academic_session_id
    delete_fee_structure(fee_structure_id)
    log_admin_action(current_user, 'fee_structure_deleted', target_type='fee_structure', target_id=fee_structure_id,
                      details=f'session_id={session_id}', ip_address=request.remote_addr)
    flash('Fee structure row deleted.')
    return redirect(url_for('admin_fee_structures', session_id=session_id))
```

- [ ] **Step 3: Add the nav link**

In `templates/admin/base_admin.html`, add a new `<li>` right after the existing Registration nav link (currently `templates/admin/base_admin.html:27`):

```html
<li><a href="{{ url_for('admin_fee_structures') }}" class="{{ 'active' if request.endpoint and request.endpoint.startswith('admin_fee_structure') }}"><i class="fas fa-money-bill-wave"></i> Fee Structure</a></li>
```

- [ ] **Step 4: Write `templates/admin/fee_structures.html`**

```html
{% extends "admin/base_admin.html" %}

{% block breadcrumbs %}Fee Structure{% endblock %}

{% block content %}
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem;">
    <form method="GET" style="display:flex; gap:0.6rem;">
        <select name="session_id" onchange="this.form.submit()" style="padding:0.5rem 0.8rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main);">
            <option value="">All Sessions</option>
            {% for s in sessions %}
            <option value="{{ s.id }}" {{ 'selected' if selected_session_id == s.id }}>{{ s.name }}{{ ' (' + s.programme.name + ')' if s.programme else ' (Shared / Legacy)' }}</option>
            {% endfor %}
        </select>
    </form>
    <a href="{{ url_for('admin_fee_structure_new') }}" style="padding:0.6rem 1.2rem; background: var(--primary); color:white; border-radius:0.5rem; text-decoration:none; font-weight:600;"><i class="fas fa-plus"></i> New Fee Structure Row</a>
</div>

<div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; overflow:hidden;">
    <table style="width:100%; border-collapse:collapse;">
        <thead>
            <tr style="text-align:left; border-bottom: 1px solid var(--border-color);">
                <th style="padding:0.8rem;">Session</th>
                <th style="padding:0.8rem;">Semester</th>
                <th style="padding:0.8rem;">Department</th>
                <th style="padding:0.8rem;">Category</th>
                <th style="padding:0.8rem;">Amount</th>
                <th style="padding:0.8rem;"></th>
            </tr>
        </thead>
        <tbody>
            {% for row in rows %}
            <tr style="border-bottom: 1px solid var(--border-color);">
                <td style="padding:0.8rem;">{{ row.academic_session.name }}{{ ' (' + row.programme.name + ')' if row.programme else '' }}</td>
                <td style="padding:0.8rem;">{{ row.semester.name if row.semester else 'All semesters' }}</td>
                <td style="padding:0.8rem;">{{ row.department.name if row.department else 'All departments' }}</td>
                <td style="padding:0.8rem;">{{ row.category.name }}</td>
                <td style="padding:0.8rem;">₦{{ '{:,.2f}'.format(row.amount) }}</td>
                <td style="padding:0.8rem; text-align:right;">
                    <a href="{{ url_for('admin_fee_structure_edit', fee_structure_id=row.id) }}" style="color: var(--primary-dark); margin-right:0.8rem;">Edit</a>
                    <form method="POST" action="{{ url_for('admin_fee_structure_delete', fee_structure_id=row.id) }}" style="display:inline;" onsubmit="return confirm('Delete this fee structure row?');">
                        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                        <button type="submit" style="background:none; border:none; color: var(--danger); cursor:pointer;">Delete</button>
                    </form>
                </td>
            </tr>
            {% else %}
            <tr><td colspan="6" style="padding:2rem; text-align:center; color: var(--text-muted);">No fee structure overrides yet — every category falls back to its default amount for every student.</td></tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}
```

- [ ] **Step 5: Write `templates/admin/fee_structure_form.html`**

```html
{% extends "admin/base_admin.html" %}

{% block breadcrumbs %}Fee Structure / {{ 'Edit' if row else 'New' }}{% endblock %}

{% block content %}
<div style="max-width:560px; background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; padding: 1.5rem;">
    <h2 style="margin-top:0;">{{ 'Edit Fee Structure Row' if row else 'New Fee Structure Row' }}</h2>

    {% if not selected_session %}
    <form method="GET">
        <div style="margin-bottom:1rem;">
            <label style="display:block; margin-bottom:0.3rem; font-weight:600;">Session</label>
            <select name="session_id" required onchange="this.form.submit()" style="width:100%; padding:0.6rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main);">
                <option value="">Select a session…</option>
                {% for s in sessions %}
                <option value="{{ s.id }}">{{ s.name }}{{ ' (' + s.programme.name + ')' if s.programme else ' (Shared / Legacy)' }}</option>
                {% endfor %}
            </select>
        </div>
    </form>
    {% else %}
    <p style="color: var(--text-muted); font-size:0.85rem; margin-top:-0.5rem; margin-bottom:1rem;">Session: {{ selected_session.name }}{{ ' — ' + selected_session.programme.name if selected_session.programme else ' — Shared / Legacy' }}</p>
    <form method="POST">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <input type="hidden" name="academic_session_id" value="{{ selected_session.id }}">
        <div style="margin-bottom:1rem;">
            <label style="display:block; margin-bottom:0.3rem; font-weight:600;">Semester</label>
            <select name="semester_id" style="width:100%; padding:0.6rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main);">
                <option value="">All semesters</option>
                {% for sem in semesters %}
                <option value="{{ sem.id }}" {{ 'selected' if row and row.semester_id == sem.id }}>{{ sem.name }}</option>
                {% endfor %}
            </select>
        </div>
        <div style="margin-bottom:1rem;">
            <label style="display:block; margin-bottom:0.3rem; font-weight:600;">Department</label>
            <select name="department_id" style="width:100%; padding:0.6rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main);">
                <option value="">All departments</option>
                {% for dept in departments %}
                <option value="{{ dept.id }}" {{ 'selected' if row and row.department_id == dept.id }}>{{ dept.name }}</option>
                {% endfor %}
            </select>
        </div>
        <div style="margin-bottom:1rem;">
            <label style="display:block; margin-bottom:0.3rem; font-weight:600;">Category</label>
            <select name="category_id" required style="width:100%; padding:0.6rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main);">
                <option value="">Select a category…</option>
                {% for cat in categories %}
                <option value="{{ cat.id }}" {{ 'selected' if row and row.category_id == cat.id }}>{{ cat.name }}</option>
                {% endfor %}
            </select>
        </div>
        <div style="margin-bottom:1.5rem;">
            <label style="display:block; margin-bottom:0.3rem; font-weight:600;">Amount (₦)</label>
            <input type="number" step="0.01" name="amount" required value="{{ row.amount if row else '' }}"
                   style="width:100%; padding:0.6rem; border:1px solid var(--border-color); border-radius:0.5rem; background: var(--bg-body); color: var(--text-main); box-sizing:border-box;">
        </div>
        <button type="submit" style="padding:0.7rem 1.5rem; background: var(--primary); color:white; border:none; border-radius:0.5rem; font-weight:600; cursor:pointer;">{{ 'Save Changes' if row else 'Create' }}</button>
        <a href="{{ url_for('admin_fee_structures', session_id=selected_session.id) }}" style="margin-left:1rem; color: var(--text-muted);">Cancel</a>
    </form>
    {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 6: Manual verification**

Start the dev server (`flask run` or however it's normally started) and, logged in as Super Administrator:
1. Visit `/admin/fee-structure` — page loads, empty state shows.
2. Click "New Fee Structure Row" — Session dropdown shown; selecting a session reloads the page with the full form.
3. Create a row (any semester/department = "All", any category, any amount) — redirects back to the list, flash message shown, new row appears.
4. Edit the row — change the amount, save — updated amount shows in the list.
5. Attempt to create a second row with the identical scope (same session/semester/department/category) — rejected with the duplicate-scope flash message.
6. Delete the row — confirm dialog, row removed from the list.
7. Log in as an Academic Administrator (lacks `sessions.manage`) and confirm `/admin/fee-structure` redirects/403s the same way `/admin/sessions` already does for that role.

- [ ] **Step 7: Commit**

```bash
git add app.py templates/admin/base_admin.html templates/admin/fee_structures.html templates/admin/fee_structure_form.html
git commit -m "feat: add Fee Structure admin routes, templates, and nav link"
```

---

### Task 5: Wire the general payment flow to resolved amounts

**Files:**
- Modify: `app.py:683-717` (`payment_create_page`, `payment_create_submit`)
- Modify: `templates/payment_create.html`
- Modify: `services/payment.py` (delete `get_active_categories`)

**Interfaces:**
- Consumes: `get_payable_categories(user)`, `resolve_amount(user, category)` (Task 2, already imported into `app.py` in Task 4 — if this task runs independently/first, add the same `from services.fee_structure import get_payable_categories, resolve_amount` import to `app.py`).

- [ ] **Step 1: Rewrite `payment_create_page`**

Replace `app.py:683-688`:
```python
@app.route('/payment/create', methods=['GET'])
@login_required
def payment_create_page():
    categories = [c for c in get_active_categories() if c.default_amount is not None]
    idempotency_key = str(uuid.uuid4())
    return render_template('payment_create.html', categories=categories, idempotency_key=idempotency_key)
```

with:
```python
@app.route('/payment/create', methods=['GET'])
@login_required
def payment_create_page():
    payable = get_payable_categories(current_user)
    idempotency_key = str(uuid.uuid4())
    return render_template('payment_create.html', payable=payable, idempotency_key=idempotency_key)
```

- [ ] **Step 2: Rewrite the amount lookup in `payment_create_submit`**

Replace `app.py:705-717`:
```python
    item_specs = []
    for sel in selections:
        if not isinstance(sel, dict):
            continue
        category = PaymentCategory.query.filter_by(id=sel.get('category_id'), is_active=True).first()
        if category is None or category.default_amount is None:
            continue
        try:
            quantity = int(sel.get('quantity', 1))
        except (TypeError, ValueError):
            quantity = 1
        quantity = max(1, min(quantity, 10))
        item_specs.append((category, quantity, category.default_amount))
```

with:
```python
    item_specs = []
    for sel in selections:
        if not isinstance(sel, dict):
            continue
        category = PaymentCategory.query.filter_by(id=sel.get('category_id'), is_active=True).first()
        if category is None:
            continue
        amount = resolve_amount(current_user, category)
        if amount is None:
            continue
        try:
            quantity = int(sel.get('quantity', 1))
        except (TypeError, ValueError):
            quantity = 1
        quantity = max(1, min(quantity, 10))
        item_specs.append((category, quantity, amount))
```

- [ ] **Step 3: Confirm the import from Task 4 is present**

Task 4 already added `from services.fee_structure import get_payable_categories, resolve_amount` to `app.py`. Confirm it's there (both names are used by Steps 1-2 above); if this task is somehow being executed before Task 4, add that import line near the existing `from services.payment import (...)` block.

- [ ] **Step 4: Remove the now-dead `get_active_categories` import and function**

In `app.py`, remove `get_active_categories` from the `from services.payment import (...)` import list.

In `services/payment.py`, delete:
```python
def get_active_categories():
    return PaymentCategory.query.filter_by(is_active=True).order_by(PaymentCategory.name).all()
```

`PaymentCategory` is imported in `services/payment.py:6` (`from models import db, now_lagos, Payment, PaymentItem, PaymentCategory`) solely for this function — confirm no other function in the file uses it (it doesn't, as of this plan), and remove `PaymentCategory` from that import line too, leaving `from models import db, now_lagos, Payment, PaymentItem`.

- [ ] **Step 5: Update `templates/payment_create.html`**

The current file (in full) is:

```html
{% extends "base.html" %}

{% block head %}
    <title>Create Payment · Student Portal</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/payment_create.css') }}">
{% endblock %}

{% block content %}
<div class="payment-create-page">
    <input type="hidden" id="csrf_token" value="{{ csrf_token() }}">
    <input type="hidden" id="idempotencyKey" value="{{ idempotency_key }}">

    <div class="page-header">
        <a href="{{ url_for('payments_history') }}" class="back-link"><i class="fas fa-arrow-left"></i> Payment History</a>
        <h1 class="page-title"><i class="fas fa-plus-circle"></i> Create Payment</h1>
        <div></div>
    </div>

    {% if not categories %}
    <div class="empty-state-card">
        <i class="fas fa-inbox"></i>
        <p>No payable items are currently available.</p>
    </div>
    {% else %}
    <div class="category-grid" id="categoryGrid">
        {% for category in categories %}
        <label class="category-card">
            <input type="checkbox" class="category-checkbox" data-id="{{ category.id }}" data-amount="{{ category.default_amount }}" data-name="{{ category.name }}">
            <div class="category-info">
                <span class="category-name">{{ category.name }}</span>
                {% if category.description %}<span class="category-desc">{{ category.description }}</span>{% endif %}
            </div>
            <span class="category-amount">₦{{ '{:,.2f}'.format(category.default_amount) }}</span>
        </label>
        {% endfor %}
    </div>

    <div class="summary-panel">
        <h3><i class="fas fa-receipt"></i> Payment Summary</h3>
        <ul id="summaryList" class="summary-list">
            <li class="summary-empty">No items selected yet.</li>
        </ul>
        <div class="summary-total">
            <span>Total</span>
            <span id="summaryTotal">₦0.00</span>
        </div>
        <button class="pay-now-btn" id="proceedBtn" disabled><i class="fas fa-credit-card"></i> Proceed to Payment</button>
    </div>
    {% endif %}
</div>

<div id="toastMsg" class="toast-msg"></div>
{% endblock %}

{% block scripts %}
<script type="module" src="{{ url_for('static', filename='js/payment_create/payment_create.js') }}"></script>
{% endblock %}
```

Change exactly two things — the empty-state check and the loop — leaving every other line (including the JS/CSS includes, the summary panel, and every class/id used by `static/js/payment_create/payment_create.js`) untouched:

```html
    {% if not payable %}
    <div class="empty-state-card">
        <i class="fas fa-inbox"></i>
        <p>No payable items are currently available.</p>
    </div>
    {% else %}
    <div class="category-grid" id="categoryGrid">
        {% for category, amount in payable %}
        <label class="category-card">
            <input type="checkbox" class="category-checkbox" data-id="{{ category.id }}" data-amount="{{ amount }}" data-name="{{ category.name }}">
            <div class="category-info">
                <span class="category-name">{{ category.name }}</span>
                {% if category.description %}<span class="category-desc">{{ category.description }}</span>{% endif %}
            </div>
            <span class="category-amount">₦{{ '{:,.2f}'.format(amount) }}</span>
        </label>
        {% endfor %}
    </div>
```

(`data-amount`'s attribute name and the JS that reads it are unchanged — only the Jinja expression producing its value changes, from `category.default_amount` to the unpacked `amount`.)

- [ ] **Step 6: Verify no other consumer of `get_active_categories` remains**

Run: `grep -rn "get_active_categories" --include=*.py .` (excluding `.claude/worktrees/`)
Expected: zero matches.

- [ ] **Step 7: Manual verification**

Throwaway script (do not commit) — confirms the wiring end-to-end via `test_client`, using a single `test_client` context per user per the established Flask-Login `app_context` caching hazard (documented in `docs/superpowers/CURRENT_STATE.md` — never share one `app_context()` across multiple different-user `test_client` interactions):
```python
from app import app
from models import db, User, AcademicSession, FeeStructure, PaymentCategory

with app.app_context():
    student = User.query.filter(User.department_id.isnot(None)).first()
    session = AcademicSession.query.filter_by(is_current=True, programme_id=None).first()
    category = PaymentCategory.query.filter(PaymentCategory.default_amount.isnot(None)).first()
    override = FeeStructure(
        academic_session_id=session.id, department_id=student.department_id,
        category_id=category.id, amount=category.default_amount + 1000,
    )
    db.session.add(override)
    db.session.commit()
    override_id = override.id

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(student.id)
    resp = client.get('/payment/create')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert f'{category.default_amount + 1000:,.2f}' in body, 'overridden amount not shown on /payment/create'
    print('GET /payment/create shows the FeeStructure-overridden amount: OK')

with app.app_context():
    db.session.delete(FeeStructure.query.get(override_id))
    db.session.commit()
    print('cleanup OK')
```
Expected: both `OK` lines print. Delete the script after running it. (Login mechanism: this codebase uses Flask-Login with `session['_user_id']` — confirm this matches the actual `User.get_id()`/login_manager setup by checking how any prior sub-project's verification scripts logged in a real student, e.g. sub-project 4's Task 5 report.)

- [ ] **Step 8: Commit**

```bash
git add app.py services/payment.py templates/payment_create.html
git commit -m "feat: wire /payment/create to FeeStructure-resolved amounts, remove dead get_active_categories"
```

---

### Task 6: End-to-end verification + `CURRENT_STATE.md` update

**Files:**
- Modify: `docs/superpowers/CURRENT_STATE.md`

**Interfaces:**
- Consumes: everything from Tasks 1-5.

- [ ] **Step 1: Confirm dev DB cleanliness before starting**

Per the established, repeatedly-confirmed lesson in this refactor (documented multiple times in `docs/superpowers/CURRENT_STATE.md`'s Notes — "dev DB not actually clean" has recurred 3+ times): before writing any new verification data, run a fresh-process query confirming `FeeStructure.query.count()` and every other table's row counts match the expected baseline (no stray rows from Tasks 1-5's own throwaway scripts, which should all have cleaned up after themselves — verify that actually happened, don't assume it).

- [ ] **Step 2: Re-verify the full resolution algorithm end-to-end**

Throwaway script exercising, against real data, in one `app_context` (no `test_client` needed for this step — pure service-layer calls, not HTTP):
1. A student with `department_id` set and a session-wide (`NULL`/`NULL`) `FeeStructure` row for a category — resolves to that row's amount.
2. The same category, same session, now with an additional department-specific row matching that student's `department_id` — resolves to the *more specific* department row, not the session-wide one.
3. A different student, different department, same session/category — still resolves to the session-wide row (or default), never the first student's department-specific override.
4. A student with `department_id=None` — never matches a department-specific row, even if one exists for some other department; always falls through to the `NULL`-department row or `category.default_amount`.
5. `get_current_session` for a student whose Programme has its own `is_current` session returns that session; a student with no Programme (or whose Programme has no current session) falls back to the shared/legacy current session.
Delete every row created during this step; re-confirm row counts match the Step 1 baseline afterward.

- [ ] **Step 3: Full HTTP-level regression — student and admin portals**

Using the single-`app_context`-per-user pattern (never multiple different users sharing one `app_context`/`test_client` pairing — the documented Flask-Login caching hazard):
- Student: `/login`, `/`, `/payment/create` (GET and a real POST creating a `Payment`), `/registration` all still 200/expected. `/add_drop/*` still works (confirms `services/registration.py` — untouched by this sub-project — has no import breakage from the new `services/fee_structure.py` module).
- Admin (Super Administrator via the session-cookie trick, since the seeded admin's real password is unknown/rotated on `main`, per prior sub-projects' documented practice): `/admin/dashboard`, `/admin/sessions`, `/admin/fee-structure`, `/admin/registration/open`, `/admin/students` all 200.
- Admin (Academic Administrator, lacks `sessions.manage`): `/admin/fee-structure` correctly denied, matching `/admin/sessions`'s existing behavior for that role.

- [ ] **Step 4: Regression-check the untouched registration-fee mechanism**

Confirm `register_student()`, `get_credit_limits()`, and `DepartmentRegistrationRule` still behave identically to before this sub-project — register a real (or throwaway) student for an open period and confirm the created `Payment`/`PaymentItem` for `registration_fee` uses `DepartmentRegistrationRule`/`period.registration_fee` exactly as before, completely unaffected by any `FeeStructure` row (confirm this even if a `FeeStructure` row happens to target the `registration_fee` category for that session — this sub-project's design explicitly keeps that category's *registration-time* charge on the old mechanism; a `FeeStructure` override for `registration_fee` would only ever be visible through `/payment/create`, a separate, optional path, never through `register_student()`).

- [ ] **Step 5: Update `docs/superpowers/CURRENT_STATE.md`**

Update `docs/superpowers/CURRENT_STATE.md` following the exact pattern used after sub-projects 1-4: set "Active Worktree" to reflect this sub-project's worktree state, add a "Completed" entry for sub-project 5 (FeeStructure) once merged (this entry gets finalized during `superpowers:finishing-a-development-branch`, not by this task directly, but this task should leave the ledger/verification notes ready for that step — document what Step 2-4 found, including any real bugs caught and fixed), update "Current Milestone"/"Next" to point at Phase C (Student/Admin Portal verification + `DEVELOPMENT_PROGRESS.md` update — the final step of the whole DDD refactor, now that this is the last of the 5 sub-projects).

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/CURRENT_STATE.md
git commit -m "docs: record sub-project 5 (FeeStructure) end-to-end verification"
```
