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
