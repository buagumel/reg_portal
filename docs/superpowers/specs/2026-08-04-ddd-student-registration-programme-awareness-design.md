# DDD Refactor Sub-project 4: Student & Registration Programme-awareness Design

**Status:** Approved for planning
**Author:** Controller (Claude), approved by user 2026-08-09

## Context

This is sub-project 4 of 5 in the Programme-centered DDD academic architecture refactor (see `docs/superpowers/specs/2026-08-04-ddd-academic-refactor-phase-a-audit.md` for the full audit and decomposition). Sub-project 2 (Academic Calendar, merged) added `AcademicSession.programme_id`/`RegistrationPeriod` Programme-scoping capability but explicitly deferred the live cutover: `get_active_period()`/`activate_period()` stayed institution-wide-single-active, so Programme-scoped periods could be configured by admins but never actually changed what any student experienced. Sub-project 3 (Course/CourseOffering split, merged) kept `CourseOffering` Programme-agnostic by design, deferring Programme linkage to this sub-project. This sub-project closes both gaps.

## Current state (confirmed by codebase audit)

- `User.department_id`/`User.programme_id` (added Phase 2) are populated via dual-write but incompletely on real data: of 11 real students, 10 have `department_id` set, only 6 have `programme_id` set. `CourseOffering.department_id`: 10 of 11 offerings set.
- `services/registration.py::get_active_period()` takes no arguments and returns the single `RegistrationPeriod.query.filter_by(is_active=True)` row — used identically by every student regardless of Programme. Real call sites (all already have a `user` object in scope at the call point): `app.py:750`, `services/registration.py:106,318`, `services/notification.py:127` (`notify_registration_window_events(user)`), `services/course_history.py:9` (`get_courses_by_semester(user)`).
- `services/admin_session.py::activate_period()` deactivates every other `RegistrationPeriod` and closes every other `AcademicSession` institution-wide, with no Programme awareness — confirmed on real data: session 4 (`programme_id=3`) exists but has zero periods and is not current; all real registration activity today runs against unscoped sessions 1/2.
- `services/validation.py::validate_course_eligible` compares `course.department`/`course.level` (legacy strings) to `user.department`/`user.level` — no FK read anywhere in the live eligibility path, no Programme check exists at all today.
- `CourseOffering` has no `programme_id` column and doesn't need one — it already has `academic_session_id`, and `AcademicSession.programme_id` already exists (from sub-project 2), so a `programme` property (mirroring `RegistrationPeriod.programme` from sub-project 2) is sufficient.

## Two decisions made before design (user-confirmed)

1. **`activate_period()` is generalized to per-Programme-scope-group, not deferred again.** A "scope group" is a Programme, or `None` for the shared/legacy group. Activating a period deactivates every other period *in the same scope group* and closes every other current session *in the same scope group* — not institution-wide. Since every period today is unscoped (`programme_id=None`), and the shared/legacy group is treated identically to any real Programme's group, this preserves today's exact observable behavior for anything not yet Programme-scoped. Only a genuinely Programme-scoped period gains independent activation from other Programmes' periods.
2. **Eligibility uses a hybrid FK/string fallback**, not a strict FK-only requirement. Department: FK match (`user.department_id == offering.department_id`) when both sides have it set; otherwise fall back to today's string comparison (`user.department == offering.department`). The same mechanical rule extends to a *new* soft Programme check (`user.programme_id == offering.programme_id`, via `CourseOffering.programme`) — enforced only when both sides have `programme_id` set; skipped (not a failure) when either side is `None`. This is what "eligibility becomes Programme-aware" means for this sub-project — not a hard new requirement that would lock out the 5 students currently missing `programme_id`.

## Data model changes

### `CourseOffering` — new property, no new column

```python
@property
def programme(self):
    return self.academic_session.programme if self.academic_session else None
```
Placed immediately after `CourseOffering`'s existing relationships, mirroring `RegistrationPeriod.programme` (sub-project 2).

## Service layer changes

### `services/admin_session.py::activate_period(period_id)`

Rewritten to scope its deactivation queries to the activating period's Programme (via `period.academic_session.programme_id`, treating `None` as its own group):

```python
def activate_period(period_id):
    """The single-active-period-per-Programme-scope-group enforcement point.
    A scope group is a Programme, or None for the shared/legacy group.
    Deactivates every other RegistrationPeriod in the same scope group,
    marks this period's session current/open, and closes any other
    currently-current session in the same scope group. Periods/sessions in
    a DIFFERENT scope group are untouched — this is what lets different
    Programmes run independent registration schedules."""
    period = get_period(period_id)
    programme_id = period.academic_session.programme_id

    # Resolve the scope group's session IDs first, then filter by
    # academic_session_id.in_(...) rather than joining AcademicSession
    # directly into the RegistrationPeriod bulk .update() query — SQLAlchemy's
    # Query.update() does not reliably support joined multi-table updates,
    # so the join is deliberately avoided here (unlike get_active_period()
    # below, which only SELECTs and can join freely).
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

Neither bulk `.update()` call joins the table it's updating: `RegistrationPeriod`'s update filters via `academic_session_id.in_(<subquery>)` instead of joining `AcademicSession`, and `AcademicSession`'s own update needs no join since `programme_id` already lives on `AcademicSession` itself. This sidesteps SQLAlchemy's unreliable support for joined multi-table bulk updates entirely, rather than working around it.

### `services/registration.py::get_active_period(user=None)`

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

All 6 real call sites updated to pass their already-in-scope `user`/`current_user`.

### `services/validation.py::validate_course_eligible(course, user, period)`

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

## Explicitly out of scope

- `get_credit_limits`/`DepartmentRegistrationRule` — stay department-string-keyed. Fee/credit-rule configuration is closer to sub-project 5's territory; not touched here.
- Any change to `Course` (master) — Programme-awareness lives entirely on `CourseOffering`, per sub-project 3's design.
- Admin UI redesign for "which Programmes currently have an active period" — the existing per-row "Active" indicator on the sessions/periods admin pages already shows each period's own state; the only UI change needed is updating the activation confirm-dialog copy so it doesn't misleadingly imply "this deactivates every period institution-wide" for a Programme-scoped period.

## Testing

No automated test framework (established convention) — manual verification via throwaway `test_client`/`app_context` scripts:
1. Activate a Programme-scoped period; confirm periods/sessions in a *different* Programme (or the shared/legacy group) are untouched.
2. Activate an unscoped (legacy) period; confirm behavior is byte-for-byte identical to before this sub-project (deactivates all other unscoped periods, closes all other current unscoped sessions) — a real regression check against sub-project 2's own Task 5 verification baseline.
3. `get_active_period(user)` for a student whose Programme has its own active period returns that period, not the shared one.
4. `get_active_period(user)` for a student whose Programme has no active period (or `programme_id=None`) falls back to the shared/legacy active period.
5. `get_active_period()` (no user) returns the shared/legacy active period exactly as before.
6. Eligibility: a student/offering pair with both `department_id` set and matching → eligible. Mismatched `department_id` → rejected via the FK path. Either side missing `department_id` → falls back to string comparison, confirm both a string-match-success and string-match-failure case. Both sides have `programme_id` set and mismatched → rejected via the new Programme check. Either side missing `programme_id` → Programme check skipped, department/level checks still apply.
7. Regression: full student registration flow (add/drop, dashboard, `/registration`) for a student with complete FK data and one with incomplete FK data, confirming neither regresses versus pre-sub-project-4 behavior.
8. Regression: admin Sessions/Periods/Registration Oversight pages unaffected beyond the activation confirm-dialog copy change.

## Deliverables

1. `CourseOffering.programme` property.
2. `services/admin_session.py::activate_period()` rewritten for per-scope-group activation.
3. `services/registration.py::get_active_period(user=None)` rewritten with Programme-then-fallback resolution; all 6 real call sites updated to pass `user`.
4. `services/validation.py::validate_course_eligible()` rewritten with hybrid FK/string department matching and new soft Programme matching.
5. Activation confirm-dialog copy update (admin templates).
6. Manual verification per the Testing section above.
