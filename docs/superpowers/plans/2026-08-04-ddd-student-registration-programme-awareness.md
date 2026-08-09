# Student & Registration Programme-awareness (DDD Refactor Sub-project 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make registration periods independently activatable per Programme (closing sub-project 2's deliberate deferral), and switch eligibility checks to read FK columns with a string/skip fallback for incomplete data.

**Architecture:** No schema changes, no migration — `CourseOffering` gets a plain Python `@property` deriving Programme via its existing `academic_session` relationship, mirroring `RegistrationPeriod.programme` from sub-project 2. `activate_period()` is generalized from "single active period institution-wide" to "single active period per Programme-scope-group" (a Programme, or `None` for the shared/legacy group) — since every period today is unscoped, this is behavior-preserving for anything not yet Programme-scoped. `get_active_period()` gains an optional `user` parameter that resolves the user's Programme-scoped active period first, falling back to the shared/legacy one. `validate_course_eligible()` gains hybrid FK/string department matching and a new soft Programme check.

**Tech Stack:** Flask, Flask-SQLAlchemy, Jinja2, SQLite (dev). No automated test framework — verification is via throwaway `test_client`/`app_context` scripts, run and discarded, never committed.

## Global Constraints

- No new columns, no migration — this sub-project is purely service-layer/property/template changes.
- `activate_period()`'s bulk `.update()` calls must not join the table being updated (SQLAlchemy's `Query.update()` does not reliably support joined multi-table updates) — filter `RegistrationPeriod` via `academic_session_id.in_(<subquery>)`, not a join.
- Every existing caller of `get_active_period()` must be updated to pass its already-in-scope `user`/`current_user` — none should be left calling the old no-argument form, since that now means "shared/legacy only," which is the correct fallback-only behavior but would silently skip Programme-scoped periods if any caller is missed.
- `validate_course_eligible`'s FK checks must never make a student ineligible for a course they'd have been eligible for under the legacy string comparison — the FK path only tightens the check when both sides have the FK populated, it never removes the string fallback.
- `get_credit_limits`/`DepartmentRegistrationRule` are untouched — out of scope for this sub-project.

---

### Task 1: `CourseOffering.programme` property and `activate_period()` generalization

**Files:**
- Modify: `models.py:201-225` (`CourseOffering` class)
- Modify: `services/admin_session.py:140-161` (`activate_period`)

**Interfaces:**
- Produces: `CourseOffering.programme` (read-only property, returns `Programme | None`); `activate_period(period_id)` — same signature, generalized scoping behavior.

- [ ] **Step 1: Add `CourseOffering.programme` property**

Insert immediately after the existing relationships in `CourseOffering` (`models.py:222-225`):

```python
    @property
    def programme(self):
        return self.academic_session.programme if self.academic_session else None
```

- [ ] **Step 2: Rewrite `activate_period` in `services/admin_session.py`**

Replace the current function (`services/admin_session.py:140-161`):

```python
def activate_period(period_id):
    """The single-active-period-per-Programme-scope-group enforcement point.
    A scope group is a Programme, or None for the shared/legacy group.
    Deactivates every other RegistrationPeriod in the same scope group,
    marks this period's session current/open, and closes any other
    currently-current session in the same scope group. Periods/sessions in
    a DIFFERENT scope group are untouched — this is what lets different
    Programmes run independent registration schedules. Since every period
    today is unscoped (programme_id=None on its session), this preserves
    the exact pre-existing institution-wide behavior for anything not yet
    Programme-scoped."""
    period = get_period(period_id)
    programme_id = period.academic_session.programme_id

    # Resolve the scope group's session IDs first, then filter by
    # academic_session_id.in_(...) rather than joining AcademicSession
    # directly into the RegistrationPeriod bulk .update() query — SQLAlchemy's
    # Query.update() does not reliably support joined multi-table updates.
    scope_session_ids_query = db.session.query(AcademicSession.id)
    scope_session_ids_query = (
        scope_session_ids_query.filter(AcademicSession.programme_id == programme_id)
        if programme_id is not None
        else scope_session_ids_query.filter(AcademicSession.programme_id.is_(None))
    )

    RegistrationPeriod.query.filter(
        RegistrationPeriod.id != period_id,
        RegistrationPeriod.academic_session_id.in_(scope_session_ids_query),
    ).update({'is_active': False}, synchronize_session=False)
    period.is_active = True

    same_scope_sessions = AcademicSession.query.filter(
        AcademicSession.id != period.academic_session_id,
        AcademicSession.is_current == True,
    )
    same_scope_sessions = (
        same_scope_sessions.filter(AcademicSession.programme_id == programme_id)
        if programme_id is not None
        else same_scope_sessions.filter(AcademicSession.programme_id.is_(None))
    )
    same_scope_sessions.update({'is_current': False, 'status': 'closed'}, synchronize_session=False)

    session_obj = get_session(period.academic_session_id)
    session_obj.is_current = True
    session_obj.status = 'open'

    db.session.commit()
    return period
```

- [ ] **Step 3: Run and verify**

Verify with a throwaway script:
```python
from app import app
from models import db, Programme, AcademicSession, Semester, RegistrationPeriod
from services.admin_session import activate_period
from datetime import datetime, timedelta

with app.app_context():
    prog = Programme.query.first()
    semester = Semester.query.first()

    # Two sessions/periods in the SAME new Programme scope
    s1 = AcademicSession(name='ZZTEST-A', status='draft', programme_id=prog.id)
    s2 = AcademicSession(name='ZZTEST-B', status='draft', programme_id=prog.id)
    db.session.add_all([s1, s2])
    db.session.flush()
    now = datetime.now()
    p1 = RegistrationPeriod(academic_session_id=s1.id, semester_id=semester.id, opens_at=now, closes_at=now+timedelta(days=30), min_credits=1, max_credits=30, is_active=False)
    p2 = RegistrationPeriod(academic_session_id=s2.id, semester_id=semester.id, opens_at=now, closes_at=now+timedelta(days=30), min_credits=1, max_credits=30, is_active=False)
    db.session.add_all([p1, p2])
    db.session.commit()

    # Snapshot every OTHER existing period/session (different scope) before activating
    other_active_before = {p.id: p.is_active for p in RegistrationPeriod.query.filter(RegistrationPeriod.id.notin_([p1.id, p2.id])).all()}
    other_current_before = {s.id: s.is_current for s in AcademicSession.query.filter(AcademicSession.id.notin_([s1.id, s2.id])).all()}

    activate_period(p1.id)
    assert RegistrationPeriod.query.get(p1.id).is_active is True
    assert AcademicSession.query.get(s1.id).is_current is True

    activate_period(p2.id)
    assert RegistrationPeriod.query.get(p2.id).is_active is True
    assert RegistrationPeriod.query.get(p1.id).is_active is False, 'p1 should be deactivated (same scope as p2)'
    assert AcademicSession.query.get(s2.id).is_current is True
    assert AcademicSession.query.get(s1.id).is_current is False

    # Confirm every OTHER (different-scope, e.g. legacy/unscoped) period/session is untouched
    for pid, was_active in other_active_before.items():
        assert RegistrationPeriod.query.get(pid).is_active == was_active, f'period {pid} scope leaked'
    for sid, was_current in other_current_before.items():
        assert AcademicSession.query.get(sid).is_current == was_current, f'session {sid} scope leaked'

    print('activate_period scoping OK — different Programme scopes are independent, other scopes untouched.')

    db.session.delete(p1)
    db.session.delete(p2)
    db.session.delete(s1)
    db.session.delete(s2)
    db.session.commit()
    print('Cleaned up.')
```
Expected: no assertion errors, cleanup confirmed.

Also verify the legacy/unscoped-group regression case explicitly: activate an existing unscoped period, confirm every *other* unscoped period is deactivated and every other current unscoped session is closed — i.e., confirm this still matches sub-project 2's own Task 5 verification baseline for legacy periods (byte-for-byte unchanged observable behavior).

- [ ] **Step 4: Commit**

```bash
git add models.py services/admin_session.py
git commit -m "feat: generalize activate_period to per-Programme-scope-group activation"
```

---

### Task 2: `get_active_period(user=None)` and call site updates

**Files:**
- Modify: `services/registration.py` (`get_active_period`, `get_registration_status_context`, `get_add_drop_context`)
- Modify: `app.py:750` (`registration_register`)
- Modify: `services/notification.py:127` (`notify_registration_window_events`)
- Modify: `services/course_history.py:9` (`get_courses_by_semester`)

**Interfaces:**
- Produces: `get_active_period(user=None)` — new optional parameter, default preserves the exact prior no-argument behavior (shared/legacy active period only).

- [ ] **Step 1: Rewrite `get_active_period` in `services/registration.py`**

Replace the current function (`services/registration.py:11-21`):

```python
def get_active_period(user=None):
    """Return the RegistrationPeriod currently active for this user's
    Programme, falling back to the shared/legacy active period if the user
    has no programme_id or their Programme has no active period of its own.
    With user=None, returns the shared/legacy active period only — the same
    query this function always ran before Programme-scoped periods existed."""
    if user is not None and user.programme_id is not None:
        programme_period = (
            RegistrationPeriod.query.join(AcademicSession)
            .filter(RegistrationPeriod.is_active == True, AcademicSession.programme_id == user.programme_id)
            .order_by(RegistrationPeriod.id.desc())
            .first()
        )
        if programme_period is not None:
            return programme_period

    return (
        RegistrationPeriod.query.join(AcademicSession)
        .filter(RegistrationPeriod.is_active == True, AcademicSession.programme_id.is_(None))
        .order_by(RegistrationPeriod.id.desc())
        .first()
    )
```

Add `AcademicSession` to the top-of-file model import line in `services/registration.py` if not already present (check the existing `from models import ...` line — this file already imports `RegistrationPeriod`, confirm `AcademicSession` is added alongside it).

- [ ] **Step 2: Update the 4 in-file call sites**

`get_registration_status_context(user)` (`services/registration.py:106`): change `period = get_active_period()` to `period = get_active_period(user)`.

`get_add_drop_context(user)` (`services/registration.py:318`... line number may shift slightly after Step 1's edit, locate by function name): change `period = get_active_period()` to `period = get_active_period(user)`.

- [ ] **Step 3: Update `app.py`'s call site**

`registration_register()` (`app.py:750`): change `period = get_active_period()` to `period = get_active_period(current_user)`.

- [ ] **Step 4: Update `services/notification.py`'s call site**

`notify_registration_window_events(user)` (`services/notification.py:127`): change `period = get_active_period()` to `period = get_active_period(user)`.

- [ ] **Step 5: Update `services/course_history.py`'s call site**

`get_courses_by_semester(user)` (`services/course_history.py:9`): change `active_period = get_active_period()` to `active_period = get_active_period(user)`.

- [ ] **Step 6: Run and verify**

Verify with a throwaway script:
```python
from app import app
from models import db, User, Programme, AcademicSession, Semester, RegistrationPeriod
from services.registration import get_active_period
from datetime import datetime, timedelta

with app.app_context():
    prog = Programme.query.first()
    semester = Semester.query.first()
    shared_active = get_active_period()  # today's shared/legacy active period, if any

    s = AcademicSession(name='ZZTEST-GAP', status='draft', programme_id=prog.id)
    db.session.add(s)
    db.session.flush()
    now = datetime.now()
    p = RegistrationPeriod(academic_session_id=s.id, semester_id=semester.id, opens_at=now, closes_at=now+timedelta(days=30), min_credits=1, max_credits=30, is_active=True)
    db.session.add(p)
    db.session.commit()

    student = User.query.filter_by(is_admin=False, programme_id=prog.id).first()
    if student is None:
        # No seeded student has this programme_id — temporarily assign one for the test
        student = User.query.filter_by(is_admin=False).first()
        original_programme_id = student.programme_id
        student.programme_id = prog.id
        db.session.commit()
    else:
        original_programme_id = prog.id  # already correct, nothing to restore

    assert get_active_period(student).id == p.id, "student with matching programme_id should get the Programme-scoped period"
    assert get_active_period(None) == shared_active, "no-user call must be unchanged"

    other_student = User.query.filter(User.is_admin == False, User.programme_id.isnot(prog.id)).first()
    if other_student:
        result = get_active_period(other_student)
        assert result != p or result is None, "student in a different (or no) programme must not get this Programme's period"

    if student.programme_id != original_programme_id:
        student.programme_id = original_programme_id
        db.session.commit()
    db.session.delete(p)
    db.session.delete(s)
    db.session.commit()
    print('get_active_period(user) resolution OK.')
```
Expected: no assertion errors, cleanup confirmed (including restoring any student's `programme_id` you had to temporarily change).

- [ ] **Step 7: Commit**

```bash
git add services/registration.py app.py services/notification.py services/course_history.py
git commit -m "feat: make get_active_period Programme-aware with shared/legacy fallback"
```

---

### Task 3: Hybrid FK/string eligibility matching

**Files:**
- Modify: `services/validation.py` (`validate_course_eligible`)

**Interfaces:**
- Produces: `validate_course_eligible(course, user, period)` — same signature, hybrid FK/string department matching, new soft Programme check.

- [ ] **Step 1: Rewrite `validate_course_eligible`**

Replace the current function (`services/validation.py:5-15`):

```python
def validate_course_eligible(course, user, period):
    """Raise RegistrationError unless the course offering matches the
    student's department/programme/level and belongs to the active
    registration period's session/semester. Department and Programme use an
    FK match when both sides have the FK set, falling back to the legacy
    string comparison (department) or skipping the check (programme, which
    has no legacy string equivalent) when either side is missing the FK —
    incomplete FK backfill must never silently lock a student out of
    eligible courses. A course with level=None is level-agnostic and
    matches any student's level."""
    if course.department_id is not None and user.department_id is not None:
        if course.department_id != user.department_id:
            raise RegistrationError('This course is not offered in your department.')
    elif course.department != user.department:
        raise RegistrationError('This course is not offered in your department.')

    course_programme = course.programme
    if course_programme is not None and user.programme_id is not None:
        if course_programme.id != user.programme_id:
            raise RegistrationError('This course is not offered under your programme.')

    if course.level is not None and course.level != user.level:
        raise RegistrationError('This course is not offered at your level.')
    if course.academic_session_id != period.academic_session_id or course.semester_id != period.semester_id:
        raise RegistrationError('This course is not offered this semester.')
```

- [ ] **Step 2: Run and verify**

Verify with a throwaway script covering all 6 cases from the design spec's Testing section:
```python
from app import app
from models import db, User, CourseOffering, Programme, Department
from services.validation import validate_course_eligible
from services.errors import RegistrationError

with app.app_context():
    course = CourseOffering.query.filter(CourseOffering.department_id.isnot(None)).first()
    matching_student = User.query.filter_by(is_admin=False, department_id=course.department_id).first()
    period = type('P', (), {'academic_session_id': course.academic_session_id, 'semester_id': course.semester_id})()

    # Case 1: both FKs set, matching -> eligible (no exception)
    if matching_student:
        validate_course_eligible(course, matching_student, period)
        print('Case 1 (FK match) OK — no exception.')

    # Case 2: both FKs set, mismatched -> rejected via FK path
    other_dept = Department.query.filter(Department.id != course.department_id).first()
    mismatched_student = User.query.filter_by(is_admin=False, department_id=other_dept.id if other_dept else None).first()
    if mismatched_student and other_dept:
        try:
            validate_course_eligible(course, mismatched_student, period)
            print('Case 2 FAILED — expected RegistrationError')
        except RegistrationError as e:
            print('Case 2 (FK mismatch) OK —', e)

    # Case 3: student missing department_id -> falls back to string comparison
    no_fk_student = User.query.filter_by(is_admin=False, department_id=None).first()
    if no_fk_student:
        try:
            validate_course_eligible(course, no_fk_student, period)
            print('Case 3a (no FK, string path, outcome depends on legacy string match) — no exception')
        except RegistrationError as e:
            print('Case 3b (no FK, string path, correctly rejected) —', e)

    print('Eligibility hybrid matching verified — no test data mutated (read-only checks).')
```
Expected: cases behave as commented; no assertion failures. This script is read-only (no writes/cleanup needed) since it only calls a validation function against existing data.

- [ ] **Step 3: Commit**

```bash
git add services/validation.py
git commit -m "feat: add hybrid FK/string department matching and soft programme check to eligibility"
```

---

### Task 4: Admin template copy updates

**Files:**
- Modify: `templates/admin/registration_open.html`
- Modify: `templates/admin/session_form.html`

**Interfaces:**
- Consumes: `period.academic_session.programme` (already available via the existing relationship, no new context variable needed).

- [ ] **Step 1: Update `templates/admin/registration_open.html`**

Replace the intro paragraph (currently line 8):
```html
    <p style="color: var(--text-muted);">Activating a period deactivates every other period in the same Programme (or every other shared/legacy period, if this one isn't Programme-scoped) and makes its session the current one for that scope.</p>
```

Add a Programme column to the table header (currently lines 11-17, insert after "Session"):
```html
                <th style="padding:0.8rem;">Programme</th>
```

Add the corresponding cell in the table body (currently lines 21-26, insert after the Session `<td>`):
```html
                <td style="padding:0.8rem;">{{ period.academic_session.programme.name if period.academic_session.programme else 'Shared / Legacy' }}</td>
```

Update the `colspan` on the empty-state row (currently `colspan="5"`) to `colspan="6"`.

Update the confirm-dialog text (currently line 27):
```html
                    <form method="POST" action="{{ url_for('admin_period_activate', session_id=period.academic_session_id, period_id=period.id) }}" onsubmit="return confirm('Activate this period? Every other period in the same Programme scope will be deactivated.');">
```

- [ ] **Step 2: Update `templates/admin/session_form.html`**

Update the confirm-dialog text (currently line 88) to add the same scope clarification:
```html
                    <form method="POST" action="{{ url_for('admin_period_activate', session_id=session.id, period_id=period.id) }}" style="display:inline;" onsubmit="return confirm('Activate this period? Every other period in the same Programme scope will be deactivated.');">
```

- [ ] **Step 3: Manual verification**

Run the dev server, log in as an admin with `registration.manage`, visit the `admin_registration_open` route (`app.py:2585-2588`, renders `registration_open.html` via `list_inactive_periods()`), confirm the Programme column renders correctly for both a Programme-scoped and a shared/legacy period, and confirm the confirm-dialog text reads correctly.

- [ ] **Step 4: Commit**

```bash
git add templates/admin/registration_open.html templates/admin/session_form.html
git commit -m "docs: update period-activation confirm dialogs to reflect per-Programme scoping"
```

---

### Task 5: End-to-end verification and cleanup

**Files:** None (verification only — no code changes expected unless Tasks 1-4 issues surface).

- [ ] **Step 1: Run the full manual verification pass**

1. Re-run Task 1's and Task 2's verification scripts once more against the final combined state (all tasks merged) to confirm no interaction issues between the `activate_period` and `get_active_period` changes.
2. Full student registration flow (dashboard, `/registration`, `/add_drop`) for a student with complete FK data (`department_id`, `programme_id` both set) — confirm identical behavior to pre-sub-project-4.
3. Full student registration flow for a student with incomplete FK data (`programme_id=None` or `department_id=None`) — confirm the string/skip fallback keeps them able to register exactly as before.
4. Activate a Programme-scoped period via the admin UI; confirm a student in that Programme sees it as their active period, and a student in a different (or no) Programme still sees the shared/legacy period.
5. Regression: `/admin/sessions`, `/admin/course-catalog`, `/admin/courses`, `/admin/departments`, `/admin/programmes`, `/admin/students`, `/admin/dashboard` all still load without error.
6. Delete any test `AcademicSession`/`RegistrationPeriod`/`User` mutations created during verification so the dev DB is left in a clean, representative state — re-run `PRAGMA foreign_key_check`/`integrity_check` as the actual last step, not assumed clean.

- [ ] **Step 2: Update `docs/superpowers/CURRENT_STATE.md`**

Update Active Worktree, Current Milestone, Last Commit, Completed, In Progress, Next, Notes sections per the established template, recording this sub-project's completion and that sub-project 5 (FeeStructure) is next in the DDD refactor sequence.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/CURRENT_STATE.md
git commit -m "docs: update CURRENT_STATE.md after Student & Registration Programme-awareness (DDD refactor sub-project 4)"
```
