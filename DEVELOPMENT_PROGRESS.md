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

## Known pre-existing issues (not yet fixed)

- `payments_history`, `pay_summary` routes are missing `@login_required` (same class of bug fixed on `dashboard`, `profile`, `registration`, `add_drop`, and `my_courses`). Not fixed yet since those pages/routes aren't otherwise touched.
- `constants_file.py` contains real credentials and is not gitignored (flagged in `CLAUDE.md`).

## Next milestone

TBD — awaiting direction on the next feature from `doc/t.txt`.
