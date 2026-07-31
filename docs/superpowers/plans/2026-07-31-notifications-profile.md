# Notification Management + Profile Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the mocked `announcements.html` with a real notification system, and extend the already-partially-wired `profile.html` with full secure profile editing, per `docs/superpowers/specs/2026-07-31-notifications-profile-design.md`.

**Architecture:** Two new models (`Notification`, `AuditLog`) plus three new `User` columns; three new/extended service modules (`services/audit.py`, `services/notification.py`, `services/profile.py`); minimal additive hooks into two already-shipped modules (`services/registration.py`, and four existing `app.py` routes) so every relevant student action creates a notification; new routes for notification CRUD and profile-picture management; `announcements.html` rewired to real AJAX-driven data (matching the Add/Drop page's proven "keep the JS, swap the data source" pattern); `profile.html` extended in place with new editable fields and a real avatar upload flow.

**Tech Stack:** Flask, Flask-SQLAlchemy (SQLite dev DB), vanilla ES module JS, Jinja2.

## Global Constraints

- No Alembic migration — dev DB rebuilt via `db.create_all()`. The `updated_at` column added to the *existing* `users` table needs the same handling prior milestones used: SQLite can't `ALTER` an existing table via `create_all()` alone. **Prefer a direct `ALTER TABLE users ADD COLUMN updated_at DATETIME` via raw SQL over deleting the dev DB** (per the precedent set finishing the previous milestone — preserves real seeded/test data). Same for `emergency_contact`/`blood_group`.
- No automated test framework — verification is manual via throwaway `test_client`/`render_template` scripts, created/run/deleted, never committed.
- All datetime columns use `now_lagos()` — never a tz-aware `datetime`.
- Every `Notification`/`AuditLog` read or write in `services/notification.py` must filter by `user_id == user.id` — never accept or trust a user id from request data for these lookups.
- `AuditLog.details` must never contain a password or OTP code.
- `services/notification.py` must not import anything from `services/registration.py` at module load time in a way that creates a cycle — `services/registration.py` already imports from `services/notification.py` in this plan (Task 4), so the dependency must stay one-directional. `notify_registration_window_events` (which does need `get_active_period`/`get_window_status`) imports them with a local `from services.registration import ...` inside the function body, not at module top level, to avoid a load-time cycle.
- Do not touch `services/course.py`, `services/course_history.py`, `services/validation.py`, or any Add/Drop/My Courses template — out of scope for this milestone.
- Feature 9 (Payments) is out of scope — do not implement it.

---

### Task 1: Data Models

**Files:**
- Modify: `models.py`

**Interfaces:**
- Produces: `Notification(id, user_id, title, message, category, priority, related_url, created_at, read_at, archived_at, deleted_at)`; `AuditLog(id, user_id, action, details, ip_address, created_at)`; `User.emergency_contact`, `User.blood_group`, `User.updated_at` (new columns).

- [ ] **Step 1: Add the three new columns to `User`**

In `models.py`, find the `User` class. Immediately after the `session = db.Column(db.String(20))` line, add:
```python
    emergency_contact = db.Column(db.String(150), nullable=True)
    blood_group = db.Column(db.String(5), nullable=True)
    updated_at = db.Column(db.DateTime, default=now_lagos, onupdate=now_lagos, nullable=False)
```

- [ ] **Step 2: Add the two new model classes**

At the end of `models.py`, append:
```python

class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(20), nullable=False)
    priority = db.Column(db.String(10), nullable=False, default='medium')
    related_url = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
    read_at = db.Column(db.DateTime, nullable=True)
    archived_at = db.Column(db.DateTime, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
```

- [ ] **Step 3: Handle the existing `users` table's new column, then boot check**

Check whether `instance/database.db` already has a `users` table (it almost certainly does, from prior milestones):
```bash
python -c "
import sqlite3
con = sqlite3.connect('instance/database.db')
cols = [r[1] for r in con.execute('PRAGMA table_info(users)')]
print('has updated_at:', 'updated_at' in cols)
con.close()
"
```
If it prints `has updated_at: False` (expected), add the column directly without losing existing data:
```bash
python -c "
import sqlite3
con = sqlite3.connect('instance/database.db')
con.execute('ALTER TABLE users ADD COLUMN emergency_contact VARCHAR(150)')
con.execute('ALTER TABLE users ADD COLUMN blood_group VARCHAR(5)')
con.execute(\"ALTER TABLE users ADD COLUMN updated_at DATETIME NOT NULL DEFAULT '2026-01-01 00:00:00'\")
con.commit()
con.close()
print('columns added')
"
```
(SQLite requires a literal default when adding a `NOT NULL` column to a non-empty table — the placeholder default is harmless since the ORM's `onupdate`/`default=now_lagos` takes over for every future write.)

Then run: `python -c "import app; print('OK')"` — expect `OK` (this also creates the two new tables via `create_all()`, which works fine for brand-new tables).

Verify:
```bash
python -c "
from app import app
from models import db
with app.app_context():
    tables = db.inspect(db.engine).get_table_names()
    assert 'notifications' in tables and 'audit_logs' in tables
    cols = [c['name'] for c in db.inspect(db.engine).get_columns('users')]
    assert all(c in cols for c in ('emergency_contact', 'blood_group', 'updated_at'))
    print('Schema verified')
"
```

- [ ] **Step 4: Commit**
```bash
git add models.py
git commit -m "feat: add Notification and AuditLog models, extend User with emergency_contact/blood_group/updated_at"
```

---

### Task 2: Audit and Notification Services

**Files:**
- Create: `services/audit.py`
- Create: `services/notification.py`

**Interfaces:**
- Produces: `log_action(user, action, details=None, ip_address=None)`; `create_notification(user, title, message, category, priority='medium', related_url=None)`; `get_notifications(user, category=None, priority=None, read_status=None, date_from=None, date_to=None, search=None, archived=False)`; `get_summary_counts(user) -> dict`; `mark_read(user, id)`; `mark_unread(user, id)`; `mark_all_read(user)`; `archive_notification(user, id)`; `delete_notification(user, id)`; `notify_registration_window_events(user)`.

- [ ] **Step 1: Create `services/audit.py`**
```python
from models import db, AuditLog


def log_action(user, action, details=None, ip_address=None):
    """Insert one AuditLog row. `details` must never contain a password or OTP code."""
    entry = AuditLog(
        user_id=user.id,
        action=action,
        details=details,
        ip_address=ip_address,
    )
    db.session.add(entry)
    db.session.commit()
    return entry
```

- [ ] **Step 2: Create `services/notification.py`**
```python
from datetime import timedelta

from models import db, now_lagos, Notification


def create_notification(user, title, message, category, priority='medium', related_url=None):
    """The single creation path — every other module that needs to notify a
    student calls this, never constructs a Notification row directly."""
    notification = Notification(
        user_id=user.id,
        title=title,
        message=message,
        category=category,
        priority=priority,
        related_url=related_url,
    )
    db.session.add(notification)
    db.session.commit()
    return notification


def get_notifications(user, category=None, priority=None, read_status=None,
                       date_from=None, date_to=None, search=None, archived=False):
    """Non-deleted notifications, newest first, with optional filters.
    archived=False (default) returns the main inbox (archived_at IS NULL);
    archived=True returns only archived rows (archived_at IS NOT NULL)."""
    query = Notification.query.filter_by(user_id=user.id, deleted_at=None)

    if archived:
        query = query.filter(Notification.archived_at.isnot(None))
    else:
        query = query.filter(Notification.archived_at.is_(None))

    if category:
        query = query.filter_by(category=category)
    if priority:
        query = query.filter_by(priority=priority)
    if read_status == 'unread':
        query = query.filter(Notification.read_at.is_(None))
    elif read_status == 'read':
        query = query.filter(Notification.read_at.isnot(None))
    if date_from:
        query = query.filter(Notification.created_at >= date_from)
    if date_to:
        query = query.filter(Notification.created_at <= date_to)
    if search:
        like = f'%{search}%'
        query = query.filter(db.or_(Notification.title.ilike(like), Notification.message.ilike(like)))

    return query.order_by(Notification.created_at.desc()).all()


def get_summary_counts(user):
    """Return {'total', 'unread', 'read', 'archived'}. total/unread/read are
    computed over non-deleted, non-archived rows; archived is its own bucket."""
    base = Notification.query.filter_by(user_id=user.id, deleted_at=None)
    total = base.filter(Notification.archived_at.is_(None)).count()
    unread = base.filter(Notification.archived_at.is_(None), Notification.read_at.is_(None)).count()
    read = total - unread
    archived = base.filter(Notification.archived_at.isnot(None)).count()
    return {'total': total, 'unread': unread, 'read': read, 'archived': archived}


def _get_owned(user, notification_id):
    return Notification.query.filter_by(id=notification_id, user_id=user.id, deleted_at=None).first()


def mark_read(user, notification_id):
    notification = _get_owned(user, notification_id)
    if notification is None:
        return None
    if notification.read_at is None:
        notification.read_at = now_lagos()
        db.session.commit()
    return notification


def mark_unread(user, notification_id):
    notification = _get_owned(user, notification_id)
    if notification is None:
        return None
    notification.read_at = None
    db.session.commit()
    return notification


def mark_all_read(user):
    now = now_lagos()
    Notification.query.filter_by(user_id=user.id, deleted_at=None, read_at=None).update({'read_at': now})
    db.session.commit()


def archive_notification(user, notification_id):
    notification = _get_owned(user, notification_id)
    if notification is None:
        return None
    notification.archived_at = now_lagos()
    db.session.commit()
    return notification


def delete_notification(user, notification_id):
    notification = _get_owned(user, notification_id)
    if notification is None:
        return None
    notification.deleted_at = now_lagos()
    db.session.commit()
    return notification


def notify_registration_window_events(user):
    """Opportunistic, idempotent per (user, period, trigger) — called once
    per dashboard/registration page load. No task scheduler exists in this
    codebase, so this is checked on-demand instead of via a background job.
    Uses a fixed related_url per (period, trigger) as the dedupe key, since
    it's a real navigable URL anyway and needs no separate tracking table."""
    from services.registration import get_active_period, get_window_status

    period = get_active_period()
    if period is None:
        return

    status = get_window_status(period)
    now = now_lagos()

    def already_notified(marker_url):
        return Notification.query.filter_by(user_id=user.id, related_url=marker_url).first() is not None

    if status == 'open':
        marker = f'/registration?opened={period.id}'
        if not already_notified(marker):
            create_notification(
                user, 'Registration is open',
                f'Registration for {period.academic_session.name} {period.semester.name} is now open.',
                category='registration', priority='high', related_url=marker,
            )
        if (period.closes_at - now) <= timedelta(days=3):
            closing_marker = f'/registration?closing={period.id}'
            if not already_notified(closing_marker):
                create_notification(
                    user, 'Registration closes soon',
                    f'Registration for {period.academic_session.name} {period.semester.name} closes on {period.closes_at.strftime("%d %b %Y")}.',
                    category='registration', priority='high', related_url=closing_marker,
                )
```

- [ ] **Step 3: Manual verification**

Run: `python -c "import app; print('OK')"` — expect `OK`.

Write a throwaway `scratch_verify_notification.py`:
```python
from app import app
from models import db, User
from services.notification import (
    create_notification, get_notifications, get_summary_counts,
    mark_read, mark_unread, mark_all_read, archive_notification, delete_notification,
)

with app.app_context():
    user = User.query.filter_by(reg_no='2308-2301-0003').first()
    assert user is not None, 'run seed_dev_data.py first'

    n1 = create_notification(user, 'Test A', 'Message A', category='system', priority='low')
    n2 = create_notification(user, 'Test B', 'Message B', category='academic', priority='high')

    counts = get_summary_counts(user)
    assert counts['unread'] >= 2, counts

    notifications = get_notifications(user, category='system')
    assert any(n.id == n1.id for n in notifications)
    assert not any(n.id == n2.id for n in notifications)

    notifications = get_notifications(user, search='Message B')
    assert any(n.id == n2.id for n in notifications)

    mark_read(user, n1.id)
    counts_after = get_summary_counts(user)
    assert counts_after['unread'] == counts['unread'] - 1

    mark_unread(user, n1.id)
    assert get_summary_counts(user)['unread'] == counts['unread']

    archive_notification(user, n1.id)
    archived_list = get_notifications(user, archived=True)
    assert any(n.id == n1.id for n in archived_list)
    inbox_list = get_notifications(user, archived=False)
    assert not any(n.id == n1.id for n in inbox_list)

    delete_notification(user, n2.id)
    assert not any(n.id == n2.id for n in get_notifications(user))

    # ownership check: another user cannot mark this user's notification
    other = User.query.filter(User.id != user.id).first()
    assert mark_read(other, n1.id) is None

    mark_all_read(user)

    # cleanup
    from models import Notification
    Notification.query.filter(Notification.id.in_([n1.id, n2.id])).delete(synchronize_session=False)
    db.session.commit()

    print('All notification service checks passed')
```
Run it, expect `All notification service checks passed`. Delete the script afterward.

- [ ] **Step 4: Commit**
```bash
git add services/audit.py services/notification.py
git commit -m "feat: add audit and notification services"
```

---

### Task 3: Profile Service

**Files:**
- Create: `services/profile.py`

**Interfaces:**
- Consumes: `validate_password_strength` from `auth_helpers`; `save_profile_picture` from `onboarding_helpers`; `log_action` from `services.audit`; `create_notification` from `services.notification`.
- Produces: `update_contact_info(user, phone=None, address=None, emergency_contact=None, blood_group=None)`; `change_password(user, current_password, new_password, confirm_password)` (raises `ValueError` on any validation failure); `update_profile_picture(user, file_storage, upload_folder)` (raises `ValueError`); `delete_profile_picture(user, static_folder)` (raises `ValueError`).

- [ ] **Step 1: Create `services/profile.py`**
```python
import os

from models import db
from auth_helpers import validate_password_strength
from onboarding_helpers import save_profile_picture
from services.audit import log_action
from services.notification import create_notification


def update_contact_info(user, phone=None, address=None, emergency_contact=None, blood_group=None):
    """Update whichever fields are passed. None means 'not being changed' —
    callers that want to clear a field must pass an explicit empty string,
    not omit the argument."""
    changes = []
    if phone is not None:
        user.phone = phone
        changes.append('phone')
    if address is not None:
        user.address = address
        changes.append('address')
    if emergency_contact is not None:
        user.emergency_contact = emergency_contact
        changes.append('emergency contact')
    if blood_group is not None:
        user.blood_group = blood_group
        changes.append('blood group')

    if not changes:
        return user

    db.session.commit()

    log_action(user, 'profile_updated', details=f"Updated: {', '.join(changes)}")
    create_notification(
        user, 'Profile updated',
        f"Your {', '.join(changes)} {'was' if len(changes) == 1 else 'were'} updated.",
        category='profile', priority='low',
    )
    return user


def change_password(user, current_password, new_password, confirm_password):
    if not current_password:
        raise ValueError('Current password is required')
    if not user.check_password(current_password):
        raise ValueError('Current password is incorrect')

    failed_rules = validate_password_strength(new_password)
    if failed_rules:
        raise ValueError('Password must contain ' + ', '.join(failed_rules) + '.')
    if new_password != confirm_password:
        raise ValueError('Passwords do not match')

    user.set_password(new_password)
    db.session.commit()

    log_action(user, 'password_changed')
    create_notification(
        user, 'Password changed', 'Your account password was changed successfully.',
        category='profile', priority='medium',
    )
    return user


def update_profile_picture(user, file_storage, upload_folder):
    old_picture = user.profile_picture
    picture_path, error = save_profile_picture(file_storage, user.reg_no, upload_folder)
    if error:
        raise ValueError(error)

    user.profile_picture = picture_path
    db.session.commit()

    if old_picture and old_picture != picture_path:
        old_full_path = os.path.join(os.path.dirname(upload_folder), old_picture)
        if os.path.exists(old_full_path):
            os.remove(old_full_path)

    log_action(
        user, 'profile_picture_updated',
        details='profile picture replaced' if old_picture else 'profile picture uploaded',
    )
    create_notification(
        user, 'Profile picture updated', 'Your profile picture was updated successfully.',
        category='profile', priority='low',
    )
    return user


def delete_profile_picture(user, static_folder):
    if not user.profile_picture:
        raise ValueError('No profile picture to remove')

    full_path = os.path.join(static_folder, user.profile_picture)
    if os.path.exists(full_path):
        os.remove(full_path)

    user.profile_picture = None
    db.session.commit()

    log_action(user, 'profile_picture_deleted')
    create_notification(
        user, 'Profile picture removed', 'Your profile picture was removed.',
        category='profile', priority='low',
    )
    return user
```

- [ ] **Step 2: Manual verification**

Run: `python -c "import app; print('OK')"` — expect `OK`.

Write a throwaway `scratch_verify_profile.py`:
```python
from app import app
from models import db, User, AuditLog, Notification
from services.profile import update_contact_info, change_password

with app.app_context():
    user = User.query.filter_by(reg_no='2308-2301-0003').first()
    assert user is not None, 'run seed_dev_data.py first'

    original_phone = user.phone
    original_address = user.address

    update_contact_info(user, phone='08099999999', address='123 Test Street')
    assert user.phone == '08099999999'
    assert user.address == '123 Test Street'

    audit_count = AuditLog.query.filter_by(user_id=user.id, action='profile_updated').count()
    assert audit_count >= 1
    notif = Notification.query.filter_by(user_id=user.id, category='profile').order_by(Notification.id.desc()).first()
    assert notif is not None and 'updated' in notif.title.lower()

    # None means don't touch
    update_contact_info(user, phone='08088888888')
    assert user.address == '123 Test Street'

    try:
        change_password(user, 'wrong-password', 'NewPass123!', 'NewPass123!')
        raise SystemExit('expected ValueError for wrong current password')
    except ValueError:
        pass

    # restore original values
    update_contact_info(user, phone=original_phone or '', address=original_address or '')

    print('All profile service checks passed')
```
Run it, expect `All profile service checks passed`. Delete the script afterward.

- [ ] **Step 3: Commit**
```bash
git add services/profile.py
git commit -m "feat: add profile service (contact info, password change, profile picture)"
```

---

### Task 4: Integrate Notification/Audit Services into Existing Routes and Modules

**Files:**
- Modify: `services/registration.py`
- Modify: `app.py`

**Interfaces:**
- Consumes: `create_notification` from `services.notification`; `log_action` from `services.audit`; `update_contact_info`, `change_password` from `services.profile` (all from Tasks 2-3).

- [ ] **Step 1: Add a payment-completed notification to `register_student`**

Open `services/registration.py`. Add near the top, with the other imports:
```python
from services.notification import create_notification
```
Find `register_student`'s success path — the `registration = StudentRegistration(...)` block followed by `db.session.add(registration)` and the `try/except IntegrityError` around `db.session.commit()`. Immediately after that commit succeeds (i.e., right before `return registration`), add:
```python
    create_notification(
        user, 'Payment completed',
        f'Your registration payment for {period.academic_session.name} {period.semester.name} was completed successfully. Reference: {registration.payment_reference}.',
        category='payments', priority='high', related_url='/registration',
    )
```

- [ ] **Step 2: Add a course-submission notification to `submit_registration`**

In the same file, find `submit_registration`. After `student_registration.courses_submitted = True` and its `db.session.commit()`, and before `return student_registration`, add:
```python
    create_notification(
        user, 'Course registration submitted',
        f'Your course selection for {period.academic_session.name} {period.semester.name} has been submitted successfully.',
        category='courses', priority='high', related_url='/my_courses',
    )
```

- [ ] **Step 3: Add imports to `app.py`**

Add, alongside the existing `services.*` imports:
```python
from services.audit import log_action
from services.notification import (
    create_notification, get_notifications, get_summary_counts,
    mark_read, mark_unread, mark_all_read, archive_notification, delete_notification,
    notify_registration_window_events,
)
from services.profile import (
    update_contact_info, change_password as profile_change_password,
    update_profile_picture, delete_profile_picture,
)
```
(`change_password` is aliased to `profile_change_password` because `app.py` already has a route function named `change_password` — the import would otherwise shadow it.)

- [ ] **Step 4: Onboarding-complete notification**

Find `onboarding_complete()`. After `current_user.onboarding_completed = True` and its `db.session.commit()`, and before the existing `try: msg = Message(...)` welcome-email block, add:
```python
    create_notification(
        current_user, 'Welcome to the Student Portal',
        'Your profile setup is complete. Welcome aboard!',
        category='profile', priority='medium',
    )
```

- [ ] **Step 5: Email-change audit + notification**

Find `verify_email_code()`. After `current_user.email = pending_email` and `current_user.email_verified = True` and their `db.session.commit()`, and before `clear_otp_session(session)`, add:
```python
    log_action(current_user, 'email_changed', details=f'Email changed to {pending_email}')
    create_notification(
        current_user, 'Email address changed',
        f'Your account email was changed to {pending_email}.',
        category='profile', priority='medium',
    )
```

- [ ] **Step 6: Rewrite `update_profile()` to delegate to `services.profile`**

Replace the entire `update_profile()` function body (it currently starts with a stray `time.sleep(5)` — remove that too, it's leftover debug code with no legitimate purpose) with:
```python
@app.route('/update-profile', methods=['POST'])
@login_required
def update_profile():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    phone = data.get('phone', '').strip()
    if not phone:
        return jsonify({'success': False, 'message': 'Phone number is required'}), 400

    address = data.get('address', '').strip()
    emergency_contact = data.get('emergency_contact', '').strip()
    blood_group = data.get('blood_group', '').strip()

    update_contact_info(
        current_user, phone=phone, address=address,
        emergency_contact=emergency_contact, blood_group=blood_group,
    )

    return jsonify({
        'success': True,
        'message': 'Profile updated successfully',
        'phone': current_user.formatted_phone,
        'email': current_user.email,
    })
```

- [ ] **Step 7: Rewrite `change_password()` to delegate to `services.profile`**

Replace the entire `change_password()` function body with:
```python
@app.route('/change-password', methods=['POST'])
@login_required
def change_password():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    current = data.get('current', '').strip()
    new_pass = data.get('new', '').strip()
    confirm = data.get('confirm', '').strip()

    try:
        profile_change_password(current_user, current, new_pass, confirm)
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({'success': True, 'message': 'Password changed successfully'})
```

- [ ] **Step 8: Manual verification**

Run: `python -c "import app; print('OK')"` — expect `OK`.

Write a throwaway `scratch_verify_triggers.py` using `test_client` (scope `app.app_context()` narrowly around DB-only lookups, never across `client.get()`/`client.post()` calls, per the established pattern from prior milestones):
1. Confirm `POST /change-password` with a wrong current password still returns 400 with a clean message (delegation didn't break the existing contract).
2. Confirm `POST /update-profile` with `{"phone": "08011112222"}` and no other keys still succeeds (the other 3 fields end up as empty strings, matching the "always pass explicit values" design — this is expected, not a bug, since the JS always sends all 4 keys together; a raw API call omitting keys will clear them, which is documented behavior for this endpoint).
3. Confirm a `Notification` row with `category='payments'` now exists for a student after calling `services.registration.register_student` for them (reuse a fresh/unregistered demo student, clean up afterward).
4. Confirm a `Notification` row with `category='profile'` exists after calling `update_contact_info`.

Delete the script afterward.

- [ ] **Step 9: Commit**
```bash
git add services/registration.py app.py
git commit -m "feat: integrate notification/audit services into existing routes and registration flow"
```

---

### Task 5: New Notification and Profile Routes

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: everything imported in Task 4, plus `update_profile_picture`/`delete_profile_picture` from `services.profile` (already imported in Task 4).

- [ ] **Step 1: Rewrite `announcements()`, add `@login_required`**

Replace:
```python
@app.route('/announcements')
def announcements():
    return render_template('announcements.html')
```
with:
```python
@app.route('/announcements')
@login_required
def announcements():
    return render_template(
        'announcements.html',
        summary=get_summary_counts(current_user),
        notifications=get_notifications(current_user),
    )
```

- [ ] **Step 2: Add the opportunistic registration-window trigger to `dashboard()` and `registration()`**

In `dashboard()`, add `notify_registration_window_events(current_user)` as the first line of the function body, before its existing `return render_template(...)`.

In `registration()`, add the same call as the first line of the function body, before its existing `return render_template(...)`.

- [ ] **Step 3: Add the notification CRUD routes**

Add these routes near `announcements()` (after it):
```python
@app.route('/notifications/data')
@login_required
def notifications_data():
    category = request.args.get('category') or None
    priority = request.args.get('priority') or None
    read_status = request.args.get('read_status') or None
    date_from = request.args.get('date_from') or None
    date_to = request.args.get('date_to') or None
    search = request.args.get('search') or None
    archived = request.args.get('archived') == 'true'

    notifications = get_notifications(
        current_user, category=category, priority=priority, read_status=read_status,
        date_from=date_from, date_to=date_to, search=search, archived=archived,
    )

    def notif_json(n):
        return {
            'id': n.id, 'title': n.title, 'message': n.message, 'category': n.category,
            'priority': n.priority, 'related_url': n.related_url,
            'created_at': n.created_at.strftime('%d %b %Y, %I:%M %p'),
            'is_read': n.read_at is not None,
            'is_archived': n.archived_at is not None,
        }

    return jsonify({
        'success': True,
        'notifications': [notif_json(n) for n in notifications],
        'summary': get_summary_counts(current_user),
    })


@app.route('/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def notification_mark_read(notification_id):
    notification = mark_read(current_user, notification_id)
    if notification is None:
        return jsonify({'success': False, 'message': 'Notification not found.'}), 404
    return jsonify({'success': True, 'summary': get_summary_counts(current_user)})


@app.route('/notifications/<int:notification_id>/unread', methods=['POST'])
@login_required
def notification_mark_unread(notification_id):
    notification = mark_unread(current_user, notification_id)
    if notification is None:
        return jsonify({'success': False, 'message': 'Notification not found.'}), 404
    return jsonify({'success': True, 'summary': get_summary_counts(current_user)})


@app.route('/notifications/<int:notification_id>/archive', methods=['POST'])
@login_required
def notification_archive(notification_id):
    notification = archive_notification(current_user, notification_id)
    if notification is None:
        return jsonify({'success': False, 'message': 'Notification not found.'}), 404
    return jsonify({'success': True, 'summary': get_summary_counts(current_user)})


@app.route('/notifications/<int:notification_id>/delete', methods=['POST'])
@login_required
def notification_delete(notification_id):
    notification = delete_notification(current_user, notification_id)
    if notification is None:
        return jsonify({'success': False, 'message': 'Notification not found.'}), 404
    return jsonify({'success': True, 'summary': get_summary_counts(current_user)})


@app.route('/notifications/mark-all-read', methods=['POST'])
@login_required
def notification_mark_all_read():
    mark_all_read(current_user)
    return jsonify({'success': True, 'summary': get_summary_counts(current_user)})
```

- [ ] **Step 4: Add the profile-picture routes**

Add these routes near `update_profile()`:
```python
@app.route('/profile/picture', methods=['POST'])
@login_required
def profile_picture_upload():
    file_storage = request.files.get('profile_picture')
    if not file_storage:
        return jsonify({'success': False, 'message': 'No file provided.'}), 400

    upload_folder = os.path.join(app.static_folder, 'uploads')
    try:
        update_profile_picture(current_user, file_storage, upload_folder)
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({
        'success': True,
        'message': 'Profile picture updated.',
        'profile_picture': url_for('static', filename=current_user.profile_picture),
    })


@app.route('/profile/picture/delete', methods=['POST'])
@login_required
def profile_picture_delete():
    try:
        delete_profile_picture(current_user, app.static_folder)
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({'success': True, 'message': 'Profile picture removed.'})
```

- [ ] **Step 5: Manual verification**

Write a throwaway `scratch_verify_routes5.py` covering, via `test_client` (session_transaction login, CSRF token fetched from an already-rendered page for POSTs, per established pattern):
1. Anonymous `GET /announcements` → 302 to login.
2. Logged-in `GET /announcements` → 200.
3. `GET /notifications/data` → 200, `success: true`.
4. `POST /notifications/<id>/read` for a notification not owned by the caller → 404 (create one for a *different* user first to test this).
5. `POST /notifications/mark-all-read` → 200, summary counts update.
6. `POST /profile/picture` with a tiny valid PNG file (construct in-memory via `io.BytesIO`) → 200, `profile_picture` field returned.
7. `POST /profile/picture/delete` → 200.
8. Confirm `dashboard()`/`registration()` still render 200 after adding the `notify_registration_window_events` call (no exception introduced).

Delete the script afterward, and delete any uploaded test picture file it created under `static/uploads/`.

- [ ] **Step 6: Commit**
```bash
git add app.py
git commit -m "feat: add notification CRUD and profile picture routes"
```

---

### Task 6: Notifications Page UI

**Files:**
- Modify: `templates/announcements.html`
- Modify: `static/css/announcements.css`
- Create: `static/js/announcements/announcements.js`

**Interfaces:**
- Consumes: `summary`/`notifications` (from Task 5's `announcements()` route); `/notifications/data`, `/notifications/<id>/read|unread|archive|delete`, `/notifications/mark-all-read` (Task 5); `postJson` from `static/js/shared/api.js`; `showToast` from `static/js/shared/toast.js`.

- [ ] **Step 1: Rewrite `templates/announcements.html`**

Replace the entire file with:
```html
{% extends "base.html" %}

{% block head %}
    <title>Notifications & Announcements · Student Portal</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/announcements.css') }}">
{% endblock %}

{% block content %}
<div class="notifications-page">
    <input type="hidden" id="csrf_token" value="{{ csrf_token() }}">

    <div class="page-header">
        <a href="{{ url_for('dashboard') }}" class="back-link"><i class="fas fa-arrow-left"></i> Dashboard</a>
        <h1 class="page-title"><i class="fas fa-bell"></i> Notifications & Announcements</h1>
        <div class="header-actions">
            <button class="btn-primary" id="markAllReadBtn"><i class="fas fa-check-double"></i> Mark all read</button>
        </div>
    </div>

    <div class="summary-grid">
        <div class="summary-card">
            <div class="summary-icon"><i class="fas fa-bell"></i></div>
            <div class="summary-content"><h4>Total</h4><div class="summary-number" id="summaryTotal">{{ summary.total }}</div></div>
        </div>
        <div class="summary-card">
            <div class="summary-icon"><i class="fas fa-envelope-open"></i></div>
            <div class="summary-content"><h4>Unread</h4><div class="summary-number" id="summaryUnread">{{ summary.unread }}</div></div>
        </div>
        <div class="summary-card">
            <div class="summary-icon"><i class="fas fa-envelope"></i></div>
            <div class="summary-content"><h4>Read</h4><div class="summary-number" id="summaryRead">{{ summary.read }}</div></div>
        </div>
        <div class="summary-card">
            <div class="summary-icon"><i class="fas fa-archive"></i></div>
            <div class="summary-content"><h4>Archived</h4><div class="summary-number" id="summaryArchived">{{ summary.archived }}</div></div>
        </div>
    </div>

    <div class="filter-bar">
        <div class="filter-tabs">
            <button class="filter-tab active" data-value="all"><i class="fas fa-inbox"></i> All</button>
            <button class="filter-tab" data-value="unread">Unread</button>
            <button class="filter-tab" data-value="archived">Archived</button>
        </div>
        <div class="search-box">
            <i class="fas fa-search"></i>
            <input type="text" id="searchInput" placeholder="Search notifications">
        </div>
    </div>

    <div class="filter-bar" style="margin-top: 0.5rem;">
        <select id="categoryFilter">
            <option value="">All categories</option>
            <option value="registration">Registration</option>
            <option value="payments">Payments</option>
            <option value="courses">Courses</option>
            <option value="academic">Academic</option>
            <option value="profile">Profile</option>
            <option value="system">System</option>
            <option value="announcements">Announcements</option>
        </select>
        <select id="priorityFilter">
            <option value="">All priorities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
        </select>
        <input type="date" id="dateFromFilter" title="From date">
        <input type="date" id="dateToFilter" title="To date">
    </div>

    <div class="notifications-list" id="notificationsList">
        {% for n in notifications %}
        <div class="notification-item priority-{{ n.priority }}" data-id="{{ n.id }}">
            <div class="notification-icon"><i class="fas fa-bell"></i></div>
            <div class="notification-content">
                <div class="notification-header">
                    <div class="notification-title">{{ n.title }} {% if not n.read_at %}<span class="unread-badge">New</span>{% endif %}</div>
                    <div class="notification-date"><i class="far fa-clock"></i> {{ n.created_at.strftime('%d %b %Y, %I:%M %p') }}</div>
                </div>
                <div class="notification-meta">
                    <span class="notification-category"><i class="fas fa-tag"></i> {{ n.category|capitalize }}</span>
                    <span><i class="fas fa-flag"></i> {{ n.priority|capitalize }} priority</span>
                </div>
                <div class="notification-message">{{ n.message }}</div>
                <div class="notification-footer">
                    {% if n.related_url %}<a href="{{ n.related_url }}" class="action-link">View <i class="fas fa-arrow-right"></i></a>{% endif %}
                    <button class="dismiss-btn toggle-read-btn" data-id="{{ n.id }}" data-read="{{ 'true' if n.read_at else 'false' }}">
                        <i class="fas fa-{{ 'envelope' if n.read_at else 'envelope-open' }}"></i> {{ 'Mark unread' if n.read_at else 'Mark read' }}
                    </button>
                    <button class="dismiss-btn archive-btn" data-id="{{ n.id }}"><i class="fas fa-archive"></i> Archive</button>
                    <button class="dismiss-btn delete-btn" data-id="{{ n.id }}"><i class="fas fa-times"></i> Delete</button>
                </div>
            </div>
        </div>
        {% endfor %}
        {% if not notifications %}
        <div class="empty-state"><i class="far fa-bell-slash"></i><p>No notifications yet.</p></div>
        {% endif %}
    </div>
</div>

<div id="toastMsg" class="toast-msg"></div>
{% endblock %}

{% block scripts %}
<script type="module" src="{{ url_for('static', filename='js/announcements/announcements.js') }}"></script>
{% endblock %}
```

- [ ] **Step 2: Create `static/js/announcements/announcements.js`**
```javascript
import { postJson } from '../shared/api.js';
import { showToast } from '../shared/toast.js';

let currentQuickFilter = 'all';

function buildParams() {
    const params = new URLSearchParams();
    if (currentQuickFilter === 'unread') params.set('read_status', 'unread');
    if (currentQuickFilter === 'archived') params.set('archived', 'true');
    const category = document.getElementById('categoryFilter').value;
    if (category) params.set('category', category);
    const priority = document.getElementById('priorityFilter').value;
    if (priority) params.set('priority', priority);
    const dateFrom = document.getElementById('dateFromFilter').value;
    if (dateFrom) params.set('date_from', dateFrom);
    const dateTo = document.getElementById('dateToFilter').value;
    if (dateTo) params.set('date_to', dateTo);
    const search = document.getElementById('searchInput').value.trim();
    if (search) params.set('search', search);
    return params;
}

function categoryLabel(c) { return c.charAt(0).toUpperCase() + c.slice(1); }
function priorityLabel(p) { return p.charAt(0).toUpperCase() + p.slice(1); }

function renderNotification(n) {
    return `
        <div class="notification-item priority-${n.priority}" data-id="${n.id}">
            <div class="notification-icon"><i class="fas fa-bell"></i></div>
            <div class="notification-content">
                <div class="notification-header">
                    <div class="notification-title">${n.title} ${!n.is_read ? '<span class="unread-badge">New</span>' : ''}</div>
                    <div class="notification-date"><i class="far fa-clock"></i> ${n.created_at}</div>
                </div>
                <div class="notification-meta">
                    <span class="notification-category"><i class="fas fa-tag"></i> ${categoryLabel(n.category)}</span>
                    <span><i class="fas fa-flag"></i> ${priorityLabel(n.priority)} priority</span>
                </div>
                <div class="notification-message">${n.message}</div>
                <div class="notification-footer">
                    ${n.related_url ? `<a href="${n.related_url}" class="action-link">View <i class="fas fa-arrow-right"></i></a>` : ''}
                    <button class="dismiss-btn toggle-read-btn" data-id="${n.id}" data-read="${n.is_read}">
                        <i class="fas fa-${n.is_read ? 'envelope' : 'envelope-open'}"></i> ${n.is_read ? 'Mark unread' : 'Mark read'}
                    </button>
                    <button class="dismiss-btn archive-btn" data-id="${n.id}"><i class="fas fa-archive"></i> Archive</button>
                    <button class="dismiss-btn delete-btn" data-id="${n.id}"><i class="fas fa-times"></i> Delete</button>
                </div>
            </div>
        </div>
    `;
}

function updateSummary(summary) {
    document.getElementById('summaryTotal').innerText = summary.total;
    document.getElementById('summaryUnread').innerText = summary.unread;
    document.getElementById('summaryRead').innerText = summary.read;
    document.getElementById('summaryArchived').innerText = summary.archived;
}

function attachRowListeners() {
    document.querySelectorAll('.toggle-read-btn').forEach(btn => {
        btn.addEventListener('click', () => toggleRead(btn.dataset.id, btn.dataset.read === 'true'));
    });
    document.querySelectorAll('.archive-btn').forEach(btn => {
        btn.addEventListener('click', () => archiveOne(btn.dataset.id));
    });
    document.querySelectorAll('.delete-btn').forEach(btn => {
        btn.addEventListener('click', () => deleteOne(btn.dataset.id));
    });
}

async function loadData() {
    const params = buildParams();
    const resp = await fetch(`/notifications/data?${params.toString()}`);
    const data = await resp.json();
    if (!data.success) {
        showToast('Failed to load notifications', true);
        return;
    }
    const list = document.getElementById('notificationsList');
    if (data.notifications.length === 0) {
        list.innerHTML = '<div class="empty-state"><i class="far fa-bell-slash"></i><p>No notifications match this filter.</p></div>';
    } else {
        list.innerHTML = data.notifications.map(renderNotification).join('');
    }
    attachRowListeners();
    updateSummary(data.summary);
}

async function toggleRead(id, isRead) {
    const endpoint = isRead ? 'unread' : 'read';
    const result = await postJson(`/notifications/${id}/${endpoint}`, {});
    if (!result.success) {
        showToast(result.message || 'Action failed', true);
        return;
    }
    await loadData();
}

async function archiveOne(id) {
    const result = await postJson(`/notifications/${id}/archive`, {});
    if (!result.success) {
        showToast(result.message || 'Action failed', true);
        return;
    }
    showToast('Notification archived');
    await loadData();
}

async function deleteOne(id) {
    const result = await postJson(`/notifications/${id}/delete`, {});
    if (!result.success) {
        showToast(result.message || 'Action failed', true);
        return;
    }
    showToast('Notification deleted');
    await loadData();
}

async function markAllRead() {
    const result = await postJson('/notifications/mark-all-read', {});
    if (!result.success) {
        showToast(result.message || 'Action failed', true);
        return;
    }
    showToast('All notifications marked as read');
    await loadData();
}

document.querySelectorAll('.filter-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.filter-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        currentQuickFilter = tab.dataset.value;
        loadData();
    });
});

document.getElementById('categoryFilter').addEventListener('change', loadData);
document.getElementById('priorityFilter').addEventListener('change', loadData);
document.getElementById('dateFromFilter').addEventListener('change', loadData);
document.getElementById('dateToFilter').addEventListener('change', loadData);

let searchDebounceHandle = null;
document.getElementById('searchInput').addEventListener('input', () => {
    clearTimeout(searchDebounceHandle);
    searchDebounceHandle = setTimeout(loadData, 300);
});

document.getElementById('markAllReadBtn').addEventListener('click', markAllRead);

attachRowListeners();
```

- [ ] **Step 3: Extend `static/css/announcements.css`**

Append:
```css

.filter-bar select,
.filter-bar input[type="date"] {
    padding: 0.5rem 0.9rem;
    border-radius: 60px;
    border: 1px solid #c7dcf5;
    background: white;
    color: #0f3150;
    font-size: 0.85rem;
}
```

- [ ] **Step 4: Manual verification across states**

Write a throwaway `scratch_verify_ui6.py` using `test_request_context()` + `login_user()` + `render_template()` (per the established isolation pattern):
1. Render `announcements.html` with `notifications=[]`, `summary={'total':0,'unread':0,'read':0,'archived':0}` — confirm "No notifications yet." appears, no Jinja error.
2. Render it with a real `notifications`/`summary` from `get_notifications`/`get_summary_counts` for a student with at least 2 seeded notifications (one read, one unread) — confirm both render, confirm the unread one shows the "New" badge and the read one doesn't, confirm summary numbers match.

Delete the script afterward.

- [ ] **Step 5: Commit**
```bash
git add templates/announcements.html static/css/announcements.css static/js/announcements/announcements.js
git commit -m "feat: replace mock notifications page with real backend-driven UI"
```

---

### Task 7: Profile Page UI Extensions

**Files:**
- Modify: `templates/profile.html`

**Interfaces:**
- Consumes: `/update-profile` (extended in Task 4), `/profile/picture`, `/profile/picture/delete` (Task 5).

- [ ] **Step 1: Make Address editable**

Replace:
```html
                    <div class="info-group">
                        <label><i class="fas fa-map-marker-alt"></i> Address</label>
                        <span class="field-display" id="displayAddressField">{{ current_user.address }}</span>
                    </div>
```
with:
```html
                    <div class="input-group">
                        <label><i class="fas fa-map-marker-alt"></i> Address</label>
                        <input type="text" id="editAddress" value="{{ current_user.address or '' }}">
                    </div>
```

- [ ] **Step 2: Add Emergency Contact and Blood Group fields**

Immediately after the block from Step 1 (still inside the `.settings-group` div, before the Program/Semester `.double-field` block), insert:
```html
                    <div class="double-field">
                        <div class="input-group">
                            <label><i class="fas fa-phone-volume"></i> Emergency Contact</label>
                            <input type="text" id="editEmergencyContact" value="{{ current_user.emergency_contact or '' }}" placeholder="Name and phone number">
                        </div>
                        <div class="input-group">
                            <label><i class="fas fa-tint"></i> Blood Group</label>
                            <select id="editBloodGroup">
                                <option value="" {% if not current_user.blood_group %}selected{% endif %}>Unknown</option>
                                {% for bg in ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'] %}
                                <option value="{{ bg }}" {% if current_user.blood_group == bg %}selected{% endif %}>{{ bg }}</option>
                                {% endfor %}
                            </select>
                        </div>
                    </div>
```

- [ ] **Step 3: Rename the save button**

Replace:
```html
                    <button class="save-btn" id="updateProfileBtn"><i class="fas fa-save"></i> Update Phone</button>
```
with:
```html
                    <button class="save-btn" id="updateProfileBtn"><i class="fas fa-save"></i> Save Changes</button>
```

- [ ] **Step 4: Real avatar upload markup**

Replace:
```html
                <div class="avatar-wrapper">
                    <div class="avatar-placeholder" id="avatarDisplay">
                        {% if current_user.profile_picture %}
                        <img src="{{ url_for('static', filename=current_user.profile_picture) }}" alt="Profile Picture" style="width:100%;height:100%;object-fit:cover;border-radius:50%;">
                        {% else %}
                        <i class="fas fa-user-graduate fa-3x"></i>
                        {% endif %}
                    </div>
                    <div class="edit-avatar-btn" id="editAvatarBtn">
                        <i class="fas fa-camera"></i>
                    </div>
                </div>
```
with:
```html
                <div class="avatar-wrapper">
                    <div class="avatar-placeholder" id="avatarDisplay">
                        {% if current_user.profile_picture %}
                        <img id="avatarImg" src="{{ url_for('static', filename=current_user.profile_picture) }}" alt="Profile Picture" style="width:100%;height:100%;object-fit:cover;border-radius:50%;">
                        {% else %}
                        <i class="fas fa-user-graduate fa-3x" id="avatarIcon"></i>
                        {% endif %}
                    </div>
                    <div class="edit-avatar-btn" id="editAvatarBtn">
                        <i class="fas fa-camera"></i>
                    </div>
                    <input type="file" id="avatarFileInput" accept=".png,.jpg,.jpeg,.webp" style="display:none;">
                </div>
                {% if current_user.profile_picture %}
                <button type="button" class="btn-outline-sm" id="removePhotoBtn" style="margin-top:0.5rem;"><i class="fas fa-trash-alt"></i> Remove photo</button>
                {% endif %}
```

- [ ] **Step 5: Replace the fake avatar-edit JS with real upload/delete**

Replace:
```javascript
        // ---------- Avatar edit ----------
        const avatarDiv = document.getElementById('avatarDisplay');
        document.getElementById('editAvatarBtn').addEventListener('click', () => {
            const icon = prompt('Enter icon name (e.g., user-graduate, book, user-astronaut)', 'user-graduate');
            if (icon && icon.trim()) {
                avatarDiv.innerHTML = `<i class="fas fa-${icon} fa-3x"></i>`;
            } else {
                avatarDiv.innerHTML = `<i class="fas fa-user-graduate fa-3x"></i>`;
            }
            showToast('Avatar updated', false);
        });
```
with:
```javascript
        // ---------- Avatar upload/delete ----------
        const avatarDiv = document.getElementById('avatarDisplay');
        const avatarFileInput = document.getElementById('avatarFileInput');
        document.getElementById('editAvatarBtn').addEventListener('click', () => avatarFileInput.click());

        avatarFileInput.addEventListener('change', function() {
            const file = this.files[0];
            if (!file) return;

            const formData = new FormData();
            formData.append('profile_picture', file);

            fetch('/profile/picture', {
                method: 'POST',
                headers: { 'X-CSRFToken': document.getElementById('csrf_token').value },
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    avatarDiv.innerHTML = `<img id="avatarImg" src="${data.profile_picture}" alt="Profile Picture" style="width:100%;height:100%;object-fit:cover;border-radius:50%;">`;
                    showToast(data.message, false);
                } else {
                    showToast(data.message, true);
                }
                avatarFileInput.value = '';
            })
            .catch(() => {
                showToast('An error occurred', true);
                avatarFileInput.value = '';
            });
        });

        const removePhotoBtn = document.getElementById('removePhotoBtn');
        if (removePhotoBtn) {
            removePhotoBtn.addEventListener('click', function() {
                fetch('/profile/picture/delete', {
                    method: 'POST',
                    headers: { 'X-CSRFToken': document.getElementById('csrf_token').value }
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        avatarDiv.innerHTML = '<i class="fas fa-user-graduate fa-3x" id="avatarIcon"></i>';
                        removePhotoBtn.remove();
                        showToast(data.message, false);
                    } else {
                        showToast(data.message, true);
                    }
                })
                .catch(() => showToast('An error occurred', true));
            });
        }
```

- [ ] **Step 6: Update the Save Changes JS to send all 4 fields**

Replace:
```javascript
        updateBtn.addEventListener('click', function() {
            const phone = editPhone.value.trim();
            if (!phone) { showToast('Phone number is required', true); return; }

            updateBtn.disabled = true;
            updateBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Updating...';

            const csrfToken = document.getElementById('csrf_token').value;

            fetch('/update-profile', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ phone: phone })
            })
            .then(response => response.json())
            .then(data => {
                updateBtn.disabled = false;
                updateBtn.innerHTML = originalBtnHtml;
                if (data.success) {
                    displayPhoneSpan.innerText = data.phone;
                    editPhone.value = data.phone;
                    showToast(data.message, false);
                } else {
                    showToast(data.message, true);
                }
            })
            .catch(() => {
                updateBtn.disabled = false;
                updateBtn.innerHTML = originalBtnHtml;
                showToast('An error occurred', true);
            });
        });
```
with:
```javascript
        updateBtn.addEventListener('click', function() {
            const phone = editPhone.value.trim();
            const address = document.getElementById('editAddress').value.trim();
            const emergencyContact = document.getElementById('editEmergencyContact').value.trim();
            const bloodGroup = document.getElementById('editBloodGroup').value;
            if (!phone) { showToast('Phone number is required', true); return; }

            updateBtn.disabled = true;
            updateBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';

            const csrfToken = document.getElementById('csrf_token').value;

            fetch('/update-profile', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({
                    phone: phone,
                    address: address,
                    emergency_contact: emergencyContact,
                    blood_group: bloodGroup
                })
            })
            .then(response => response.json())
            .then(data => {
                updateBtn.disabled = false;
                updateBtn.innerHTML = originalBtnHtml;
                if (data.success) {
                    displayPhoneSpan.innerText = data.phone;
                    editPhone.value = data.phone;
                    const displayAddressSpan = document.getElementById('displayAddress');
                    if (displayAddressSpan) displayAddressSpan.innerText = address;
                    showToast(data.message, false);
                } else {
                    showToast(data.message, true);
                }
            })
            .catch(() => {
                updateBtn.disabled = false;
                updateBtn.innerHTML = originalBtnHtml;
                showToast('An error occurred', true);
            });
        });
```

- [ ] **Step 7: Manual verification**

Render `profile.html` via `test_request_context()` + `login_user()` + `render_template()` for a demo student with `emergency_contact`/`blood_group` set and one without — confirm the input values pre-populate correctly (`value="..."` for the set case, empty for the unset case, correct `selected` option for blood group). Grep the file to confirm no `prompt(` calls remain. Then a `test_client` round-trip: POST `/update-profile` with all 4 fields, confirm the DB row updated and an `AuditLog`+`Notification` were created (reusing the pattern from Task 3's verification). Delete any throwaway script afterward.

- [ ] **Step 8: Commit**
```bash
git add templates/profile.html
git commit -m "feat: add editable address/emergency-contact/blood-group and real profile picture upload"
```

---

### Task 8: Seed Demo Data

**Files:**
- Modify: `seed_dev_data.py`

**Interfaces:**
- Consumes: `Notification` from `models`.

- [ ] **Step 1: Add `Notification` to the imports**

Update the `from models import (...)` block to also include `Notification`.

- [ ] **Step 2: Add `seed_notifications()`**

Append to `seed_dev_data.py`:
```python

def seed_notifications():
    chiamaka = User.query.filter_by(reg_no='2308-2301-0003').first()
    if not chiamaka:
        print('Skipping notification seed — run student seeding first')
        return

    existing_count = Notification.query.filter_by(user_id=chiamaka.id).count()
    if existing_count > 0:
        print(f'Skipping notification seed for {chiamaka.reg_no} (already has {existing_count})')
        return

    from services.notification import create_notification

    n1 = create_notification(
        chiamaka, 'Welcome to the Student Portal', 'Your profile setup is complete. Welcome aboard!',
        category='profile', priority='medium',
    )
    n2 = create_notification(
        chiamaka, 'Second semester exam timetable released',
        'Official examination timetable for the second semester is now available.',
        category='academic', priority='medium', related_url='/announcements',
    )
    n3 = create_notification(
        chiamaka, 'System maintenance scheduled', 'The portal will be briefly unavailable for maintenance this weekend.',
        category='system', priority='low',
    )
    n4 = create_notification(
        chiamaka, 'Library extended hours during exams',
        'Main library extended hours (7:00 AM - 11:00 PM) starting during examination weeks.',
        category='announcements', priority='low',
    )
    n4.read_at = now_lagos()

    n5 = create_notification(
        chiamaka, 'Departmental seminar reminder', 'A departmental seminar takes place this week — attendance is optional.',
        category='academic', priority='low',
    )
    n5.read_at = now_lagos()
    n5.archived_at = now_lagos()

    db.session.commit()
    print(f'Created 5 demo notifications for {chiamaka.reg_no} (2 unread, 2 read, 1 archived)')


def seed_profile_extras():
    david = User.query.filter_by(reg_no='2308-2301-0004').first()
    if david and not david.emergency_contact:
        david.emergency_contact = 'Mrs. Adeyemi Adeyemi - 08033445566'
        david.blood_group = 'O+'
        db.session.commit()
        print(f'Set emergency contact/blood group for {david.reg_no}')
    else:
        print('Skipping profile extras seed (already set or David not found)')
```

- [ ] **Step 3: Call both from `seed()`**

Find the line `seed_courses()` inside `seed()` and add, immediately after it:
```python
        seed_notifications()
        seed_profile_extras()
```

- [ ] **Step 4: Run and verify**

Run: `python seed_dev_data.py` twice — first run creates the notifications and sets David's fields; second run shows "Skipping" for both.

Verify:
```bash
python -c "
from app import app
from models import Notification, User
with app.app_context():
    chiamaka = User.query.filter_by(reg_no='2308-2301-0003').first()
    count = Notification.query.filter_by(user_id=chiamaka.id).count()
    assert count == 5, count
    david = User.query.filter_by(reg_no='2308-2301-0004').first()
    assert david.blood_group == 'O+'
    print('Seed data verified: 5 notifications, David has blood_group set')
"
```

- [ ] **Step 5: Commit**
```bash
git add seed_dev_data.py
git commit -m "feat: seed demo notifications and profile extras"
```

---

### Task 9: End-to-End Verification and Progress Doc

**Files:**
- Modify: `DEVELOPMENT_PROGRESS.md`

- [ ] **Step 1: Full flow verification**

Write a throwaway `scratch_verify_e2e9.py` covering, via `test_client`:
1. Login as a fully-onboarded demo student (Chiamaka), `GET /announcements` → 200, confirm the 5 seeded notifications appear with correct summary counts (2 unread visible in "All"/"Unread" tabs, 1 archived only visible with `archived=true`).
2. `POST /notifications/<id>/read` on an unread one → `unread` count decreases by 1.
3. `POST /notifications/<id>/archive` on a non-archived one → moves out of the default inbox view, `archived` count increases.
4. `GET /notifications/data?category=academic` → only academic-category notifications returned.
5. `GET /notifications/data?search=timetable` → only the matching notification returned.
6. `POST /notifications/mark-all-read` → `unread` count becomes 0.
7. Login as David (`2308-2301-0004`, needs `first_login=False` — already true per an earlier milestone's fix), `GET /profile` → 200, confirm `emergency_contact`/`blood_group` render.
8. `POST /update-profile` with new address/emergency_contact/blood_group values → confirm `AuditLog` and `Notification` rows created, confirm values persisted.
9. Trigger `services.registration.register_student` for a fresh unregistered demo student (or reuse existing test infrastructure) → confirm a `category='payments'` notification was created.
10. Confirm `announcements()`/`profile()` both still require login (anonymous → 302).

Delete the script afterward. Cleanup is not required for this final task's created rows (may remain as real demonstrable state), except restore any demo student field values you changed for testing purposes back to their seeded originals if doing so is cheap and doesn't risk leaving the DB inconsistent.

- [ ] **Step 2: Update `DEVELOPMENT_PROGRESS.md`**

Add a new section (after the "Feature 5 & 6" section, before "Known pre-existing issues"):
```markdown
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

## Next milestone

Feature 9: Payments — awaiting approval before starting.
```

- [ ] **Step 3: Boot check and commit**
```bash
python -c "import app; print('OK')"
git add DEVELOPMENT_PROGRESS.md
git commit -m "docs: record notification and profile management as complete in progress log"
```
