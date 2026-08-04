# DDD Refactor Sub-project 2: Academic Calendar Design

**Status:** Approved for planning
**Author:** Controller (Claude), approved by user 2026-08-04

## Context

This is sub-project 2 of 5 in the Programme-centered DDD academic architecture refactor (see `docs/superpowers/specs/2026-08-04-ddd-academic-refactor-phase-a-audit.md` for the full audit and decomposition). Sub-project 1 (merged, `726f64f`) related `Programme` and `Department` and added `Programme.uses_semesters`/`uses_terms`/`duration`. This sub-project gives `AcademicSession` (and transitively `RegistrationPeriod`) an optional Programme scope, and enables term-based academic cycles — without changing any live, student-facing registration behavior. That cutover is explicitly deferred to sub-project 4 (Student & Registration Programme-awareness).

## Current state (confirmed by codebase audit)

- `AcademicSession` (`models.py:106`): flat, global — `id, name (unique), is_current, start_date, end_date, status`. Not Programme-scoped.
- `Semester` (`models.py:116`): flat, global lookup — `id, name (unique), order`. No discriminator between "semester" and "term" naming.
- `RegistrationPeriod` (`models.py:123`): `academic_session_id, semester_id, opens_at, closes_at, ...`. Not Programme-scoped.
- `services/registration.py::get_active_period()` returns the single `RegistrationPeriod` with `is_active=True` — used by every student regardless of Programme. `services/admin_session.py::activate_period()` is the single-active-session-and-period enforcement point: activating one period deactivates every other period and closes every other session, institution-wide, with no Programme awareness.
- `User.session` is a free-text string, not an FK to `AcademicSession` — unrelated to this sub-project's scope (that's sub-project 4).

## Two decisions made before design (user-confirmed)

1. **Schema only, cutover deferred.** This sub-project adds the Programme-scoping schema and admin UI capability. `get_active_period()`/`activate_period()` are NOT touched — there is still exactly one globally-active period after this sub-project merges, exactly as today. Admins can create and configure Programme-scoped sessions/periods, but the live student registration flow keeps reading the single global active period until sub-project 4 rewires it.
2. **No new Term model.** `Semester` is reused for term-based cycles via a new `period_type` discriminator column, rather than introducing a parallel first-class `Term` entity that would largely duplicate `Semester`'s CRUD/validation logic.

## Data model changes

### `AcademicSession` — new column + constraint change

- `programme_id` (Integer, `db.ForeignKey('programmes.id')`, nullable=True). Existing rows keep `programme_id=NULL` — meaning "legacy/shared, applies across programmes," exactly today's behavior.
- Unique constraint changes from `name` (unique=True on the column) to a table-level `UniqueConstraint('name', 'programme_id')`. This works cleanly with NULLs (SQL treats each NULL as distinct in a unique constraint), so legacy sessions stay effectively globally unique in practice (there's only ever one or two), while Programme-scoped sessions can share a label like "2026/2027" across different Programmes — per the original request's own HND/International Diploma example.
- New relationship: `AcademicSession.programme` (`db.relationship('Programme')`).

### `Semester` — new column

- `period_type` (String(20), `nullable=False`, `default='semester'`, `server_default='semester'`). Existing rows backfill to `'semester'`. Migration seeds three new rows: "Term 1"/"Term 2"/"Term 3" (`order=1,2,3`, `period_type='term'`).

### `RegistrationPeriod` — no new column

Deliberately does NOT get its own `programme_id`. Its Programme is always the one inherited transitively from `academic_session_id` — adding a second, independently-settable FK here would be a drift risk (the two could disagree) with no benefit, since a period's session already determines its Programme. A read-only Python property is added instead:
```python
@property
def programme(self):
    return self.academic_session.programme if self.academic_session else None
```

## Services (`services/admin_session.py`)

- `create_session(name, start_date, end_date, programme_id=None)` — new optional parameter, default `None` preserves existing callers' behavior exactly.
- `update_session(session_id, name, start_date, end_date, programme_id=None)` — same.
- `list_sessions(programme_id=None)` — new optional filter parameter; `None` (default) returns everything, matching today's behavior exactly.
- New `list_semesters_for_programme(programme)`: returns `Semester` rows filtered by `period_type` — if `programme` is `None` or has neither flag meaningfully set, return all Semester rows (today's behavior, used when no Programme is selected in the period form); if `programme.uses_terms`, return rows with `period_type='term'`; if `programme.uses_semesters`, return rows with `period_type='semester'`; if both flags are true, return both types combined.
- `create_period`/`update_period`: no signature change — a period's Programme is always derived from its `academic_session_id`, never set directly (matches the "no second FK" decision above).

## Admin UI

Extends the existing Sessions module (no new module, unlike sub-project 1's Programme Management):

- `templates/admin/session_form.html`: gains an optional "Programme" `<select>` (blank option = legacy/shared, matching existing behavior for every current session).
- `templates/admin/sessions.html`: gains a Programme column, and a Programme filter alongside the existing status filter.
- Registration Period form: gains a read-only display of the Programme inherited from the selected session (not independently settable, per the "no second FK" decision). The Semester `<select>` in this form now calls `list_semesters_for_programme(session.programme)` instead of listing every Semester unconditionally, so a term-based Programme's period form only offers Term rows (and vice versa); a legacy/unscoped session continues to offer every Semester row, unchanged from today.

## Explicitly out of scope for this sub-project

- `get_active_period()`, `activate_period()`, and any live student-facing registration/eligibility logic — untouched, per decision 1 above. This means after this sub-project merges, Programme-scoped sessions/periods can be created and configured by admins but do not yet change what any student actually experiences.
- `User.session` and any Student/Registration Programme-awareness — sub-project 4's scope.
- `Course`/`CourseOffering` — sub-project 3's scope.
- `FeeStructure` — sub-project 5's scope.

## Testing

No automated test framework (established convention) — manual verification via a throwaway `test_client`/`app_context` script:
1. Create a Programme-scoped `AcademicSession` named "2026/2027" under Programme A, then create another `AcademicSession` also named "2026/2027" under Programme B — both succeed (constraint is per-programme, not global).
2. Confirm attempting to create a second session named "2026/2027" under Programme A (same name, same programme) correctly fails as a duplicate.
3. Confirm the existing legacy session(s) with `programme_id=NULL` still activate/deactivate exactly as before — `activate_period()` behavior is completely unchanged.
4. Confirm `list_semesters_for_programme` returns only Term rows for a `uses_terms=True` Programme, only Semester rows for a `uses_semesters=True` Programme, and all rows when no Programme is passed.
5. Regression: existing Sessions/Periods admin pages and the student-facing `/registration` and dashboard flows are entirely unaffected — verify by walking through registration as a seeded student before and after this change.

## Deliverables

1. Migration: `AcademicSession.programme_id` + constraint change, `Semester.period_type` + backfill + 3 new Term rows.
2. Service layer changes in `services/admin_session.py` (optional-parameter additions, new `list_semesters_for_programme`).
3. Admin UI: Programme selector on the session form, Programme column/filter on the sessions list, filtered Semester dropdown on the period form.
4. Manual verification per the Testing section above.
