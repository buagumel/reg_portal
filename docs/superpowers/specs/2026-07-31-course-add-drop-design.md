# Course Add/Drop + My Courses — Design Spec

Date: 2026-07-31
Status: Approved
Scope: Replace the mocked `add_drop.html` and `my_courses.html` pages with a real, database-driven course registration workflow (Features 5 & 6): browsing/adding/dropping courses against an active `StudentRegistration`, submitting the final selection, printing a registration slip, and viewing course history grouped by session/semester with a course-details view.

## Goal

Turn Add/Drop and My Courses into real features backed by a `Course` catalog and `RegisteredCourse` selections, completing the workflow Feature 4 (Semester Registration) started: pay → select courses → submit → see them in My Courses.

## Audit findings (baseline)

- `add_drop()` and `my_courses()` in `app.py` both lack `@login_required` (same bug class fixed on `dashboard`, `profile`, and `registration` in prior milestones). Fixed here since both routes are being rewritten.
- `add_drop.html` is fully client-rendered: a hardcoded `allCourses` JS array, `registeredCourses` kept only in a JS variable (lost on refresh), and `submitRegistration()` just shows a toast — no backend call at all.
- `my_courses.html` has no JS/dynamic behavior whatsoever — pure static HTML mock (stats, course tables, semester groupings all hardcoded). No "View Details" implementation exists (the buttons are inert `<button>` elements with no handler).
- No `Course` model exists. `StudentRegistration.credits_registered` exists (added in Feature 4) but is always `0` — its own code comment says it's "populated by future Add/Drop milestone," i.e. this one.

## Architectural decision: two different integration styles

`add_drop.html`'s existing architecture is "JS array → render functions" — Add/Drop/Submit are just array mutations today. The least invasive way to honor "keep the UI exactly as it is" is to **keep that architecture** and replace only the data source and the mutating actions: fetch real data on load, and turn Add/Drop/Submit into real API calls whose responses re-drive the same render functions. This is not a rewrite into server-side Jinja — it's the JS mock's own approach, made real.

`my_courses.html` has no JS to preserve — it's a static mock, structurally identical to what `registration.html` was before Feature 4. It gets the same treatment Feature 4 used: server-rendered Jinja loops over real query results, keeping the existing markup/CSS as-is.

## Data model (`models.py`)

```python
class Course(db.Model):
    __tablename__ = 'courses'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), nullable=False)          # e.g. "CSC 310"
    title = db.Column(db.String(200), nullable=False)
    credits = db.Column(db.Integer, nullable=False)
    department = db.Column(db.String(150), nullable=False)   # matches User.department
    level = db.Column(db.String(50), nullable=True)           # matches User.level; NULL = level-agnostic
    course_type = db.Column(db.String(20), nullable=False)    # 'core' | 'elective' | 'lab' — matches existing filter buttons
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
    grade = db.Column(db.String(5), nullable=True)   # e.g. "A", "B+" — never set by this milestone; My Courses shows a placeholder when NULL
    added_at = db.Column(db.DateTime, default=now_lagos, nullable=False)

    __table_args__ = (db.UniqueConstraint('student_registration_id', 'course_id'),)

    course = db.relationship('Course')
    student_registration = db.relationship('StudentRegistration', backref='registered_courses')
```

Extend `StudentRegistration` with one new column:
```python
courses_submitted = db.Column(db.Boolean, default=False, nullable=False)
```
`credits_registered` (already present) is kept in sync — recomputed and saved on every add/drop.

Assessment Breakdown is **not** a DB column: the spec frames it as always-placeholder content, so the course-details view renders a static "Assessment breakdown not yet available" string rather than inventing a fake structured data source for it.

No Alembic migration (established convention — `db.create_all()`).

## Business rules

- **Eligibility**: a course is addable only if `course.department == student.department` and (`course.level == student.level` or `course.level is None` — level-agnostic, covering International-program students whose own `level` is `None`) and it belongs to the currently active `RegistrationPeriod`'s session/semester.
- **Credit ceiling**: adding a course must not push `credits_registered` over the max resolved via Feature 4's existing `get_credit_limits(period, department)` — reused, not reimplemented.
- **Duplicate prevention**: DB `UniqueConstraint('student_registration_id', 'course_id')` + an explicit pre-check for a clean error message, mirroring Feature 4's duplicate-registration pattern (including the `IntegrityError` → clean-error safety net for the race case).
- **Submission finalization**: `submit` requires the registration window still open, `payment_status == 'paid'`, `credits_registered` within `[min_credits, max_credits]`, at least one course selected, and `courses_submitted == False` (not already finalized). On success, sets `courses_submitted = True`; all further add/drop/submit calls for that registration are rejected server-side afterward — the UI additionally disables the controls, but the server check is what actually enforces it.
- **No active registration**: if the student has no `StudentRegistration` for the active period (hasn't completed Feature 4's Register Now yet) or no active period exists at all, `/add_drop` redirects to `/registration` — Add/Drop only makes sense after payment, matching the workflow doc's step ordering (pay → select courses).

## Service layer

Following the existing functional-module style (`services/registration.py`, `services/student_profile.py` — plain functions, not class-based "Service" objects), organized by responsibility:

**`services/course.py`** (CourseService equivalent)
- `get_available_courses(user, period, search=None, course_type=None)` — courses matching the eligibility rule above, minus ones already in the student's `RegisteredCourse` set, with optional search (code/title substring) and type filter.
- `get_course_details(course_id)` — single course for the details view.

**`services/validation.py`** (ValidationService equivalent — pure checks, no DB writes)
- `validate_course_eligible(course, user, period)` — raises `RegistrationError` (reusing Feature 4's exception type — one error vocabulary for the whole registration domain) if department/level/session/semester don't match.
- `validate_credit_ceiling(current_credits, course_credits, max_credits)` — raises if it would overflow.
- `validate_not_duplicate(student_registration, course)` — raises if already registered.
- `validate_can_submit(student_registration, period)` — raises if window closed, unpaid, credits out of range, no courses, or already submitted.

**`services/registration.py`** (extended — RegistrationService)
- `add_course(user, period, course_id)` — runs the validators above, creates `RegisteredCourse`, recomputes+saves `credits_registered`, returns the updated registration state.
- `drop_course(user, registration, course_id)` — removes the row, recomputes+saves `credits_registered`.
- `submit_registration(user, registration)` — runs `validate_can_submit`, sets `courses_submitted = True`, commits.
- `get_add_drop_context(user)` — assembles everything `/add_drop`'s data endpoint needs: period, registration, resolved credit limits, `courses_submitted` flag.

**`services/course_history.py`** (CourseHistoryService equivalent)
- `get_courses_by_semester(user)` — all of the student's `RegisteredCourse` rows across every `StudentRegistration`, grouped by `(academic_session, semester)`, newest first, each group tagged `is_current` (matches the active period) for the expand/collapse default.

## Routes (`app.py`)

- `GET /add_drop` — `@login_required` (bug fix). Redirects to `/registration` if no eligible `StudentRegistration` exists for the active period. Otherwise renders `add_drop.html` (page shell only — no course data in the initial render, matching the "keep the JS-driven architecture" decision).
- `GET /add_drop/data` — `@login_required`, JSON. Returns everything the page needs on load: session/semester names, deadline, min/max credits, `courses_submitted`, available courses, currently selected courses, running credit total.
- `POST /add_drop/add` — `@login_required`, JSON body `{course_id}`. Calls `add_course`, returns the updated selection + totals, or a 400 with a clean message on any `RegistrationError`.
- `POST /add_drop/drop` — `@login_required`, JSON body `{course_id}`. Calls `drop_course`, returns updated state.
- `POST /add_drop/submit` — `@login_required`. Calls `submit_registration`; on success returns `{success: true, redirect: url_for('my_courses')}`.
- `GET /registration/slip` — `@login_required`. Renders a print-friendly page (own minimal template, `window.print()` pattern already used in `payments_history.html` — no new dependency) showing the student's submitted registration + course list. Redirects to `/registration` with an explanatory message if the student has no submitted registration to show.
- `GET /my_courses` — `@login_required` (bug fix). Server-renders grouped course history via `get_courses_by_semester`.
- `GET /courses/<id>/details` — `@login_required`, JSON, for the course-details modal (used only from My Courses' "View" buttons). Returns 404 unless the requested course is one the requesting student has an actual `RegisteredCourse` row for — this authorization check is deliberately narrow (not "any course in the catalog") since the only UI entry point is a student's own course history.

## UI

**`add_drop.html`** — markup/CSS untouched. The existing `<script>` block is rewritten (same function names/shapes where possible) to: fetch `/add_drop/data` on load instead of using a hardcoded array; `addCourse`/`dropCourse` become `async` functions calling the new POST endpoints and re-rendering from the response instead of mutating a local array; `submitRegistration` calls `/add_drop/submit`, and on success opens `/registration/slip` in a new tab (`window.open(..., '_blank')`) then redirects the current page to `/my_courses`. When `courses_submitted` is true on load, Add/Drop/Submit controls render disabled (mirroring how Feature 4 disabled Register Now based on state) and a toast explains why if a disabled action is somehow triggered.

**`my_courses.html`** — markup/CSS untouched structurally; the hardcoded stat numbers and the three hardcoded `.semester-category` blocks are replaced with Jinja loops over `get_courses_by_semester(user)` groups. Each group renders as a `<details>` element (open for the `is_current` group, closed otherwise) styled to match the existing `.semester-category`/`.semester-title` look — native HTML for the expand/collapse behavior instead of new JS, since the mock currently has none to preserve. Each course row's "View"/"Review" button gets a click handler (small new inline script, since none existed before) that fetches `/courses/<id>/details` and renders the course-details modal (new, minimal, styled consistently with the rest of the app's hand-rolled components — no third-party modal library).

**Course-details modal** — new. Shows description, department, credits, semester, instructor, schedule (each falling back to a "Not available" placeholder when unset), and a static "Assessment breakdown not yet available" line.

**Registration slip (`/registration/slip`)** — new minimal template: student info, session/semester, submitted course list with credits, total credits, a "Print" button (`window.print()`), print-oriented CSS (`@media print`) hiding navigation chrome, consistent with `payments_history.html`'s existing print pattern.

## Demo data (`seed_dev_data.py`)

Extend, idempotently:
- ~8 `Course` rows for the active `RegistrationPeriod`'s session/semester, split across the two seeded departments ("Computer Science", "Information Technology"), covering `core`/`elective`/`lab` types, at least one with `level=None` (level-agnostic, to exercise the International-student path), most with `instructor`/`schedule` set and at least one left `NULL` to exercise the placeholder path.
- No pre-seeded `RegisteredCourse` rows — Add/Drop's "draft persists across refresh" behavior is best demonstrated by actually adding a course through the flow during verification, not by seeding one in a state that might not match a fresh checkout's active period.

## Testing approach

Manual verification via `test_client`, per established project convention (no automated test framework in this repo), covering the deliverables' checklist: add course, remove course, credit validation (both under-min at submit time and over-max at add time), duplicate prevention, persistence across a simulated "refresh" (re-fetch `/add_drop/data` and confirm the prior selection is still there), submit (including its business-rule rejections: window closed, unpaid, already submitted), My Courses reflecting the submission, and the registration slip rendering with the right course list and total.

## Out of scope

- Grading (the `grade` column exists but nothing in this milestone ever sets it).
- Real PDF generation for the registration slip (browser print only, matching the existing `payments_history.html` pattern).
- Editing/removing courses after submission (the whole point of `courses_submitted` is to lock the selection — a future "late add/drop window" feature, if ever needed, is separate).
- Admin UI for managing the `Course` catalog — seed-script-only, matching Feature 4's precedent for `RegistrationPeriod` configuration.
