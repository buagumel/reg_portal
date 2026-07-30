# Semester Registration Foundation — Design Spec

Date: 2026-07-30
Status: Approved
Scope: Replace the fully-mocked `registration.html` page with a real, database-driven semester registration workflow: registration status, registration history, and a simulated "Register Now" flow. Course selection (Add/Drop) is explicitly out of scope for this milestone.

## Goal

Give students a real way to see whether semester registration is open, register (with payment simulated for now), and see their registration history — all driven by database state instead of hardcoded dates/numbers, so the next milestone (Course Add/Drop) has a real `StudentRegistration` record to attach course selections to.

## Audit findings (baseline)

`templates/registration.html` is entirely mock:
- The "ongoing registration" card hardcodes "2024/2025 Second Semester", a fake 65%-filled progress bar, static open/close dates, and "Min 15 | Max 24 credits" — none of it backed by any model.
- `pastRegistrations` is a hardcoded JS array of 5 fake records rendered client-side.
- The back-link and both action buttons (`continueRegistration()`, `viewCurrentCourses()`, `viewPastRegistration()`) are `alert()`/`console` demos — no real navigation or backend calls.

Route bug found during audit: `registration()` in `app.py` has **no `@login_required`** (unlike `dashboard()` and `profile()`, both fixed in the previous milestone). Combined with the `before_request` onboarding gate — which only acts when `current_user.is_authenticated` — this means an anonymous visitor can currently load `/registration` directly. Fixed as part of this milestone since the route is being rewritten anyway. The same missing-decorator issue likely exists on `add_drop`, `my_courses`, `payments_history`, and `pay_summary`, but those routes/pages are untouched by this milestone's scope, so they're left as a known issue, not fixed here.

`models.py` contains an unused `Payment` stub (`id` column only, no other fields, referenced nowhere in the codebase). It predates this feature and doesn't fit the shape needed here (it's not linked to a session/semester/period). Left as dead code, not repurposed — new models are added fresh.

No admin UI exists for configuring academic sessions, semesters, or registration periods. Building one is out of scope for this milestone (it's not listed in the deliverables); configuration is seeded via an extended `seed_dev_data.py`, the same mechanism used for demo students since Milestone 1. Models are shaped so a future admin UI can manage the same tables without schema changes.

## Open design question resolved

`doc/t.txt` (the workflow doc) flags an open question: *"how would we identify if there's any ongoing registration? are there specific periods, or does the admin toggle registrations on/off?"*

Resolved as **both**: an admin marks exactly one `RegistrationPeriod` row `is_active=True` (which period is "live" right now), and within that period, whether registration is actually open right now is still date-driven (`opens_at` / `closes_at`). This keeps the countdown and open/not-yet-open/closed states automatic (no daily admin babysitting) while giving admins control over which session/semester is current.

## Data model (`models.py`)

```python
class AcademicSession(db.Model):
    __tablename__ = 'academic_sessions'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(20), unique=True, nullable=False)  # e.g. "2025/2026"
    is_current = db.Column(db.Boolean, default=False, nullable=False)

class Semester(db.Model):
    __tablename__ = 'semesters'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)  # e.g. "First Semester"
    order = db.Column(db.Integer, nullable=False)  # 1, 2 — for sorting/next-semester logic

class RegistrationPeriod(db.Model):
    __tablename__ = 'registration_periods'
    id = db.Column(db.Integer, primary_key=True)
    academic_session_id = db.Column(db.Integer, db.ForeignKey('academic_sessions.id'), nullable=False)
    semester_id = db.Column(db.Integer, db.ForeignKey('semesters.id'), nullable=False)
    opens_at = db.Column(db.DateTime, nullable=False)
    closes_at = db.Column(db.DateTime, nullable=False)
    min_credits = db.Column(db.Integer, nullable=False)
    max_credits = db.Column(db.Integer, nullable=False)
    registration_fee = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(LAGOS_TZ))

    academic_session = db.relationship('AcademicSession')
    semester = db.relationship('Semester')

class DepartmentRegistrationRule(db.Model):
    __tablename__ = 'department_registration_rules'
    id = db.Column(db.Integer, primary_key=True)
    registration_period_id = db.Column(db.Integer, db.ForeignKey('registration_periods.id'), nullable=False)
    department = db.Column(db.String(150), nullable=False)  # matches User.department
    min_credits = db.Column(db.Integer, nullable=True)   # overrides period default when set
    max_credits = db.Column(db.Integer, nullable=True)
    registration_fee = db.Column(db.Numeric(10, 2), nullable=True)

    __table_args__ = (db.UniqueConstraint('registration_period_id', 'department'),)

class StudentRegistration(db.Model):
    __tablename__ = 'student_registrations'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    registration_period_id = db.Column(db.Integer, db.ForeignKey('registration_periods.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='registered')  # 'registered' | 'cancelled'
    payment_status = db.Column(db.String(20), nullable=False, default='pending')  # 'pending' | 'paid' | 'failed'
    payment_reference = db.Column(db.String(100), nullable=True)
    credits_registered = db.Column(db.Integer, nullable=False, default=0)  # populated by future Add/Drop milestone
    registered_at = db.Column(db.DateTime, default=lambda: datetime.now(LAGOS_TZ))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(LAGOS_TZ), onupdate=lambda: datetime.now(LAGOS_TZ))

    __table_args__ = (db.UniqueConstraint('user_id', 'registration_period_id'),)

    registration_period = db.relationship('RegistrationPeriod')
```

The `UniqueConstraint('user_id', 'registration_period_id')` is the DB-level enforcement of "prevent duplicate registrations" — the service layer also checks this explicitly first, to return a clean error message instead of relying on a raw `IntegrityError`.

No Alembic migration; the dev SQLite database continues to be rebuilt via `db.create_all()`, consistent with prior milestones.

## Service layer (`services/registration.py`)

New module. All business logic lives here — routes stay thin.

```python
class RegistrationError(Exception):
    """Raised for any business-rule violation in the registration flow.
    Carries a user-facing message; routes catch this and return it as a 400."""

def get_active_period():
    """Return the RegistrationPeriod with is_active=True, or None if none configured."""

def get_window_status(period):
    """Return 'not_yet_open' | 'open' | 'closed' by comparing now() (Lagos TZ) to
    period.opens_at / period.closes_at. period must not be None."""

def get_credit_limits(period, department):
    """Return (min_credits, max_credits, registration_fee) for a department, using the
    DepartmentRegistrationRule override when one exists (falling back field-by-field
    to the period's defaults for any override left unset), else the period defaults."""

def get_registration_status_context(user):
    """Assemble everything the registration page needs for the current student:
    active period (or None), window status, resolved credit limits, and the
    student's StudentRegistration for that period (or None if not yet registered)."""

def register_student(user, period):
    """Validate (window must be 'open'; user must not already have a StudentRegistration
    for this period) and create one with payment_status='paid' and a simulated
    payment_reference. Raises RegistrationError on any violation. Returns the created record.
    # TODO: replace the simulated payment_reference/payment_status with a real Remita
    # payment-initiation + webhook-verified confirmation when that integration is built.
    """

def get_registration_history(user):
    """Return the student's past StudentRegistration records (all of them, including
    the current period's if any), newest first, with period/session/semester eager-loaded
    for display."""
```

## Route changes (`app.py`)

- `registration()`: add `@login_required` (bug fix, see audit). Render `registration.html` with `status=get_registration_status_context(current_user)` and `history=get_registration_history(current_user)`.
- New `POST /registration/register`, `@login_required`: calls `register_student`, catching `RegistrationError` → `{'success': False, 'message': str(e)}, 400`. On success, returns `{'success': True, 'message': ..., 'registration': {...}}` with enough fields (session name, semester name, payment reference, credits) for the JS to update the page without a full reload.

No change to the `before_request` onboarding gate — `registration` isn't in the exempt list, so it already requires the full auth→onboarding→email-verified gate to pass before a student can reach it, which is correct (a student shouldn't register for courses before finishing onboarding).

## UI (`registration.html`, kept as the same page/URL, mock JS removed)

Server-rendered via Jinja from `status`/`history` context (no more client-side mock array). State resolution order: existing registration is checked first (a student who registered while the window was open still sees the confirmation state after the window later closes); only when there's no existing registration does window status (`not_yet_open` / `open` / `closed`) decide which card to show. States:

- **No active period configured** (`status.period is None`): informational empty state — "No registration is currently available. Check back soon." No Register Now button.
- **Not yet open** (`window_status == 'not_yet_open'`): card shows session/semester/dates/credit limits/fee, badge "Opens soon", a live countdown to `opens_at`, Register Now button disabled.
- **Open, not yet registered** (`window_status == 'open'`, no existing `StudentRegistration`): full card as specified — session, semester, open/close dates, live countdown to `closes_at`, min/max credits, fee, badge "Registration Open", enabled "Register Now" button.
- **Open, already registered**: card switches to a "You're registered ✓" confirmation state showing the stored registration's details (payment reference, date, credits) instead of the button. No link into Add/Drop (that page doesn't handle real data yet — out of scope this milestone), just a note that course selection opens separately.
- **Closed** (`window_status == 'closed'`, no registration): badge "Registration Closed", Register Now button disabled/hidden, explanatory message.

**Register Now flow:** click → confirm (simple `confirm()`-style inline prompt, consistent with the existing page's lightweight interaction style) → `postJson('/registration/register', {})` (new `static/js/registration/registration.js` ES module, following the `onboarding.js`/`password-change.js` pattern, using the existing `shared/api.js` + `shared/toast.js`) → on success, re-render the card into the "registered" state and show a success toast; on error, show the error message from the response as an error toast. Loading state: button shows a spinner/disables itself for the duration of the request (matching existing `.btn-primary` disabled styling conventions already used elsewhere, or added minimally if none exists).

**Registration History:** each `StudentRegistration` renders as a `.reg-item` (existing markup/CSS reused) showing session, semester, registration date, status, payment status. "View Details" toggles an inline expand within the row (no new modal system, no new page) revealing credits registered, payment reference, and full timestamp. Empty state (no history at all) reuses the existing `.empty-state` CSS class already defined in `registration.css`.

`registration.css` is extended (not replaced) with styles for the new states (registered-confirmation card, disabled countdown states, expand/collapse detail panel) — existing rules for `.ongoing-card`, `.reg-item`, `.status-badge`, `.empty-state`, `.toast-msg` etc. are reused as-is.

## Business rules enforced

- **Duplicate registration**: DB unique constraint on `(user_id, registration_period_id)` + explicit service-layer check before insert (clean error message, not a raw integrity error).
- **Outside allowed period**: `register_student` re-checks `get_window_status(period) == 'open'` server-side — never trusts the client's rendered state (a stale page open past the deadline can't sneak a registration through).
- **Onboarding completeness**: already enforced by the existing `before_request` gate for every route reaching `registration()`/`/registration/register`.
- **Timestamps & audit**: `registered_at` set on creation, `updated_at` auto-updates, `payment_reference` recorded (simulated now, real Remita reference later per the TODO).

## Demo data (`seed_dev_data.py`)

Extend the script to also seed, idempotently (skip if already present):
- Two `Semester` rows: "First Semester" (order 1), "Second Semester" (order 2).
- One `AcademicSession`: "2025/2026" (`is_current=True`), matching the seeded students' existing `session` field.
- Two `RegistrationPeriod` rows so both the "open" and "not yet open" scenarios are testable out of the box:
  - 2025/2026 First Semester: `is_active=True`, `opens_at` in the past, `closes_at` a few weeks in the future (currently **open**), `min_credits=15`, `max_credits=24`, `registration_fee=45000`.
  - 2025/2026 Second Semester: `is_active=False`, both dates in the future (**not yet open** — also exercises the "no active period" path implicitly via `is_active`, and the not-yet-open path if toggled active later for manual testing).
- One `DepartmentRegistrationRule` for "Information Technology" on the active period (slightly different credit limits) to exercise the override path.
- One pre-existing `StudentRegistration` for demo student `2308-2301-0004` (David Adeyemi, already fully onboarded) against the active period, so the "already registered" state and registration history are both viewable without manually registering first.

## Testing approach

No automated test framework exists in this repo (established convention). Verification is manual via `test_client`/`render_template`, per the pattern used in prior milestones, covering the 6 scenarios from the deliverables:
- Registration open (unregistered demo student) → full card + enabled button.
- Registration closed (toggle a period's dates into the past) → closed state, no button.
- Already registered (demo student 0004) → confirmation state, no duplicate button.
- Registration not yet opened (the seeded Second Semester period) → countdown-to-open state.
- Registration history exists (demo student 0004) → history list renders the seeded record.
- Registration history empty (a freshly onboarded student with no `StudentRegistration` rows) → empty state renders.

Plus: `POST /registration/register` rejected outside the open window (400 + `RegistrationError` message), rejected on duplicate attempt (400), and the `registration()` route now requires login (anonymous request redirects to `/login`, not a crash or mock render).

## Out of scope (explicitly, per milestone instructions)

- Course Add/Drop (`add_drop.html`, `my_courses.html`) — next milestone.
- Real Remita payment integration — marked with `# TODO` comments in `register_student`.
- Admin UI for managing sessions/periods/rules — configuration is seed-script-only for now.
- Fixing the missing `@login_required` on `add_drop`, `my_courses`, `payments_history`, `pay_summary` — noted as a known pre-existing issue, not fixed here (those pages/routes aren't touched by this milestone).
