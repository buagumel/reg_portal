# Semester Registration Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fully-mocked `registration.html` page with a real, database-driven semester registration workflow (status card, register-now with simulated payment, registration history), per `docs/superpowers/specs/2026-07-30-semester-registration-design.md`.

**Architecture:** Five new SQLAlchemy models (`AcademicSession`, `Semester`, `RegistrationPeriod`, `DepartmentRegistrationRule`, `StudentRegistration`), a new `services/registration.py` business-logic module, two routes in `app.py` (rewritten `registration()`, new `POST /registration/register`), and a rewritten `registration.html` + new `registration.js` consuming server-rendered context instead of a hardcoded mock array.

**Tech Stack:** Flask, Flask-SQLAlchemy (SQLite dev DB), vanilla ES module JS (`fetch`, no framework), Jinja2.

## Global Constraints

- No Alembic migration — the dev DB is rebuilt via `db.create_all()`, per established project convention.
- No automated test framework in this repo — verification is manual via Flask `test_client` / `test_request_context` scripts, per established project convention (see Milestone 1/2 plans).
- Do NOT implement Course Add/Drop (`add_drop.html`, `my_courses.html`) — next milestone.
- Do NOT build a real Remita integration — `register_student` simulates a successful payment and marks the exact integration point with a `# TODO` comment.
- Do NOT build an admin UI for managing sessions/periods/rules — configuration comes from `seed_dev_data.py` only.
- Do NOT fix the missing `@login_required` on `add_drop`, `my_courses`, `payments_history`, `pay_summary` — known pre-existing issue, out of scope (those routes/pages aren't touched here).
- All new datetime columns (`opens_at`, `closes_at`, `registered_at`, `updated_at`, `created_at`) store **naive datetimes representing Lagos local time** — never pass a timezone-aware `datetime` into these columns (SQLite has no native tz support and round-trips inconsistently). Use the `now_lagos()` helper added in Task 1 everywhere "now" is needed.
- `RegistrationPeriod.registration_fee` / `DepartmentRegistrationRule.registration_fee` are `db.Numeric(10, 2)` — treat as `Decimal` in Python (comparisons, formatting), not `float`.

---

### Task 1: Data Models

**Files:**
- Modify: `models.py`

**Interfaces:**
- Produces: `now_lagos()` helper function; `AcademicSession(id, name, is_current)`; `Semester(id, name, order)`; `RegistrationPeriod(id, academic_session_id, semester_id, opens_at, closes_at, min_credits, max_credits, registration_fee, is_active, created_at, academic_session, semester)`; `DepartmentRegistrationRule(id, registration_period_id, department, min_credits, max_credits, registration_fee)`; `StudentRegistration(id, user_id, registration_period_id, status, payment_status, payment_reference, credits_registered, registered_at, updated_at, registration_period)`.

- [ ] **Step 1: Add the `now_lagos()` helper**

In `models.py`, right after the `LAGOS_TZ = ZoneInfo("Africa/Lagos")` line (line 13), add:

```python

def now_lagos():
    """Current time as a naive datetime representing Lagos local time.
    SQLite has no native timezone support, so every datetime column in this
    app stores naive values on this convention — never store a tz-aware
    datetime directly."""
    return datetime.now(LAGOS_TZ).replace(tzinfo=None)
```

- [ ] **Step 2: Add the five new model classes**

At the end of `models.py` (after the `Payment` class, which stays untouched), append:

```python

class AcademicSession(db.Model):
    __tablename__ = 'academic_sessions'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(20), unique=True, nullable=False)
    is_current = db.Column(db.Boolean, default=False, nullable=False)


class Semester(db.Model):
    __tablename__ = 'semesters'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    order = db.Column(db.Integer, nullable=False)


class RegistrationPeriod(db.Model):
    __tablename__ = 'registration_periods'
    id = db.Column(db.Integer, primary_key=True)
    academic_session_id = db.Column(db.Integer, db.ForeignKey('academic_sessions.id'), nullable=False)
    semester_id = db.Column(db.Integer, db.ForeignKey('semesters.id'), nullable=False)
    opens_at = db.Column(db.DateTime, nullable=False)
    closes_at = db.Column(db.DateTime, nullable=False)
    min_credits = db.Column(db.Integer, nullable=False)
    max_credits = db.Column(db.Integer, nullable=False)
    registration_fee = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)

    academic_session = db.relationship('AcademicSession')
    semester = db.relationship('Semester')


class DepartmentRegistrationRule(db.Model):
    __tablename__ = 'department_registration_rules'
    id = db.Column(db.Integer, primary_key=True)
    registration_period_id = db.Column(db.Integer, db.ForeignKey('registration_periods.id'), nullable=False)
    department = db.Column(db.String(150), nullable=False)
    min_credits = db.Column(db.Integer, nullable=True)
    max_credits = db.Column(db.Integer, nullable=True)
    registration_fee = db.Column(db.Numeric(10, 2), nullable=True)

    __table_args__ = (db.UniqueConstraint('registration_period_id', 'department'),)


class StudentRegistration(db.Model):
    __tablename__ = 'student_registrations'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    registration_period_id = db.Column(db.Integer, db.ForeignKey('registration_periods.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='registered')
    payment_status = db.Column(db.String(20), nullable=False, default='pending')
    payment_reference = db.Column(db.String(100), nullable=True)
    credits_registered = db.Column(db.Integer, nullable=False, default=0)
    registered_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
    updated_at = db.Column(db.DateTime, default=now_lagos, onupdate=now_lagos, nullable=False)

    __table_args__ = (db.UniqueConstraint('user_id', 'registration_period_id'),)

    registration_period = db.relationship('RegistrationPeriod')
```

- [ ] **Step 3: Boot check and table verification**

Run: `python -c "import app; print('OK')"`
Expected: prints `OK` with no traceback (this also runs `db.create_all()`, creating the 5 new tables in `instance/database.db`).

Then run:
```bash
python -c "
from app import app
from models import db
with app.app_context():
    tables = db.inspect(db.engine).get_table_names()
    for t in ('academic_sessions', 'semesters', 'registration_periods', 'department_registration_rules', 'student_registrations'):
        assert t in tables, f'{t} missing'
    print('All 5 tables present')
"
```
Expected: `All 5 tables present`, no assertion error.

- [ ] **Step 4: Commit**

```bash
git add models.py
git commit -m "feat: add registration data models (session, semester, period, department rule, student registration)"
```

---

### Task 2: Service Layer

**Files:**
- Create: `services/registration.py`

**Interfaces:**
- Consumes: `db`, `now_lagos`, `RegistrationPeriod`, `DepartmentRegistrationRule`, `StudentRegistration` from `models` (Task 1).
- Produces: `RegistrationError(Exception)`; `get_active_period() -> RegistrationPeriod | None`; `get_window_status(period) -> str` (`'not_yet_open' | 'open' | 'closed'`); `get_credit_limits(period, department) -> (min_credits, max_credits, registration_fee)`; `get_registration_status_context(user) -> dict` (keys: `period`, `window_status`, `min_credits`, `max_credits`, `registration_fee`, `existing_registration`); `register_student(user, period) -> StudentRegistration`; `get_registration_history(user) -> list[StudentRegistration]`.

- [ ] **Step 1: Write the service module**

Create `services/registration.py`:

```python
import random
import string

from models import db, now_lagos, RegistrationPeriod, DepartmentRegistrationRule, StudentRegistration


class RegistrationError(Exception):
    """Raised for a business-rule violation in the registration flow.
    The message is user-facing."""


def get_active_period():
    """Return the RegistrationPeriod the admin has marked as current, or None
    if none is configured. If more than one is ever marked active (shouldn't
    happen, but nothing enforces it at the DB level), the most recently
    created one wins."""
    return (
        RegistrationPeriod.query
        .filter_by(is_active=True)
        .order_by(RegistrationPeriod.id.desc())
        .first()
    )


def get_window_status(period):
    """Return 'not_yet_open', 'open', or 'closed' for the given period,
    based on now_lagos() vs. period.opens_at / period.closes_at."""
    now = now_lagos()
    if now < period.opens_at:
        return 'not_yet_open'
    if now > period.closes_at:
        return 'closed'
    return 'open'


def get_credit_limits(period, department):
    """Return (min_credits, max_credits, registration_fee) for a department,
    applying any DepartmentRegistrationRule override field-by-field over the
    period's defaults."""
    min_credits = period.min_credits
    max_credits = period.max_credits
    registration_fee = period.registration_fee

    rule = DepartmentRegistrationRule.query.filter_by(
        registration_period_id=period.id, department=department
    ).first()
    if rule:
        if rule.min_credits is not None:
            min_credits = rule.min_credits
        if rule.max_credits is not None:
            max_credits = rule.max_credits
        if rule.registration_fee is not None:
            registration_fee = rule.registration_fee

    return min_credits, max_credits, registration_fee


def get_registration_status_context(user):
    """Assemble everything the registration page needs for the current
    student: the active period (or None), its window status, the student's
    resolved credit limits/fee, and their existing StudentRegistration for
    that period (or None)."""
    period = get_active_period()
    if period is None:
        return {
            'period': None,
            'window_status': None,
            'min_credits': None,
            'max_credits': None,
            'registration_fee': None,
            'existing_registration': None,
        }

    min_credits, max_credits, registration_fee = get_credit_limits(period, user.department)
    existing_registration = StudentRegistration.query.filter_by(
        user_id=user.id, registration_period_id=period.id
    ).first()

    return {
        'period': period,
        'window_status': get_window_status(period),
        'min_credits': min_credits,
        'max_credits': max_credits,
        'registration_fee': registration_fee,
        'existing_registration': existing_registration,
    }


def _generate_payment_reference():
    # TODO: replace with the real Remita payment reference once the Remita
    # integration is built (initiate payment -> webhook/callback verifies
    # the transaction -> only then create/confirm this record).
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
    return f'SIMULATED-{suffix}'


def register_student(user, period):
    """Validate and create a StudentRegistration for the given period, with
    payment simulated as immediately successful. Raises RegistrationError on
    any business-rule violation."""
    if get_window_status(period) != 'open':
        raise RegistrationError('Registration is not currently open for this period.')

    existing = StudentRegistration.query.filter_by(
        user_id=user.id, registration_period_id=period.id
    ).first()
    if existing:
        raise RegistrationError('You are already registered for this period.')

    # TODO: this is where real Remita payment initiation would happen instead
    # of immediately marking payment_status='paid'. For now the full workflow
    # (record creation + "successful payment") is simulated so downstream
    # features (Add/Drop, payment history) can be built against a real record.
    registration = StudentRegistration(
        user_id=user.id,
        registration_period_id=period.id,
        status='registered',
        payment_status='paid',
        payment_reference=_generate_payment_reference(),
        credits_registered=0,
    )
    db.session.add(registration)
    db.session.commit()
    return registration


def get_registration_history(user):
    """Return all of the student's StudentRegistration records, newest first."""
    return (
        StudentRegistration.query
        .filter_by(user_id=user.id)
        .order_by(StudentRegistration.registered_at.desc())
        .all()
    )
```

- [ ] **Step 2: Manual verification script**

Create a throwaway script `scratch_verify_service.py` in the project root:

```python
from datetime import timedelta

from app import app
from models import db, now_lagos, AcademicSession, Semester, RegistrationPeriod, DepartmentRegistrationRule, User
from services.registration import (
    get_active_period, get_window_status, get_credit_limits,
    get_registration_status_context, register_student, get_registration_history,
    RegistrationError,
)

with app.app_context():
    db.create_all()

    session = AcademicSession(name='TEST/SESSION', is_current=True)
    semester = Semester(name='Test Semester', order=1)
    db.session.add_all([session, semester])
    db.session.commit()

    open_period = RegistrationPeriod(
        academic_session_id=session.id, semester_id=semester.id,
        opens_at=now_lagos() - timedelta(days=1), closes_at=now_lagos() + timedelta(days=7),
        min_credits=15, max_credits=24, registration_fee=45000, is_active=True,
    )
    db.session.add(open_period)
    db.session.commit()

    assert get_active_period().id == open_period.id
    assert get_window_status(open_period) == 'open'

    closed_period = RegistrationPeriod(
        academic_session_id=session.id, semester_id=semester.id,
        opens_at=now_lagos() - timedelta(days=30), closes_at=now_lagos() - timedelta(days=1),
        min_credits=15, max_credits=24, registration_fee=45000, is_active=False,
    )
    not_yet_period = RegistrationPeriod(
        academic_session_id=session.id, semester_id=semester.id,
        opens_at=now_lagos() + timedelta(days=1), closes_at=now_lagos() + timedelta(days=7),
        min_credits=15, max_credits=24, registration_fee=45000, is_active=False,
    )
    db.session.add_all([closed_period, not_yet_period])
    db.session.commit()
    assert get_window_status(closed_period) == 'closed'
    assert get_window_status(not_yet_period) == 'not_yet_open'

    rule = DepartmentRegistrationRule(
        registration_period_id=open_period.id, department='Information Technology',
        min_credits=12, max_credits=None, registration_fee=None,
    )
    db.session.add(rule)
    db.session.commit()
    min_c, max_c, fee = get_credit_limits(open_period, 'Information Technology')
    assert (min_c, max_c) == (12, 24), (min_c, max_c)
    min_c, max_c, fee = get_credit_limits(open_period, 'Computer Science')
    assert (min_c, max_c) == (15, 24), (min_c, max_c)

    user = User.query.filter_by(reg_no='2308-2301-0004').first()
    assert user is not None, 'run seed_dev_data.py first'

    ctx = get_registration_status_context(user)
    assert ctx['period'].id == open_period.id
    assert ctx['existing_registration'] is None

    reg = register_student(user, open_period)
    assert reg.payment_status == 'paid'
    assert reg.payment_reference.startswith('SIMULATED-')

    try:
        register_student(user, open_period)
        raise SystemExit('expected RegistrationError on duplicate registration')
    except RegistrationError:
        pass

    try:
        register_student(user, closed_period)
        raise SystemExit('expected RegistrationError on closed period')
    except RegistrationError:
        pass

    history = get_registration_history(user)
    assert len(history) == 1
    assert history[0].id == reg.id

    # cleanup this script's own rows so re-runs stay idempotent
    db.session.delete(reg)
    db.session.delete(rule)
    db.session.delete(open_period)
    db.session.delete(closed_period)
    db.session.delete(not_yet_period)
    db.session.delete(session)
    db.session.delete(semester)
    db.session.commit()

    print('All service-layer checks passed')
```

Run: `python seed_dev_data.py` (if not already run) then `python scratch_verify_service.py`
Expected: `All service-layer checks passed`, no assertion errors, no traceback.

Delete the script afterward: `rm scratch_verify_service.py` (do not commit it).

- [ ] **Step 3: Commit**

```bash
git add services/registration.py
git commit -m "feat: add registration service layer (status, register, history)"
```

---

### Task 3: Seed Data

**Files:**
- Modify: `seed_dev_data.py`

**Interfaces:**
- Consumes: `AcademicSession`, `Semester`, `RegistrationPeriod`, `DepartmentRegistrationRule`, `StudentRegistration`, `now_lagos` from `models` (Task 1).

- [ ] **Step 1: Extend the seed script**

In `seed_dev_data.py`, update the imports (line 8-9) to:

```python
from datetime import date, timedelta

from app import app
from models import (
    db, User, now_lagos,
    AcademicSession, Semester, RegistrationPeriod, DepartmentRegistrationRule, StudentRegistration,
)
```

Then, after the existing `def seed():` function's student-seeding loop and its `db.session.commit()` (so demo students exist first, since the registration seed needs `User.query` to find student `2308-2301-0004`), and before the final `print(...)` line, add a second function and call it from `seed()`:

```python
def seed_registration_config():
    session_name = '2025/2026'
    academic_session = AcademicSession.query.filter_by(name=session_name).first()
    if not academic_session:
        academic_session = AcademicSession(name=session_name, is_current=True)
        db.session.add(academic_session)
        db.session.commit()
        print(f'Created academic session {session_name}')
    else:
        print(f'Skipping academic session {session_name} (already exists)')

    semesters = {}
    for name, order in [('First Semester', 1), ('Second Semester', 2)]:
        semester = Semester.query.filter_by(name=name).first()
        if not semester:
            semester = Semester(name=name, order=order)
            db.session.add(semester)
            db.session.commit()
            print(f'Created semester {name}')
        else:
            print(f'Skipping semester {name} (already exists)')
        semesters[name] = semester

    active_period = RegistrationPeriod.query.filter_by(
        academic_session_id=academic_session.id, semester_id=semesters['First Semester'].id
    ).first()
    if not active_period:
        active_period = RegistrationPeriod(
            academic_session_id=academic_session.id,
            semester_id=semesters['First Semester'].id,
            opens_at=now_lagos() - timedelta(days=3),
            closes_at=now_lagos() + timedelta(days=21),
            min_credits=15, max_credits=24, registration_fee=45000,
            is_active=True,
        )
        db.session.add(active_period)
        db.session.commit()
        print('Created active RegistrationPeriod: 2025/2026 First Semester (open)')
    else:
        print('Skipping active RegistrationPeriod (already exists)')

    upcoming_period = RegistrationPeriod.query.filter_by(
        academic_session_id=academic_session.id, semester_id=semesters['Second Semester'].id
    ).first()
    if not upcoming_period:
        upcoming_period = RegistrationPeriod(
            academic_session_id=academic_session.id,
            semester_id=semesters['Second Semester'].id,
            opens_at=now_lagos() + timedelta(days=90),
            closes_at=now_lagos() + timedelta(days=110),
            min_credits=15, max_credits=24, registration_fee=45000,
            is_active=False,
        )
        db.session.add(upcoming_period)
        db.session.commit()
        print('Created upcoming RegistrationPeriod: 2025/2026 Second Semester (not yet open)')
    else:
        print('Skipping upcoming RegistrationPeriod (already exists)')

    rule = DepartmentRegistrationRule.query.filter_by(
        registration_period_id=active_period.id, department='Information Technology'
    ).first()
    if not rule:
        rule = DepartmentRegistrationRule(
            registration_period_id=active_period.id,
            department='Information Technology',
            min_credits=12, max_credits=21, registration_fee=None,
        )
        db.session.add(rule)
        db.session.commit()
        print('Created DepartmentRegistrationRule for Information Technology')
    else:
        print('Skipping DepartmentRegistrationRule for Information Technology (already exists)')

    david = User.query.filter_by(reg_no='2308-2301-0004').first()
    if david:
        existing_reg = StudentRegistration.query.filter_by(
            user_id=david.id, registration_period_id=active_period.id
        ).first()
        if not existing_reg:
            demo_registration = StudentRegistration(
                user_id=david.id,
                registration_period_id=active_period.id,
                status='registered',
                payment_status='paid',
                payment_reference='SIMULATED-DEMO000001',
                credits_registered=0,
            )
            db.session.add(demo_registration)
            db.session.commit()
            print(f'Created demo StudentRegistration for {david.reg_no}')
        else:
            print(f'Skipping demo StudentRegistration for {david.reg_no} (already exists)')
```

Then update the bottom of `seed()` (after its existing `db.session.commit()` and `print(...)` lines, still inside the `with app.app_context():` block) to call it:

```python
        seed_registration_config()
```

- [ ] **Step 2: Run and verify**

Run: `python seed_dev_data.py`
Expected: prints creation lines for the session, 2 semesters, 2 registration periods, 1 department rule, and 1 demo registration for `2308-2301-0004` (or "Skipping ... (already exists)" lines if re-run).

Run again immediately: `python seed_dev_data.py`
Expected: every registration-related line now says "Skipping ... (already exists)" — confirms idempotency.

Verify via query:
```bash
python -c "
from app import app
from models import db, RegistrationPeriod, StudentRegistration, User
with app.app_context():
    periods = RegistrationPeriod.query.all()
    assert len(periods) == 2, len(periods)
    david = User.query.filter_by(reg_no='2308-2301-0004').first()
    regs = StudentRegistration.query.filter_by(user_id=david.id).all()
    assert len(regs) == 1, len(regs)
    print('Seed data verified:', len(periods), 'periods,', len(regs), 'registration(s) for David')
"
```
Expected: `Seed data verified: 2 periods, 1 registration(s) for David`.

- [ ] **Step 3: Commit**

```bash
git add seed_dev_data.py
git commit -m "feat: seed demo academic session, semesters, registration periods, and department rule"
```

---

### Task 4: Routes

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: `get_registration_status_context`, `register_student`, `get_registration_history`, `get_active_period`, `RegistrationError` from `services.registration` (Task 2).

- [ ] **Step 1: Add the import**

In `app.py`, after the existing line `from services.student_profile import get_profile_display` (line 20), add:

```python
from services.registration import (
    get_registration_status_context, register_student, get_registration_history,
    get_active_period, RegistrationError,
)
```

- [ ] **Step 2: Replace the `registration()` route**

Replace (around line 313-315):

```python
@app.route('/registration')
def registration():
    return render_template('registration.html')
```

with:

```python
@app.route('/registration')
@login_required
def registration():
    return render_template(
        'registration.html',
        status=get_registration_status_context(current_user),
        history=get_registration_history(current_user),
    )


@app.route('/registration/register', methods=['POST'])
@login_required
def registration_register():
    period = get_active_period()
    if period is None:
        return jsonify({'success': False, 'message': 'No registration period is currently configured.'}), 400

    try:
        reg = register_student(current_user, period)
    except RegistrationError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({
        'success': True,
        'message': 'Registration successful.',
        'registration': {
            'session': reg.registration_period.academic_session.name,
            'semester': reg.registration_period.semester.name,
            'payment_reference': reg.payment_reference,
            'registered_at': reg.registered_at.strftime('%d %b %Y, %I:%M %p'),
            'credits_registered': reg.credits_registered,
        },
    })
```

- [ ] **Step 3: Verify with a manual test script**

Create a throwaway script `scratch_verify_routes.py` in the project root:

```python
from app import app
from models import db, User
from services.registration import get_active_period

with app.app_context():
    # Anonymous access is rejected
    client = app.test_client()
    resp = client.get('/registration', follow_redirects=False)
    assert resp.status_code == 302 and '/login' in resp.headers['Location'], resp.headers.get('Location')
    print('Anonymous GET /registration redirects to login: OK')

    period = get_active_period()
    assert period is not None, 'run seed_dev_data.py first'

    # A fresh, fully-onboarded, unregistered student (Chiamaka, 2308-2301-0003)
    chiamaka = User.query.filter_by(reg_no='2308-2301-0003').first()
    assert chiamaka is not None

    with client.session_transaction() as sess:
        sess['_user_id'] = str(chiamaka.id)
        sess['_fresh'] = True

    resp = client.get('/registration')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Register Now' in body or 'register-now' in body.lower(), 'expected an active register action for an open, unregistered period'
    print('GET /registration for unregistered student: OK (200, page rendered)')

    resp = client.post('/registration/register')
    data = resp.get_json()
    assert resp.status_code == 200 and data['success'] is True, data
    assert data['registration']['payment_reference'].startswith('SIMULATED-')
    print('POST /registration/register success: OK ->', data['registration'])

    resp = client.post('/registration/register')
    data = resp.get_json()
    assert resp.status_code == 400 and data['success'] is False, data
    print('POST /registration/register duplicate rejected: OK ->', data['message'])

    # cleanup this script's own row
    from models import StudentRegistration
    StudentRegistration.query.filter_by(user_id=chiamaka.id, registration_period_id=period.id).delete()
    db.session.commit()

    print('All route checks passed')
```

Run: `python scratch_verify_routes.py`
Expected: `All route checks passed`, no assertion errors.

Delete the script afterward: `rm scratch_verify_routes.py` (do not commit it).

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: wire registration routes to real backend data and add register-now endpoint"
```

---

### Task 5: Registration Page UI

**Files:**
- Modify: `templates/registration.html`
- Modify: `static/css/registration.css`
- Create: `static/js/registration/registration.js`

**Interfaces:**
- Consumes: `status` dict and `history` list passed from `registration()` (Task 4); `postJson` from `static/js/shared/api.js`; `showToast` from `static/js/shared/toast.js` (both already exist, established in Milestone 1).

- [ ] **Step 1: Rewrite `templates/registration.html`**

Replace the entire file with:

```html
{% extends "base.html" %}

{% block head %}
    <title>Course Registration · Student Portal</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/registration.css') }}">
{% endblock %}


{% block content %}
<div class="registration-dashboard">
    <input type="hidden" id="csrf_token" value="{{ csrf_token() }}">

    <div class="page-header">
        <a href="{{ url_for('dashboard') }}" class="back-link"><i class="fas fa-arrow-left"></i> Dashboard</a>
        <h1><i class="fas fa-edit"></i> Course Registration</h1>
        <div></div>
    </div>

    <div class="ongoing-section" id="registrationCardSection" data-status="{{ status.window_status or 'none' }}">
        <h3><i class="fas fa-hourglass-half"></i> Registration Status</h3>

        {% if status.period is none %}
        <div class="ongoing-card no-period-card">
            <div class="empty-state">
                <i class="fas fa-info-circle" style="font-size: 2rem; opacity: 0.5;"></i>
                <p>No registration is currently available. Check back soon.</p>
            </div>
        </div>

        {% elif status.existing_registration %}
        <div class="ongoing-card registered-card" id="registeredCard">
            <div class="card-content">
                <div class="ongoing-info">
                    <div class="ongoing-badge registered-badge"><i class="fas fa-check-circle"></i> Registered</div>
                    <h2>{{ status.period.academic_session.name }} {{ status.period.semester.name }}</h2>
                    <div class="reg-details">
                        <span class="detail-item"><i class="fas fa-receipt"></i> Ref: {{ status.existing_registration.payment_reference }}</span>
                        <span class="detail-item"><i class="fas fa-calendar-check"></i> Registered: {{ status.existing_registration.registered_at.strftime('%d %b %Y') }}</span>
                        <span class="detail-item"><i class="fas fa-money-bill-wave"></i> Payment: {{ status.existing_registration.payment_status|capitalize }}</span>
                    </div>
                    <p class="course-selection-note"><i class="fas fa-info-circle"></i> Course selection will open separately once available.</p>
                </div>
            </div>
        </div>

        {% else %}
        <div class="ongoing-card" id="registrationCard">
            <div class="card-content">
                <div class="ongoing-info">
                    {% if status.window_status == 'open' %}
                    <div class="ongoing-badge"><i class="fas fa-hourglass-half"></i> Registration Open</div>
                    {% elif status.window_status == 'not_yet_open' %}
                    <div class="ongoing-badge not-open-badge"><i class="fas fa-clock"></i> Opens Soon</div>
                    {% else %}
                    <div class="ongoing-badge closed-badge"><i class="fas fa-lock"></i> Registration Closed</div>
                    {% endif %}

                    <h2>{{ status.period.academic_session.name }} {{ status.period.semester.name }}</h2>

                    <div class="countdown-area" data-target="{{ (status.period.opens_at if status.window_status == 'not_yet_open' else status.period.closes_at).isoformat() }}" data-mode="{{ 'opens' if status.window_status == 'not_yet_open' else 'closes' }}">
                        <div class="progress-label"><i class="fas fa-stopwatch"></i> <span id="countdownLabel">Calculating…</span></div>
                    </div>

                    <div class="reg-details">
                        <span class="detail-item"><i class="fas fa-calendar-alt"></i> Opens: {{ status.period.opens_at.strftime('%d %b %Y') }}</span>
                        <span class="detail-item deadline"><i class="fas fa-clock"></i> Deadline: {{ status.period.closes_at.strftime('%d %b %Y') }}</span>
                        <span class="detail-item"><i class="fas fa-layer-group"></i> Min {{ status.min_credits }} | Max {{ status.max_credits }} credits</span>
                        {% if status.registration_fee %}
                        <span class="detail-item"><i class="fas fa-money-bill-wave"></i> Fee: ₦{{ '{:,.2f}'.format(status.registration_fee) }}</span>
                        {% endif %}
                    </div>
                </div>
                <div class="ongoing-action">
                    <button class="btn-primary" id="registerNowBtn" {% if status.window_status != 'open' %}disabled{% endif %}>
                        <i class="fas fa-arrow-right"></i> Register Now
                    </button>
                </div>
            </div>
        </div>
        {% endif %}
    </div>

    <div class="past-section">
        <h3><i class="fas fa-history"></i> Registration History</h3>
        <div class="registrations-list" id="pastRegistrationsList">
            {% if not history %}
            <div class="empty-state">
                <i class="fas fa-inbox" style="font-size: 2rem; opacity: 0.5;"></i>
                <p>No past registrations found</p>
            </div>
            {% else %}
            {% for reg in history %}
            <div class="reg-item">
                <div class="reg-info">
                    <div class="reg-semester">{{ reg.registration_period.academic_session.name }} {{ reg.registration_period.semester.name }}</div>
                    <div class="reg-meta">
                        <span><i class="far fa-calendar-check"></i> Registered: {{ reg.registered_at.strftime('%d %b %Y') }}</span>
                        <span><i class="fas fa-layer-group"></i> {{ reg.credits_registered }} credits</span>
                    </div>
                </div>
                <div class="reg-status">
                    <span class="status-badge status-{{ 'approved' if reg.status == 'registered' else 'closed' }}">{{ reg.status|capitalize }}</span>
                    <span class="status-badge status-{{ 'approved' if reg.payment_status == 'paid' else 'pending' }}">{{ reg.payment_status|capitalize }}</span>
                    <a href="#" class="view-link view-details-toggle"><span class="toggle-text">View details</span> <i class="fas fa-chevron-right"></i></a>
                </div>
                <div class="reg-detail-panel" hidden>
                    <span><strong>Payment reference:</strong> {{ reg.payment_reference or '—' }}</span>
                    <span><strong>Registered at:</strong> {{ reg.registered_at.strftime('%d %b %Y, %I:%M %p') }}</span>
                    <span><strong>Last updated:</strong> {{ reg.updated_at.strftime('%d %b %Y, %I:%M %p') }}</span>
                </div>
            </div>
            {% endfor %}
            {% endif %}
        </div>
    </div>
</div>

<div id="toastMsg" class="toast-msg"></div>
{% endblock %}

{% block scripts %}
<script type="module" src="{{ url_for('static', filename='js/registration/registration.js') }}"></script>
{% endblock %}
```

- [ ] **Step 2: Create `static/js/registration/registration.js`**

```javascript
import { postJson } from '../shared/api.js';
import { showToast } from '../shared/toast.js';

function setupCountdown() {
    const area = document.querySelector('.countdown-area');
    if (!area) return;

    const target = new Date(area.dataset.target).getTime();
    const mode = area.dataset.mode;
    const label = document.getElementById('countdownLabel');

    function tick() {
        const diff = target - Date.now();
        if (diff <= 0) {
            label.textContent = mode === 'opens' ? 'Opening now…' : 'Closing now…';
            clearInterval(timer);
            return;
        }
        const days = Math.floor(diff / (1000 * 60 * 60 * 24));
        const hours = Math.floor((diff / (1000 * 60 * 60)) % 24);
        const minutes = Math.floor((diff / (1000 * 60)) % 60);
        const seconds = Math.floor((diff / 1000) % 60);
        const verb = mode === 'opens' ? 'Opens in' : 'Closes in';
        label.textContent = `${verb} ${days}d ${hours}h ${minutes}m ${seconds}s`;
    }

    tick();
    const timer = setInterval(tick, 1000);
}

function renderRegisteredCard(section, registration) {
    section.innerHTML = `
        <h3><i class="fas fa-hourglass-half"></i> Registration Status</h3>
        <div class="ongoing-card registered-card">
            <div class="card-content">
                <div class="ongoing-info">
                    <div class="ongoing-badge registered-badge"><i class="fas fa-check-circle"></i> Registered</div>
                    <h2>${registration.session} ${registration.semester}</h2>
                    <div class="reg-details">
                        <span class="detail-item"><i class="fas fa-receipt"></i> Ref: ${registration.payment_reference}</span>
                        <span class="detail-item"><i class="fas fa-calendar-check"></i> Registered: ${registration.registered_at}</span>
                        <span class="detail-item"><i class="fas fa-money-bill-wave"></i> Payment: Paid</span>
                    </div>
                    <p class="course-selection-note"><i class="fas fa-info-circle"></i> Course selection will open separately once available.</p>
                </div>
            </div>
        </div>
    `;
}

function setupRegisterNow() {
    const btn = document.getElementById('registerNowBtn');
    if (!btn) return;

    btn.addEventListener('click', async () => {
        if (!window.confirm('Confirm semester registration? This will simulate a successful payment for development purposes.')) {
            return;
        }

        btn.disabled = true;
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Registering…';

        const result = await postJson('/registration/register', {});

        if (result.success) {
            showToast(result.message || 'Registration successful.');
            const section = document.getElementById('registrationCardSection');
            renderRegisteredCard(section, result.registration);
        } else {
            showToast(result.message || 'Registration failed.', true);
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    });
}

function setupHistoryToggles() {
    document.querySelectorAll('.view-details-toggle').forEach((link) => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const item = link.closest('.reg-item');
            const panel = item.querySelector('.reg-detail-panel');
            const text = link.querySelector('.toggle-text');
            const expanded = !panel.hidden;
            panel.hidden = expanded;
            text.textContent = expanded ? 'View details' : 'Hide details';
        });
    });
}

setupCountdown();
setupRegisterNow();
setupHistoryToggles();
```

- [ ] **Step 3: Extend `static/css/registration.css`**

Append to the end of the file:

```css

/* Registered confirmation state */
.registered-card {
    background: linear-gradient(135deg, #0f7b4e, #1a9e6b);
}
.registered-badge {
    background: #ffffff;
    color: #0f7b4e;
}
.course-selection-note {
    margin-top: 1rem;
    font-size: 0.85rem;
    opacity: 0.9;
    display: flex;
    align-items: center;
    gap: 0.4rem;
}

/* Not-open / closed badges */
.not-open-badge {
    background: #fff0d9;
    color: #b45b1c;
}
.closed-badge {
    background: #f0d9d9;
    color: #8a2f2f;
}

/* Countdown */
.countdown-area {
    margin: 0.8rem 0;
    font-weight: 600;
}

/* No-period state */
.no-period-card {
    background: white;
    box-shadow: none;
}

/* Register button disabled state */
#registerNowBtn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
    transform: none !important;
}

/* History detail expand panel */
.reg-item {
    flex-wrap: wrap;
}
.reg-detail-panel {
    flex-basis: 100%;
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
    margin-top: 0.8rem;
    padding-top: 0.8rem;
    border-top: 1px dashed #d9e9ff;
    font-size: 0.85rem;
    color: #4a6a86;
}
.reg-status {
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
```

- [ ] **Step 4: Manual verification across all 6 scenarios**

Create a throwaway script `scratch_verify_ui.py` in the project root:

```python
from datetime import timedelta

from app import app
from models import db, now_lagos, User, RegistrationPeriod, StudentRegistration

with app.app_context():
    client = app.test_client()
    active_period = RegistrationPeriod.query.filter_by(is_active=True).first()
    upcoming_period = RegistrationPeriod.query.filter(RegistrationPeriod.id != active_period.id).first()

    def login_as(reg_no):
        user = User.query.filter_by(reg_no=reg_no).first()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True
        return user

    # Scenario: already registered (David, seeded)
    login_as('2308-2301-0004')
    resp = client.get('/registration')
    body = resp.get_data(as_text=True)
    assert 'Registered' in body and 'SIMULATED-DEMO000001' in body
    assert 'No past registrations found' not in body
    print('Scenario "already registered" + "history exists": OK')

    # Scenario: open, unregistered (Chiamaka, seeded, no registration)
    login_as('2308-2301-0003')
    resp = client.get('/registration')
    body = resp.get_data(as_text=True)
    assert 'Register Now' in body and 'disabled' not in body.split('registerNowBtn')[1][:60]
    assert 'No past registrations found' in body
    print('Scenario "registration open" + "history empty": OK')

    # Scenario: not yet opened - temporarily flip the active flag
    active_period.is_active = False
    upcoming_period.is_active = True
    db.session.commit()
    resp = client.get('/registration')
    body = resp.get_data(as_text=True)
    assert 'Opens Soon' in body
    print('Scenario "not yet opened": OK')

    # Scenario: closed - push the upcoming period's dates into the past
    original_opens, original_closes = upcoming_period.opens_at, upcoming_period.closes_at
    upcoming_period.opens_at = now_lagos() - timedelta(days=10)
    upcoming_period.closes_at = now_lagos() - timedelta(days=1)
    db.session.commit()
    resp = client.get('/registration')
    body = resp.get_data(as_text=True)
    assert 'Registration Closed' in body
    print('Scenario "registration closed": OK')

    # restore seeded state exactly
    upcoming_period.opens_at = original_opens
    upcoming_period.closes_at = original_closes
    upcoming_period.is_active = False
    active_period.is_active = True
    db.session.commit()

    print('All UI scenario checks passed')
```

Run: `python scratch_verify_ui.py`
Expected: all six `OK` lines print (already-registered, history-exists, open+history-empty, not-yet-opened, closed — the sixth, "already registered", doubles as confirming an existing-registration student never sees a duplicate button), ending with `All UI scenario checks passed`.

Delete the script afterward: `rm scratch_verify_ui.py` (do not commit it).

- [ ] **Step 5: Commit**

```bash
git add templates/registration.html static/css/registration.css static/js/registration/registration.js
git commit -m "feat: replace mock registration page with real backend-driven UI"
```

---

### Task 6: End-to-End Verification and Progress Doc

**Files:**
- Create: `DEVELOPMENT_PROGRESS.md`

**Interfaces:**
- Consumes: the full stack from Tasks 1-5.

- [ ] **Step 1: Full auth → onboarding → dashboard → registration walkthrough**

Create a throwaway script `scratch_verify_e2e.py` in the project root:

```python
from app import app
from models import db, User

with app.app_context():
    client = app.test_client()

    # A first_login=True, non-onboarded student: 2308-2301-0001
    resp = client.post('/login', data={'studentId': '2308-2301-0001', 'password': 'Default@123'}, follow_redirects=False)
    assert resp.status_code == 302 and 'force-password-change' in resp.headers['Location'], resp.headers.get('Location')

    resp = client.get('/registration', follow_redirects=False)
    assert resp.status_code == 302 and 'force-password-change' in resp.headers['Location']
    print('Gate: non-password-changed student blocked from /registration -> OK')

    # A fully onboarded student reaches dashboard and registration cleanly
    user = User.query.filter_by(reg_no='2308-2301-0004').first()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True

    resp = client.get('/')
    assert resp.status_code == 200
    resp = client.get('/registration')
    assert resp.status_code == 200
    print('Fully onboarded student: dashboard -> registration both 200 -> OK')

    print('End-to-end chain verified')
```

Run: `python scratch_verify_e2e.py`
Expected: `End-to-end chain verified`, no assertion errors.

Delete the script afterward: `rm scratch_verify_e2e.py` (do not commit it).

- [ ] **Step 2: Write `DEVELOPMENT_PROGRESS.md`**

Create `DEVELOPMENT_PROGRESS.md`:

```markdown
# Development Progress

Tracks completed milestones against `doc/t.txt` (Student Registration Workflow).

## Feature 1-2: Authentication & Onboarding — Complete

- Forced first-login password change (8+ chars, upper/lower/number/special).
- 3-step onboarding wizard: student info + profile picture upload, email OTP verification (3-attempt limit), review & confirm.
- Single-source-of-truth access gate (`auth_helpers.get_gate_redirect`) enforced via `before_request`.
- Spec: `docs/superpowers/specs/2026-07-29-auth-onboarding-design.md`

## Feature 3: Student Data Integration — Complete

- Dashboard and profile pages now render real `User` data instead of hardcoded values (programme, level/semester, session, profile picture, notification badge).
- Dashboard's "Registered Courses" and "Recent payment history" mock tables replaced with honest empty states (real data arrives in later milestones).
- Spec: `docs/superpowers/specs/2026-07-30-student-data-integration-design.md`

## Feature 4: Semester Registration Foundation — Complete

- New models: `AcademicSession`, `Semester`, `RegistrationPeriod`, `DepartmentRegistrationRule`, `StudentRegistration`.
- `services/registration.py`: registration status resolution, credit-limit resolution (with department overrides), simulated register-now flow, registration history.
- `registration.html` rewritten to render real backend state: no active period / not-yet-open / open / closed / already-registered, with a live countdown and an expandable registration history list.
- Payment is simulated as immediately successful (`payment_status='paid'`, a `SIMULATED-` reference) — `services/registration.py` marks the exact spot for a real Remita integration with `# TODO` comments.
- Fixed: `/registration` was missing `@login_required`, allowing anonymous access — fixed as part of rewriting the route.
- Spec: `docs/superpowers/specs/2026-07-30-semester-registration-design.md`
- Out of scope (deferred): Course Add/Drop, real Remita integration, admin UI for managing registration periods.

## Known pre-existing issues (not yet fixed)

- `add_drop`, `my_courses`, `payments_history`, `pay_summary` routes are missing `@login_required` (same class of bug fixed on `dashboard`, `profile`, and now `registration`). Not fixed yet since those pages/routes aren't otherwise touched.
- `constants_file.py` contains real credentials and is not gitignored (flagged in `CLAUDE.md`).

## Next milestone

Feature 5: Course Add/Drop — students select courses against their active `StudentRegistration`, respecting the resolved `min_credits`/`max_credits`.
```

- [ ] **Step 3: Boot check**

Run: `python -c "import app; print('OK')"`
Expected: `OK`, no traceback.

- [ ] **Step 4: Commit**

```bash
git add DEVELOPMENT_PROGRESS.md
git commit -m "docs: record semester registration foundation as complete in progress log"
```
