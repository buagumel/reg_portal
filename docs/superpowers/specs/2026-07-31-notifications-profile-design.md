# Notification Management + Profile Management — Design Spec

Date: 2026-07-31
Status: Approved
Scope: Replace the mocked `announcements.html` with a real, database-driven notification system (Feature 7), and extend the already-partially-wired `profile.html` with full secure profile editing — address, emergency contact, blood group, and profile picture upload/replace/delete (Feature 8). Payments (Feature 9) is explicitly out of scope.

## Goal

Give every other feature in this app a single, reusable way to notify a student about something that happened (`NotificationService`), and give students a real, auditable way to manage their own contact/profile information.

## Audit findings (baseline)

`templates/announcements.html` is entirely mock: hardcoded summary numbers (24/8/5/12), a static list of 7 notification `<div>`s with fabricated content, filter tabs that don't match the real category taxonomy (`announcements`/`deadlines`/`payments`/`events` vs. the required Registration/Payments/Courses/Academic/Profile/System/Announcements), no priority or date-range filtering, and every action (`dismissNotification`, `markAllReadDemo`, `markVisibleAsRead`) mutates the DOM only — nothing persists.

`app.py`'s `announcements()` route has no `@login_required` — same bug class fixed on every other route touched in a prior milestone (`dashboard`, `profile`, `registration`, `add_drop`, `my_courses`). Fixed here since the route is being rewritten.

`templates/profile.html` is *not* a fresh mock — it already has real, working AJAX flows from earlier milestones: `/update-profile` (phone only), `/change-password`, and a full email-change OTP flow (`/send-email-code` + `/verify-email-code`, reusing `onboarding_helpers`' OTP session functions). This milestone extends that existing wiring rather than replacing it:
- Address is currently a **display-only** `<span>` (`displayAddressField`) — needs to become an editable input, matching the existing Phone input's markup pattern.
- Emergency Contact and Blood Group **don't exist anywhere** — no UI field, no model column.
- The avatar edit button (`editAvatarBtn`) calls `prompt('Enter icon name...')` and swaps in a Font Awesome icon — entirely fake. Needs a real file-picker upload flow.
- No "remove profile picture" affordance exists.

No `Notification`, `AuditLog` model, and no `User.emergency_contact` / `User.blood_group` / `User.updated_at` columns exist yet.

## Scope decision: time-based automatic notifications

Two of the required automatic-notification triggers — "registration opens" and "registration closes soon" — are time-based system events, not responses to a student action. This codebase has no task scheduler (no Celery, no APScheduler, nothing in `requirements.txt`), and adding one is significant new infrastructure well outside this milestone's scope.

Resolved as: generate these two opportunistically, checked once per relevant page load (`dashboard()` and `registration()`), idempotent per `(user, period, trigger)` so a repeat visit never creates a duplicate. This is not a true background job, but is functionally equivalent from the student's perspective in a system where nothing runs when no one is browsing anyway.

## Data model (`models.py`)

```python
class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(20), nullable=False)   # registration|payments|courses|academic|profile|system|announcements
    priority = db.Column(db.String(10), nullable=False, default='medium')  # critical|high|medium|low
    related_url = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
    read_at = db.Column(db.DateTime, nullable=True)        # NULL = unread
    archived_at = db.Column(db.DateTime, nullable=True)    # NULL = not archived
    deleted_at = db.Column(db.DateTime, nullable=True)     # NULL = not deleted (soft delete)


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)   # e.g. 'phone_updated', 'password_changed', 'profile_picture_updated'
    details = db.Column(db.Text, nullable=True)          # short human-readable summary — never a password or OTP code
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
```

Extend `User` with 3 new columns:
```python
emergency_contact = db.Column(db.String(150), nullable=True)
blood_group = db.Column(db.String(5), nullable=True)
updated_at = db.Column(db.DateTime, default=now_lagos, onupdate=now_lagos, nullable=False)
```

No Alembic migration (established convention — `db.create_all()`; the `updated_at` addition to the existing `users` table needs the same "delete-or-ALTER the dev DB" handling documented in prior milestones' plans, since SQLite can't add a column to an existing table via `create_all()` alone).

## Service layer

**`services/audit.py`** — the simplest layer, no dependencies on anything else in this feature:
```python
def log_action(user, action, details=None, ip_address=None):
    """Insert one AuditLog row. `details` must never contain a password or OTP code."""
```

**`services/notification.py`** — the reusable core every other module (existing and future) calls into:
```python
def create_notification(user, title, message, category, priority='medium', related_url=None):
    """The single creation path. Every other service that needs to notify a
    student calls this — never constructs a Notification row directly."""

def get_notifications(user, category=None, priority=None, read_status=None,
                       date_from=None, date_to=None, search=None, archived=False):
    """Non-deleted notifications, newest first, with optional filters.
    archived=False (default) returns the main inbox (archived_at IS NULL);
    archived=True returns only archived rows (archived_at IS NOT NULL) —
    a clean boolean toggle, not two separate query shapes."""

def get_summary_counts(user):
    """Return {'total', 'unread', 'read', 'archived'}. total/unread/read are
    computed over non-deleted, non-archived rows; archived is its own bucket
    (deleted_at IS NULL AND archived_at IS NOT NULL)."""

def mark_read(user, notification_id):
def mark_unread(user, notification_id):
def mark_all_read(user):
def archive_notification(user, notification_id):
def delete_notification(user, notification_id):  # soft delete: sets deleted_at

def notify_registration_window_events(user):
    """Opportunistic, idempotent: called from dashboard()/registration().
    Checks the active RegistrationPeriod against now_lagos() and creates
    at most one 'registration_open' and one 'registration_closing_soon'
    notification per (user, period) — never duplicates on repeat visits."""
```

Every `mark_*`/`archive_notification`/`delete_notification` function takes `user` and looks up the notification scoped to `user_id == user.id` — a request for a notification belonging to someone else returns a clean "not found" rather than ever touching another student's row. This is the ownership-validation requirement, satisfied structurally rather than as a bolted-on check.

**`services/profile.py`** — every write function here performs all four of the "every profile update should..." requirements by construction: it operates only on the `user` object passed in (never an arbitrary id from client input — that's what "validate ownership" means in a single-tenant-per-request Flask-Login app), it writes through `User.updated_at`'s `onupdate=now_lagos`, and it always calls both `log_action` and `create_notification` before returning.

```python
def update_contact_info(user, phone=None, address=None, emergency_contact=None, blood_group=None):
    """Update whichever of the 4 fields were actually provided (None means
    'not being changed', not 'clear this field' — a student who only fills
    in the Address input on a partial form shouldn't accidentally wipe their
    blood group). Logs one AuditLog + one Notification summarizing what changed."""

def change_password(user, current_password, new_password, confirm_password):
    """Same validation this app already uses at onboarding
    (auth_helpers.validate_password_strength) — reused, not reimplemented.
    Raises ValueError with a user-facing message on any validation failure
    (current password wrong, new/confirm mismatch, policy violation)."""

def update_profile_picture(user, file_storage):
    """Reuses onboarding_helpers.save_profile_picture for validation
    (type/size) and storage. If the user already had a picture, the old
    file is deleted from disk after the new one is saved (replace, not
    accumulate)."""

def delete_profile_picture(user):
    """Deletes the file from disk (if present) and clears User.profile_picture."""
```

`services/registration.py` (existing, extended minimally): `register_student` and `submit_registration` each gain one `create_notification(...)` call at their existing success point — "payment completed" and "course registration submitted" respectively. This is the one place an already-shipped module is touched, and it's additive only (one new line at an existing success path, not a change to any existing behavior).

`app.py`'s `onboarding_complete()` route gains one `create_notification(...)` call after `onboarding_completed = True` is set.

No new `OTPService` file — the email-change OTP flow (`onboarding_helpers.start_otp_session` / `register_failed_otp_attempt` / `otp_attempts_exceeded` / `clear_otp_session`, driving `app.py`'s existing `/send-email-code` and `/verify-email-code` routes) already exists and keeps working unchanged; this satisfies "reuse existing implementation" literally. `verify_email_code()` gains `log_action` + `create_notification` calls on success ("email changed").

## Routes (`app.py`)

- `announcements()`: add `@login_required` (bug fix). Renders `announcements.html` with `summary=get_summary_counts(current_user)` and an initial `notifications=get_notifications(current_user)` (unfiltered first page) — filtering/search happen via AJAX against a new JSON endpoint so the page doesn't need a full reload per filter change, matching the existing tab-based filter UI's instant-feedback feel.
- `GET /notifications/data` — JSON, accepts query params `category`, `priority`, `read_status`, `date_from`, `date_to`, `search`, `archived` (bool) — calls `get_notifications`/`get_summary_counts` and returns both the filtered list and fresh summary counts in one payload (so the summary cards update live without a second request).
- `POST /notifications/<id>/read` — mark read.
- `POST /notifications/<id>/unread` — mark unread.
- `POST /notifications/<id>/archive` — archive.
- `POST /notifications/<id>/delete` — soft delete.
- `POST /notifications/mark-all-read` — mark all read.
- `POST /update-profile`: extended to accept `phone`, `address`, `emergency_contact`, `blood_group` (any subset — omitted keys are left unchanged), delegating to `services.profile.update_contact_info`.
- `POST /change-password`: unchanged request/response shape, but its body now delegates to `services.profile.change_password` instead of inline validation (refactor — "move business logic into services").
- `POST /profile/picture` — multipart form upload, delegates to `update_profile_picture`.
- `POST /profile/picture/delete` — delegates to `delete_profile_picture`.
- `dashboard()` and `registration()`: each gains one call to `notify_registration_window_events(current_user)` before rendering (the opportunistic trigger described above).

No new routes get added to `enforce_onboarding_gate`'s `exempt_endpoints` — all new endpoints stay behind the full gate except `announcements`/its data endpoint follow the same pattern as every other already-gated page.

## UI

**`announcements.html`** — markup/CSS structure kept (summary-grid, filter-bar, notifications-list, pagination). Changes:
- Summary cards render real counts from `summary` on initial load, then update live from each AJAX response's fresh counts (no page reload needed after an action).
- Filter tabs become the 7 real categories + "All" + "Unread" (relabeling `data-filter` values to match; same tab-button markup/CSS).
- Filter bar gains: a search input (mirroring `payments_history.html`'s `.search-box` pattern), a priority `<select>`, and two date inputs (from/to) — new elements, but styled with the same existing input conventions used elsewhere in this app, not a new design language.
- Each notification's footer gains real action buttons: Mark Read/Unread (toggle depending on current state), Archive, Delete — small icon buttons added alongside the existing action-link, replacing the fake `dismiss-btn`'s demo behavior with real POSTs.
- List items render server-side from real `Notification` rows (category/priority/timestamp/read-state driving the same CSS classes the mock already defines — `priority-high`, `priority-medium`, etc. get reused, just driven by real data instead of hardcoded per-item classes).
- Empty state when a filter matches nothing reuses the existing `.empty-state` pattern already established elsewhere in this app.

**`profile.html`** — extends the existing Edit Profile tab:
- Address's `<span class="field-display">` becomes an `<input>`, identical treatment to the existing Phone input.
- Two new fields added in the same `.double-field` row pattern: Emergency Contact (text input) and Blood Group (text input or a small fixed `<select>` — a short list is more consistent with a real hospital form, so `<select>` with options A+/A-/B+/B-/AB+/AB-/O+/O-/Unknown).
- The single "Update Phone" button becomes "Save Changes" and its POST body includes all 4 editable text fields.
- Avatar edit: the camera-icon button now triggers a hidden `<input type="file">` instead of `prompt()`; on file selection, POSTs to `/profile/picture` (multipart) and updates the displayed avatar `<img>` on success. A small "Remove photo" link appears next to the camera icon only when `current_user.profile_picture` is set, POSTing to `/profile/picture/delete`.
- Password change tab: no UI change (already real) — only its backend delegates to the new service.

## Business rules / security

- Every `ProfileService` write is scoped to the passed-in `user` object only — never accepts a user id from request data, so there's no cross-user write surface to defend against.
- `change_password` re-validates the current password server-side before accepting a new one (already true in the existing route; preserved).
- Profile picture upload reuses the existing size/type validation (`onboarding_helpers.ALLOWED_PICTURE_EXTENSIONS`, `MAX_PICTURE_SIZE_BYTES`) — no new validation logic invented.
- `AuditLog.details` must never contain a password, OTP code, or full profile-picture binary — only short human-readable summaries (e.g. `"phone: 0801... -> 0802..."`, `"profile picture replaced"`).
- Notification/AuditLog rows are never exposed cross-user: every read/write in `services/notification.py` filters by `user_id == user.id`.

## Demo data (`seed_dev_data.py`)

Extend, idempotently: seed a handful of `Notification` rows for the fully-onboarded demo students (a mix of categories/priorities/read-states, including at least one archived and one that exercises `related_url`) so the Notifications page has real content to browse without needing to trigger every automatic-notification path manually first. Also seed `emergency_contact`/`blood_group` values for at least one demo student, leaving another `None` to exercise the profile page's empty-field display.

## Testing approach

Manual verification via `test_client`/`render_template`, per established project convention (no automated test framework in this repo), covering: notification CRUD (mark read/unread, archive, soft-delete, mark-all-read) each scoped correctly to the acting user; every filter combination (category, priority, read status, date range, search) against seeded data; summary counts staying consistent after each action; the automatic-notification triggers (onboarding complete, payment/registration completed, course registration submitted, profile updated, email changed, password changed) each producing exactly one notification per real event; the opportunistic registration-window notifications firing once and not duplicating on a second page load; profile contact-info update (partial payloads don't clobber untouched fields); profile picture upload/replace (old file removed)/delete; each `ProfileService` write producing both an `AuditLog` row and a `Notification`; and the `announcements`/`profile` routes requiring login.

## Out of scope

- Feature 9 (Payments) — explicitly deferred per the milestone instructions.
- A real background scheduler for time-based notifications — replaced with the opportunistic on-page-load check described above.
- Push notifications / email notifications for the Notification model itself (this feature is in-app only; the existing `Message`/`mail.send` usage elsewhere is unrelated and untouched).
- An admin UI for composing/broadcasting notifications — out of scope; all notification creation in this milestone is triggered by the student's own actions or system events, not admin-authored content.
