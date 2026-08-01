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

## Next milestone

Admin Portal — not yet started.
