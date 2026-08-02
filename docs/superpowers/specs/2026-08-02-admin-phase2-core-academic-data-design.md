# Admin Portal Phase 2 — Core Academic Data Design

**Status:** Approved for planning
**Author:** Controller (Claude), approved by user 2026-08-02

## Goal

Build the four modules that sit directly on top of the Admin Foundation milestone: Student Management, Departments, Academic Sessions & Semesters, and Course Management. Replace every mock/placeholder admin surface these touch with real backend-driven functionality, following the exact same governing pattern Admin Foundation established (flat routes under `/admin/...` in `app.py`, `@permission_required(code)` gating, function-based `services/*.py` modules, `services/admin_audit.py` logging every action).

Source: the user's pasted "STUDENT PORTAL SYSTEM - ADMIN SECTION COMPLETE DESCRIPTION" document (full admin vision, not a repo file), explicitly narrowed by the user to a "Phase 2 — Core Academic Data" milestone covering only these four modules. Registration Oversight, Bulk Operations, and Student Onboarding Management are explicitly Phase 3, out of scope here. Two supplementary documents were also provided: "STUDENT PORTAL SYSTEM - COMPLETE SYSTEM FLOW" (describes the already-shipped student-facing features; nothing new for this milestone — one stale line, "DO NOT USE Flask WTF," contradicts the actual shipped codebase which uses Flask-WTF's `CSRFProtect` throughout, and is disregarded) and "Student Programs and Study Cycles" (describes three structurally different academic calendars — see "Programme and term-cycle scope" below for how this is handled).

## Current state (confirmed by codebase audit)

- No `Department`, `Programme`, `CoursePrerequisite`, `CourseCorequisite`, `CourseAssessmentComponent`, `StudentImportJob`, `StudentImportError`, `CourseImportJob`, `CourseImportError`, or `AcademicHoliday` models exist.
- `User.department`, `User.course` ("Programme" in the UI — confirmed via `profile_display.programme` in `profile.html`/`dashboard.html`), and `Course.department` are free-text string columns, read by every already-shipped student-facing feature (onboarding, profile, registration, add/drop, course catalog, dashboard).
- `User` has no `account_status`, and no creation timestamp at all (only `updated_at`).
- `Course` has no `status`/`max_capacity`.
- `AcademicSession` has `is_current`; `Semester` is a small global lookup (name, order) shared across all sessions — not session-owned. `RegistrationPeriod` is the (session × semester) join, already carrying `opens_at`/`closes_at`/`min_credits`/`max_credits`/`registration_fee`/`is_active`.
- `DepartmentRegistrationRule` (department-specific credit/fee overrides) already exists and is reused as-is.
- Flask-Migrate is wired into `app.py` (`migrate = Migrate(app, db)`) and `migrations/` is scaffolded (`flask db init` was run) but **no migration has ever been generated or applied** — every schema change so far has been purely additive, handled by `db.create_all()`. This milestone is the first to need real `ALTER TABLE` changes.
- Admin Foundation's seeded permission catalog: `dashboard.view`, `sessions.manage`, `students.manage`, `courses.manage`, `registration.manage`, `announcements.manage`, `reports.view` — no `departments.manage` yet.
- Six permission-gated stub routes exist from Admin Foundation Task 8, rendering a generic "Coming soon" page: `admin_stub_sessions_new` (`sessions.manage`), `admin_stub_students_import` (`students.manage`), `admin_stub_courses` (`courses.manage`), `admin_stub_registration_open` (`registration.manage`), `admin_stub_announcements_new` (`announcements.manage`), `admin_stub_reports` (`reports.view`). This milestone **replaces** the first four (their sidebar/Quick-Action links must point at real routes, using the same permission codes) — the last two stay stubs (Phase 3+).
- No admin templates/CSS/JS exist yet for any Phase 2 module — "the frontend UI already exists where applicable" does not apply to these four modules; new templates are needed, styled consistently with `static/css/admin.css`/`base_admin.html`.

## Architecture

Same foundation as Admin Foundation: one Flask app, routes added flat into `app.py` under `/admin/...`, `services/*.py` are **function-based modules** (not classes — the pasted spec calls for "StudentService," "DepartmentService," etc., but every existing service in this codebase — `services/registration.py`, `services/course.py`, `services/payment.py` — is a plain module of functions, not a class; this design follows that established convention rather than introducing a new style). `services/admin_audit.py`'s existing `log_admin_action(...)` is reused for every new action — no new "AuditService" module, since one already exists and does exactly this job.

### Data model

Two migration categories:

**A. New, purely additive tables** (`db.create_all()`-compatible, no `ALTER TABLE`):

```python
class Department(db.Model):
    __tablename__ = 'departments'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    faculty = db.Column(db.String(150), nullable=True)
    head_name = db.Column(db.String(150), nullable=True)   # placeholder text field, no AdminUser/User FK
    status = db.Column(db.String(20), nullable=False, default='active')  # active/inactive/archived
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)

class Programme(db.Model):
    __tablename__ = 'programmes'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)   # "National Diploma", "International Diploma", ...
    code = db.Column(db.String(20), unique=True, nullable=False)
    program_type = db.Column(db.String(20), nullable=False)         # 'international' / 'nd' / 'hnd'
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='active')
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)

class CoursePrerequisite(db.Model):
    __tablename__ = 'course_prerequisites'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    prerequisite_course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('course_id', 'prerequisite_course_id'),)

class CourseCorequisite(db.Model):
    __tablename__ = 'course_corequisites'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    corequisite_course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('course_id', 'corequisite_course_id'),)

class CourseAssessmentComponent(db.Model):
    __tablename__ = 'course_assessment_components'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)     # "Exam", "Assignment", "Project"
    weight_percent = db.Column(db.Integer, nullable=False)

class AcademicHoliday(db.Model):
    __tablename__ = 'academic_holidays'
    id = db.Column(db.Integer, primary_key=True)
    academic_session_id = db.Column(db.Integer, db.ForeignKey('academic_sessions.id'), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    starts_on = db.Column(db.Date, nullable=False)
    ends_on = db.Column(db.Date, nullable=False)

class StudentImportJob(db.Model):
    __tablename__ = 'student_import_jobs'
    id = db.Column(db.Integer, primary_key=True)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_users.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='processing')  # processing/completed/failed
    created_count = db.Column(db.Integer, nullable=False, default=0)
    updated_count = db.Column(db.Integer, nullable=False, default=0)
    skipped_count = db.Column(db.Integer, nullable=False, default=0)
    duplicate_count = db.Column(db.Integer, nullable=False, default=0)
    error_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)

class StudentImportError(db.Model):
    __tablename__ = 'student_import_errors'
    id = db.Column(db.Integer, primary_key=True)
    import_job_id = db.Column(db.Integer, db.ForeignKey('student_import_jobs.id'), nullable=False)
    row_number = db.Column(db.Integer, nullable=False)
    raw_row = db.Column(db.Text, nullable=False)   # JSON-encoded original row, for admin review/re-upload
    reason = db.Column(db.String(300), nullable=False)

# CourseImportJob / CourseImportError: identical column shape to the Student pair
# above (job carries the same 5 counters, error carries row_number/raw_row/reason).
# Only the validation rules that populate `reason` differ, and are course-specific:
# duplicate code, invalid department, missing credits, invalid semester.
```

**B. Small, additive `ALTER TABLE` changes to three existing tables** (first real use of this repo's Flask-Migrate setup — generated via `flask db migrate`, reviewed by hand before applying, per Alembic's normal workflow):

1. `users`: add `department_id` (nullable FK → `departments.id`), `programme_id` (nullable FK → `programmes.id`), `account_status` (`String(20)`, `default='active'`, `nullable=False`), `created_at` (`DateTime`, nullable — backfilled to `now_lagos()` for existing rows in the same migration's data step, since "enrollment date" filtering needs it and none exists today).
2. `courses`: add `department_id` (nullable FK → `departments.id`), `status` (`String(20)`, `default='active'`, `nullable=False`), `max_capacity` (nullable `Integer`).
3. `registration_periods`: add `late_registration_ends_at` (nullable `DateTime`), `late_registration_fee` (nullable `Numeric(10,2)`), `exam_starts_at`/`exam_ends_at` (nullable `DateTime`), `result_release_at` (nullable `DateTime`) — the fields the pasted spec calls for under "Semesters" (see Academic Sessions & Semesters module below for why these live on `RegistrationPeriod` rather than a session-owned `Semester`).
4. `academic_sessions`: add `start_date`/`end_date` (nullable `Date`) and `status` (`String(20)`, `default='draft'`; values `draft`/`open`/`closed`/`archived`) — the milestone explicitly requires "Each session contains: Academic Year, Start Date, End Date, Status," which the existing `id`/`name`/`is_current` columns don't cover. `status` is distinct from `is_current`: `status` tracks the session's own lifecycle (a session can be `closed` or `archived` without another session having taken over `is_current` yet), while `is_current` is still the single source of truth for "which one session is active right now," enforced the same app-side way described in migration item 3's module section below.

All four are handled by one `flask db migrate` + hand-reviewed migration file, run once against `main`'s dev DB. None of them are destructive — every new column is nullable or has a server-side default, so existing rows never lose data.

A one-time backfill script (run once, part of the migration or a follow-up data script, not committed as a throwaway) does three things: (a) collects every distinct existing `User.department`/`Course.department` string value and creates one `Department` row per distinct value, generating a `code` by slugifying the name (uppercased, truncated, de-duplicated with a numeric suffix on collision); (b) sets `department_id` on every existing `User`/`Course` row by matching its string value to the new `Department.name`; (c) leaves `programme_id` `NULL` for all existing rows (no reliable source data to backfill from — `User.course` today holds arbitrary free text, not one of the three defined program types) with a printed report at migration end listing how many rows still need a manual admin follow-up.

**Every existing student-facing read path keeps reading the legacy string columns (`department`, `course`) unchanged.** Going forward, admin-driven create/edit in the new Student/Department/Course Management UI writes both the FK and the legacy string field, so nothing downstream needs to change.

### Programme and term-cycle scope

The "Student Programs and Study Cycles" document describes three structurally different academic calendars (a 3-term International Program vs. annual-rotation ND/HND), which the current schema — and this milestone's own deliverable list — doesn't model at all. Per the user's explicit decision: `Programme` is added now as **structured metadata only** (name, code, `program_type`, description, status) for association and filtering, replacing the free-text-only `User.course`. Building actual per-program-type term-cycle registration logic (making `RegistrationPeriod` program-aware) is **not** part of this milestone — it's flagged under Deferred below. `Programme` captures the qualification track (e.g. "National Diploma," "International Diploma"); year/stage (ND1 vs ND2) continues to be represented by the existing `User.level` string field, unchanged. `Course` does not get a `programme_id` — the milestone's course fields don't include Programme, and course eligibility is already keyed off department.

### Permissions

New permission code `departments.manage`, granted to **both** seeded roles (Super Administrator and Academic Administrator) — the pasted RBAC doc explicitly lists "Departments" under both roles' descriptions. `students.manage`, `courses.manage`, `sessions.manage`, `registration.manage` already exist in the seeded catalog and are reused unchanged for the routes below.

## Module designs

### Departments (`/admin/departments`, permission `departments.manage`)

- `GET /admin/departments` — directory: search by name/code, filter by status, pagination.
- `GET/POST /admin/departments/new`, `GET/POST /admin/departments/<id>/edit`.
- `POST /admin/departments/<id>/activate|deactivate|archive`.
- `GET /admin/departments/<id>` — detail: student count and course count computed via the `department_id` FK (falls back to 0 for any legacy row the backfill couldn't match).
- `services/admin_department.py`: `list_departments(filters)`, `create_department(...)`, `update_department(...)`, `set_department_status(...)`, `get_department_detail(id)`.
- Duplicate-code prevention: a uniqueness check in `services/admin_validation.py`, shared with Course's code-uniqueness check.

### Academic Sessions & Semesters (`/admin/sessions`)

- `GET /admin/sessions` — list (name, start/end date, status, current indicator), `sessions.manage`.
- `GET/POST /admin/sessions/new`, `GET/POST /admin/sessions/<id>/edit` — sets `name` (academic year, e.g. "2026/2027"), `start_date`, `end_date`. New sessions start `status='draft'`. `POST /admin/sessions/<id>/archive` sets `status='archived'` (only allowed once a session is no longer `is_current`). `sessions.manage`. This replaces `admin_stub_sessions_new`.
- `POST /admin/sessions/<id>/clone` — creates a new `draft` session and clones its `RegistrationPeriod` configs (credit limits, fees, department overrides) as a starting template; dates are never copied, admin must set new ones — `sessions.manage`.
- Within a session, manage its `RegistrationPeriod` rows — this is what the pasted spec calls "Semesters." `Semester` itself stays the existing global lookup (`First Semester`/`Second Semester`); `RegistrationPeriod` is the actual per-session-semester config object, and already existed before this milestone — extending it (migration item 3) is far lower-risk than restructuring `Semester` to be session-owned, which would ripple through `Course.semester_id`, `RegisteredCourse`, and `DepartmentRegistrationRule`, all frozen student-facing code. Routes: `GET/POST /admin/sessions/<id>/periods/new`, `GET/POST /admin/sessions/<sid>/periods/<pid>/edit` — `sessions.manage`.
- `POST /admin/sessions/<sid>/periods/<pid>/activate` — `registration.manage` (this is what the existing "Open Registration" Quick Action maps to, replacing `admin_stub_registration_open`). Deactivates every other `RegistrationPeriod`; marks the period's parent session `is_current=True` and `status='open'`, deactivating/closing other sessions (`is_current=False`; any session losing `is_current` this way that was `'open'` becomes `'closed'`) — this is how "only one session and one semester active at a time" is enforced, app-side (matches this codebase's existing style — no DB-level partial-unique constraint).
- `RegistrationPeriod` gains the new nullable fields listed under migration item 3 above (`late_registration_ends_at`, `late_registration_fee`, `exam_starts_at`, `exam_ends_at`, `result_release_at`).
- Holiday periods: simple CRUD on `AcademicHoliday`, scoped to a session — `sessions.manage`.
- `services/admin_session.py`: `list_sessions()`, `create_session(...)`, `update_session(...)`, `archive_session(...)`, `clone_session(...)`, `create_period(...)`, `update_period(...)`, `activate_period(...)` (the enforcement function), `list_holidays(session_id)`, `create_holiday(...)`.

### Course Management (`/admin/courses`, permission `courses.manage`)

- `GET /admin/courses` — catalog: search (code/title/description), filter (department/level/semester/credit range/status), sort, paginate. Replaces `admin_stub_courses`.
- `GET/POST /admin/courses/new`, `GET/POST /admin/courses/<id>/edit`.
- `POST /admin/courses/<id>/deactivate` (hides for current offering, `status='inactive'`, reversible) vs. `POST /admin/courses/<id>/archive` (`status='archived'`, permanent retirement, history preserved — matches the spec's explicit distinction between "deactivate for a semester" and "archive outdated").
- `GET /admin/courses/<id>` — detail: prerequisites/corequisites, assessment components. Registration analytics per course is explicitly Phase 3 (Registration Oversight) — not built here.
- `POST /admin/courses/<id>/prerequisites`, `POST /admin/courses/<id>/corequisites`, `POST /admin/courses/<id>/assessment` — manage the respective child rows.
- `GET /admin/courses/import`, `POST /admin/courses/import` — CSV upload, validating duplicate codes (within file and against the existing `UniqueConstraint('code', 'academic_session_id', 'semester_id')`), invalid department (must resolve to an existing `Department`), missing credits, invalid semester (must match an existing `Semester.name`). Produces a `CourseImportJob` + per-row `CourseImportError` rows and a summary page.
- Timetable allocation and lecturer assignment: visible but inert placeholder fields on the course form. `Course.instructor`/`Course.schedule` already exist and are already *displayed* to students in the course-details modal (`app.py`'s `/add_drop/data` handler, ~line 840) but have never had an admin-facing way to be set — this milestone finally gives admins a form field for them, with no new columns needed. They stay simple text inputs (no real timetable/scheduling system) per the "leave as placeholders" instruction.
- `services/admin_course.py`: `list_courses(filters)`, `create_course(...)`, `update_course(...)`, `set_course_status(...)`, `get_course_detail(id)`, `set_prerequisites(...)`, `set_corequisites(...)`, `set_assessment_components(...)`.

### Student Management (`/admin/students`, permission `students.manage`)

- `GET /admin/students` — directory with every listed filter (reg no., name, department, programme, level, semester, status, enrollment date range), sort, pagination, bulk-select checkboxes. Replaces `admin_stub_students_import`'s link target (the sidebar "Students" nav item points here now; CSV import gets its own sub-route below).
- `GET /admin/students/<id>` — profile: Personal Information, Academic Information, Registration History (reuses `services/registration.py`'s existing history query), Course History (reuses `services/course_history.py`), Payment History (reuses `services/payment.py`), Activity Log (existing `AuditLog` rows for that user), Support Tickets (literal "Not yet available" placeholder card, no ticket system exists — matches the dashboard's established pattern for the same gap).
- `GET/POST /admin/students/<id>/edit` — admin override of personal/academic fields. No per-field authorization tiers (out of scope, see below) — the whole edit action is gated by `students.manage` like everything else.
- `POST /admin/students/<id>/activate|suspend|deactivate` — sets `account_status`; suspended/deactivated block student login (one narrow, necessary edit to the shared login check in `auth_helpers.py`/`app.py`'s `login()` route, inserted right after `user.check_password(password)` succeeds and before `login_user(...)`).
- `POST /admin/students/<id>/reset-password` — reuses the existing password-hashing/`first_login=True` mechanism (same pattern as seeded default-password accounts).
- `POST /admin/students/<id>/resend-verification` — reuses `onboarding_helpers`'s existing OTP session mechanism.
- `GET/POST /admin/students/new` — manual individual creation.
- `GET /admin/students/import`, `POST /admin/students/import` — CSV upload; `GET /admin/students/import/<job_id>` — report page (counts + downloadable per-row error detail).
- `GET /admin/students/import/admission-portal` — permission-gated "not yet available" page (reuses the existing `coming_soon.html` pattern), backed by `services/admission_portal_service.py`: a clean interface with one method, `fetch_admitted_students(session_id)`, raising `NotImplementedError` with a `# TODO` describing the real integration — no external API call implemented.
- `POST /admin/students/bulk-status` — the one bulk action built in this phase (activate/suspend/deactivate multiple students at once — a direct N-repeat of the already-designed single-student action). Bulk email, bulk export, and bulk course registration are explicitly Phase 3.
- CSV import semantics (my definitions, since the spec names five report categories without defining them): **Created** = new `reg_no`; **Updated** = existing `reg_no` with ≥1 changed field among name/department/programme/level/semester/session/demographics (never password or an already-verified email, to avoid accidentally locking out a mid-onboarding student); **Skipped** = existing `reg_no`, no field actually differs from the CSV; **Duplicates** = the same `reg_no` appears more than once *within the uploaded file* (only the first occurrence is processed); **Errors** = row fails validation, reason recorded per-row in `StudentImportError`.
- `services/admin_student.py`: `list_students(filters)`, `create_student(...)`, `update_student(...)`, `set_account_status(...)`, `reset_student_password(...)`, `resend_verification(...)`, `get_student_profile(id)`, `bulk_set_status(ids, status)`.
- `services/admin_import.py`: shared CSV-parsing/row-iteration/report-building helpers used by both student and course import (header validation, row dict iteration, `ImportJob`/`ImportError` persistence helpers parameterized by model).
- `services/admin_validation.py`: shared validators — department/course code uniqueness, department/programme/semester reference validity, credit-range checks — used across all four modules' create/edit/import paths.

## Explicitly out of scope for this milestone

Present in the fuller pasted document but not in the user's Phase 2 deliverable list, or requiring changes to already-shipped/frozen student-facing modules: merging duplicate student records, manually editing grades (`RegisteredCourse.grade` stays unset, as it has been since Feature 5&6), per-field edit-authorization tiers on the student profile, per-program-type term-cycle registration logic (flagged above), full Bulk Operations (bulk email/export/course-registration — only bulk status-change ships now), Registration Oversight (monitoring dashboard, individual registration overrides, add/drop period admin config), Student Onboarding Management dashboard (completion-rate tracking, reminder sending), admin MFA / 12-char password policy / progressive lockout (already an accepted, previously-approved Admin Foundation exclusion), real-time WebSocket activity feed, charts/analytics, Support Tickets, Payments admin UI, Reports.

## Testing

No automated test suite in this repo (established convention) — verification is manual, throwaway `test_client`/`app_context` scripts, never committed. Covers: student search/filtering, profile view, manual creation, CSV import (including a deliberately malformed CSV to exercise the error path), department CRUD, session CRUD, period/holiday CRUD, active-session-enforcement (activating one deactivates all others), course CRUD, course import, and audit logging (one `AdminAuditLog` row per action type across all four modules).

## Deliverables

1. Audit all Phase 2 admin pages (this document's "Current state" section).
2. Replace mock/stub data with real backend functionality across all four modules.
3. Implement Student Management, Department Management, Academic Sessions & Semesters, Course Management as designed above.
4. Build the services and validation layer described above.
5. Update `DEVELOPMENT_PROGRESS.md` with a new "Phase 2: Core Academic Data" entry, matching the existing entries' format.
6. Stop and wait for approval before beginning Phase 3 (Registration Oversight, Bulk Operations, Student Onboarding Management).
