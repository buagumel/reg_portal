# Admin Portal Phase 3 — Academic Operations Design

**Status:** Approved for planning
**Author:** Controller (Claude), approved by user 2026-08-03

## Goal

Build the three modules Phase 2's own spec flagged as explicitly out of scope: Registration Oversight, Bulk Student Operations, and Student Onboarding Management. Replace every remaining mock/placeholder surface these touch with real backend-driven functionality, following the exact governing pattern established in Admin Foundation and Phase 2 (flat routes under `/admin/...` in `app.py`, `@permission_required(code)` gating, function-based `services/*.py` modules, `services/admin_audit.py` logging every action, templates extending `templates/admin/base_admin.html` with the established inline-`style` convention).

Source: the user's "Admin Workflow" document (the pasted "STUDENT PORTAL SYSTEM - ADMIN SECTION COMPLETE DESCRIPTION," sections 6, 3.3, 3.4), narrowed and made concrete by a detailed Phase 3 requirements message covering three modules, followed by eight rounds of scoping questions resolved with the user (recorded below).

## Current state (confirmed by codebase audit)

- `Course.max_capacity` exists (Phase 2) but nothing enforces it — `services/registration.py`'s `add_course` never checks it. "Allow authorized overrides beyond capacity" is meaningless without real enforcement to override.
- OTP codes (`onboarding_helpers.py`) live only in the Flask session (`email_verification_code`/`_expiry`/`_attempts`) — nothing is ever written to the database on send/verify/fail. No durable OTP history exists or has ever existed.
- `User` has no `last_login_at` — only `AdminUser` tracks logins. `User` also has no `onboarding_completed_at` — `onboarding_completed` is a boolean with no timestamp of when it flipped.
- `RegistrationPeriod` has a single `opens_at`/`closes_at` window; `add_course`/`drop_course` both gate on `get_window_status(period) == 'open'` — there is no separate Add/Drop window distinct from the main registration window.
- `StudentRegistration` has no lock flag and no per-student deadline override — every student in a period shares exactly the same window, enforced identically.
- RBAC is entirely permission-code-based (`services/admin_permission.py`'s `has_permission`/`permission_required`) — there is no existing hardcoded-role-name check anywhere in the codebase, and Super Administrators can already create custom roles, so a Super-Admin-only action needs its own permission code, not a role-name comparison.
- `services/admin_student.py` (Phase 2) already has `create_student`, `update_student`, `set_account_status`, `bulk_set_status`, `reset_student_password`, `resend_verification` — Bulk Student Operations extends this, not a new module.
- `services/student_import.py`/`services/course_import.py` (Phase 2) validate: missing `reg_no`/`name`, duplicate `reg_no` within file, unknown department, unknown programme. They do **not** validate duplicate email, or level-vs-programme validity, and have no preview-before-commit step — upload runs the full import immediately.
- `services/admin_validation.py` has `resolve_department`/`resolve_programme`/`resolve_semester`/code-uniqueness checks. No level-validity concept exists anywhere.
- `Programme.program_type` values (seeded): `'international'` (covers CIFS, International Diploma, Advanced Diploma — these are not distinguished by `program_type`, only by `Programme.code`), `'nd'`, `'hnd'`. No `Term` model or concept exists anywhere in the schema; `Semester` is a flat 2-row global lookup shared across all programme types (Phase 2 explicitly kept it that way).
- No dependency in `requirements.txt` writes `.xlsx` (`reportlab` is PDF-only, used for payment receipts).
- No dedicated `EmailService` abstraction exists — every call site (`onboarding`, admin resend-verification) calls `Flask-Mail`'s `mail.send(Message(...))` directly, inline.
- `services/admin_audit.py`'s `log_admin_action(admin_user, action, target_type, target_id, details, ip_address)` and `services/notification.py`'s `create_notification(...)` are the existing, reused-everywhere audit/notification primitives — no new equivalents needed.

## Scoping decisions (resolved with the user before design)

1. **Course capacity enforcement**: added for real to the student-facing `add_course` path (not just displayed in the admin view) — only an admin override bypasses it. This is the one deliberate, narrow edit to a "completed" module (Course Add/Drop), justified because "override beyond capacity" requires something real to override.
2. **OTP History / Failed Verification Attempts**: placeholder ("Not tracked"), matching the existing Support Tickets precedent — OTPs were never designed to persist, and adding that now is a materially separate feature.
3. **`User.last_login_at`**: added (new nullable column, set on every successful student login) — needed for the onboarding dashboard's "Not Logged In" bucket to be real rather than approximated.
4. **Excel export**: `openpyxl` added as a new dependency (pure Python, no external binary).
5. **Super-Admin-only "Mark Onboarding Complete"**: new permission code `onboarding.override`, seeded only to Super Administrator — not a hardcoded role-name check.
6. **Lock/Unlock registration**: locked blocks *all* self-service actions (add/drop/submit), not just add/drop.
7. **Per-student deadline extension**: new nullable `StudentRegistration.deadline_override` column, not a repurposed department-level rule table.
8. **Bulk Assign Department/Programme**: dual-writes the new FK *and* the legacy string column, matching `create_student`/`update_student`'s existing pattern — every downstream student-facing read path keeps working unchanged.
9. **CSV "Invalid Levels" validation**: the user initially asked for the *full* CIFS/International/ND/HND term-cycle distinction. Investigated and flagged: that requires a `Term` model and reworking `RegistrationPeriod`/`Course` to be scoped by term instead of just semester — a structural change on the scale of its own phase, touching the registration engine Phase 2 explicitly left alone. **Resolved**: validation-only scope. A `LEVELS_BY_PROGRAM_TYPE` data mapping (below) validates a student's `level` against their `Programme.program_type` on CSV import and manual create/edit. The registration/semester engine itself is untouched. The full term-cycle rebuild is out of scope for this phase (see below) — a candidate for its own future spec if wanted.

## Architecture

### Data model

**New columns** (all nullable/defaulted — additive, no destructive changes):

```python
# User
last_login_at = db.Column(db.DateTime, nullable=True)          # set in login() on every successful student login
onboarding_completed_at = db.Column(db.DateTime, nullable=True) # set once, when onboarding_completed flips to True

# StudentRegistration
is_locked = db.Column(db.Boolean, default=False, nullable=False, server_default='0')
deadline_override = db.Column(db.DateTime, nullable=True)       # per-student override of the period's closes_at

# RegistrationPeriod
add_drop_opens_at = db.Column(db.DateTime, nullable=True)       # NULL => falls back to opens_at/closes_at (today's behavior)
add_drop_closes_at = db.Column(db.DateTime, nullable=True)
```

**New table:**

```python
class RegistrationOverride(db.Model):
    __tablename__ = 'registration_overrides'
    id = db.Column(db.Integer, primary_key=True)
    student_registration_id = db.Column(db.Integer, db.ForeignKey('student_registrations.id'), nullable=False)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_users.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)   # locked/unlocked/reopened/deadline_extended/capacity_overridden/course_added_by_admin/course_removed_by_admin
    reason = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)

    student_registration = db.relationship('StudentRegistration', backref='overrides')
    admin_user = db.relationship('AdminUser')
```

Why a dedicated table instead of just `AdminAuditLog.details`: every Module 1 override *requires* a reason (not optional, unlike most existing audit entries), and the per-student Registration tab needs to render a filtered "why was this touched" timeline without grepping the global admin audit feed. Every `RegistrationOverride` write is paired with a `log_admin_action` call too (structured index, not a replacement) — the global feed stays complete.

No new table is needed for onboarding actions (Module 3) — `log_admin_action` alone is sufficient there, since there's no equivalent per-student-filtered-timeline requirement beyond what `AuditLog`/`AdminAuditLog` already provide.

**New permission code**: `onboarding.override`, seeded only to Super Administrator.

**New dependency**: `openpyxl` (added to `requirements.txt`), for `.xlsx` export.

**Level-validity data** (`services/admin_validation.py`, validation-only, no schema/engine impact):

```python
LEVELS_BY_PROGRAM_TYPE = {
    'nd': ['ND 1', 'ND 2'],
    'hnd': ['HND 1', 'HND 2'],
    'international': ['First Semester', 'Second Semester'],  # International Diploma, Advanced Diploma
}
# Programme.code == 'CIFS' is a special case within 'international': one-term program,
# no level required (level may be blank/None).

def valid_levels_for_programme(programme):
    """Returns the list of acceptable `level` strings for this programme, or None if
    there's no constraint to apply (e.g. programme unset, or an unrecognized program_type —
    never block on something we can't classify)."""
```

Applied in CSV import (student), manual create, and manual edit — only when a programme is resolved. Existing seeded rows (free-text `'Year 1'`/`'Year 2'`) are never re-validated retroactively; the rule only applies going forward.

### Programme/term-cycle scope (reaffirmed)

Per scoping decision #9: this phase adds *validation* keyed off `program_type`, not a `Term` model or a term-scoped registration engine. Building the real 3-term International vs. annual ND/HND registration cycle remains explicitly deferred, same as Phase 2's own deferral — now with the specific shape of that future work identified (a `Term` model; `RegistrationPeriod`/`Course` scoped by `(programme_type, term)` instead of just `(session, semester)`; a reworked window/eligibility engine) so a future spec can pick it up without re-deriving this analysis.

## Module 1 — Registration Oversight

Route family `/admin/registration/oversight/...`, permission `registration.manage` (existing — no new code needed for this module).

**Registration Dashboard** (`GET /admin/registration/oversight`, `GET /admin/registration/oversight/data` for the AJAX payload) — `templates/admin/registration_oversight.html`, following the established filter-bar + JSON-endpoint pattern (`students.html`/`courses.html`). Defaults to the active `RegistrationPeriod`, selectable to any other. Metrics (`services/admin_registration.py`):
- Total Eligible Students — students matching the period's session's eligible population (same department/level matching `services/course.py`'s eligibility logic already uses).
- Registered / Pending / Incomplete — counts by `StudentRegistration.status`/`courses_submitted`/`payment_status`.
- Registration Completion Percentage.
- Total Registered Credits — `sum(StudentRegistration.credits_registered)` for the period.
- Deadline Countdown — reuses the same countdown the student-facing `registration.html` already renders, server-computed from `closes_at`.
Filters: academic session, semester, department, programme, level, registration status.

**Registration Management (per-student)** — new "Registration" section added to the *existing* `student_profile.html` (Phase 2 already has Personal/Academic/Registration History/Course History/Payment History/Activity Log/Support-Tickets-placeholder). Adds:
- View current-period registration detail (status, payment, credits, courses, lock state, deadline override).
- Add/remove course on the student's behalf — calls `services/registration.py`'s existing `add_course`/`drop_course` directly (same operation, admin as actor instead of the student), each writing a `RegistrationOverride` row (`course_added_by_admin`/`course_removed_by_admin`) + `log_admin_action`.
- Override registration restrictions / capacity override — a checkbox on the admin's add-course action that bypasses the new capacity check (admin-only bypass path in `add_course`, gated by `registration.manage`).
- Extend deadline — sets `StudentRegistration.deadline_override`; the window-status check consults this first for that student before falling back to the period's `closes_at`.
- Approve registration exceptions — a generic "override" action: writes a `RegistrationOverride` row with a free-text reason, no state change beyond the record itself (covers ad hoc exceptions that don't map to a specific field).
- Lock / Unlock — sets `StudentRegistration.is_locked`; `add_course`/`drop_course`/`submit_registration` all reject while locked, checked before the window-status check, regardless of window state.
- Reopen submitted registration — sets `courses_submitted = False` back so the student can resume self-service add/drop (subject to the normal window/lock checks from then on).

All seven actions: mandatory `reason` field, one `RegistrationOverride` row, one `log_admin_action` call.

**Course Enrollment** — no new page. Adds columns to the *existing* `courses.html` directory and `course_detail.html` (Phase 2): Current Enrollment (`count(RegisteredCourse where course_id=X)`), Maximum Capacity (`Course.max_capacity`), Remaining Capacity (computed, blank if no capacity set), Waitlist Count (static "—" placeholder — no waitlist system exists, explicitly allowed as a placeholder per the requirements).

**Registration Period Management** — almost entirely already built in Phase 2 (`sessions.html`/`period_form.html`/`registration_open.html`): Open = `activate_period`, Close/Extend = edit `closes_at` via `update_period`, Late Registration and Credit Limits already exist. The one addition: two new fields on `period_form.html` for `add_drop_opens_at`/`add_drop_closes_at`. `add_course`/`drop_course` check this window when set (falls back to the main window when unset — identical behavior to every existing period, zero behavior change for periods that don't configure it).

## Module 2 — Bulk Student Operations

**CSV Import** — extends `services/student_import.py`/`services/course_import.py`, `services/admin_validation.py`, `services/admin_import.py` (not replaced):
- **Preview step**: `POST /admin/students/import/preview` (and the course equivalent) runs identical row-validation logic to the real import but commits nothing — returns JSON counts + a sample of flagged rows, rendered as a preview table with a "Confirm Import" button that then calls the existing commit endpoint.
- **Duplicate email detection**: within-file and against `User.email`, same shape as the existing within-file/DB `reg_no` duplicate checks.
- **Invalid department/programme**: already implemented (`resolve_department`/`resolve_programme`) — no change.
- **Invalid level**: new `valid_levels_for_programme` check (see Architecture above), applied only when a programme is resolved for that row.
- **Missing required fields**: already implemented (`reg_no`/`name`) — unchanged.
- **Import Progress**: synchronous within the request (no background task runner exists in this codebase — an established constraint since Phase 1) — a client-side spinner during the request, not a polled job status.
- **Import Summary**: already exists (`StudentImportJob`/`CourseImportJob` + report page, Phase 2) — unchanged.

**Manual Student Creation** — `create_student` (Phase 2) already generates a temp password and sets `first_login=True`. New: after creation, if an email was provided, send an onboarding email via `mail.send(Message(...))` (same inline pattern as the existing admin resend-verification route) containing `reg_no` + temp password.

**Bulk Actions** — extends `services/admin_student.py`. Activate/Suspend/Deactivate already exist (Phase 2 Task 12). New:
- `bulk_reset_password(student_ids)` — N-repeat of `reset_student_password`, returns a reg_no→temp-password list for the admin to export/distribute.
- `bulk_resend_onboarding_email(student_ids)` — N-repeat of the resend-verification email.
- `bulk_assign_department(student_ids, department_id)` / `bulk_assign_programme(student_ids, programme_id)` — dual-write FK + legacy string field per scoping decision #8.
- `bulk_export(student_ids, format)` — delegates to the new export service (below).
All wired into the existing bulk-select bar (`students.js`, Task 12's pattern) — more buttons, same mechanism. Every bulk action writes one `log_admin_action` row summarizing the whole batch (matching `student_bulk_status_changed`'s existing shape — count + ids in `details`), not one row per student.

**Export** (`services/admin_export.py`, new; routes gated on `reports.view` — the permission already seeded for exactly this purpose) — Students, Registrations, Courses, Departments as real CSV (stdlib `csv`) and Excel (`openpyxl`); Payments as real CSV/Excel too (that module is complete, not a placeholder-eligible case per the requirements' own carve-out); PDF stays a disabled "Coming soon" button across all five, consistent with the requirements' explicit PDF placeholder allowance.

## Module 3 — Student Onboarding Management

Route family `/admin/onboarding/...`, new `templates/admin/onboarding_dashboard.html`, permission `students.manage` — except the one Super-Admin-only action (`onboarding.override`).

**Dashboard** (`services/admin_onboarding.py`) — five independent, non-exclusive, filterable counts:
- Not Logged In: `User.last_login_at IS NULL`
- Password Not Changed: `User.first_login == True`
- Profile Incomplete: `User.onboarding_completed == False`
- Email Not Verified: `User.email_verified == False`
- Onboarding Completed: `User.onboarding_completed == True`

Plus completion percentage, filterable by department/programme/session (same filter-bar convention).

**Onboarding Actions:**
- Resend Verification Email — already exists (`admin_student_resend_verification`, Phase 2), surfaced here too.
- Reset Onboarding — sets `onboarding_completed = False`. Does not clear any already-entered profile data — the student's next login just re-enters the onboarding gate, with the wizard's step 1 pre-showing their existing DB values as it already does today.
- Manually Verify Email — sets `email_verified = True` directly, bypassing OTP.
- Mark Onboarding Complete (`onboarding.override`, Super Administrator only) — sets `onboarding_completed = True` and `onboarding_completed_at = now_lagos()` directly, bypassing the 3-step wizard's own validation.
- View Onboarding Timeline — assembled, not stored: `created_at`, `last_login_at`, `onboarding_completed_at`, plus that student's existing `AuditLog` rows (profile/password changes already logged there since the Profile Management milestone).
- OTP History / Failed Verification Attempts — placeholder card ("Not tracked"), per scoping decision #2.

All four mutating actions: mandatory reason, one `log_admin_action` row each (`onboarding_reset`, `email_manually_verified`, `onboarding_marked_complete`, `verification_resent`).

**Analytics**: Onboarding Completion Rate (aggregate), Average Completion Time (`avg(onboarding_completed_at - created_at)` over completed students), Completion by Department, Completion by Session — all straightforward aggregate queries over existing + new timestamp columns.

## Explicitly out of scope for this milestone

The full CIFS/International/ND/HND term-cycle rebuild (`Term` model, term-scoped `RegistrationPeriod`/`Course`, reworked eligibility engine — see scoping decision #9 and "Programme/term-cycle scope" above); waitlist system (capacity overflow has no queueing, just a blocked add unless admin-overridden); real background job processing for CSV import (stays synchronous); OTP/verification-attempt persistence (placeholder); real admission-portal integration (`services/admission_portal_service.py`'s `fetch_admitted_students` stays a documented `NotImplementedError`, unchanged from Phase 2); PDF export (placeholder button, all five data types); per-field edit-authorization tiers; merging duplicate student records; admin MFA; Payments admin UI proper (Phase 4 — Finance & Payment Administration); Reports module; Support Tickets.

## Testing

No automated test suite (established convention) — manual, throwaway `test_client`/`app_context` scripts per task, never committed. Covers: capacity enforcement (student-side reject, admin-side override), lock/unlock blocking all three self-service actions, deadline override taking precedence over the period's `closes_at`, reopen-submitted-registration, add-drop-window fallback behavior for periods that don't set it, CSV preview producing zero DB writes, duplicate-email/invalid-level detection, manual creation sending the onboarding email, each new bulk action (reset-password, resend-onboarding-email, assign-department, assign-programme) plus its single summarizing audit row, CSV/Excel export producing well-formed files for all five data types, each onboarding-dashboard bucket query, each onboarding action (including the `onboarding.override` permission actually blocking Academic Administrator), and one final whole-milestone smoke test (every Phase 3 route reachable, no `coming_soon` fallback) before the `DEVELOPMENT_PROGRESS.md` update.

## Deliverables

1. Audit all Phase 3 admin pages (this document's "Current state" section).
2. Replace remaining mock/placeholder functionality across all three modules with real backend-driven behavior.
3. Implement Registration Oversight as designed above.
4. Implement Bulk Student Operations as designed above.
5. Implement Student Onboarding Management as designed above.
6. Build/extend the services described above (`admin_registration`, `admin_export`, `admin_onboarding` new; `admin_student`, `student_import`, `course_import`, `admin_validation`, `admin_import` extended).
7. Verify all Student Portal integrations continue to work unchanged (capacity enforcement is the only behavior change to a completed module, and is additive/rejecting-only — no existing successful registration is retroactively affected).
8. Update `DEVELOPMENT_PROGRESS.md` with a new "Phase 3: Academic Operations" entry, matching the existing entries' format.
9. Stop and wait for approval before beginning Phase 4 (Finance & Payment Administration).
