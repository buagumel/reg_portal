# Authentication & Onboarding Stepper — Design Spec

Date: 2026-07-29
Status: Approved
Scope: Features 1 (Authentication & First-Time Setup) and 2 (Onboarding Stepper Process) from `doc/System Workflow.txt`. No dashboard, registration, payments, or admin work in this milestone.

## Goal

Refactor the current login flow so that after a successful login:

- If `first_login == True` → the student must change their password before anything else, then complete a 3-step onboarding wizard, then land on the dashboard.
- Otherwise → the student goes straight to the dashboard (subject to the existing onboarding-completed check for accounts that never finished onboarding).

## Data model changes (`models.py`)

Add to `User`:

| Column | Type | Default | Purpose |
|---|---|---|---|
| `first_login` | Boolean | `True` | Gates the forced password-change screen |
| `onboarding_completed` | Boolean | `False` | Gates the onboarding wizard |
| `semester` | String(50) | `None` | Read-only field shown in onboarding Step 1 |
| `department` | String(150) | `None` | Read-only field shown in onboarding Step 1 |
| `course` | String(150) | `None` | Read-only field shown in onboarding Step 1 |
| `profile_picture` | String(300) | `None` | Relative path under `static/uploads/` |

These are new columns because `semester`/`department`/`course` are currently only hardcoded placeholder text in `dashboard.html`/`profile.html` templates, not real data. They're treated as pre-existing "university database" fields per the spec (read-only, seeded, not editable by the student).

OTP state (code, expiry timestamp, attempt count) continues to live in the Flask `session`, matching the existing pattern in `/send-email-code` / `/verify-email-code`. No new DB columns for OTP.

No Alembic migration is created for this change. The dev SQLite database (`instance/database.db`, already gitignored) will be deleted and rebuilt via the existing `db.create_all()` startup call, then repopulated by the seed script.

## Access-gate logic

Replace the current `check_email_verification` before_request hook in `app.py` with an ordered check. The decision logic is extracted into `get_gate_redirect(user)` in `auth_helpers.py` so it's reusable (by the login route, to decide where to redirect immediately after authenticating, and by the before_request hook, to guard every subsequent request) and unit-testable in isolation from Flask request context.

Order of checks (first match wins):

1. `current_user.first_login is True` → redirect to `/force-password-change` (GET) or 403 JSON (non-GET), except for the `force_password_change` and `logout`/`static` endpoints.
2. `current_user.onboarding_completed is False` → redirect to `/onboarding` (GET) or 403 JSON (non-GET), except for `onboarding`-prefixed endpoints, `send_email_code`, `verify_email_code`, `logout`/`static`.
3. `current_user.email_verified is False` → existing behavior (redirect to `/profile`), kept as a safety net for accounts that reach this state outside the onboarding flow (e.g. a future admin tool). In practice, once `onboarding_completed` is `True`, `email_verified` is already `True` because onboarding Step 2 requires it.
4. Otherwise → no redirect, normal access.

This checks `first_login` and `onboarding_completed` independently rather than treating "first_login" as "always run the full onboarding wizard again." That distinction matters for one edge case: if an admin resets a fully-onboarded student's password later (re-flagging `first_login = True`), the student is correctly routed through password-change only, not back through onboarding — because gate 2 is evaluated separately and `onboarding_completed` is still `True`. This is a deliberate deviation from a literal reading of the prompt's "first_login → password change → onboarding wizard" as one fixed sequence, made because the literal reading would force already-onboarded students to redo onboarding after any password reset, which has no basis in the spec's intent and no seeded demo case would otherwise exercise the `onboarding_completed` gate independently.

## Routes

All new routes live in `app.py` (per existing project convention of a single routes file); business logic is delegated to helper modules so `app.py` stays a thin routing layer.

- `GET /force-password-change` — standalone page (no `base.html` nav — the student has no accessible destination yet). Reuses `login.css`'s visual language via a new `force_password_change.css`.
- `POST /force-password-change` — body: `{new, confirm}`. No current-password field (student authenticated with the default password seconds earlier). Validates via `auth_helpers.validate_password_strength`. On success: sets password, `first_login = False`, commits, returns `{success, redirect}` where `redirect` is computed by `get_gate_redirect` (so it naturally goes to `/onboarding` or `/` depending on `onboarding_completed`).
- `GET /onboarding` — standalone page rendering all 3 steps (JS-toggled sections, same pattern as the tab-switching already used in `profile.html`).
- `POST /onboarding/save-info` — Step 1. `multipart/form-data`: `email`, `phone`, `address`, `profile_picture` (file, required — all four are required fields per the spec). Validates presence of all fields and file type/size via `onboarding_helpers.save_profile_picture`; rejects the whole submission with a field-level error if any is missing or invalid, matching the "validation should prevent moving to the next step until all required fields are complete" requirement. Does not mark anything complete yet — Step 2 (email verification) still needs to happen for the email just saved.
- `POST /send-email-code`, `POST /verify-email-code` — existing endpoints, reused for onboarding Step 2. Extended with a 3-attempt counter (`session['email_verification_attempts']`) via `onboarding_helpers`; exceeding 3 wrong attempts invalidates the code and requires a resend.
- `POST /onboarding/complete` — Step 3 confirm. Requires `email_verified == True` (guards against skipping Step 2 via direct API call). Sets `onboarding_completed = True`, sends a welcome email, returns `{success, redirect: url_for('dashboard')}`.
- `/reg` is removed. It was a hardcoded, non-idempotent dev-seed route (fails on second use due to unique constraints on `reg_no`/`email`) and is superseded by `seed_dev_data.py`.
- `/change-password` (existing, profile page) is upgraded to use the same `auth_helpers.validate_password_strength` instead of its current standalone 6-character-minimum check, so the app enforces one password policy everywhere rather than two different ones.

## Password policy

Minimum 8 characters, at least one uppercase, one lowercase, one number, one special character. Enforced by `auth_helpers.validate_password_strength(password) -> list[str]` (empty list = valid; otherwise a list of human-readable failed-rule messages used directly in the error response). Used by both `/force-password-change` and `/change-password`. Mirrored client-side in `static/js/shared/validation.js` for live feedback, with the server remaining authoritative.

## File structure

```
auth_helpers.py            # validate_password_strength(), get_gate_redirect()
onboarding_helpers.py       # OTP attempt tracking, save_profile_picture()
seed_dev_data.py            # dev-only, run manually, idempotent by reg_no

templates/
  force_password_change.html
  onboarding.html            # all 3 steps in one template, JS-toggled

static/css/
  force_password_change.css
  onboarding.css

static/js/
  shared/
    api.js                    # fetch wrapper: CSRF header + JSON parse + error normalization
    toast.js                  # showToast(), factored out of the copy duplicated in login.html/profile.html
    validation.js              # password/email/phone rule checks, shared across auth + onboarding
    stepper.js                  # progress indicator + step navigation; generic, reusable by any future wizard
  onboarding/
    onboarding.js               # orchestrates steps 1-3 via stepper.js, wires save-info / OTP / complete calls
    otp.js                       # countdown timer, resend cooldown, attempt-count UI
  auth/
    password-change.js
```

No bundler exists in this project (plain Jinja2 + vanilla JS). File separation is achieved with native ES modules (`<script type="module">`, `import`/`export`), which all target browsers support without added build tooling. This does not change the existing Python side of the architecture (still a single `app.py` for routes, per the project's established convention — confirmed with the user rather than introducing Flask Blueprints).

## Demo seed data (`seed_dev_data.py`)

Creates 4 students, idempotent by `reg_no` (skips if the reg_no already exists), covering every combination needed to exercise both gates independently:

| Student | `first_login` | `onboarding_completed` | Purpose |
|---|---|---|---|
| A | `True` | `False` | Brand-new student — full flow: password change → onboarding |
| B | `False` | `False` | Abandoned onboarding mid-way — password already changed, still gated into `/onboarding` on login |
| C | `False` | `True` | Fully set up — goes straight to dashboard |
| D | `True` | `True` | Admin-reset-password edge case — password change only, then straight to dashboard (no onboarding replay) |

Students A and D share a known default password (documented in the script) since both start with `first_login = True`.

## Error handling

- All new POST endpoints return the existing project convention: `{'success': bool, 'message': str, ...}` JSON with appropriate HTTP status codes.
- File upload validation (profile picture): required; rejects non-image types and files over 2MB with a clear message. Since it's required, an invalid or missing picture blocks the whole Step 1 submission (consistent with the other required fields), rather than saving partial data.
- OTP: existing 5-minute expiry kept; new 3-attempt limit returns a distinct message from "expired" so the client can prompt for resend vs. re-entry appropriately.
- Network/fetch failures on the client are caught and surfaced via toast, matching the existing pattern in `login.html`/`profile.html`.

## Out of scope for this milestone

- Login-attempt lockout / progressive delays (mentioned in `doc/System Workflow.txt` §1 but not in the Feature 1/2 requirements given for this milestone).
- JWT-based session management (`doc/System Workflow.txt` §12) — the app continues using Flask-Login's session cookies.
- Dashboard, registration, payments, admin — explicitly excluded per instructions.

## Testing approach

No test framework exists in the repo yet. Verification for this milestone is manual, using the seeded demo accounts to exercise:
- Login as Student A → forced password change (weak password rejected, strong password accepted) → onboarding Step 1 (validation blocks progression until required fields complete) → Step 2 (OTP send, wrong code up to 3 times, expiry, resend) → Step 3 (review, confirm) → lands on dashboard, `onboarding_completed` persisted.
- Login as Student B → skips password change, lands directly in `/onboarding`.
- Login as Student C → lands directly on dashboard.
- Login as Student D → forced password change only, then dashboard (no onboarding wizard shown).
- Existing `/change-password` on the profile page still works end-to-end with the upgraded strength rule.
