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

## Feature 5 & 6: Course Add/Drop and My Courses — Complete

- New models: `Course`, `RegisteredCourse`; `StudentRegistration.courses_submitted` flag added.
- New services: `services/course.py` (catalog/eligibility filtering), `services/course_history.py` (My Courses grouping), `services/validation.py` (reusable business-rule checks), `services/registration.py` extended with `add_course`/`drop_course`/`submit_registration`/`get_add_drop_context`. `RegistrationError` moved to `services/errors.py` to break a circular import, still re-exported from `services.registration` for backward compatibility.
- `add_drop.html` keeps its original JS-array-driven architecture, rewired to fetch real data (`/add_drop/data`) and perform real add/drop/submit actions instead of mutating in-memory-only state — selections now survive a page refresh.
- `my_courses.html` converted to server-rendered Jinja (matching Feature 4's `registration.html` precedent), grouped by session/semester with the current semester expanded by default (native `<details>`/`<summary>`).
- New course-details modal (My Courses' "View" buttons) and a printable registration slip (`/registration/slip`, browser print, no new dependency).
- Fixed: `/add_drop` and `/my_courses` were missing `@login_required` — fixed as part of rewriting both routes.
- Spec: `docs/superpowers/specs/2026-07-31-course-add-drop-design.md`
- Out of scope (deferred): grading (the `grade` column exists but nothing sets it yet), real PDF generation, post-submission editing, admin UI for the course catalog.

## Feature 7: Notification Management — Complete

- New model: `Notification` (title, message, category, priority, read/archived/deleted state, optional related URL).
- `services/notification.py`: centralized `create_notification` (the single creation path for every other module), filtering/search, summary counts, mark read/unread, mark-all-read, archive, soft-delete — every read/write scoped to the acting user.
- Automatic notifications wired into: onboarding completion, payment/registration completion, course registration submission, profile updates, password changes, email changes.
- Registration-window notifications ("opens" / "closes soon") are generated opportunistically on dashboard/registration page loads rather than via a background scheduler — this codebase has no task runner, and idempotency is enforced per (user, period, trigger) so repeat visits never duplicate.
- `announcements.html` rewired to real backend data: server-rendered initial load, AJAX-driven filtering (category, priority, read status, date range, search) and actions, matching the Add/Drop page's "keep the JS, swap the data source" pattern.
- Fixed: `/announcements` was missing `@login_required`.
- Spec: `docs/superpowers/specs/2026-07-31-notifications-profile-design.md`

## Feature 8: Profile Management — Complete

- New model: `AuditLog`. New `User` columns: `emergency_contact`, `blood_group`, `updated_at`.
- `services/profile.py`: contact-info updates (phone/address/emergency contact/blood group), password change (reusing the same policy from onboarding), profile picture upload/replace/delete (reusing `onboarding_helpers.save_profile_picture`) — every write creates both an `AuditLog` row and a `Notification`, and is scoped only to the acting user (no cross-user write surface).
- `profile.html` extended in place: Address is now editable, Emergency Contact and Blood Group are new fields, and the previously-fake avatar edit (a `prompt()` demo) is now a real file upload with replace/delete support.
- Email-change OTP flow reused unchanged from the earlier onboarding milestone (`onboarding_helpers`) — satisfies "reuse existing OTP implementation," no new OTP service was needed.
- `/change-password` and `/update-profile` refactored to delegate to `services/profile.py` (moved business logic out of the route, including removing a stray unexplained `time.sleep(5)` debug leftover from `update_profile`).
- Spec: `docs/superpowers/specs/2026-07-31-notifications-profile-design.md`
- Out of scope (deferred): Feature 9 (Payments), a real background scheduler, push/email notifications for the Notification model, an admin notification-composition UI.

## Known pre-existing issues (not yet fixed)

- `constants_file.py` contains real credentials and is not gitignored (flagged in `CLAUDE.md`).

## Feature 9, 10 & 11: Payment Module (History, Independent Creation, Processing) — Complete

- New models: `PaymentCategory`, `PaymentItem`, `PaymentReceipt`, `GatewayResponse`; `Payment` extended from its unused one-column stub into the real transaction record.
- New services: `services/payment_gateway.py` (`PaymentGateway` abstraction with a real `RemitaGateway` against Remita's published test/demo sandbox, and an offline `SimulatedGateway` used only by manual verification scripts), `services/payment.py` (create/initiate/verify/retry/cancel/history — `verify_payment` is idempotent), `services/payment_validation.py` (duplicate-pending detection), `services/receipt.py` (reportlab PDF generation, resend-by-email).
- `services/registration.py`'s `register_student()` refactored: registration payment is no longer simulated as instantly successful — it creates a real pending `Payment` and the student completes it via `payment_summary.html`'s Pay Now button, through the real gateway.
- `payments_history.html` and `payment_summary.html` keep their existing visual structure, wired to real data (AJAX-driven search/status filter/date-range filter/pagination for history, matching the Notifications page's established pattern). New `/payment/create` page for independent payments (Library Fee, Hostel Fee, ID Card, etc.) against the admin-configurable `PaymentCategory` catalog.
- Printable receipts (`window.print()`, matching the registration slip pattern) plus real PDF download (`reportlab`) and resend-by-email.
- Fixed: `/payments_history` and `/pay_summary` (now `/payment/registration/<id>`) were missing `@login_required`.
- Spec: `docs/superpowers/specs/2026-08-01-payment-module-design.md`
- Out of scope (deferred): Admin UI for managing `PaymentCategory` (Admin Portal not started), gating Add/Drop or course submission on `payment_status`.

## Admin Portal — Foundation (Auth, RBAC, Layout, Dashboard, Audit Logging) — Complete

- New models: `AdminRole`, `Permission`, `RolePermission`, `AdminUser`, `AdminAuditLog` — a fully separate admin identity from `User` (the dead `User.is_admin` column is untouched). Loaded by the existing shared `LoginManager` via a prefixed id (`admin:<id>`), so one `user_loader` distinguishes student and admin sessions.
- Admin auth under `/admin/...`: login, logout, Remember Me, forgot-password/OTP-verify/reset (reusing the existing `onboarding_helpers` OTP session mechanism), first-login forced password change, and a 15-minute idle session timeout scoped only to admin sessions.
- RBAC: two seeded roles (Super Administrator, Academic Administrator) over a 7-code permission catalog, enforced by `@admin_required`/`@permission_required(code)` decorators — proven end-to-end via 6 permission-gated Quick Action stub routes (navigation only, no feature logic yet) and a real "Access Denied" page on an unauthorized direct hit.
- Reusable admin layout (`templates/admin/base_admin.html`): sidebar, top bar, profile menu, notification indicator, breadcrumbs, search UI, responsive collapse, light/dark theme toggle — replaces the previous fully-mocked, unreachable `admin_dashboard.html`.
- Live dashboard: 7 summary cards backed by real queries (Total/Active Students, Current Semester Registrations, Total Payments, Active Courses, Departments, and a literal "Not yet available" placeholder for Support Tickets, since that module doesn't exist), plus a real activity feed merged from existing registration/payment/course/notification/admin-login data — no new event-logging system needed.
- `services/admin_audit.py`: every admin login/login-failure/logout/password-change/reset writes an `AdminAuditLog` row.
- Spec: `docs/superpowers/specs/2026-08-01-admin-foundation-design.md`
- Out of scope (deferred): MFA, admin self-service account management, real-time push, charts, Student Management, Payments admin UI, Course Management, Registration Oversight, Reports, Support Tickets.

## Admin Portal — Phase 2 (Departments, Academic Sessions & Semesters, Course Management, Student Management) — Complete

- New models: `Department`, `Programme`, `CoursePrerequisite`, `CourseCorequisite`, `CourseAssessmentComponent`, `AcademicHoliday`, `StudentImportJob`/`StudentImportError`, `CourseImportJob`/`CourseImportError`. First real Flask-Migrate/Alembic schema migration in this repo (previously everything was purely additive via `db.create_all()`) — added `department_id`/`programme_id`/`account_status`/`created_at` to `User`, `department_id`/`status`/`max_capacity` to `Course`, late-registration/exam/result-release fields to `RegistrationPeriod`, and `start_date`/`end_date`/`status` to `AcademicSession`. A one-time backfill created `Department` rows from every distinct legacy `User.department`/`Course.department` string and pointed existing rows at them via the new FK — every existing student-facing read path keeps reading the legacy string columns unchanged.
- New permission code `departments.manage`, granted to both seeded roles.
- `services/admin_department.py`, `services/admin_session.py`, `services/admin_course.py`, `services/admin_student.py`: CRUD, status transitions, and cross-module lookups for each module. `services/admin_validation.py`/`services/admin_import.py`: shared validators and CSV-parsing/report helpers reused across Course and Student import. `services/student_import.py`/`services/course_import.py`: CSV import with per-row validation and a Created/Updated/Skipped/Duplicates/Errors report. `services/admission_portal_service.py`: a clean interface (`fetch_admitted_students`) with a `NotImplementedError` TODO — no external integration built.
- Departments: full CRUD, activate/deactivate/archive, student/course counts.
- Academic Sessions & Semesters: session CRUD, clone (copies `RegistrationPeriod` configuration into a new draft session), and registration-period ("semester") CRUD including late registration, exam dates, result release, and holidays. Activating a period deactivates every other period and makes its session current — the app-side enforcement of "only one session and one semester active at a time." Replaces `admin_stub_sessions_new` and `admin_stub_registration_open`.
- Course Management: CRUD, activate/deactivate/archive, prerequisites/corequisites, assessment structure (component/weight rows, not strictly enforced to sum to 100%), and CSV import. Replaces `admin_stub_courses`.
- Student Management: directory with the full filter set (reg no., name, department, programme, level, semester, status, enrollment date range) plus sort/pagination/bulk-select; a profile page aggregating Personal/Academic Information, Registration History, Course History, Payment History, and Activity Log (reusing the existing student-facing history services unchanged), with a "Not yet available" Support Tickets placeholder; account actions (activate/suspend/deactivate/reset-password/resend-verification); manual creation; CSV import; and one bulk action (bulk activate/suspend/deactivate). Replaces `admin_stub_students_import`. One narrow, necessary edit to the shared student `login()` route in `app.py`, gating on the new `account_status` column.
- Spec: `docs/superpowers/specs/2026-08-02-admin-phase2-core-academic-data-design.md`
- Out of scope (deferred): per-program-type term-cycle registration logic (the 3-term International vs. annual ND/HND calendars — `Programme` exists as structured metadata only), merging duplicate student records, manual grade editing, per-field edit-authorization tiers, full Bulk Operations (bulk email/export/course-registration), Registration Oversight, Student Onboarding Management dashboard, admin MFA/12-char password policy/progressive lockout (already accepted in Admin Foundation), real-time activity feed, charts/analytics, Support Tickets, Payments admin UI, Reports.

## Admin Portal — Phase 3 (Registration Oversight, Bulk Student Operations, Student Onboarding Management) — Complete

- New columns: `User.last_login_at`/`onboarding_completed_at`, `StudentRegistration.is_locked`/`deadline_override`, `RegistrationPeriod.add_drop_opens_at`/`add_drop_closes_at`. New table `RegistrationOverride` (every Registration Oversight action requires a reason and writes one row here, mirrored into `AdminAuditLog`). Second real Alembic migration in this repo. New permission `onboarding.override`, seeded only to Super Administrator. New dependency: `openpyxl` (Excel export).
- Course capacity is now enforced for real in the student-facing `add_course` path (Course Add/Drop's one deliberate, narrow behavior change this phase) — admin-only override bypasses it. `add_course`/`drop_course`/`submit_registration` also now reject while a registration is locked.
- Registration Oversight (`/admin/registration/oversight`, `registration.manage`): a real-time dashboard (eligible/registered/pending/incomplete counts, completion %, total registered credits, deadline countdown) filterable by session/department/programme/level/status; a per-student "Registration Management" section on the Student Profile page (view, add/remove course on the student's behalf, capacity override, lock/unlock, deadline extension, reopen a submitted registration, approve a general exception) with a mandatory reason and a visible override history for every action; course enrollment/capacity/remaining now shown in the Course Directory and detail page (waitlist stays a placeholder — no waitlist system exists); a configurable Add/Drop window independent of the main registration window (falls back to it when unset).
- Bulk Student Operations: CSV import preview step (validates without writing) for both Student and Course import; duplicate-email detection; level validated against the student's programme's `program_type` (`ND 1/2`, `HND 1/2`, `First/Second Semester`, CIFS exempt) on import and manual create/edit; manual student creation now emails the temp credentials; four new bulk actions (reset-password, resend-onboarding-email, assign-department, assign-programme — the latter two dual-write the FK and legacy string field, matching Phase 2's own pattern); a new Export Center (`/admin/export`, `reports.view`) with real CSV/Excel export for Students, Registrations, Courses, Departments, and Payments (PDF stays a placeholder button), plus a bulk "Export Selected" action on the Student Directory.
- Student Onboarding Management (`/admin/onboarding`, `students.manage`): a dashboard with five independent buckets (Not Logged In, Password Not Changed, Profile Incomplete, Email Not Verified, Onboarding Completed), completion percentage, and analytics (average completion time, completion by department/session); per-student actions (Resend Verification Email, Reset Onboarding, Manually Verify Email, and a Super-Administrator-only Mark Onboarding Complete gated by the new `onboarding.override` permission) plus an assembled Onboarding Timeline on the Student Profile page. OTP History / Failed Verification Attempts stay an explicit "Not tracked" placeholder — OTPs were never designed to persist.
- Spec: `docs/superpowers/specs/2026-08-03-admin-phase3-academic-operations-design.md`
- Out of scope (deferred): the full CIFS/International/ND/HND term-cycle rebuild (a `Term` model and term-scoped registration engine — flagged as its own future phase-sized effort), waitlist queueing, real background job processing for CSV import, OTP/verification-attempt persistence, real admission-portal integration, PDF export, per-field edit-authorization tiers, merging duplicate student records, admin MFA, Payments admin UI proper, Reports module, Support Tickets.

## Dashboard Ongoing Registration Card — Complete

- New card on the student dashboard, shown above "Registered Courses (Current)" whenever a student has a registration for the active period that hasn't yet reached course submission (payment-pending or paid-not-submitted), with a "Complete Registration" CTA gated on the real Add/Drop window status and admin-lock state (not just the coarser main registration window) — previously `/registration` had no next-step action at all once payment succeeded.
- Purely additive: no schema changes, one new key (`add_drop_window_status`) added to `get_registration_status_context`'s return dict.
- Spec: `docs/superpowers/specs/2026-08-04-dashboard-ongoing-registration-card-design.md`

## DDD Academic Architecture Refactor (Programme↔Department Foundation, Academic Calendar, Course/CourseOffering Split, Student & Registration Programme-awareness, FeeStructure) — Complete

Five sub-projects, planned together via a Phase A audit and built/merged one at a time via `superpowers:subagent-driven-development`, each with an independent end-to-end verification task and a final whole-branch review before merge.

- **Architecture changes:**
  - `Programme` gained `uses_semesters`/`uses_terms`/`duration` and a `ProgrammeDepartment` junction table, giving Programmes a real relationship to Departments (sub-project 1).
  - `AcademicSession`/`RegistrationPeriod` scoped to `Programme` (nullable — `None` means the shared/legacy scope group), and `Semester` gained `period_type` (`semester` vs `term`) so CIFS/International-style term-based Programmes and ND/HND-style semester-based Programmes can each have their own calendar shape (sub-project 2). `activate_period()`/`get_active_period()` generalized from "one active period institution-wide" to "one active period per Programme-scope-group," with shared/legacy fallback (sub-projects 2 and 4).
  - `Course` split into a curriculum-level master `Course` (code/title/credits/course_type/description/status) and a per-semester `CourseOffering` (everything scheduling-specific — department/level/instructor/schedule/session/semester/capacity), with `CourseOffering` keeping the original `courses` table's row IDs so every pre-existing FK into it kept resolving unchanged; `CoursePrerequisite`/`CourseCorequisite` repointed to the new master `Course` (sub-project 3). A new Course Catalog admin module manages masters; offering create/edit now key off a master-course picker and dual-write its catalog fields onto the offering.
  - `validate_course_eligible()` given hybrid FK/string department matching (FK compared only when both sides have `department_id` set, else legacy string fallback) plus a soft Programme check (sub-project 4).
  - New `FeeStructure` model: a Programme/Session/Semester/Department-scoped fee-override layer on top of the existing flat `PaymentCategory.default_amount`, resolved by `services/fee_structure.py` (most-specific-match priority: session+semester+dept → session+semester → session+dept → session-wide → category default). Admin CRUD gated by the existing `sessions.manage` permission — no new permission code. `DepartmentRegistrationRule` and the `registration_fee` category's registration-time charge were deliberately left untouched — `register_student()`/`get_credit_limits()` are a separate, older mechanism `FeeStructure` never touches; the general `/payment/create` fee-payment flow excludes the `registration_fee` category at every layer (a shared query filter plus a route-level backstop) so it can never be paid there without reconciling a registration (sub-project 5).
- **Migration notes:** four new Alembic migrations — `d41f9a3c7b52` (Programme columns + `ProgrammeDepartment`), `b7f4a1de9c63` (`AcademicSession.programme_id`, `Semester.period_type` — a raw-SQL table rebuild for `academic_sessions`), `a29d6f0c81e5` (`courses`→`course_offerings` rename + new master `courses` table, backfilled and deduped by code from existing offering rows), `f3a7c9d21e04` (`FeeStructure`, purely additive). Sub-project 4 needed no migration — pure service-layer/behavioral change. All four were independently re-applied and re-verified (`PRAGMA foreign_key_check`/`integrity_check`, schema/row-count spot-checks) against `main`'s real, populated dev DB after each merge, not just the isolated worktrees' fresh seeds.
- **Breaking / behavioral changes:**
  - `activate_period()`'s core meaning changed: multiple `RegistrationPeriod` rows can now legitimately be `is_active=True` simultaneously (one per Programme-scope-group). Code still calling the old `RegistrationPeriod.query.filter_by(is_active=True)...first()` pattern directly instead of `get_active_period(user)` now silently means "whichever scope group's active period has the highest id," not "the" active period — two such call sites (`services/admin_dashboard.py`'s summary query, the Registration Oversight default period) were identified and deliberately left as-is; see Remaining tasks below.
  - Every pre-split flat-`Course` consumer had to be repointed to `CourseOffering` — six real call sites across the codebase (student add/drop, admin dashboard, admin department detail, admin export, credit recomputation, and `seed_dev_data.py`'s fresh-DB bootstrap) needed fixing beyond what the original task plans named.
- **Remaining tasks / deferred, not done here:**
  - `services/course.py`'s `get_available_courses` (student-facing course browse list) still matches department purely by legacy string, unlike `validate_course_eligible`'s hybrid FK/string check — a latent asymmetry, not a regression.
  - `services/admin_dashboard.py`'s summary query and the Registration Oversight default period selector still resolve "the active period" via the old non-Programme-aware query — neither has per-student context to resolve against; a future sub-project should decide whether the dashboard should aggregate per-Programme or across all scope groups.
  - `FeeStructure`'s scope uniqueness is enforced only at the application level (check-then-insert, no DB `UniqueConstraint`) — a rare concurrent-double-submit race could create two rows for the same scope; would need a new migration to close.
  - Minor perf-only items in the Fee Structure admin list/resolution path (N+1 queries, redundant per-category re-querying) — no correctness impact at this repo's scale, not fixed.
  - The full CIFS/International/ND/HND term-cycle registration engine (a `Term` model and term-scoped registration logic) remains its own future phase-sized effort — this refactor only laid the `period_type`/Programme-scoping groundwork for it.
- Specs: `docs/superpowers/specs/2026-08-04-ddd-academic-refactor-phase-a-audit.md` (overall audit), plus one design spec + implementation plan per sub-project under `docs/superpowers/specs/` and `docs/superpowers/plans/` (`2026-08-04-ddd-programme-department-foundation*`, `2026-08-04-ddd-academic-calendar*`, `2026-08-04-ddd-course-offering-split*`, `2026-08-04-ddd-student-registration-programme-awareness*`, `2026-08-09-ddd-fee-structure*`).

## Next milestone

Admin Portal Phase 4 (Finance & Payment Administration) — not yet started, pending approval.
