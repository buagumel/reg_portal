# Course Add/Drop + My Courses Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the mocked `add_drop.html` and `my_courses.html` with a real, database-driven course registration workflow, per `docs/superpowers/specs/2026-07-31-course-add-drop-design.md`.

**Architecture:** New `Course`/`RegisteredCourse` models, a `courses_submitted` flag on `StudentRegistration`, four service modules (`services/validation.py`, `services/course.py`, `services/course_history.py`, extended `services/registration.py`), 8 routes in `app.py`, `add_drop.html`'s existing JS-array architecture kept but rewired to real endpoints, `my_courses.html` converted to server-rendered Jinja (matching Feature 4's precedent), a new course-details modal, and a new printable registration-slip template.

**Tech Stack:** Flask, Flask-SQLAlchemy (SQLite dev DB), vanilla ES module JS, Jinja2.

## Global Constraints

- No Alembic migration — dev DB rebuilt via `db.create_all()`.
- No automated test framework — verification is manual via `test_client`/`render_template` throwaway scripts, created/run/deleted, never committed.
- All datetime columns use `now_lagos()` (naive, Lagos-local) — never a tz-aware `datetime`.
- `add_drop.html`'s markup/CSS must stay visually unchanged — only add `id` attributes where strictly needed to target dynamic values (documented per-task where this happens); do not restructure layout, classes, or remove existing elements.
- `my_courses.html`'s markup/CSS must stay visually unchanged in structure/style — convert its static content to Jinja loops, but preserve class names and visual layout exactly.
- `services/registration.py`'s existing `RegistrationError` symbol must remain importable from `services.registration` (existing `app.py` code depends on `from services.registration import RegistrationError`) even after the refactor in Task 2.
- Reuse Feature 4's `get_credit_limits`, `get_window_status`, `get_active_period` from `services/registration.py` — do not reimplement.
- `add_drop`, `add_drop_data`, `add_drop_add`, `add_drop_drop`, `add_drop_submit`, `registration_slip`, `my_courses`, `course_details` must NOT be added to `enforce_onboarding_gate`'s `exempt_endpoints` in `app.py` — they must stay behind the full auth/onboarding gate, matching `registration`/`registration_register`.

---

### Task 1: Data Models

**Files:**
- Modify: `models.py`

**Interfaces:**
- Produces: `Course(id, code, title, credits, department, level, course_type, academic_session_id, semester_id, description, instructor, schedule, academic_session, semester)`; `RegisteredCourse(id, student_registration_id, course_id, grade, added_at, course, student_registration)`; `StudentRegistration.courses_submitted` (new column).

- [ ] **Step 1: Add `courses_submitted` to `StudentRegistration`**

In `models.py`, find the `StudentRegistration` class. Immediately after the `credits_registered = db.Column(db.Integer, nullable=False, default=0)` line, add:
```python
    courses_submitted = db.Column(db.Boolean, default=False, nullable=False)
```

- [ ] **Step 2: Add the two new model classes**

At the end of `models.py` (after the `StudentRegistration` class), append:
```python

class Course(db.Model):
    __tablename__ = 'courses'
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

    __table_args__ = (db.UniqueConstraint('code', 'academic_session_id', 'semester_id'),)

    academic_session = db.relationship('AcademicSession')
    semester = db.relationship('Semester')


class RegisteredCourse(db.Model):
    __tablename__ = 'registered_courses'
    id = db.Column(db.Integer, primary_key=True)
    student_registration_id = db.Column(db.Integer, db.ForeignKey('student_registrations.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    grade = db.Column(db.String(5), nullable=True)
    added_at = db.Column(db.DateTime, default=now_lagos, nullable=False)

    __table_args__ = (db.UniqueConstraint('student_registration_id', 'course_id'),)

    course = db.relationship('Course')
    student_registration = db.relationship('StudentRegistration', backref='registered_courses')
```

- [ ] **Step 3: Boot check and table verification**

Run: `python -c "import app; print('OK')"` — expect `OK`, no traceback (this runs `db.create_all()`, adding the 2 new tables and the `courses_submitted` column via a fresh table — note: SQLite `create_all()` cannot ALTER an existing `student_registrations` table to add a column if the table already exists with rows. If the dev DB already has a `student_registrations` table, delete `instance/database.db` first, then run the boot check, then re-run `python seed_dev_data.py` to reseed everything).

Then verify:
```bash
python -c "
from app import app
from models import db
with app.app_context():
    tables = db.inspect(db.engine).get_table_names()
    assert 'courses' in tables and 'registered_courses' in tables
    cols = [c['name'] for c in db.inspect(db.engine).get_columns('student_registrations')]
    assert 'courses_submitted' in cols
    print('Tables and column verified')
"
```

- [ ] **Step 4: Commit**
```bash
git add models.py
git commit -m "feat: add Course and RegisteredCourse models, courses_submitted flag"
```

---

### Task 2: Validation Service

**Files:**
- Create: `services/errors.py`
- Create: `services/validation.py`
- Modify: `services/registration.py`

**Interfaces:**
- Produces: `services.errors.RegistrationError`; `validate_course_eligible(course, user, period)`; `validate_credit_ceiling(current_credits, course_credits, max_credits)`; `validate_not_duplicate(student_registration, course)`; `validate_can_submit(student_registration, window_status, min_credits, max_credits)` — all raise `RegistrationError` on violation, return `None` otherwise.
- Consumes: `Course`, `RegisteredCourse` from `models` (Task 1).

**Why the refactor:** `services/validation.py` needs `RegistrationError`, and `services/registration.py` (Task 4) will need to import the `validate_*` functions from `services/validation.py`. Both modules importing from each other at the top level is a circular import. Moving `RegistrationError` to its own tiny module breaks the cycle: both `registration.py` and `validation.py` import it one-directionally from `services/errors.py`, and `validation.py` takes already-resolved plain values (not period/DB objects requiring a call back into `registration.py`) so it never needs to import from `registration.py` at all.

- [ ] **Step 1: Create `services/errors.py`**
```python
class RegistrationError(Exception):
    """Raised for a business-rule violation in the registration flow.
    The message is user-facing."""
```

- [ ] **Step 2: Refactor `services/registration.py`'s `RegistrationError`**

Open `services/registration.py`. Find the existing class definition:
```python
class RegistrationError(Exception):
    """Raised for a business-rule violation in the registration flow.
    The message is user-facing."""
```
Replace it with an import so the symbol stays available at `services.registration.RegistrationError` for existing callers (`app.py` already does `from services.registration import RegistrationError`):
```python
from services.errors import RegistrationError
```
Place this import alongside the file's other imports (top of file), not where the class used to be. Do not change anything else in this file in this step — verify with `python -c "from services.registration import RegistrationError; print('OK')"` that the re-export still works, then run `python -c "import app; print('OK')"` to confirm nothing else broke.

- [ ] **Step 3: Create `services/validation.py`**
```python
from models import RegisteredCourse
from services.errors import RegistrationError


def validate_course_eligible(course, user, period):
    """Raise RegistrationError unless the course matches the student's own
    department/level and belongs to the active registration period's
    session/semester. A course with level=None is level-agnostic and
    matches any student's level."""
    if course.department != user.department:
        raise RegistrationError('This course is not offered in your department.')
    if course.level is not None and course.level != user.level:
        raise RegistrationError('This course is not offered at your level.')
    if course.academic_session_id != period.academic_session_id or course.semester_id != period.semester_id:
        raise RegistrationError('This course is not offered this semester.')


def validate_credit_ceiling(current_credits, course_credits, max_credits):
    """Raise RegistrationError if adding course_credits would exceed max_credits."""
    if current_credits + course_credits > max_credits:
        raise RegistrationError(f'Adding this course would exceed the maximum of {max_credits} credits.')


def validate_not_duplicate(student_registration, course):
    """Raise RegistrationError if the course is already registered."""
    existing = RegisteredCourse.query.filter_by(
        student_registration_id=student_registration.id, course_id=course.id
    ).first()
    if existing:
        raise RegistrationError('You have already added this course.')


def validate_can_submit(student_registration, window_status, min_credits, max_credits):
    """Raise RegistrationError unless the registration is ready to be
    finalized. Duplicate courses are not re-checked here — the DB unique
    constraint plus validate_not_duplicate at add-time make duplicates
    structurally impossible by the time submission happens."""
    if window_status != 'open':
        raise RegistrationError('Registration is not currently open.')
    if student_registration.payment_status != 'paid':
        raise RegistrationError('Payment must be completed before submitting course selection.')
    if student_registration.courses_submitted:
        raise RegistrationError('Course selection has already been submitted.')
    if student_registration.credits_registered < min_credits:
        raise RegistrationError(f'You must register at least {min_credits} credits before submitting.')
    if student_registration.credits_registered > max_credits:
        raise RegistrationError(f'You cannot exceed {max_credits} credits.')
```

- [ ] **Step 4: Manual verification**

Run: `python -c "import app; print('OK')"` — expect `OK`.

Write a throwaway `scratch_verify_validation.py`:
```python
from app import app
from services.errors import RegistrationError
from services.validation import validate_course_eligible, validate_credit_ceiling, validate_not_duplicate, validate_can_submit

class FakeCourse:
    def __init__(self, department, level, academic_session_id=1, semester_id=1):
        self.department = department
        self.level = level
        self.academic_session_id = academic_session_id
        self.semester_id = semester_id

class FakeUser:
    def __init__(self, department, level):
        self.department = department
        self.level = level

class FakePeriod:
    academic_session_id = 1
    semester_id = 1

with app.app_context():
    user = FakeUser('Computer Science', 'Year 1')
    period = FakePeriod()

    validate_course_eligible(FakeCourse('Computer Science', 'Year 1'), user, period)
    validate_course_eligible(FakeCourse('Computer Science', None), user, period)
    print('eligible checks passed (no raise)')

    try:
        validate_course_eligible(FakeCourse('Information Technology', 'Year 1'), user, period)
        raise SystemExit('expected RegistrationError for wrong department')
    except RegistrationError:
        pass

    try:
        validate_course_eligible(FakeCourse('Computer Science', 'Year 2'), user, period)
        raise SystemExit('expected RegistrationError for wrong level')
    except RegistrationError:
        pass

    validate_credit_ceiling(10, 3, 24)
    try:
        validate_credit_ceiling(22, 5, 24)
        raise SystemExit('expected RegistrationError for credit overflow')
    except RegistrationError:
        pass

    class FakeReg:
        payment_status = 'paid'
        courses_submitted = False
        credits_registered = 18

    validate_can_submit(FakeReg(), 'open', 15, 24)
    try:
        validate_can_submit(FakeReg(), 'closed', 15, 24)
        raise SystemExit('expected RegistrationError for closed window')
    except RegistrationError:
        pass

    print('All validation checks passed')
```
Run it, expect `All validation checks passed`, no traceback. Delete it afterward.

- [ ] **Step 5: Commit**
```bash
git add services/errors.py services/validation.py services/registration.py
git commit -m "feat: add validation service, extract RegistrationError to break import cycle"
```

---

### Task 3: Course Service and Course History Service

**Files:**
- Create: `services/course.py`
- Create: `services/course_history.py`

**Interfaces:**
- Consumes: `Course`, `RegisteredCourse`, `StudentRegistration`, `db` from `models`; `get_active_period` from `services.registration`.
- Produces: `get_available_courses(user, period, student_registration, search=None, course_type=None) -> list[Course]`; `get_course_details(course_id) -> Course | None`; `get_courses_by_semester(user) -> list[dict]` (each dict: `academic_session`, `semester`, `is_current`, `courses_submitted`, `courses` — a list of `RegisteredCourse`).

- [ ] **Step 1: Create `services/course.py`**
```python
from models import db, Course


def get_available_courses(user, period, student_registration, search=None, course_type=None):
    """Return Course rows the student can still add: matching their
    department, matching their level (or level-agnostic), belonging to the
    active period's session/semester, and not already registered."""
    query = Course.query.filter(
        Course.department == user.department,
        Course.academic_session_id == period.academic_session_id,
        Course.semester_id == period.semester_id,
    )
    query = query.filter(db.or_(Course.level == user.level, Course.level.is_(None)))

    if student_registration is not None:
        registered_ids = [rc.course_id for rc in student_registration.registered_courses]
        if registered_ids:
            query = query.filter(~Course.id.in_(registered_ids))

    if search:
        like = f'%{search}%'
        query = query.filter(db.or_(Course.code.ilike(like), Course.title.ilike(like)))

    if course_type and course_type != 'all':
        query = query.filter(Course.course_type == course_type)

    return query.order_by(Course.code).all()


def get_course_details(course_id):
    return Course.query.get(course_id)
```

- [ ] **Step 2: Create `services/course_history.py`**
```python
from models import RegisteredCourse, StudentRegistration
from services.registration import get_active_period


def get_courses_by_semester(user):
    """Return the student's RegisteredCourse rows grouped by
    (academic_session, semester), newest registration first. Each group:
    {academic_session, semester, is_current, courses_submitted, courses}."""
    active_period = get_active_period()

    registrations = (
        StudentRegistration.query
        .filter_by(user_id=user.id)
        .order_by(StudentRegistration.registered_at.desc())
        .all()
    )

    groups = []
    for reg in registrations:
        courses = (
            RegisteredCourse.query
            .filter_by(student_registration_id=reg.id)
            .order_by(RegisteredCourse.added_at)
            .all()
        )
        if not courses:
            continue
        groups.append({
            'academic_session': reg.registration_period.academic_session.name,
            'semester': reg.registration_period.semester.name,
            'is_current': active_period is not None and reg.registration_period_id == active_period.id,
            'courses_submitted': reg.courses_submitted,
            'courses': courses,
        })
    return groups
```
Note: groups with zero courses are skipped (a `StudentRegistration` with no `RegisteredCourse` rows yet — e.g. paid but hasn't added any courses — has nothing meaningful to show in My Courses; Add/Drop is where that in-progress state lives).

- [ ] **Step 3: Manual verification**

Run: `python -c "import app; print('OK')"` — expect `OK`.

Write a throwaway `scratch_verify_course.py` that, inside `app.app_context()`, imports `get_available_courses`/`get_course_details`/`get_courses_by_semester`, confirms they're callable and importable without error against the real dev DB (no courses seeded yet at this point in the plan — Task 5 seeds them — so just confirm `get_courses_by_semester(some_user)` returns `[]` cleanly for a user with no registrations, and `Course.query.count() == 0`). Delete it afterward.

- [ ] **Step 4: Commit**
```bash
git add services/course.py services/course_history.py
git commit -m "feat: add course catalog and course history services"
```

---

### Task 4: Extend Registration Service

**Files:**
- Modify: `services/registration.py`

**Interfaces:**
- Consumes: `validate_course_eligible`, `validate_credit_ceiling`, `validate_not_duplicate`, `validate_can_submit` from `services.validation` (Task 2); `Course`, `RegisteredCourse` from `models` (Task 1).
- Produces: `add_course(user, period, student_registration, course_id) -> StudentRegistration`; `drop_course(user, student_registration, course_id) -> StudentRegistration`; `submit_registration(user, period, student_registration) -> StudentRegistration`; `get_add_drop_context(user) -> dict` (keys: `period`, `student_registration`, `min_credits`, `max_credits`).

- [ ] **Step 1: Add imports**

At the top of `services/registration.py`, alongside the existing imports, add:
```python
from models import Course, RegisteredCourse
from services.validation import validate_course_eligible, validate_credit_ceiling, validate_not_duplicate, validate_can_submit
```

- [ ] **Step 2: Add the new functions**

Append to the end of `services/registration.py`:
```python

def _recompute_credits(student_registration):
    """Recompute and store credits_registered from the current
    RegisteredCourse rows — always re-queried (not read from an in-memory
    relationship collection) so it's correct regardless of add/drop order."""
    total = (
        db.session.query(db.func.coalesce(db.func.sum(Course.credits), 0))
        .join(RegisteredCourse, RegisteredCourse.course_id == Course.id)
        .filter(RegisteredCourse.student_registration_id == student_registration.id)
        .scalar()
    )
    student_registration.credits_registered = total


def add_course(user, period, student_registration, course_id):
    """Validate and add a course to the student's registration. Raises
    RegistrationError on any business-rule violation."""
    course = Course.query.get(course_id)
    if course is None:
        raise RegistrationError('Course not found.')

    if student_registration.courses_submitted:
        raise RegistrationError('Course selection has already been submitted.')

    validate_course_eligible(course, user, period)
    validate_not_duplicate(student_registration, course)

    _, max_credits, _ = get_credit_limits(period, user.department)
    validate_credit_ceiling(student_registration.credits_registered, course.credits, max_credits)

    registered_course = RegisteredCourse(
        student_registration_id=student_registration.id,
        course_id=course.id,
    )
    db.session.add(registered_course)

    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise RegistrationError('You have already added this course.')

    _recompute_credits(student_registration)
    db.session.commit()
    return student_registration


def drop_course(user, student_registration, course_id):
    """Remove a course from the student's registration. Raises
    RegistrationError if not found or already submitted."""
    if student_registration.courses_submitted:
        raise RegistrationError('Course selection has already been submitted.')

    registered_course = RegisteredCourse.query.filter_by(
        student_registration_id=student_registration.id, course_id=course_id
    ).first()
    if registered_course is None:
        raise RegistrationError('Course not found in your registration.')

    db.session.delete(registered_course)
    db.session.flush()
    _recompute_credits(student_registration)
    db.session.commit()
    return student_registration


def submit_registration(user, period, student_registration):
    """Validate and finalize the student's course selection. Raises
    RegistrationError on any business-rule violation."""
    window_status = get_window_status(period)
    min_credits, max_credits, _ = get_credit_limits(period, user.department)
    validate_can_submit(student_registration, window_status, min_credits, max_credits)

    student_registration.courses_submitted = True
    db.session.commit()
    return student_registration


def get_add_drop_context(user):
    """Assemble everything the Add/Drop page needs. period/student_registration
    are None if there's nothing eligible to add courses against."""
    period = get_active_period()
    if period is None:
        return {'period': None, 'student_registration': None, 'min_credits': None, 'max_credits': None}

    student_registration = StudentRegistration.query.filter_by(
        user_id=user.id, registration_period_id=period.id
    ).first()
    if student_registration is None:
        return {'period': period, 'student_registration': None, 'min_credits': None, 'max_credits': None}

    min_credits, max_credits, _ = get_credit_limits(period, user.department)
    return {
        'period': period,
        'student_registration': student_registration,
        'min_credits': min_credits,
        'max_credits': max_credits,
    }
```

- [ ] **Step 3: Manual verification**

Run: `python seed_dev_data.py` (ensures demo students + active period exist), then a throwaway `scratch_verify_registration_ext.py` that, inside `app.app_context()`:
1. Creates one temporary `Course` row for the active period matching Chiamaka's (`2308-2301-0003`) department/level (query `User.department`/`level` first).
2. Fetches/creates a `StudentRegistration` for Chiamaka against the active period if she doesn't have one (reuse `services.registration.register_student` — she should already be unregistered per Feature 4's seed state, so register her).
3. Calls `add_course(chiamaka, period, her_registration, course.id)`, asserts `credits_registered` increased by the course's credits, asserts a `RegisteredCourse` row exists.
4. Calls `add_course(...)` again with the same course, asserts `RegistrationError` ("already added").
5. Calls `drop_course(...)`, asserts `credits_registered` back to 0, no `RegisteredCourse` row remains.
6. Re-adds the course, calls `submit_registration(chiamaka, period, her_registration)` — if her credits are below `min_credits`, expect a `RegistrationError` (this is fine/expected — assert the error message mentions the minimum); do not force it to succeed if real seeded credit minimums aren't met by one course.
7. Cleans up: delete the temporary `Course` and any `RegisteredCourse`/`StudentRegistration` rows this script created, so the dev DB is left as it was (check what already existed before creating, only delete what the script itself added).

Delete the script afterward.

- [ ] **Step 4: Commit**
```bash
git add services/registration.py
git commit -m "feat: add course add/drop/submit orchestration to registration service"
```

---

### Task 5: Seed Course Data

**Files:**
- Modify: `seed_dev_data.py`

**Interfaces:**
- Consumes: `Course` from `models`; `AcademicSession`, `Semester` (already imported).

- [ ] **Step 1: Add `Course` to the imports**

Update the `from models import (...)` block to also include `Course`.

- [ ] **Step 2: Add `seed_courses()`**

Append to `seed_dev_data.py`:
```python

def seed_courses():
    academic_session = AcademicSession.query.filter_by(name='2025/2026').first()
    first_semester = Semester.query.filter_by(name='First Semester').first()
    if not academic_session or not first_semester:
        print('Skipping course seed — run seed_registration_config first')
        return

    courses_data = [
        dict(code='CSC 310', title='Database Systems', credits=3, department='Computer Science',
             level='Year 1', course_type='core', instructor='Dr. A. Bello', schedule='Mon/Wed 10:00-11:30'),
        dict(code='MAT 202', title='Calculus II', credits=4, department='Computer Science',
             level='Year 1', course_type='core', instructor='Dr. F. Musa', schedule='Tue/Thu 08:00-09:30'),
        dict(code='CSC 212', title='Digital Logic', credits=3, department='Computer Science',
             level='Year 1', course_type='core', instructor=None, schedule=None),
        dict(code='GST 202', title='Entrepreneurship', credits=1, department='Computer Science',
             level=None, course_type='elective', instructor='Mrs. K. Eze', schedule='Fri 09:00-10:00'),
        dict(code='CSC 330', title='Artificial Intelligence', credits=3, department='Computer Science',
             level='Year 1', course_type='elective', instructor='Dr. A. Bello', schedule='Wed 13:00-15:00'),
        dict(code='ITC 301', title='Network Fundamentals', credits=3, department='Information Technology',
             level=None, course_type='core', instructor='Mr. S. Danjuma', schedule='Mon/Wed 12:00-13:30'),
        dict(code='ITC 315', title='Web Technologies', credits=3, department='Information Technology',
             level=None, course_type='elective', instructor='Mr. S. Danjuma', schedule='Thu 10:00-12:00'),
        dict(code='ITC 320', title='IT Systems Lab', credits=2, department='Information Technology',
             level=None, course_type='lab', instructor=None, schedule=None),
    ]

    created = 0
    for data in courses_data:
        existing = Course.query.filter_by(
            code=data['code'], academic_session_id=academic_session.id, semester_id=first_semester.id
        ).first()
        if existing:
            continue
        course = Course(
            academic_session_id=academic_session.id,
            semester_id=first_semester.id,
            description=f"{data['title']} — core curriculum course.",
            **data,
        )
        db.session.add(course)
        created += 1
    db.session.commit()
    print(f'Created {created} course(s).')
```

- [ ] **Step 3: Call it from `seed()`**

Find the line `seed_registration_config()` inside `seed()` (added in the Feature 4 plan) and add `seed_courses()` immediately after it:
```python
        seed_registration_config()
        seed_courses()
```

- [ ] **Step 4: Run and verify**

Run: `python seed_dev_data.py` twice — first run creates 8 courses, second run shows "Created 0 course(s)" (idempotent).

Verify:
```bash
python -c "
from app import app
from models import Course
with app.app_context():
    assert Course.query.count() == 8
    cs = Course.query.filter_by(department='Computer Science').count()
    it = Course.query.filter_by(department='Information Technology').count()
    assert cs == 5 and it == 3, (cs, it)
    print('Course seed verified:', cs, 'CS courses,', it, 'IT courses')
"
```

- [ ] **Step 5: Commit**
```bash
git add seed_dev_data.py
git commit -m "feat: seed demo course catalog for the active registration period"
```

---

### Task 6: Routes

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: `get_available_courses`, `get_course_details` from `services.course`; `get_courses_by_semester` from `services.course_history`; `add_course`, `drop_course`, `submit_registration`, `get_add_drop_context` from `services.registration`; `RegisteredCourse`, `StudentRegistration` from `models`.

- [ ] **Step 1: Add imports**

In `app.py`, after the existing `from services.registration import (...)` block, add:
```python
from services.course import get_available_courses, get_course_details
from services.course_history import get_courses_by_semester
```
Update the existing `from services.registration import (...)` import to also include `add_course, drop_course, submit_registration, get_add_drop_context`.
Update the existing `from models import (...)` import to also include `RegisteredCourse`.

- [ ] **Step 2: Replace `add_drop()` and `my_courses()`, add the new routes**

Replace:
```python
@app.route('/add_drop')
def add_drop():
    return render_template('add_drop.html')
```
with:
```python
@app.route('/add_drop')
@login_required
def add_drop():
    context = get_add_drop_context(current_user)
    if context['period'] is None or context['student_registration'] is None:
        flash('Please complete semester registration before selecting courses.')
        return redirect(url_for('registration'))
    return render_template('add_drop.html')


@app.route('/add_drop/data')
@login_required
def add_drop_data():
    context = get_add_drop_context(current_user)
    period, student_registration = context['period'], context['student_registration']
    if period is None or student_registration is None:
        return jsonify({'success': False, 'message': 'No active registration found.'}), 400

    available = get_available_courses(current_user, period, student_registration)
    selected = RegisteredCourse.query.filter_by(student_registration_id=student_registration.id).all()

    def course_json(c):
        return {'id': c.id, 'code': c.code, 'title': c.title, 'credits': c.credits, 'type': c.course_type}

    return jsonify({
        'success': True,
        'session': period.academic_session.name,
        'semester': period.semester.name,
        'deadline': period.closes_at.strftime('%d %b %Y'),
        'closes_at_iso': period.closes_at.isoformat(),
        'min_credits': context['min_credits'],
        'max_credits': context['max_credits'],
        'credits_registered': student_registration.credits_registered,
        'courses_submitted': student_registration.courses_submitted,
        'available_courses': [course_json(c) for c in available],
        'selected_courses': [course_json(rc.course) for rc in selected],
    })


@app.route('/add_drop/add', methods=['POST'])
@login_required
def add_drop_add():
    data = request.get_json()
    if not data or 'course_id' not in data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    context = get_add_drop_context(current_user)
    period, student_registration = context['period'], context['student_registration']
    if period is None or student_registration is None:
        return jsonify({'success': False, 'message': 'No active registration found.'}), 400

    try:
        add_course(current_user, period, student_registration, data['course_id'])
    except RegistrationError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({'success': True, 'credits_registered': student_registration.credits_registered})


@app.route('/add_drop/drop', methods=['POST'])
@login_required
def add_drop_drop():
    data = request.get_json()
    if not data or 'course_id' not in data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    context = get_add_drop_context(current_user)
    student_registration = context['student_registration']
    if student_registration is None:
        return jsonify({'success': False, 'message': 'No active registration found.'}), 400

    try:
        drop_course(current_user, student_registration, data['course_id'])
    except RegistrationError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({'success': True, 'credits_registered': student_registration.credits_registered})


@app.route('/add_drop/submit', methods=['POST'])
@login_required
def add_drop_submit():
    context = get_add_drop_context(current_user)
    period, student_registration = context['period'], context['student_registration']
    if period is None or student_registration is None:
        return jsonify({'success': False, 'message': 'No active registration found.'}), 400

    try:
        submit_registration(current_user, period, student_registration)
    except RegistrationError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({'success': True, 'redirect': url_for('my_courses')})


@app.route('/registration/slip')
@login_required
def registration_slip():
    student_registration = (
        StudentRegistration.query
        .filter_by(user_id=current_user.id, courses_submitted=True)
        .order_by(StudentRegistration.registered_at.desc())
        .first()
    )
    if student_registration is None:
        flash('No submitted registration found to print.')
        return redirect(url_for('registration'))

    courses = RegisteredCourse.query.filter_by(student_registration_id=student_registration.id).all()
    return render_template('registration_slip.html', registration=student_registration, courses=courses)
```

Replace:
```python
@app.route('/my_courses')
def my_courses():
    return render_template('my_courses.html')
```
with:
```python
@app.route('/my_courses')
@login_required
def my_courses():
    return render_template('my_courses.html', groups=get_courses_by_semester(current_user))


@app.route('/courses/<int:course_id>/details')
@login_required
def course_details(course_id):
    registered_course = RegisteredCourse.query.join(StudentRegistration).filter(
        RegisteredCourse.course_id == course_id,
        StudentRegistration.user_id == current_user.id,
    ).first()
    if registered_course is None:
        return jsonify({'success': False, 'message': 'Course not found.'}), 404

    course = registered_course.course
    return jsonify({
        'success': True,
        'code': course.code,
        'title': course.title,
        'credits': course.credits,
        'department': course.department,
        'semester': course.semester.name,
        'description': course.description or 'Not available',
        'instructor': course.instructor or 'Not available',
        'schedule': course.schedule or 'Not available',
    })
```

- [ ] **Step 3: Manual verification**

Write a throwaway `scratch_verify_routes.py` covering, against the real dev DB (login via `session_transaction` per established pattern from Feature 4's task reports — avoid holding one `app.app_context()` open across multiple `test_client()` calls, and fetch a real CSRF token from an already-rendered page before any POST, per the documented pattern from Feature 4's Task 4/5/6):
1. Anonymous `GET /add_drop` → 302 to login.
2. Anonymous `GET /my_courses` → 302 to login.
3. A logged-in student with no `StudentRegistration` → `GET /add_drop` → 302 to `/registration`.
4. A logged-in, registered-but-not-submitted student (register one via `services.registration.register_student` if needed) → `GET /add_drop` → 200; `GET /add_drop/data` → 200 with `available_courses` containing only courses matching their department/level.
5. `POST /add_drop/add` with a valid `course_id` → 200, `credits_registered` increases.
6. `POST /add_drop/add` with the same `course_id` again → 400 (duplicate).
7. `POST /add_drop/drop` with that `course_id` → 200, `credits_registered` back down.
8. `GET /my_courses` → 200 (should render even with no submitted courses yet — empty groups list is fine).
9. Clean up any `RegisteredCourse`/`StudentRegistration` rows this script itself created, leaving seeded state intact.

Delete the script afterward.

- [ ] **Step 4: Commit**
```bash
git add app.py
git commit -m "feat: wire add/drop and my courses routes to real backend data"
```

---

### Task 7: Add/Drop Page UI

**Files:**
- Modify: `templates/add_drop.html`

**Interfaces:**
- Consumes: `/add_drop/data`, `/add_drop/add`, `/add_drop/drop`, `/add_drop/submit` (Task 6); `postJson` from `static/js/shared/api.js`; `showToast` from `static/js/shared/toast.js`.

- [ ] **Step 1: Add minimal `id` attributes for dynamic values**

The existing stats row (3 `.stat-card` divs for Deadline/Min Credits/Max Credits) and the credit-summary's `/ 24 credits` text have no `id`s to target from JS. Add exactly these three attributes (no other markup change — same tags, same classes, same visible text as placeholders):
- The Deadline `.stat-value` div → add `id="deadlineValue"`.
- The Min Credits `.stat-value` div → add `id="minCreditsValue"`.
- The Max Credits `.stat-value` div → add `id="maxCreditsValue"`.
- Change `<div><span id="totalCredits">0</span> / 24 credits</div>` to `<div><span id="totalCredits">0</span> / <span id="maxCreditsInline">24</span> credits</div>`.
- Add `<input type="hidden" id="csrf_token" value="{{ csrf_token() }}">` right after the opening `<div class="registration-page">` tag (matches the established CSRF pattern for `postJson`).

- [ ] **Step 2: Replace the `<script>` block**

Replace the entire existing `<script>...</script>` block (the one with `allCourses`, `registeredCourses`, `addCourse`, etc.) with:
```html
<script type="module" src="{{ url_for('static', filename='js/add_drop/add_drop.js') }}"></script>
```
And add, right before the closing `{% endblock %}` for content (keep the existing `{% block scripts %}{% endblock %}` as-is — do not put the module script there, put it inline in content like `registration.html` does).

- [ ] **Step 3: Create `static/js/add_drop/add_drop.js`**
```javascript
import { postJson } from '../shared/api.js';
import { showToast } from '../shared/toast.js';

let allCourses = [];
let registeredCourses = [];
let currentFilter = 'all';
let searchTerm = '';
let MIN_CREDITS = 0;
let MAX_CREDITS = 0;
let coursesSubmitted = false;

function getTotalCredits() {
    return registeredCourses.reduce((sum, c) => sum + c.credits, 0);
}

function getTypeClass(type) { return type === 'core' ? 'type-core' : type === 'elective' ? 'type-elective' : 'type-lab'; }
function getTypeLabel(type) { return type === 'core' ? 'Core' : type === 'elective' ? 'Elective' : 'Lab'; }

function updateUI() {
    const total = getTotalCredits();
    document.getElementById('totalCredits').innerText = total;
    const percentage = MAX_CREDITS ? (total / MAX_CREDITS) * 100 : 0;
    document.getElementById('creditProgressBar').style.width = Math.min(percentage, 100) + '%';
    document.getElementById('registeredCount').innerText = registeredCourses.length;

    const warningDiv = document.getElementById('creditWarning');
    if (total < MIN_CREDITS) {
        warningDiv.innerHTML = `<i class="fas fa-exclamation-triangle"></i> Need ${MIN_CREDITS - total} more credits (min ${MIN_CREDITS})`;
        warningDiv.style.color = '#b45b1c';
    } else if (total > MAX_CREDITS) {
        warningDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> Exceeds max by ${total - MAX_CREDITS}`;
        warningDiv.style.color = '#b13e3e';
    } else {
        warningDiv.innerHTML = `<i class="fas fa-check-circle"></i> Within credit limits`;
        warningDiv.style.color = '#0f7b4e';
    }

    const registeredBody = document.getElementById('registeredTableBody');
    if (registeredCourses.length === 0) {
        registeredBody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:1.5rem; color:#5a7b99;">No courses registered yet</td></tr>';
    } else {
        registeredBody.innerHTML = registeredCourses.map(c => `
            <tr>
                <td><strong>${c.code}</strong></td>
                <td>${c.title}</td>
                <td><span class="credit-badge">${c.credits} cr</span></td>
                <td>${coursesSubmitted ? '' : `<button class="remove-btn" data-course-id="${c.id}" title="Drop"><i class="fas fa-trash-alt"></i></button>`}</td>
            </tr>
        `).join('');
        registeredBody.querySelectorAll('.remove-btn').forEach(btn => {
            btn.addEventListener('click', () => dropCourse(Number(btn.dataset.courseId)));
        });
    }

    renderAvailableCourses();

    const submitBtn = document.querySelector('.action-buttons .btn-primary');
    const resetBtn = document.querySelector('.action-buttons .btn-secondary');
    if (submitBtn) submitBtn.disabled = coursesSubmitted;
    if (resetBtn) resetBtn.disabled = coursesSubmitted;
}

function renderAvailableCourses() {
    const tbody = document.getElementById('coursesTableBody');
    if (coursesSubmitted) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:1.5rem; color:#5a7b99;">Course selection has been submitted</td></tr>';
        return;
    }

    const filtered = allCourses.filter(course => {
        const matchesFilter = currentFilter === 'all' || course.type === currentFilter;
        const matchesSearch = course.code.toLowerCase().includes(searchTerm) || course.title.toLowerCase().includes(searchTerm);
        return matchesFilter && matchesSearch;
    });

    if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:1.5rem; color:#5a7b99;">No courses available</td></tr>';
        return;
    }

    tbody.innerHTML = filtered.map(course => `
        <tr>
            <td><strong>${course.code}</strong></td>
            <td>${course.title}</td>
            <td><span class="credit-badge">${course.credits} cr</span></td>
            <td><span class="type-badge ${getTypeClass(course.type)}">${getTypeLabel(course.type)}</span></td>
            <td><button class="add-btn" data-course-id="${course.id}"><i class="fas fa-plus-circle"></i> Add</button></td>
        </tr>
    `).join('');
    tbody.querySelectorAll('.add-btn').forEach(btn => {
        btn.addEventListener('click', () => addCourse(Number(btn.dataset.courseId)));
    });
}

async function loadData() {
    const resp = await fetch('/add_drop/data');
    const data = await resp.json();
    if (!data.success) {
        showToast(data.message || 'Failed to load registration data', true);
        return;
    }
    MIN_CREDITS = data.min_credits;
    MAX_CREDITS = data.max_credits;
    coursesSubmitted = data.courses_submitted;
    allCourses = data.available_courses;
    registeredCourses = data.selected_courses;

    document.getElementById('deadlineValue').innerText = data.deadline;
    document.getElementById('minCreditsValue').innerText = MIN_CREDITS;
    document.getElementById('maxCreditsValue').innerText = MAX_CREDITS;
    document.getElementById('maxCreditsInline').innerText = MAX_CREDITS;

    updateUI();
}

async function addCourse(courseId) {
    const result = await postJson('/add_drop/add', { course_id: courseId });
    if (!result.success) {
        showToast(result.message || 'Failed to add course', true);
        return;
    }
    await loadData();
    showToast('Course added');
}

async function dropCourse(courseId) {
    const result = await postJson('/add_drop/drop', { course_id: courseId });
    if (!result.success) {
        showToast(result.message || 'Failed to drop course', true);
        return;
    }
    await loadData();
    showToast('Course removed');
}

async function resetRegistration() {
    if (registeredCourses.length === 0 || coursesSubmitted) return;
    if (!confirm('Clear all registered courses?')) return;
    for (const c of [...registeredCourses]) {
        await postJson('/add_drop/drop', { course_id: c.id });
    }
    await loadData();
    showToast('Registration reset');
}

async function submitRegistration() {
    const result = await postJson('/add_drop/submit', {});
    if (!result.success) {
        showToast(result.message || 'Failed to submit registration', true);
        return;
    }
    showToast('Registration submitted');
    window.open('/registration/slip', '_blank');
    setTimeout(() => { window.location.href = result.redirect; }, 1200);
}

document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentFilter = btn.dataset.filter;
        renderAvailableCourses();
    });
});

document.getElementById('searchCourse').addEventListener('input', (e) => {
    searchTerm = e.target.value.toLowerCase();
    renderAvailableCourses();
});

document.querySelector('.action-buttons .btn-secondary').addEventListener('click', resetRegistration);
document.querySelector('.action-buttons .btn-primary').addEventListener('click', submitRegistration);

loadData();
```
Note: the original HTML has `onclick="resetRegistration()"` / `onclick="submitRegistration()"` / `onclick="addCourse(${id})"` / `onclick="dropCourse(${id})"` inline attributes. Since this is now an ES module (`type="module"`), functions are scoped to the module and NOT available as global `onclick` handlers. Remove the `onclick="resetRegistration()"` and `onclick="submitRegistration()"` attributes from the two `.action-buttons` buttons in the HTML (Step 1 of this task — add this to that step's edit list) since the JS above attaches listeners programmatically instead; the per-row Add/Drop buttons already switched to `data-course-id` + programmatic listeners in the JS above, so their template-string `onclick` attributes are simply not emitted by the new render functions (they never existed in the new template strings shown above).

- [ ] **Step 4: Manual verification**

Since this task changes only client-side JS/markup with no new server logic, verify via `render_template` that `add_drop.html` renders without a Jinja error (it has no new template variables, so this is just a syntax check) and via a quick grep that no `onclick="resetRegistration()"` / `onclick="submitRegistration()"` remain in the file. Then do one live-flow smoke check: start the dev server is not required — instead confirm the JS file has no syntax errors via `node --check static/js/add_drop/add_drop.js` if Node is available in this environment; if not, visually re-read the file once for balanced braces/parens before committing.

- [ ] **Step 5: Commit**
```bash
git add templates/add_drop.html static/js/add_drop/add_drop.js
git commit -m "feat: rewire add/drop page to real backend data and actions"
```

---

### Task 8: My Courses UI, Course Details Modal, Registration Slip

**Files:**
- Modify: `templates/my_courses.html`
- Modify: `static/css/my_courses.css`
- Create: `static/js/my_courses/my_courses.js`
- Create: `templates/registration_slip.html`

**Interfaces:**
- Consumes: `groups` (from `get_courses_by_semester`, passed by the `my_courses()` route in Task 6); `GET /courses/<id>/details` (Task 6); `registration`/`courses` (from the `registration_slip()` route in Task 6).

- [ ] **Step 1: Rewrite the stats and course-list sections of `templates/my_courses.html`**

Keep the page header, term-chip, and filter-bar sections exactly as they are (still static — no backend data feeds them in this milestone; they're cosmetic and out of scope per the design's "keep existing UI" instruction beyond what's explicitly listed as needing real data).

Replace the 4 hardcoded `.stat-card` numbers in `.stats-row` with computed values. `groups` is already passed in by the route (Task 6). Compute the 4 stat totals with a Jinja `namespace` loop placed right before the `.stats-row` div:
```html
{% set ns = namespace(enrolled=0, in_progress=0, completed=0, credit_total=0) %}
{% for group in groups %}
    {% for rc in group.courses %}
        {% set ns.enrolled = ns.enrolled + 1 %}
        {% set ns.credit_total = ns.credit_total + rc.course.credits %}
        {% if group.is_current %}
            {% set ns.in_progress = ns.in_progress + 1 %}
        {% else %}
            {% set ns.completed = ns.completed + 1 %}
        {% endif %}
    {% endfor %}
{% endfor %}
```
Place this right before the `.stats-row` div. Then set each `.stat-number` to `{{ ns.enrolled }}`, `{{ ns.in_progress }}`, `{{ ns.completed }}`, `{{ ns.credit_total }}` respectively (same 4 cards, same order: Enrolled, In progress, Completed, Credit total).

Replace the three hardcoded `.semester-category` blocks with:
```html
{% for group in groups %}
<details class="semester-category" {% if group.is_current %}open{% endif %}>
    <summary class="semester-title">
        <i class="fas fa-play-circle" style="color: {{ '#0f7b4e' if group.is_current else '#7f8fa4' }};"></i>
        {{ group.academic_session }} {{ group.semester }}{% if group.is_current %} (Current){% endif %}
    </summary>
    <div class="courses-table-wrapper">
        <table class="courses-table">
            <thead><tr><th>Course Code</th><th>Course Title</th><th>Credits</th><th>Grade</th><th></th></tr></thead>
            <tbody>
                {% for rc in group.courses %}
                <tr>
                    <td>{{ rc.course.code }}</td>
                    <td>{{ rc.course.title }}</td>
                    <td><span class="credit-badge-list">{{ rc.course.credits }}</span></td>
                    <td>{{ rc.grade or 'Not yet available' }}</td>
                    <td><button class="action-btn view-details-btn" data-course-id="{{ rc.course.id }}"><i class="fas fa-eye"></i> View</button></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</details>
{% endfor %}
{% if not groups %}
<div class="empty-state" style="text-align:center; padding:2rem; color:#5a7b99;">
    <p>No courses registered yet.</p>
</div>
{% endif %}
```
Keep the `.info-legend` block below it as-is.

Add `<input type="hidden" id="csrf_token" value="{{ csrf_token() }}">` near the top of the content block (not strictly needed for GET-only fetches to `/courses/<id>/details`, but consistent with the established convention — include it for future-proofing since `postJson` isn't used here, only plain `fetch`, so this is optional; include it anyway for consistency).

Add the course-details modal markup, right before the closing `</div>` of `.courses-page`:
```html
<div id="courseDetailsModal" class="course-modal-overlay" hidden>
    <div class="course-modal">
        <button class="course-modal-close" id="courseModalClose"><i class="fas fa-times"></i></button>
        <h3 id="modalCourseTitle"></h3>
        <div class="course-modal-body">
            <div><strong>Code:</strong> <span id="modalCourseCode"></span></div>
            <div><strong>Department:</strong> <span id="modalCourseDepartment"></span></div>
            <div><strong>Credits:</strong> <span id="modalCourseCredits"></span></div>
            <div><strong>Semester:</strong> <span id="modalCourseSemester"></span></div>
            <div><strong>Instructor:</strong> <span id="modalCourseInstructor"></span></div>
            <div><strong>Schedule:</strong> <span id="modalCourseSchedule"></span></div>
            <div><strong>Description:</strong> <p id="modalCourseDescription"></p></div>
            <div><strong>Assessment Breakdown:</strong> <p>Assessment breakdown not yet available.</p></div>
        </div>
    </div>
</div>
```

Add the module script include right before `{% block scripts %}`:
```html
<script type="module" src="{{ url_for('static', filename='js/my_courses/my_courses.js') }}"></script>
```

- [ ] **Step 2: Create `static/js/my_courses/my_courses.js`**
```javascript
const modal = document.getElementById('courseDetailsModal');

function openModal(data) {
    document.getElementById('modalCourseTitle').innerText = `${data.code} — ${data.title}`;
    document.getElementById('modalCourseCode').innerText = data.code;
    document.getElementById('modalCourseDepartment').innerText = data.department;
    document.getElementById('modalCourseCredits').innerText = data.credits;
    document.getElementById('modalCourseSemester').innerText = data.semester;
    document.getElementById('modalCourseInstructor').innerText = data.instructor;
    document.getElementById('modalCourseSchedule').innerText = data.schedule;
    document.getElementById('modalCourseDescription').innerText = data.description;
    modal.hidden = false;
}

document.querySelectorAll('.view-details-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        const courseId = btn.dataset.courseId;
        const resp = await fetch(`/courses/${courseId}/details`);
        const data = await resp.json();
        if (!data.success) return;
        openModal(data);
    });
});

document.getElementById('courseModalClose').addEventListener('click', () => { modal.hidden = true; });
modal.addEventListener('click', (e) => { if (e.target === modal) modal.hidden = true; });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') modal.hidden = true; });
```

- [ ] **Step 3: Append modal CSS to `static/css/my_courses.css`**
```css

.course-modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(15, 49, 80, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1200;
}
.course-modal {
    background: white;
    border-radius: 1.2rem;
    padding: 2rem;
    max-width: 500px;
    width: 90%;
    max-height: 80vh;
    overflow-y: auto;
    position: relative;
    box-shadow: 0 20px 40px rgba(0,0,0,0.2);
}
.course-modal-close {
    position: absolute;
    top: 1rem;
    right: 1rem;
    background: none;
    border: none;
    font-size: 1.2rem;
    color: #5a7b99;
    cursor: pointer;
}
.course-modal-body > div {
    margin-bottom: 0.8rem;
    color: #2c3e50;
}
```

- [ ] **Step 4: Create `templates/registration_slip.html`**
```html
{% extends "base.html" %}

{% block head %}
    <title>Registration Slip · Student Portal</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        .slip-container { max-width: 700px; margin: 2rem auto; background: white; padding: 2rem; border-radius: 1rem; border: 1px solid #d9e9ff; }
        .slip-header { text-align: center; margin-bottom: 1.5rem; }
        .slip-table { width: 100%; border-collapse: collapse; margin: 1rem 0; }
        .slip-table th, .slip-table td { padding: 0.6rem; border-bottom: 1px solid #eef3fc; text-align: left; }
        .print-btn { display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.6rem 1.5rem; border-radius: 60px; background: #0f3150; color: white; border: none; cursor: pointer; }
        @media print {
            .navbar, .print-btn { display: none !important; }
        }
    </style>
{% endblock %}

{% block content %}
<div class="slip-container">
    <div class="slip-header">
        <h2><i class="fas fa-file-alt"></i> Course Registration Slip</h2>
        <p>{{ registration.registration_period.academic_session.name }} · {{ registration.registration_period.semester.name }}</p>
    </div>
    <div>
        <strong>Name:</strong> {{ current_user.name }}<br>
        <strong>Reg No:</strong> {{ current_user.reg_no }}<br>
        <strong>Department:</strong> {{ current_user.department }}<br>
        <strong>Submitted:</strong> {{ registration.updated_at.strftime('%d %b %Y, %I:%M %p') }}
    </div>
    <table class="slip-table">
        <thead><tr><th>Code</th><th>Title</th><th>Credits</th></tr></thead>
        <tbody>
            {% for rc in courses %}
            <tr><td>{{ rc.course.code }}</td><td>{{ rc.course.title }}</td><td>{{ rc.course.credits }}</td></tr>
            {% endfor %}
        </tbody>
    </table>
    <p><strong>Total Credits:</strong> {{ registration.credits_registered }}</p>
    <button class="print-btn" onclick="window.print()"><i class="fas fa-print"></i> Print</button>
</div>
{% endblock %}
```

- [ ] **Step 5: Manual verification**

Write a throwaway `scratch_verify_ui8.py` that, inside `app.app_context()` and using `test_request_context()` + `login_user()` + `render_template()` (per the established pattern from Feature 4's Task 5 report — bypasses gate concerns to isolate template rendering):
1. Renders `my_courses.html` with `groups=[]` — confirm no Jinja error, confirm "No courses registered yet" appears.
2. Renders `my_courses.html` with a real `groups` result from `get_courses_by_semester` for a student who has actually added+submitted at least one course (set this up first via `add_course`/`submit_registration`, or reuse state from Task 6's verification if still present) — confirm the course code/title appear, confirm the group's `<details open>` when `is_current` is true.
3. Renders `registration_slip.html` for that same submitted registration — confirm it renders without error and contains the course code.

Delete the script afterward. Also confirm cleanup: any `RegisteredCourse`/`StudentRegistration` rows created solely for this verification are removed unless they're meant to remain as the final demonstrable state (your judgment — leaving one real submitted registration for manual browser testing is reasonable and doesn't need to be deleted).

- [ ] **Step 6: Commit**
```bash
git add templates/my_courses.html templates/registration_slip.html static/css/my_courses.css static/js/my_courses/my_courses.js
git commit -m "feat: implement my courses page, course details modal, and registration slip"
```

---

### Task 9: End-to-End Verification and Progress Doc

**Files:**
- Modify: `DEVELOPMENT_PROGRESS.md`

- [ ] **Step 1: Full flow verification**

Write a throwaway `scratch_verify_e2e9.py` covering, via `test_client` with a fresh (or reset) unregistered-and-unsubmitted demo student:
1. Login → complete Feature 4's Register Now (`POST /registration/register`) → `GET /add_drop` → 200.
2. `GET /add_drop/data` → confirm `available_courses` only shows courses for the student's own department/level.
3. Add 2-3 courses via `POST /add_drop/add`, confirming `credits_registered` accumulates correctly and stays within the seeded max (24).
4. Re-fetch `GET /add_drop/data` (simulating a page refresh) → confirm `selected_courses` still shows the same courses (persistence).
5. `POST /add_drop/submit`:
   - If credits are below the seeded minimum (15), expect a 400 with a clear message — add more courses until at/above minimum, then retry submit and expect success.
6. After successful submit, `GET /add_drop/data` → confirm `courses_submitted: true` and `POST /add_drop/add`/`drop` now both reject with a clean error.
7. `GET /my_courses` → 200, confirm the submitted courses appear in a `(Current)` group.
8. `GET /registration/slip` → 200, confirm it contains the submitted course codes and the right total credits.

Delete the script afterward. This test's created rows may remain in the dev DB as a real demonstrable end state (consistent with Feature 4's precedent of leaving one seeded "already registered" demo student reachable) — no cleanup required for this final task's script, unlike the scoped throwaway scripts in earlier tasks.

- [ ] **Step 2: Update `DEVELOPMENT_PROGRESS.md`**

Add a new section (after the existing "Feature 4" section, before "Known pre-existing issues"):
```markdown
## Feature 5 & 6: Course Add/Drop and My Courses — Complete

- New models: `Course`, `RegisteredCourse`; `StudentRegistration.courses_submitted` flag added.
- New services: `services/course.py` (catalog/eligibility filtering), `services/course_history.py` (My Courses grouping), `services/validation.py` (reusable business-rule checks), `services/registration.py` extended with `add_course`/`drop_course`/`submit_registration`/`get_add_drop_context`. `RegistrationError` moved to `services/errors.py` to break a circular import, still re-exported from `services.registration` for backward compatibility.
- `add_drop.html` keeps its original JS-array-driven architecture, rewired to fetch real data (`/add_drop/data`) and perform real add/drop/submit actions instead of mutating in-memory-only state — selections now survive a page refresh.
- `my_courses.html` converted to server-rendered Jinja (matching Feature 4's `registration.html` precedent), grouped by session/semester with the current semester expanded by default (native `<details>`/`<summary>`).
- New course-details modal (My Courses' "View" buttons) and a printable registration slip (`/registration/slip`, browser print, no new dependency).
- Fixed: `/add_drop` and `/my_courses` were missing `@login_required` — fixed as part of rewriting both routes.
- Spec: `docs/superpowers/specs/2026-07-31-course-add-drop-design.md`
- Out of scope (deferred): grading (the `grade` column exists but nothing sets it yet), real PDF generation, post-submission editing, admin UI for the course catalog.

## Next milestone

TBD — awaiting direction on the next feature from `doc/t.txt`.
```
Also update the "Known pre-existing issues" section: remove the now-fixed `add_drop`/`my_courses` items from that list (only `payments_history`/`pay_summary` remain missing `@login_required`).

- [ ] **Step 3: Boot check and commit**
```bash
python -c "import app; print('OK')"
git add DEVELOPMENT_PROGRESS.md
git commit -m "docs: record course add/drop and my courses as complete in progress log"
```
