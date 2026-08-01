# Admin Portal Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the admin infrastructure every future admin module sits on: a separate `AdminUser` identity with RBAC, admin authentication (login/logout/remember-me/forgot-reset/first-login-change/15-min idle timeout), a reusable admin layout, a live dashboard backed by real queries, and admin audit logging — one Flask app, one deployment.

**Architecture:** All new routes live under `/admin/...`, added directly into the existing flat `app.py` (no Blueprint — matching this codebase's convention). A separate `AdminUser` model (not `User.is_admin`, which stays dead/untouched) is loaded by the single shared `LoginManager` via a prefixed id (`admin:<id>`) so one `user_loader` can tell student and admin sessions apart. `@admin_required`/`@permission_required(code)` decorators — not `@login_required` — gate every admin route, checking `isinstance(current_user, AdminUser)`.

**Tech Stack:** Flask, Flask-SQLAlchemy (SQLite dev DB), Flask-Login (single shared instance), Flask-Mail (OTP emails, reusing `onboarding_helpers`), vanilla ES module JS, Jinja2.

Full design rationale: `docs/superpowers/specs/2026-08-01-admin-foundation-design.md`.

## Global Constraints

- No automated test framework in this repo — verification is manual via throwaway `test_client`/`app_context` scripts, created, run, and deleted, never committed.
- All datetime columns use `now_lagos()` — never a tz-aware `datetime`.
- `User`, student auth, and every completed student-facing module are untouched except two narrow, necessary edits: (1) `load_user()`'s body, to add the `admin:` prefix branch; (2) `enforce_onboarding_gate()`'s first line, to bail out immediately for an `AdminUser` (otherwise it crashes calling `get_gate_redirect(current_user)`, which reads `.first_login`/`.onboarding_completed`/`.email_verified` — attributes `AdminUser` doesn't have).
- `User.is_admin` is not read, written, or referenced anywhere in this plan — dead column, left alone.
- New tables only (`admin_roles`, `permissions`, `role_permissions`, `admin_users`, `admin_audit_logs`) — `db.create_all()` handles them with no `ALTER TABLE` needed.
- `permission_required(code)` fully subsumes `admin_required`'s checks (authentication + `isinstance(current_user, AdminUser)` + `is_active`) — a route never stacks both decorators, it uses whichever one matches what it needs (`admin_required` alone for "any logged-in admin," `permission_required('code')` for a specific permission).
- The admin-only 15-minute idle-session-timeout `before_request` hook must return `None` immediately for anyone who isn't an authenticated `AdminUser` — it must never affect student session behavior.
- CSRF is already global (`CSRFProtect(app)`) — every new admin form includes the same `{{ csrf_token() }}` hidden-field pattern used everywhere else in this codebase; no route-level CSRF opt-out.
- Admin password policy reuses `auth_helpers.validate_password_strength` (the existing 8+/upper/lower/digit/special rule) — not a separate 12-character rule.
- No admin self-service account creation in this milestone — the only `AdminUser` rows come from `seed_dev_data.py`.
- Accepted minor edge case (documented, not fixed): the admin forgot-password OTP flow reuses `onboarding_helpers`'s session-key names (`email_verification_code`, `pending_email`, etc.) — the same keys the student email-change OTP flow uses. A single browser mid-way through both an admin password reset AND a student email-change OTP at the same time would have one clobber the other's session state. This is an unlikely combination (both are already mutually exclusive with "who's currently logged in," given the shared session/cookie constraint from the design) and not worth a parallel OTP-key namespace for this foundation milestone.
- Out of scope: MFA, admin self-service account management, real-time push, charts, Student Management, Payments admin UI, Course Management, Registration Oversight, Reports, Support Tickets. The 6 Quick Action routes render a literal "Coming soon" page — no real feature logic behind them.
- Expected mid-plan gap: Task 6's `templates/admin/base_admin.html` (the sidebar/topbar shell every admin page extends) links to `admin_dashboard`, `admin_logout`, and 4 `admin_stub_*` endpoints that aren't defined until Task 7 (dashboard) and Task 8 (stubs). This doesn't break Task 6 itself — Jinja's `url_for()` only resolves at render time, and Task 6's own verification only smoke-tests that the template parses, not that it fully renders. Task 7's manual verification is the first real end-to-end render, once those endpoints exist. Don't flag this as broken in Task 6's review — verify it's actually resolved once Task 7/8 land.

---

### Task 1: Data Models + Flask-Login Wiring

**Files:**
- Modify: `models.py`
- Modify: `app.py`

**Interfaces:**
- Produces: `Permission(id, code, description)`; `AdminRole(id, name, description, permissions)` (`permissions` is a relationship to `Permission` via `role_permissions`); `RolePermission(id, role_id, permission_id)`; `AdminUser(id, email, password_hash, name, role_id, is_active, first_login, created_at, last_login_at, last_login_ip, role)` with `set_password`/`check_password`/`get_id` (returns `f'admin:{self.id}'`); `AdminAuditLog(id, admin_user_id, action, target_type, target_id, details, ip_address, created_at)`.

- [ ] **Step 1: Append the 5 new model classes to `models.py`**

At the end of `models.py` (after the existing `GatewayResponse` class), append:
```python


class Permission(db.Model):
    __tablename__ = 'permissions'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)


class AdminRole(db.Model):
    __tablename__ = 'admin_roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)

    permissions = db.relationship('Permission', secondary='role_permissions', backref='roles')


class RolePermission(db.Model):
    __tablename__ = 'role_permissions'
    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey('admin_roles.id'), nullable=False)
    permission_id = db.Column(db.Integer, db.ForeignKey('permissions.id'), nullable=False)

    __table_args__ = (db.UniqueConstraint('role_id', 'permission_id'),)


class AdminUser(db.Model, UserMixin):
    __tablename__ = 'admin_users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(250), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    name = db.Column(db.String(250), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('admin_roles.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    first_login = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)
    last_login_ip = db.Column(db.String(45), nullable=True)

    role = db.relationship('AdminRole')

    def get_id(self):
        return f'admin:{self.id}'

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class AdminAuditLog(db.Model):
    __tablename__ = 'admin_audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_users.id'), nullable=True)
    action = db.Column(db.String(50), nullable=False)
    target_type = db.Column(db.String(50), nullable=True)
    target_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
```
(`UserMixin`, `generate_password_hash`, `check_password_hash`, `db.relationship` are already imported at the top of `models.py` — no new imports needed there.)

- [ ] **Step 2: Update `load_user()` in `app.py` to handle the `admin:` prefix**

Find:
```python
@login_manager.user_loader
def load_user(idn):
    return db.get_or_404(User, idn)
```
Replace with:
```python
@login_manager.user_loader
def load_user(idn):
    if idn.startswith('admin:'):
        return AdminUser.query.get(int(idn.split(':', 1)[1]))
    return db.get_or_404(User, idn)
```

- [ ] **Step 3: Bail out of `enforce_onboarding_gate()` for admins**

Find:
```python
@app.before_request
def enforce_onboarding_gate():
    if not current_user.is_authenticated:
        return None
```
Replace with:
```python
@app.before_request
def enforce_onboarding_gate():
    if not current_user.is_authenticated:
        return None
    if isinstance(current_user, AdminUser):
        return None
```

- [ ] **Step 4: Add `AdminUser` to `app.py`'s `models` import**

Find the existing `from models import (...)` block at the top of `app.py` (currently `db, User, RegisteredCourse, StudentRegistration, Payment, PaymentCategory`) and add `AdminUser` to it. Leave every other name in that import untouched.

- [ ] **Step 5: Boot check and schema verification**
```bash
python -c "import app; print('OK')"
python -c "
from app import app
from models import db
with app.app_context():
    tables = db.inspect(db.engine).get_table_names()
    for t in ('permissions', 'admin_roles', 'role_permissions', 'admin_users', 'admin_audit_logs'):
        assert t in tables, f'{t} missing'
    print('Schema verified')
"
```

- [ ] **Step 6: Commit**
```bash
git add models.py app.py
git commit -m "feat: add AdminRole/Permission/RolePermission/AdminUser/AdminAuditLog models, wire admin identity into the shared LoginManager"
```

---

### Task 2: Admin Permission and Audit Services

**Files:**
- Create: `services/admin_audit.py`
- Create: `services/admin_permission.py`

**Interfaces:**
- Produces: `log_admin_action(admin_user, action, target_type=None, target_id=None, details=None, ip_address=None)`; `has_permission(admin_user, code)`; `admin_required(view)` (decorator); `permission_required(code)` (decorator factory); `get_visible_quick_actions(admin_user)`.

- [ ] **Step 1: Create `services/admin_audit.py`**
```python
from models import db, AdminAuditLog


def log_admin_action(admin_user, action, target_type=None, target_id=None, details=None, ip_address=None):
    """Insert one AdminAuditLog row. admin_user may be None (a failed login
    attempt against an email with no matching account). `details` must
    never contain a password or OTP code."""
    entry = AdminAuditLog(
        admin_user_id=admin_user.id if admin_user else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
        ip_address=ip_address,
    )
    db.session.add(entry)
    db.session.commit()
    return entry
```

- [ ] **Step 2: Create `services/admin_permission.py`**
```python
from functools import wraps

from flask import redirect, url_for, render_template
from flask_login import current_user

from models import AdminUser

QUICK_ACTIONS = [
    ('admin_stub_sessions_new', 'sessions.manage', 'Create Session', 'fa-calendar-plus'),
    ('admin_stub_students_import', 'students.manage', 'Upload Students', 'fa-file-import'),
    ('admin_stub_courses', 'courses.manage', 'Manage Courses', 'fa-book'),
    ('admin_stub_registration_open', 'registration.manage', 'Open Registration', 'fa-door-open'),
    ('admin_stub_announcements_new', 'announcements.manage', 'Create Announcement', 'fa-bullhorn'),
    ('admin_stub_reports', 'reports.view', 'Generate Reports', 'fa-chart-bar'),
]


def has_permission(admin_user, code):
    if admin_user is None or admin_user.role is None:
        return False
    return any(p.code == code for p in admin_user.role.permissions)


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not isinstance(current_user, AdminUser):
            return redirect(url_for('admin_login'))
        if not current_user.is_active:
            return redirect(url_for('admin_login'))
        return view(*args, **kwargs)
    return wrapped


def permission_required(code):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated or not isinstance(current_user, AdminUser):
                return redirect(url_for('admin_login'))
            if not current_user.is_active:
                return redirect(url_for('admin_login'))
            if not has_permission(current_user, code):
                return render_template('admin/access_denied.html'), 403
            return view(*args, **kwargs)
        return wrapped
    return decorator


def get_visible_quick_actions(admin_user):
    """Quick Action entries the given admin's role is permitted to use —
    drives which buttons render on the dashboard. The underlying stub
    routes are independently protected by @permission_required, so this
    is a UX convenience, not the actual security boundary."""
    return [qa for qa in QUICK_ACTIONS if has_permission(admin_user, qa[1])]
```

- [ ] **Step 3: Manual verification**
```bash
python -c "
from app import app
from models import db, AdminRole, Permission, AdminUser
from services.admin_permission import has_permission, get_visible_quick_actions

with app.app_context():
    role = AdminRole(name='Test Role', description='temp')
    perm = Permission(code='dashboard.view', description='temp')
    db.session.add_all([role, perm])
    db.session.commit()
    role.permissions.append(perm)
    db.session.commit()

    admin = AdminUser(email='test.perm@example.com', name='Test', role_id=role.id, is_active=True)
    admin.set_password('Whatever@123')
    db.session.add(admin)
    db.session.commit()

    print('has dashboard.view:', has_permission(admin, 'dashboard.view'))
    print('has courses.manage:', has_permission(admin, 'courses.manage'))
    print('visible quick actions:', [qa[2] for qa in get_visible_quick_actions(admin)])

    db.session.delete(admin)
    db.session.delete(role)
    db.session.delete(perm)
    db.session.commit()
    print('cleanup done')
"
```
Expected: `has dashboard.view: True`, `has courses.manage: False`, `visible quick actions: []` (empty, since this test role was only granted `dashboard.view`, and no Quick Action needs that specific code). This script is throwaway — do not commit it.

- [ ] **Step 4: Commit**
```bash
git add services/admin_audit.py services/admin_permission.py
git commit -m "feat: add admin audit logging and RBAC permission/decorator services"
```

---

### Task 3: Admin Auth — Login, Logout, Session Timeout, First-Login Password Change

**Files:**
- Create: `services/admin_auth.py`
- Modify: `app.py`
- Create: `templates/admin/admin_login.html`
- Create: `templates/admin/admin_force_password_change.html`
- Create: `static/css/admin_auth.css`

**Interfaces:**
- Consumes: `services.admin_audit.log_admin_action`, `services.admin_permission.admin_required`, `auth_helpers.validate_password_strength`.
- Produces: `authenticate_admin(email, password, ip_address=None)`, `change_admin_password(admin, new_password)`; routes `admin_login`, `admin_logout`, `admin_force_password_change` at `/admin/login`, `/admin/logout`, `/admin/force-password-change`.

- [ ] **Step 1: Create `services/admin_auth.py`**
```python
from models import db, now_lagos, AdminUser
from services.admin_audit import log_admin_action


def authenticate_admin(email, password, ip_address=None):
    """Returns the AdminUser on a successful login, or None. Logs the
    attempt either way (a failed attempt against an unknown email logs
    with admin_user=None)."""
    admin = AdminUser.query.filter_by(email=email).first()

    if admin and admin.is_active and admin.check_password(password):
        admin.last_login_at = now_lagos()
        admin.last_login_ip = ip_address
        db.session.commit()
        log_admin_action(admin, 'login', ip_address=ip_address)
        return admin

    log_admin_action(admin, 'login_failed', details=f'attempted email: {email}', ip_address=ip_address)
    return None


def change_admin_password(admin, new_password):
    admin.set_password(new_password)
    admin.first_login = False
    db.session.commit()
```

- [ ] **Step 2: Add imports and config to `app.py`**

Add near the other service imports:
```python
from services.admin_auth import authenticate_admin, change_admin_password
from services.admin_audit import log_admin_action
from services.admin_permission import admin_required, permission_required, get_visible_quick_actions
```

Add near the top-level constants (after the `app = Flask(__name__)` / config block, anywhere before the routes):
```python
ADMIN_SESSION_TIMEOUT_SECONDS = 15 * 60
```

- [ ] **Step 3: Add the admin session-timeout `before_request` hook**

Add this as a new `@app.before_request` function, placed after the existing `enforce_onboarding_gate` function:
```python
@app.before_request
def enforce_admin_session_timeout():
    if not current_user.is_authenticated or not isinstance(current_user, AdminUser):
        return None
    if request.endpoint in ('admin_login', 'static'):
        return None

    now_ts = time.time()
    last_activity = session.get('admin_last_activity')
    if last_activity is not None and (now_ts - last_activity) > ADMIN_SESSION_TIMEOUT_SECONDS:
        logout_user()
        session.pop('admin_last_activity', None)
        flash('Your admin session expired due to inactivity. Please log in again.')
        return redirect(url_for('admin_login'))

    session['admin_last_activity'] = now_ts
    return None
```
(`time`, `session`, `flash`, `redirect`, `url_for`, `logout_user`, `request` are all already imported at the top of `app.py`.)

- [ ] **Step 4: Add the login/logout/force-password-change routes**

Replace the existing orphaned stub:
```python
@app.route('/admin')
def admin():
    return render_template('admin/admin_login.html')
```
with:
```python
@app.route('/admin')
def admin():
    return redirect(url_for('admin_login'))


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated and isinstance(current_user, AdminUser):
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        remember = True if request.form.get('rememberCheck') else False

        admin_user = authenticate_admin(email, password, ip_address=request.remote_addr)
        if admin_user:
            login_user(admin_user, remember=remember)
            session['admin_last_activity'] = time.time()
            if admin_user.first_login:
                return redirect(url_for('admin_force_password_change'))
            return redirect(url_for('admin_dashboard'))

        return render_template('admin/admin_login.html', error='Invalid email or password.', email=email, remember=remember)

    return render_template('admin/admin_login.html')


@app.route('/admin/logout')
@admin_required
def admin_logout():
    log_admin_action(current_user, 'logout', ip_address=request.remote_addr)
    logout_user()
    session.pop('admin_last_activity', None)
    return redirect(url_for('admin_login'))


@app.route('/admin/force-password-change', methods=['GET', 'POST'])
@admin_required
def admin_force_password_change():
    if request.method == 'GET':
        if not current_user.first_login:
            return redirect(url_for('admin_dashboard'))
        return render_template('admin/admin_force_password_change.html')

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    new_pass = data.get('new', '').strip()
    confirm = data.get('confirm', '').strip()

    if not new_pass:
        return jsonify({'success': False, 'message': 'New password is required'}), 400
    if new_pass != confirm:
        return jsonify({'success': False, 'message': 'Passwords do not match'}), 400

    failed_rules = validate_password_strength(new_pass)
    if failed_rules:
        return jsonify({'success': False, 'message': 'Password must contain ' + ', '.join(failed_rules) + '.'}), 400

    change_admin_password(current_user, new_pass)
    log_admin_action(current_user, 'password_changed', ip_address=request.remote_addr)

    return jsonify({
        'success': True,
        'message': 'Password changed successfully.',
        'redirect': url_for('admin_dashboard'),
    })
```
(`validate_password_strength` is already imported at the top of `app.py`.)

- [ ] **Step 5: Create `static/css/admin_auth.css`**

A small admin-specific override sheet, loaded alongside the existing shared `login.css`/`force_password_change.css` (same pattern `force_password_change.html` already uses — layer an admin-specific sheet on top of the shared one rather than duplicating it):
```css
.admin-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    background: #0f3150;
    color: #ffd966;
    padding: 0.3rem 0.9rem;
    border-radius: 60px;
    font-size: 0.8rem;
    font-weight: 600;
    margin-bottom: 1rem;
}
```

- [ ] **Step 6: Create `templates/admin/admin_login.html`**

Mirrors `templates/login.html`'s structure exactly (same `.login-container`/`.login-left`/`.login-right` markup, same CSS files, traditional form POST with server-rendered error-on-failure, no client-side fake-credential JS) but with an email field instead of registration-number, admin-facing copy, and a real link to `/admin/forgot-password`:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes" />
    <title>Admin Login | JSPICT</title>

    <link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,300;14..32,400;14..32,500;14..32,600;14..32,700&display=swap" rel="stylesheet" />
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css" />
    <link rel="stylesheet" href="{{ url_for('static', filename='css/login.css') }}" />
    <link rel="stylesheet" href="{{ url_for('static', filename='css/admin_auth.css') }}" />
</head>

<body>
    <div class="giant-bg"></div>

    <div class="login-container">
        <div class="login-left">
            <div class="school-logo">
                <img class="school-logo-img" src="{{ url_for('static', filename='img/jspict-logo.png') }}" alt="JSPICT Logo" />
            </div>
            <div class="school-name">JSPICT</div>
            <div class="school-tagline">Jigawa State Polytechnic for Information Communication Technology, Kazaure</div>
            <div class="welcome-text">
                <p><i class="fas fa-quote-left"></i> Administrative access to the Student Portal system.</p>
            </div>
        </div>

        <div class="login-right">
            <div class="form-header">
                <span class="admin-badge"><i class="fas fa-user-shield"></i> Admin Portal</span>
                <h2>Administrator sign in</h2>
                <p>Enter your institutional email and password</p>
            </div>

            {% if error %}
            <input type="hidden" id="error-msg" value="{{ error }}" />
            {% else %}
            <input type="hidden" id="error-msg" value="" />
            {% endif %}

            <form id="adminLoginForm" method="POST" action="{{ url_for('admin_login') }}">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}" />

                <div class="input-group">
                    <label>Email</label>
                    <div class="input-icon">
                        <i class="fas fa-envelope"></i>
                        <input type="email" id="email" name="email"
                               placeholder="admin@jspict.edu.ng"
                               value="{{ email if email else '' }}" required />
                    </div>
                </div>

                <div class="input-group">
                    <label>Password</label>
                    <div class="input-icon">
                        <i class="fas fa-key"></i>
                        <input type="password" id="password" name="password" placeholder="••••••••" required />
                    </div>
                </div>

                <div class="flex-options">
                    <div class="checkbox-row">
                        <label class="remember">
                            <input type="checkbox" name="rememberCheck" id="rememberCheck" {% if remember %}checked{% endif %} />
                            <span>Remember me</span>
                        </label>
                    </div>
                    <div class="forgot-link-wrap">
                        <a href="{{ url_for('admin_forgot_password') }}" class="forgot-link">Forgot password?</a>
                    </div>
                </div>

                <button type="submit" class="login-btn" id="loginBtn">
                    <i class="fas fa-arrow-right-to-bracket"></i> Login
                </button>
            </form>
        </div>
    </div>

    <div id="toastMsg" class="alert-toast"></div>

    <script>
        (function() {
            const toast = document.getElementById('toastMsg');
            const errorInput = document.getElementById('error-msg');
            if (errorInput && errorInput.value) {
                toast.textContent = errorInput.value;
                toast.style.backgroundColor = '#b13e3e';
                toast.style.display = 'block';
                setTimeout(function() { toast.style.display = 'none'; }, 3000);
            }
        })();
    </script>
</body>
</html>
```
Note: `.flex-options`/`.checkbox-row`/`.forgot-link-wrap` layout rules live in `login.html`'s own `<style>` block, not `login.css` itself — since this template doesn't inline that block, those three classes will fall back to plain block/inline styling (functional, just not the exact spacing polish `login.html` has). This is an accepted, minor visual gap for this milestone — do not copy `login.html`'s inline `<style>` block wholesale, since duplicating it would drift from the source of truth. If a future pass wants pixel parity, move those rules into `static/css/admin_auth.css` then.

- [ ] **Step 7: Create `templates/admin/admin_force_password_change.html`**

Mirrors `templates/force_password_change.html` exactly, POSTing to the admin endpoint instead:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Set a New Password | JSPICT Admin</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,300;14..32,400;14..32,500;14..32,600;14..32,700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/login.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/force_password_change.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/admin_auth.css') }}">
</head>
<body>
    <div class="giant-bg"></div>

    <div class="login-container">
        <div class="login-left">
            <div class="school-logo">
                <img class="school-logo-img" src="{{ url_for('static', filename='img/jspict-logo.png') }}" alt="JSPICT Logo">
            </div>
            <div class="school-name">JSPICT</div>
            <div class="school-tagline">Jigawa State Polytechnic for Information Communication Technology, Kazaure</div>
            <div class="welcome-text">
                <p><i class="fas fa-quote-left"></i> For your security, set a new password before continuing.</p>
            </div>
        </div>

        <div class="login-right">
            <div class="form-header">
                <span class="admin-badge"><i class="fas fa-user-shield"></i> Admin Portal</span>
                <h2>Set a new password</h2>
                <p>This is your first login &mdash; choose a new password to continue</p>
            </div>

            <form id="passwordChangeForm">
                <input type="hidden" id="csrf_token" value="{{ csrf_token() }}">

                <div class="input-group">
                    <label>New Password</label>
                    <div class="input-icon">
                        <i class="fas fa-key"></i>
                        <input type="password" id="newPassword" required>
                    </div>
                </div>

                <div class="input-group">
                    <label>Confirm Password</label>
                    <div class="input-icon">
                        <i class="fas fa-key"></i>
                        <input type="password" id="confirmPassword" required>
                    </div>
                </div>

                <ul class="password-rules" id="passwordRules">
                    <li data-rule="length"><i class="fas fa-circle"></i> At least 8 characters</li>
                    <li data-rule="uppercase"><i class="fas fa-circle"></i> An uppercase letter</li>
                    <li data-rule="lowercase"><i class="fas fa-circle"></i> A lowercase letter</li>
                    <li data-rule="number"><i class="fas fa-circle"></i> A number</li>
                    <li data-rule="special"><i class="fas fa-circle"></i> A special character</li>
                </ul>

                <button type="submit" class="login-btn" id="submitBtn">
                    <i class="fas fa-arrow-right-to-bracket"></i> Continue
                </button>
            </form>
        </div>
    </div>

    <div id="toastMsg" class="alert-toast"></div>

    <script type="module" src="{{ url_for('static', filename='js/admin/admin-password-change.js') }}"></script>
</body>
</html>
```

- [ ] **Step 8: Create `static/js/admin/admin-password-change.js`**

Identical to `static/js/auth/password-change.js` except it posts to the admin endpoint:
```js
import { showToast } from '../shared/toast.js';
import { postJson } from '../shared/api.js';
import { checkPasswordRules, isPasswordValid } from '../shared/validation.js';

const form = document.getElementById('passwordChangeForm');
const newPasswordInput = document.getElementById('newPassword');
const confirmPasswordInput = document.getElementById('confirmPassword');
const submitBtn = document.getElementById('submitBtn');
const rulesList = document.getElementById('passwordRules');

function updateRuleChecklist() {
    const results = checkPasswordRules(newPasswordInput.value);
    results.forEach(({ key, met }) => {
        const item = rulesList.querySelector(`[data-rule="${key}"]`);
        if (item) item.classList.toggle('met', met);
    });
}

newPasswordInput.addEventListener('input', updateRuleChecklist);

form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const newPassword = newPasswordInput.value;
    const confirmPassword = confirmPasswordInput.value;

    if (!isPasswordValid(newPassword)) {
        showToast('Password does not meet all requirements', true);
        return;
    }
    if (newPassword !== confirmPassword) {
        showToast('Passwords do not match', true);
        return;
    }

    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';

    const result = await postJson('/admin/force-password-change', { new: newPassword, confirm: confirmPassword });

    if (result.success) {
        showToast(result.message, false);
        window.location.href = result.redirect;
    } else {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="fas fa-arrow-right-to-bracket"></i> Continue';
        showToast(result.message, true);
    }
});
```

- [ ] **Step 9: Manual verification**
```bash
python -c "
from app import app
from models import db, AdminRole, AdminUser

with app.app_context():
    role = AdminRole.query.filter_by(name='Test Login Role').first()
    if not role:
        role = AdminRole(name='Test Login Role', description='temp')
        db.session.add(role)
        db.session.commit()
    admin = AdminUser.query.filter_by(email='logintest@example.com').first()
    if not admin:
        admin = AdminUser(email='logintest@example.com', name='Login Test', role_id=role.id, is_active=True, first_login=True)
        admin.set_password('Whatever@123')
        db.session.add(admin)
        db.session.commit()

    client = app.test_client()
    page = client.get('/admin/login')
    print('GET /admin/login:', page.status_code)

    import re
    csrf = re.search(rb'name=\"csrf_token\" value=\"([^\"]+)\"', page.data).group(1).decode()
    resp = client.post('/admin/login', data={'email': 'logintest@example.com', 'password': 'Whatever@123', 'csrf_token': csrf}, follow_redirects=False)
    print('POST /admin/login status:', resp.status_code, 'location:', resp.headers.get('Location'))
    assert '/admin/force-password-change' in resp.headers.get('Location', '')

    force_page = client.get('/admin/force-password-change')
    print('GET force-password-change:', force_page.status_code)
    assert force_page.status_code == 200

    db.session.delete(admin)
    db.session.delete(role)
    db.session.commit()
    print('cleanup done')
"
```
Expected: `POST /admin/login` redirects to `/admin/force-password-change` (since `first_login=True`), and that page loads `200`. This script is throwaway — do not commit it.

- [ ] **Step 10: Commit**
```bash
git add services/admin_auth.py app.py templates/admin/admin_login.html templates/admin/admin_force_password_change.html static/css/admin_auth.css static/js/admin/admin-password-change.js
git commit -m "feat: add admin login/logout/session-timeout/first-login-password-change"
```

---

### Task 4: Admin Forgot Password / Reset Flow

**Files:**
- Modify: `app.py`
- Create: `templates/admin/admin_forgot_password.html`
- Create: `templates/admin/admin_verify_reset_code.html`
- Create: `templates/admin/admin_reset_password.html`
- Create: `static/js/admin/admin-verify-reset-code.js`
- Create: `static/js/admin/admin-reset-password.js`

**Interfaces:**
- Consumes: `onboarding_helpers.start_otp_session`/`register_failed_otp_attempt`/`otp_attempts_exceeded`/`clear_otp_session`, `services.admin_auth.change_admin_password`.
- Produces: routes `admin_forgot_password`, `admin_verify_reset_code`, `admin_reset_password` at `/admin/forgot-password`, `/admin/verify-reset-code`, `/admin/reset-password`.

- [ ] **Step 1: Add imports to `app.py`**

`start_otp_session`, `register_failed_otp_attempt`, `otp_attempts_exceeded`, `clear_otp_session` are already imported from `onboarding_helpers` at the top of `app.py` — no new import needed for those. `Message`/`mail` are already imported too.

- [ ] **Step 2: Add the three routes**

```python
@app.route('/admin/forgot-password', methods=['GET', 'POST'])
def admin_forgot_password():
    if request.method == 'GET':
        return render_template('admin/admin_forgot_password.html')

    email = request.form.get('email', '').strip()
    admin_user = AdminUser.query.filter_by(email=email).first()

    if admin_user:
        code = start_otp_session(session, email)
        session['admin_reset_admin_id'] = admin_user.id
        try:
            msg = Message('Admin Password Reset Code', recipients=[email])
            msg.body = f'Your password reset code is: {code}\nThis code expires in 5 minutes.'
            mail.send(msg)
        except Exception:
            app.logger.warning('Failed to send admin password reset email to %s', email)

    # Always redirect the same way regardless of whether the email matched
    # an account, so this endpoint never reveals which emails are admins.
    return redirect(url_for('admin_verify_reset_code'))


@app.route('/admin/verify-reset-code', methods=['GET', 'POST'])
def admin_verify_reset_code():
    if 'email_verification_code' not in session:
        return redirect(url_for('admin_forgot_password'))

    if request.method == 'GET':
        return render_template('admin/admin_verify_reset_code.html', email=session.get('pending_email'))

    data = request.get_json()
    code = (data.get('code', '') if data else '').strip()

    if otp_attempts_exceeded(session):
        clear_otp_session(session)
        session.pop('admin_reset_admin_id', None)
        return jsonify({'success': False, 'message': 'Too many attempts. Please request a new code.'}), 400

    if time.time() > session.get('email_verification_expiry', 0):
        return jsonify({'success': False, 'message': 'This code has expired. Please request a new one.'}), 400

    if code != session.get('email_verification_code'):
        register_failed_otp_attempt(session)
        return jsonify({'success': False, 'message': 'Incorrect code.'}), 400

    session['admin_reset_verified'] = True
    return jsonify({'success': True, 'redirect': url_for('admin_reset_password')})


@app.route('/admin/reset-password', methods=['GET', 'POST'])
def admin_reset_password():
    if not session.get('admin_reset_verified') or 'admin_reset_admin_id' not in session:
        return redirect(url_for('admin_forgot_password'))

    if request.method == 'GET':
        return render_template('admin/admin_reset_password.html')

    data = request.get_json()
    new_pass = (data.get('new', '') if data else '').strip()
    confirm = (data.get('confirm', '') if data else '').strip()

    if not new_pass or new_pass != confirm:
        return jsonify({'success': False, 'message': 'Passwords do not match'}), 400

    failed_rules = validate_password_strength(new_pass)
    if failed_rules:
        return jsonify({'success': False, 'message': 'Password must contain ' + ', '.join(failed_rules) + '.'}), 400

    admin_user = AdminUser.query.get(session['admin_reset_admin_id'])
    change_admin_password(admin_user, new_pass)
    log_admin_action(admin_user, 'password_reset', ip_address=request.remote_addr)

    clear_otp_session(session)
    session.pop('admin_reset_admin_id', None)
    session.pop('admin_reset_verified', None)

    return jsonify({
        'success': True,
        'message': 'Password reset successfully. Please log in.',
        'redirect': url_for('admin_login'),
    })
```

- [ ] **Step 3: Create `templates/admin/admin_forgot_password.html`**
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Forgot Password | JSPICT Admin</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,300;14..32,400;14..32,500;14..32,600;14..32,700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/login.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/admin_auth.css') }}">
</head>
<body>
    <div class="giant-bg"></div>
    <div class="login-container">
        <div class="login-left">
            <div class="school-logo">
                <img class="school-logo-img" src="{{ url_for('static', filename='img/jspict-logo.png') }}" alt="JSPICT Logo">
            </div>
            <div class="school-name">JSPICT</div>
            <div class="school-tagline">Jigawa State Polytechnic for Information Communication Technology, Kazaure</div>
        </div>
        <div class="login-right">
            <div class="form-header">
                <span class="admin-badge"><i class="fas fa-user-shield"></i> Admin Portal</span>
                <h2>Forgot password</h2>
                <p>Enter your admin email — if it matches an account, we'll send a reset code</p>
            </div>

            <form method="POST" action="{{ url_for('admin_forgot_password') }}">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <div class="input-group">
                    <label>Email</label>
                    <div class="input-icon">
                        <i class="fas fa-envelope"></i>
                        <input type="email" name="email" placeholder="admin@jspict.edu.ng" required>
                    </div>
                </div>
                <button type="submit" class="login-btn">
                    <i class="fas fa-paper-plane"></i> Send reset code
                </button>
            </form>
        </div>
    </div>
</body>
</html>
```

- [ ] **Step 4: Create `templates/admin/admin_verify_reset_code.html`**
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Enter Reset Code | JSPICT Admin</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,300;14..32,400;14..32,500;14..32,600;14..32,700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/login.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/admin_auth.css') }}">
</head>
<body>
    <div class="giant-bg"></div>
    <div class="login-container">
        <div class="login-left">
            <div class="school-logo">
                <img class="school-logo-img" src="{{ url_for('static', filename='img/jspict-logo.png') }}" alt="JSPICT Logo">
            </div>
            <div class="school-name">JSPICT</div>
            <div class="school-tagline">Jigawa State Polytechnic for Information Communication Technology, Kazaure</div>
        </div>
        <div class="login-right">
            <div class="form-header">
                <span class="admin-badge"><i class="fas fa-user-shield"></i> Admin Portal</span>
                <h2>Enter reset code</h2>
                <p>We've sent a 6-digit code to {{ email or 'your email' }} (if it matched an account). It expires in 5 minutes.</p>
            </div>

            <form id="verifyCodeForm">
                <input type="hidden" id="csrf_token" value="{{ csrf_token() }}">
                <div class="input-group">
                    <label>Reset Code</label>
                    <div class="input-icon">
                        <i class="fas fa-shield-halved"></i>
                        <input type="text" id="code" maxlength="6" inputmode="numeric" autocomplete="one-time-code" required>
                    </div>
                </div>
                <button type="submit" class="login-btn" id="verifyBtn">
                    <i class="fas fa-check"></i> Verify code
                </button>
            </form>
        </div>
    </div>

    <div id="toastMsg" class="alert-toast"></div>
    <script type="module" src="{{ url_for('static', filename='js/admin/admin-verify-reset-code.js') }}"></script>
</body>
</html>
```

- [ ] **Step 5: Create `static/js/admin/admin-verify-reset-code.js`**
```js
import { showToast } from '../shared/toast.js';
import { postJson } from '../shared/api.js';

const form = document.getElementById('verifyCodeForm');
const codeInput = document.getElementById('code');
const verifyBtn = document.getElementById('verifyBtn');

form.addEventListener('submit', async (e) => {
    e.preventDefault();

    verifyBtn.disabled = true;
    verifyBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Verifying...';

    const result = await postJson('/admin/verify-reset-code', { code: codeInput.value.trim() });

    if (result.success) {
        window.location.href = result.redirect;
    } else {
        verifyBtn.disabled = false;
        verifyBtn.innerHTML = '<i class="fas fa-check"></i> Verify code';
        showToast(result.message, true);
    }
});
```

- [ ] **Step 6: Create `templates/admin/admin_reset_password.html`**
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Reset Password | JSPICT Admin</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,300;14..32,400;14..32,500;14..32,600;14..32,700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/login.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/force_password_change.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/admin_auth.css') }}">
</head>
<body>
    <div class="giant-bg"></div>
    <div class="login-container">
        <div class="login-left">
            <div class="school-logo">
                <img class="school-logo-img" src="{{ url_for('static', filename='img/jspict-logo.png') }}" alt="JSPICT Logo">
            </div>
            <div class="school-name">JSPICT</div>
            <div class="school-tagline">Jigawa State Polytechnic for Information Communication Technology, Kazaure</div>
        </div>
        <div class="login-right">
            <div class="form-header">
                <span class="admin-badge"><i class="fas fa-user-shield"></i> Admin Portal</span>
                <h2>Set a new password</h2>
            </div>

            <form id="resetPasswordForm">
                <input type="hidden" id="csrf_token" value="{{ csrf_token() }}">

                <div class="input-group">
                    <label>New Password</label>
                    <div class="input-icon">
                        <i class="fas fa-key"></i>
                        <input type="password" id="newPassword" required>
                    </div>
                </div>

                <div class="input-group">
                    <label>Confirm Password</label>
                    <div class="input-icon">
                        <i class="fas fa-key"></i>
                        <input type="password" id="confirmPassword" required>
                    </div>
                </div>

                <ul class="password-rules" id="passwordRules">
                    <li data-rule="length"><i class="fas fa-circle"></i> At least 8 characters</li>
                    <li data-rule="uppercase"><i class="fas fa-circle"></i> An uppercase letter</li>
                    <li data-rule="lowercase"><i class="fas fa-circle"></i> A lowercase letter</li>
                    <li data-rule="number"><i class="fas fa-circle"></i> A number</li>
                    <li data-rule="special"><i class="fas fa-circle"></i> A special character</li>
                </ul>

                <button type="submit" class="login-btn" id="submitBtn">
                    <i class="fas fa-check"></i> Reset password
                </button>
            </form>
        </div>
    </div>

    <div id="toastMsg" class="alert-toast"></div>
    <script type="module" src="{{ url_for('static', filename='js/admin/admin-reset-password.js') }}"></script>
</body>
</html>
```

- [ ] **Step 7: Create `static/js/admin/admin-reset-password.js`**
```js
import { showToast } from '../shared/toast.js';
import { postJson } from '../shared/api.js';
import { checkPasswordRules, isPasswordValid } from '../shared/validation.js';

const form = document.getElementById('resetPasswordForm');
const newPasswordInput = document.getElementById('newPassword');
const confirmPasswordInput = document.getElementById('confirmPassword');
const submitBtn = document.getElementById('submitBtn');
const rulesList = document.getElementById('passwordRules');

function updateRuleChecklist() {
    const results = checkPasswordRules(newPasswordInput.value);
    results.forEach(({ key, met }) => {
        const item = rulesList.querySelector(`[data-rule="${key}"]`);
        if (item) item.classList.toggle('met', met);
    });
}

newPasswordInput.addEventListener('input', updateRuleChecklist);

form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const newPassword = newPasswordInput.value;
    const confirmPassword = confirmPasswordInput.value;

    if (!isPasswordValid(newPassword)) {
        showToast('Password does not meet all requirements', true);
        return;
    }
    if (newPassword !== confirmPassword) {
        showToast('Passwords do not match', true);
        return;
    }

    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';

    const result = await postJson('/admin/reset-password', { new: newPassword, confirm: confirmPassword });

    if (result.success) {
        showToast(result.message, false);
        window.location.href = result.redirect;
    } else {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="fas fa-check"></i> Reset password';
        showToast(result.message, true);
    }
});
```

- [ ] **Step 8: Manual verification**
```bash
python -c "
from app import app
from models import db, AdminRole, AdminUser

with app.app_context():
    role = AdminRole.query.filter_by(name='Test Reset Role').first()
    if not role:
        role = AdminRole(name='Test Reset Role', description='temp')
        db.session.add(role)
        db.session.commit()
    admin = AdminUser.query.filter_by(email='resettest@example.com').first()
    if not admin:
        admin = AdminUser(email='resettest@example.com', name='Reset Test', role_id=role.id, is_active=True, first_login=False)
        admin.set_password('OldPass@123')
        db.session.add(admin)
        db.session.commit()

    client = app.test_client()
    resp = client.post('/admin/forgot-password', data={'email': 'resettest@example.com'}, follow_redirects=False)
    print('POST forgot-password status:', resp.status_code, 'location:', resp.headers.get('Location'))

    with client.session_transaction() as sess:
        code = sess['email_verification_code']
        print('otp code captured from session:', code)

    verify_resp = client.post('/admin/verify-reset-code', json={'code': code})
    print('verify result:', verify_resp.get_json())

    reset_resp = client.post('/admin/reset-password', json={'new': 'NewPass@456', 'confirm': 'NewPass@456'})
    print('reset result:', reset_resp.get_json())

    db.session.refresh(admin)
    print('password actually changed:', admin.check_password('NewPass@456'))

    db.session.delete(admin)
    db.session.delete(role)
    db.session.commit()
    print('cleanup done')
"
```
Expected: forgot-password redirects, the OTP code is readable straight from the test session (a legitimate testing shortcut — no email server needed), verify succeeds, reset succeeds, and `password actually changed: True`. This script is throwaway — do not commit it.

- [ ] **Step 9: Commit**
```bash
git add app.py templates/admin/admin_forgot_password.html templates/admin/admin_verify_reset_code.html templates/admin/admin_reset_password.html static/js/admin/admin-verify-reset-code.js static/js/admin/admin-reset-password.js
git commit -m "feat: add admin forgot-password / OTP verify / reset-password flow"
```

---

### Task 5: Admin Dashboard Service

**Files:**
- Create: `services/admin_dashboard.py`

**Interfaces:**
- Produces: `get_dashboard_summary()` → dict with `total_students`, `active_students`, `current_semester_registrations`, `total_payments`, `active_courses`, `departments`; `get_activity_feed(limit=20)` → list of `{icon, description, timestamp}` dicts, newest first.

- [ ] **Step 1: Write `services/admin_dashboard.py`**
```python
from models import (
    db, User, StudentRegistration, RegistrationPeriod, Payment, Course,
    RegisteredCourse, AdminAuditLog, AuditLog, Notification, AdminUser,
)


def get_dashboard_summary():
    active_period = RegistrationPeriod.query.filter_by(is_active=True).order_by(RegistrationPeriod.id.desc()).first()

    current_semester_registrations = 0
    active_courses = 0
    if active_period is not None:
        current_semester_registrations = StudentRegistration.query.filter_by(
            registration_period_id=active_period.id
        ).count()
        active_courses = Course.query.filter_by(
            academic_session_id=active_period.academic_session_id,
            semester_id=active_period.semester_id,
        ).count()

    total_students = User.query.count()
    active_students = User.query.filter_by(onboarding_completed=True).count()
    total_payments = Payment.query.filter_by(status='successful').count()
    departments = db.session.query(User.department).filter(User.department.isnot(None)).distinct().count()

    return {
        'total_students': total_students,
        'active_students': active_students,
        'current_semester_registrations': current_semester_registrations,
        'total_payments': total_payments,
        'active_courses': active_courses,
        'departments': departments,
    }


def get_activity_feed(limit=20):
    """Merge recent activity from several existing tables into one
    newest-first feed. No new event-logging system — this reads data
    that already exists for other reasons."""
    events = []

    for reg in StudentRegistration.query.order_by(StudentRegistration.registered_at.desc()).limit(limit).all():
        student = User.query.get(reg.user_id)
        events.append({
            'icon': 'fa-user-plus',
            'description': f'{student.name if student else "A student"} registered for {reg.registration_period.academic_session.name} {reg.registration_period.semester.name}',
            'timestamp': reg.registered_at,
        })

    for payment in Payment.query.filter_by(status='successful').order_by(Payment.verified_at.desc()).limit(limit).all():
        if payment.verified_at is None:
            continue
        events.append({
            'icon': 'fa-credit-card',
            'description': f'{payment.user.name} completed a payment of ₦{payment.total_amount:,.2f} (reference {payment.reference})',
            'timestamp': payment.verified_at,
        })

    for rc in RegisteredCourse.query.order_by(RegisteredCourse.added_at.desc()).limit(limit).all():
        student = User.query.get(rc.student_registration.user_id)
        events.append({
            'icon': 'fa-book-open',
            'description': f'{student.name if student else "A student"} registered for {rc.course.code} {rc.course.title}',
            'timestamp': rc.added_at,
        })

    for log in AdminAuditLog.query.filter_by(action='login').order_by(AdminAuditLog.created_at.desc()).limit(limit).all():
        admin_user = AdminUser.query.get(log.admin_user_id) if log.admin_user_id else None
        name = admin_user.name if admin_user else 'An administrator'
        events.append({
            'icon': 'fa-user-shield',
            'description': f'{name} logged into the admin portal',
            'timestamp': log.created_at,
        })

    for log in AuditLog.query.filter_by(action='profile_updated').order_by(AuditLog.created_at.desc()).limit(limit).all():
        user = User.query.get(log.user_id)
        name = user.name if user else 'A student'
        events.append({
            'icon': 'fa-id-card',
            'description': f'{name} updated their profile',
            'timestamp': log.created_at,
        })

    for note in Notification.query.filter_by(category='announcements').order_by(Notification.created_at.desc()).limit(limit).all():
        events.append({
            'icon': 'fa-bullhorn',
            'description': note.title,
            'timestamp': note.created_at,
        })

    events.sort(key=lambda e: e['timestamp'], reverse=True)
    return events[:limit]
```
Verified directly against `services/profile.py`: `update_contact_info` logs `log_action(user, 'profile_updated', ...)` — that's the exact action string used above, not a guess. If no rows exist yet, that source of the feed is simply empty (harmless — the feed still works from the other 5 sources).

- [ ] **Step 2: Manual verification**
```bash
python -c "
from app import app
from services.admin_dashboard import get_dashboard_summary, get_activity_feed

with app.app_context():
    summary = get_dashboard_summary()
    print('summary:', summary)
    assert set(summary.keys()) == {'total_students', 'active_students', 'current_semester_registrations', 'total_payments', 'active_courses', 'departments'}

    feed = get_activity_feed(limit=10)
    print('feed entries:', len(feed))
    for e in feed[:5]:
        print(' -', e['timestamp'], e['description'])
    if len(feed) > 1:
        assert feed[0]['timestamp'] >= feed[-1]['timestamp'], 'feed not sorted newest-first'
        print('sort order verified')
"
```
Expected: a real summary dict with actual counts from the seeded dev DB, and a feed with entries drawn from real registration/payment/course/notification data, sorted newest-first. This script is throwaway — do not commit it.

- [ ] **Step 3: Commit**
```bash
git add services/admin_dashboard.py
git commit -m "feat: add admin dashboard service (summary card queries + merged activity feed)"
```

---

### Task 6: Admin Base Layout

**Files:**
- Create: `templates/admin/base_admin.html`
- Create: `templates/admin/access_denied.html`
- Create: `templates/admin/coming_soon.html`
- Create: `static/css/admin.css`
- Create: `static/js/admin/admin-layout.js`

**Interfaces:**
- Produces: a `{% block content %}`-based base template every future admin page extends, matching the `{% block head %}`/`{% block content %}`/`{% block scripts %}` structure the student `base.html` already uses.

- [ ] **Step 1: Create `static/css/admin.css`**

Reuses the same `:root` variable palette already established in `payments_history.css`, plus a sidebar/topbar layout and a dark-theme override block:
```css
:root {
    --bg-body: #f5faff;
    --card-bg: rgba(255, 255, 255, 0.9);
    --glass-border: rgba(255, 255, 255, 0.7);
    --primary-dark: #103957;
    --primary: #1d4f7c;
    --primary-light: #e3efff;
    --accent: #286b9f;
    --success: #0e7a4b;
    --warning: #b6580b;
    --danger: #b13e3e;
    --text-main: #102c42;
    --text-secondary: #2b5277;
    --text-muted: #5f7e9c;
    --border-color: #cfe0f2;
    --sidebar-width: 260px;
}

:root[data-admin-theme="dark"] {
    --bg-body: #0b1826;
    --card-bg: #142943;
    --primary-dark: #0b1e30;
    --text-main: #e6f0fa;
    --text-secondary: #b7cbe0;
    --text-muted: #7f9bb8;
    --border-color: #24405e;
}

* { box-sizing: border-box; font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
body { margin: 0; background: var(--bg-body); color: var(--text-main); }

.admin-shell { display: flex; min-height: 100vh; }

.admin-sidebar {
    width: var(--sidebar-width);
    background: var(--primary-dark);
    color: white;
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
    transition: margin-left 0.2s;
}
.admin-sidebar.collapsed { margin-left: calc(-1 * var(--sidebar-width)); }
.admin-sidebar .brand { display: flex; align-items: center; gap: 0.6rem; padding: 1.2rem; font-weight: 700; }
.admin-sidebar .brand img { width: 32px; height: 32px; border-radius: 50%; object-fit: cover; }
.admin-nav { list-style: none; padding: 0; margin: 0; flex: 1; overflow-y: auto; }
.admin-nav a {
    display: flex; align-items: center; gap: 0.7rem;
    padding: 0.8rem 1.2rem; color: #cfe0f2; text-decoration: none; font-size: 0.92rem;
}
.admin-nav a:hover, .admin-nav a.active { background: rgba(255,255,255,0.08); color: white; }

.admin-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }

.admin-topbar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 1rem 1.5rem; background: var(--card-bg); border-bottom: 1px solid var(--border-color);
}
.admin-topbar .breadcrumbs { color: var(--text-muted); font-size: 0.85rem; }
.admin-topbar .topbar-actions { display: flex; align-items: center; gap: 1rem; }
.admin-search { display: flex; align-items: center; gap: 0.5rem; background: var(--bg-body); border: 1px solid var(--border-color); border-radius: 40px; padding: 0.4rem 1rem; }
.admin-search input { border: none; background: transparent; outline: none; color: var(--text-main); }
.admin-notif-btn, .admin-theme-btn { position: relative; background: none; border: none; font-size: 1.1rem; color: var(--text-secondary); cursor: pointer; }
.admin-notif-badge { position: absolute; top: -4px; right: -6px; background: var(--danger); color: white; font-size: 0.65rem; border-radius: 50%; padding: 0.1rem 0.35rem; }
.admin-profile-menu { position: relative; }
.admin-profile-btn { display: flex; align-items: center; gap: 0.5rem; background: none; border: none; cursor: pointer; color: var(--text-main); }
.admin-profile-dropdown { display: none; position: absolute; right: 0; top: 120%; background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 0.8rem; min-width: 180px; box-shadow: 0 10px 30px -10px rgba(0,0,0,0.3); }
.admin-profile-dropdown.open { display: block; }
.admin-profile-dropdown a { display: block; padding: 0.7rem 1rem; color: var(--text-main); text-decoration: none; font-size: 0.9rem; }
.admin-profile-dropdown a:hover { background: var(--primary-light); }

.admin-content { padding: 1.5rem; flex: 1; }

.admin-hamburger { display: none; background: none; border: none; font-size: 1.3rem; color: var(--text-main); cursor: pointer; }
@media (max-width: 900px) {
    .admin-hamburger { display: block; }
    .admin-sidebar { position: fixed; z-index: 50; height: 100vh; margin-left: calc(-1 * var(--sidebar-width)); }
    .admin-sidebar.mobile-open { margin-left: 0; }
}
```

- [ ] **Step 2: Create `static/js/admin/admin-layout.js`**
```js
(function() {
    const hamburger = document.getElementById('adminHamburger');
    const sidebar = document.getElementById('adminSidebar');
    const profileBtn = document.getElementById('adminProfileBtn');
    const profileDropdown = document.getElementById('adminProfileDropdown');
    const themeBtn = document.getElementById('adminThemeBtn');

    if (hamburger && sidebar) {
        hamburger.addEventListener('click', () => sidebar.classList.toggle('mobile-open'));
    }

    if (profileBtn && profileDropdown) {
        profileBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            profileDropdown.classList.toggle('open');
        });
        document.addEventListener('click', () => profileDropdown.classList.remove('open'));
    }

    if (themeBtn) {
        const stored = localStorage.getItem('adminTheme');
        if (stored === 'dark') {
            document.documentElement.setAttribute('data-admin-theme', 'dark');
        }
        themeBtn.addEventListener('click', () => {
            const isDark = document.documentElement.getAttribute('data-admin-theme') === 'dark';
            if (isDark) {
                document.documentElement.removeAttribute('data-admin-theme');
                localStorage.setItem('adminTheme', 'light');
            } else {
                document.documentElement.setAttribute('data-admin-theme', 'dark');
                localStorage.setItem('adminTheme', 'dark');
            }
        });
    }
})();
```

- [ ] **Step 3: Create `templates/admin/base_admin.html`**
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/admin.css') }}">
    {% block head %}{% endblock %}
</head>
<body>
    <div class="admin-shell">
        <aside class="admin-sidebar" id="adminSidebar">
            <div class="brand">
                <img src="{{ url_for('static', filename='img/jspict-logo.png') }}" alt="JSPICT Logo">
                <span>JSPICT Admin</span>
            </div>
            <ul class="admin-nav">
                <li><a href="{{ url_for('admin_dashboard') }}" class="{{ 'active' if request.endpoint == 'admin_dashboard' }}"><i class="fas fa-gauge"></i> Dashboard</a></li>
                <li><a href="{{ url_for('admin_stub_students_import') }}"><i class="fas fa-users"></i> Students</a></li>
                <li><a href="{{ url_for('admin_stub_courses') }}"><i class="fas fa-book"></i> Courses</a></li>
                <li><a href="{{ url_for('admin_stub_registration_open') }}"><i class="fas fa-door-open"></i> Registration</a></li>
                <li><a href="{{ url_for('admin_stub_reports') }}"><i class="fas fa-file-invoice-dollar"></i> Payments</a></li>
                <li><a href="{{ url_for('admin_stub_announcements_new') }}"><i class="fas fa-bullhorn"></i> Announcements</a></li>
                <li><a href="{{ url_for('admin_stub_reports') }}"><i class="fas fa-chart-bar"></i> Reports</a></li>
                <li><a href="{{ url_for('admin_logout') }}"><i class="fas fa-sign-out-alt"></i> Logout</a></li>
            </ul>
        </aside>

        <div class="admin-main">
            <div class="admin-topbar">
                <div style="display:flex; align-items:center; gap:1rem;">
                    <button class="admin-hamburger" id="adminHamburger"><i class="fas fa-bars"></i></button>
                    <div class="breadcrumbs">{% block breadcrumbs %}Admin{% endblock %}</div>
                </div>
                <div class="topbar-actions">
                    <div class="admin-search">
                        <i class="fas fa-search" style="color: var(--text-muted);"></i>
                        <input type="text" placeholder="Search...">
                    </div>
                    <button class="admin-theme-btn" id="adminThemeBtn"><i class="fas fa-moon"></i></button>
                    <button class="admin-notif-btn"><i class="fas fa-bell"></i></button>
                    <div class="admin-profile-menu">
                        <button class="admin-profile-btn" id="adminProfileBtn">
                            <i class="fas fa-user-shield"></i>
                            <span>{{ current_user.name }}</span>
                            <i class="fas fa-chevron-down" style="font-size:0.7rem;"></i>
                        </button>
                        <div class="admin-profile-dropdown" id="adminProfileDropdown">
                            <div style="padding: 0.7rem 1rem; color: var(--text-muted); font-size: 0.8rem;">{{ current_user.role.name }}</div>
                            <a href="{{ url_for('admin_logout') }}"><i class="fas fa-sign-out-alt"></i> Logout</a>
                        </div>
                    </div>
                </div>
            </div>

            {% with messages = get_flashed_messages() %}
            {% if messages %}
            <div style="padding: 0.8rem 1.5rem;">
                {% for message in messages %}
                <div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 0.6rem; padding: 0.7rem 1rem; margin-bottom: 0.5rem;">{{ message }}</div>
                {% endfor %}
            </div>
            {% endif %}
            {% endwith %}

            <div class="admin-content">
                {% block content %}{% endblock %}
            </div>
        </div>
    </div>

    <script src="{{ url_for('static', filename='js/admin/admin-layout.js') }}"></script>
    {% block scripts %}{% endblock %}
</body>
</html>
```

- [ ] **Step 4: Create `templates/admin/access_denied.html`**
```html
{% extends "admin/base_admin.html" %}

{% block breadcrumbs %}Access Denied{% endblock %}

{% block content %}
<div style="text-align:center; padding: 4rem 2rem; background: var(--card-bg); border-radius: 1rem; border: 1px solid var(--border-color);">
    <i class="fas fa-lock" style="font-size: 3rem; color: var(--danger); margin-bottom: 1rem;"></i>
    <h2>Access Denied</h2>
    <p style="color: var(--text-muted);">Your role ({{ current_user.role.name }}) doesn't have permission to view this page.</p>
    <a href="{{ url_for('admin_dashboard') }}" style="display:inline-block; margin-top:1rem; color: var(--primary-dark); font-weight:600;">Back to Dashboard</a>
</div>
{% endblock %}
```

- [ ] **Step 5: Create `templates/admin/coming_soon.html`**
```html
{% extends "admin/base_admin.html" %}

{% block breadcrumbs %}{{ feature_name }}{% endblock %}

{% block content %}
<div style="text-align:center; padding: 4rem 2rem; background: var(--card-bg); border-radius: 1rem; border: 1px solid var(--border-color);">
    <i class="fas fa-hammer" style="font-size: 3rem; color: var(--accent); margin-bottom: 1rem;"></i>
    <h2>{{ feature_name }}</h2>
    <p style="color: var(--text-muted);">This feature isn't built yet — it's coming in a future milestone.</p>
    <a href="{{ url_for('admin_dashboard') }}" style="display:inline-block; margin-top:1rem; color: var(--primary-dark); font-weight:600;">Back to Dashboard</a>
</div>
{% endblock %}
```

- [ ] **Step 6: Manual verification**

This template can't be meaningfully rendered stand-alone yet (it needs `admin_dashboard`/`admin_stub_*`/`admin_logout` endpoints, which land in Tasks 7-8) — verify only that it parses as valid Jinja and the CSS/JS files are syntactically sound:
```bash
python -c "
from app import app
with app.app_context():
    env = app.jinja_env
    src = env.loader.get_source(env, 'admin/base_admin.html')[0]
    env.parse(src)
    print('base_admin.html parses OK')
    src2 = env.loader.get_source(env, 'admin/access_denied.html')[0]
    env.parse(src2)
    print('access_denied.html parses OK')
    src3 = env.loader.get_source(env, 'admin/coming_soon.html')[0]
    env.parse(src3)
    print('coming_soon.html parses OK')
"
node -e "console.log('admin-layout.js has valid JS syntax:'); new Function(require('fs').readFileSync('static/js/admin/admin-layout.js', 'utf8')); console.log('OK')" 2>/dev/null || echo "node not available — skipping JS syntax check, will be verified visually in Task 7/8"
```
Full end-to-end rendering is verified in Task 7's manual check, once the referenced routes exist.

- [ ] **Step 7: Commit**
```bash
git add templates/admin/base_admin.html templates/admin/access_denied.html templates/admin/coming_soon.html static/css/admin.css static/js/admin/admin-layout.js
git commit -m "feat: add reusable admin layout (sidebar, topbar, profile menu, theme toggle) and Access Denied / Coming Soon pages"
```

---

### Task 7: Dashboard Route and Page

**Files:**
- Modify: `app.py`
- Create: `templates/admin/admin_dashboard.html` (replaces the orphaned mock — same filename, entirely new content)

**Interfaces:**
- Consumes: `services.admin_dashboard.get_dashboard_summary`/`get_activity_feed`, `services.admin_permission.permission_required`/`get_visible_quick_actions`.
- Produces: route `admin_dashboard` at `/admin/dashboard`.

- [ ] **Step 1: Add imports and the dashboard route to `app.py`**

Add `from services.admin_dashboard import get_dashboard_summary, get_activity_feed` to the imports block.

```python
@app.route('/admin/dashboard')
@permission_required('dashboard.view')
def admin_dashboard():
    summary = get_dashboard_summary()
    activity_feed = get_activity_feed(limit=20)
    quick_actions = get_visible_quick_actions(current_user)
    return render_template(
        'admin/admin_dashboard.html',
        summary=summary, activity_feed=activity_feed, quick_actions=quick_actions,
    )
```

- [ ] **Step 2: Replace `templates/admin/admin_dashboard.html`**

Delete the entire existing 622-line mocked file and replace it with:
```html
{% extends "admin/base_admin.html" %}

{% block breadcrumbs %}Dashboard{% endblock %}

{% block content %}
<div style="display:grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 1.2rem; margin-bottom: 1.5rem;">
    <div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; padding: 1.2rem;">
        <div style="color: var(--text-muted); font-size: 0.85rem;"><i class="fas fa-user-graduate"></i> Total Students</div>
        <div style="font-size: 1.8rem; font-weight: 700; color: var(--primary-dark);">{{ summary.total_students }}</div>
    </div>
    <div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; padding: 1.2rem;">
        <div style="color: var(--text-muted); font-size: 0.85rem;"><i class="fas fa-user-check"></i> Active Students</div>
        <div style="font-size: 1.8rem; font-weight: 700; color: var(--primary-dark);">{{ summary.active_students }}</div>
    </div>
    <div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; padding: 1.2rem;">
        <div style="color: var(--text-muted); font-size: 0.85rem;"><i class="fas fa-clipboard-list"></i> Current Semester Registrations</div>
        <div style="font-size: 1.8rem; font-weight: 700; color: var(--primary-dark);">{{ summary.current_semester_registrations }}</div>
    </div>
    <div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; padding: 1.2rem;">
        <div style="color: var(--text-muted); font-size: 0.85rem;"><i class="fas fa-credit-card"></i> Total Payments</div>
        <div style="font-size: 1.8rem; font-weight: 700; color: var(--primary-dark);">{{ summary.total_payments }}</div>
    </div>
    <div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; padding: 1.2rem;">
        <div style="color: var(--text-muted); font-size: 0.85rem;"><i class="fas fa-book"></i> Active Courses</div>
        <div style="font-size: 1.8rem; font-weight: 700; color: var(--primary-dark);">{{ summary.active_courses }}</div>
    </div>
    <div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; padding: 1.2rem;">
        <div style="color: var(--text-muted); font-size: 0.85rem;"><i class="fas fa-building"></i> Departments</div>
        <div style="font-size: 1.8rem; font-weight: 700; color: var(--primary-dark);">{{ summary.departments }}</div>
    </div>
    <div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; padding: 1.2rem;">
        <div style="color: var(--text-muted); font-size: 0.85rem;"><i class="fas fa-headset"></i> Pending Support Tickets</div>
        <div style="font-size: 1.1rem; font-weight: 600; color: var(--text-muted);">Not yet available</div>
    </div>
</div>

<div style="display:grid; grid-template-columns: 1fr; gap: 1.2rem;">
    {% if quick_actions %}
    <div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; padding: 1.2rem;">
        <h3 style="margin-top:0;"><i class="fas fa-bolt"></i> Quick Actions</h3>
        <div style="display:flex; flex-wrap:wrap; gap: 0.8rem;">
            {% for endpoint, code, label, icon in quick_actions %}
            <a href="{{ url_for(endpoint) }}" style="display:flex; align-items:center; gap:0.5rem; padding: 0.7rem 1.2rem; background: var(--primary-light); border-radius: 0.6rem; color: var(--primary-dark); text-decoration:none; font-weight:600; font-size:0.9rem;">
                <i class="fas {{ icon }}"></i> {{ label }}
            </a>
            {% endfor %}
        </div>
    </div>
    {% endif %}

    <div style="background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 1rem; padding: 1.2rem;">
        <h3 style="margin-top:0;"><i class="fas fa-history"></i> Recent Activity</h3>
        {% if not activity_feed %}
        <p style="color: var(--text-muted);">No recent activity yet.</p>
        {% else %}
        <ul style="list-style:none; padding:0; margin:0; display:flex; flex-direction:column; gap:0.7rem;">
            {% for event in activity_feed %}
            <li style="display:flex; align-items:flex-start; gap:0.8rem; padding-bottom:0.7rem; border-bottom: 1px solid var(--border-color);">
                <i class="fas {{ event.icon }}" style="color: var(--accent); margin-top:0.2rem;"></i>
                <div>
                    <div>{{ event.description }}</div>
                    <div style="color: var(--text-muted); font-size: 0.78rem;">{{ event.timestamp.strftime('%d %b %Y, %I:%M %p') }}</div>
                </div>
            </li>
            {% endfor %}
        </ul>
        {% endif %}
    </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Manual verification**
```bash
python -c "
from app import app
from models import db, AdminRole, Permission, AdminUser

with app.app_context():
    role = AdminRole.query.filter_by(name='Test Dashboard Role').first()
    if not role:
        role = AdminRole(name='Test Dashboard Role', description='temp')
        db.session.add(role)
        db.session.commit()
    perm = Permission.query.filter_by(code='dashboard.view').first()
    if not perm:
        perm = Permission(code='dashboard.view', description='View the admin dashboard')
        db.session.add(perm)
        db.session.commit()
    if perm not in role.permissions:
        role.permissions.append(perm)
        db.session.commit()

    admin = AdminUser.query.filter_by(email='dashtest@example.com').first()
    if not admin:
        admin = AdminUser(email='dashtest@example.com', name='Dash Test', role_id=role.id, is_active=True, first_login=False)
        admin.set_password('Whatever@123')
        db.session.add(admin)
        db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = f'admin:{admin.id}'
        sess['_fresh'] = True

    resp = client.get('/admin/dashboard')
    print('GET /admin/dashboard status:', resp.status_code)
    assert resp.status_code == 200
    assert b'Total Students' in resp.data
    print('dashboard renders with real summary cards: OK')

    db.session.delete(admin)
    db.session.commit()
    print('cleanup done (role/permission left seeded for later tasks to reuse if convenient, or delete them too — either is fine)')
"
```
Expected: `200`, dashboard HTML contains the real card labels. This script is throwaway — do not commit it.

- [ ] **Step 4: Commit**
```bash
git add app.py templates/admin/admin_dashboard.html
git commit -m "feat: add live admin dashboard (real summary cards, merged activity feed, permission-filtered quick actions)"
```

---

### Task 8: Quick Action Stub Routes

**Files:**
- Modify: `app.py`

**Interfaces:**
- Produces: 6 routes (`admin_stub_sessions_new`, `admin_stub_students_import`, `admin_stub_courses`, `admin_stub_registration_open`, `admin_stub_announcements_new`, `admin_stub_reports`), each gated by its own permission code, each rendering `admin/coming_soon.html`.

- [ ] **Step 1: Add the 6 stub routes to `app.py`**

```python
@app.route('/admin/sessions/new')
@permission_required('sessions.manage')
def admin_stub_sessions_new():
    return render_template('admin/coming_soon.html', feature_name='Create Session')


@app.route('/admin/students/import')
@permission_required('students.manage')
def admin_stub_students_import():
    return render_template('admin/coming_soon.html', feature_name='Upload Students')


@app.route('/admin/courses')
@permission_required('courses.manage')
def admin_stub_courses():
    return render_template('admin/coming_soon.html', feature_name='Manage Courses')


@app.route('/admin/registration/open')
@permission_required('registration.manage')
def admin_stub_registration_open():
    return render_template('admin/coming_soon.html', feature_name='Open Registration')


@app.route('/admin/announcements/new')
@permission_required('announcements.manage')
def admin_stub_announcements_new():
    return render_template('admin/coming_soon.html', feature_name='Create Announcement')


@app.route('/admin/reports')
@permission_required('reports.view')
def admin_stub_reports():
    return render_template('admin/coming_soon.html', feature_name='Generate Reports')
```

- [ ] **Step 2: Manual verification — this is the RBAC proof point, verify it precisely**
```bash
python -c "
from app import app
from models import db, AdminRole, Permission, AdminUser

with app.app_context():
    super_role = AdminRole.query.filter_by(name='Super Administrator').first()
    academic_role = AdminRole.query.filter_by(name='Academic Administrator').first()
    if not super_role or not academic_role:
        print('Roles not seeded yet (Task 9 seeds them) — creating temporary ones for this check only')
        super_role = AdminRole(name='Temp Super', description='temp')
        academic_role = AdminRole(name='Temp Academic', description='temp')
        db.session.add_all([super_role, academic_role])
        db.session.commit()

        courses_perm = Permission(code='courses.manage', description='temp')
        sessions_perm = Permission(code='sessions.manage', description='temp')
        db.session.add_all([courses_perm, sessions_perm])
        db.session.commit()
        super_role.permissions.extend([courses_perm, sessions_perm])
        academic_role.permissions.append(courses_perm)
        db.session.commit()

    super_admin = AdminUser(email='stubtest.super@example.com', name='Super Test', role_id=super_role.id, is_active=True, first_login=False)
    super_admin.set_password('Whatever@123')
    academic_admin = AdminUser(email='stubtest.academic@example.com', name='Academic Test', role_id=academic_role.id, is_active=True, first_login=False)
    academic_admin.set_password('Whatever@123')
    db.session.add_all([super_admin, academic_admin])
    db.session.commit()

    client = app.test_client()

    with client.session_transaction() as sess:
        sess['_user_id'] = f'admin:{academic_admin.id}'
        sess['_fresh'] = True
    resp_allowed = client.get('/admin/courses')
    resp_denied = client.get('/admin/sessions/new')
    print('Academic Admin -> /admin/courses status:', resp_allowed.status_code)
    print('Academic Admin -> /admin/sessions/new status:', resp_denied.status_code)
    assert resp_allowed.status_code == 200
    assert resp_denied.status_code == 403
    assert b'Access Denied' in resp_denied.data

    with client.session_transaction() as sess:
        sess['_user_id'] = f'admin:{super_admin.id}'
        sess['_fresh'] = True
    resp_super = client.get('/admin/sessions/new')
    print('Super Admin -> /admin/sessions/new status:', resp_super.status_code)
    assert resp_super.status_code == 200

    db.session.delete(super_admin)
    db.session.delete(academic_admin)
    db.session.commit()
    print('RBAC proof verified: Academic Admin blocked from a Super-only route with a real 403 + Access Denied page; Super Admin allowed.')
"
```
Expected: Academic Administrator gets `200` on `/admin/courses`, `403` + Access Denied HTML on `/admin/sessions/new`; Super Administrator gets `200` on `/admin/sessions/new`. This is the deliverable's "✓ Role Validation ✓ Unauthorized Access" proof — verify the exact output, don't skip this. This script is throwaway — do not commit it.

- [ ] **Step 3: Commit**
```bash
git add app.py
git commit -m "feat: add permission-gated Quick Action stub routes (navigation only, no feature logic yet)"
```

---

### Task 9: Seed Data and Progress Log

**Files:**
- Modify: `seed_dev_data.py`
- Modify: `DEVELOPMENT_PROGRESS.md`

**Interfaces:**
- Produces: `seed_admin_rbac()` (permissions + 2 roles + role-permission assignments), `seed_admin_users()` (2 `AdminUser` accounts), both called from `seed()`.

- [ ] **Step 1: Read `seed_dev_data.py` first, then add `seed_admin_rbac()`**

Add `AdminRole, Permission, AdminUser` to the `from models import (...)` block at the top of the file.

Following the file's established idempotent pattern:
```python
def seed_admin_rbac():
    permissions = [
        ('dashboard.view', 'View the admin dashboard'),
        ('sessions.manage', 'Create and manage academic sessions'),
        ('students.manage', 'Bulk-import and manage student accounts'),
        ('courses.manage', 'Manage the course catalog'),
        ('registration.manage', 'Open/close registration periods'),
        ('announcements.manage', 'Create system announcements'),
        ('reports.view', 'View and generate reports'),
    ]
    perm_objs = {}
    for code, description in permissions:
        perm = Permission.query.filter_by(code=code).first()
        if not perm:
            perm = Permission(code=code, description=description)
            db.session.add(perm)
            db.session.commit()
            print(f'Seeded permission: {code}')
        else:
            print(f'Skipping permission {code} (already exists)')
        perm_objs[code] = perm

    roles = {
        'Super Administrator': (
            'Complete system access',
            ['dashboard.view', 'sessions.manage', 'students.manage', 'courses.manage', 'registration.manage', 'announcements.manage', 'reports.view'],
        ),
        'Academic Administrator': (
            'Course management, registration oversight, and announcements',
            ['dashboard.view', 'courses.manage', 'registration.manage', 'announcements.manage'],
        ),
    }
    for name, (description, codes) in roles.items():
        role = AdminRole.query.filter_by(name=name).first()
        if not role:
            role = AdminRole(name=name, description=description)
            db.session.add(role)
            db.session.commit()
            print(f'Seeded admin role: {name}')
        else:
            print(f'Skipping admin role {name} (already exists)')

        for code in codes:
            if perm_objs[code] not in role.permissions:
                role.permissions.append(perm_objs[code])
        db.session.commit()
```

- [ ] **Step 2: Add `seed_admin_users()`**
```python
def seed_admin_users():
    super_role = AdminRole.query.filter_by(name='Super Administrator').first()
    academic_role = AdminRole.query.filter_by(name='Academic Administrator').first()
    if not super_role or not academic_role:
        print('Skipping seed_admin_users (admin roles not seeded yet)')
        return

    admins = [
        ('super.admin@jspict.edu.ng', 'Amina Super-Admin', super_role.id),
        ('academic.admin@jspict.edu.ng', 'Bello Academic-Admin', academic_role.id),
    ]
    for email, name, role_id in admins:
        if AdminUser.query.filter_by(email=email).first():
            print(f'Skipping admin user {email} (already exists)')
            continue
        admin = AdminUser(email=email, name=name, role_id=role_id, is_active=True, first_login=True)
        admin.set_password(DEFAULT_PASSWORD)
        db.session.add(admin)
        db.session.commit()
        print(f'Seeded admin user: {email} ({name})')

    print(f'Default password for seeded admin accounts: {DEFAULT_PASSWORD}')
```
(`DEFAULT_PASSWORD` is the existing module-level constant `"Default@123"` already defined at the top of this file — reused here rather than introducing a second default password to remember.)

- [ ] **Step 3: Call both from `seed()`, run the seed script**

In the `seed()` function, add calls to `seed_admin_rbac()` and `seed_admin_users()` after the existing `seed_payments()` call.

```bash
python seed_dev_data.py
```
Expected: prints permission/role/admin-user seed lines (or "Skipping" if re-run — including gracefully absorbing any leftover temp roles/admins created by earlier tasks' manual verification scripts, which were cleaned up after each run).

- [ ] **Step 4: Update `DEVELOPMENT_PROGRESS.md`**

Replace:
```
## Next milestone

Admin Portal — not yet started.
```
with:
```
## Admin Portal — Foundation (Auth, RBAC, Layout, Dashboard, Audit Logging) — Complete

- New models: `AdminRole`, `Permission`, `RolePermission`, `AdminUser`, `AdminAuditLog` — a fully separate admin identity from `User` (the dead `User.is_admin` column is untouched). Loaded by the existing shared `LoginManager` via a prefixed id (`admin:<id>`), so one `user_loader` distinguishes student and admin sessions.
- Admin auth under `/admin/...`: login, logout, Remember Me, forgot-password/OTP-verify/reset (reusing the existing `onboarding_helpers` OTP session mechanism), first-login forced password change, and a 15-minute idle session timeout scoped only to admin sessions.
- RBAC: two seeded roles (Super Administrator, Academic Administrator) over a 7-code permission catalog, enforced by `@admin_required`/`@permission_required(code)` decorators — proven end-to-end via 6 permission-gated Quick Action stub routes (navigation only, no feature logic yet) and a real "Access Denied" page on an unauthorized direct hit.
- Reusable admin layout (`templates/admin/base_admin.html`): sidebar, top bar, profile menu, notification indicator, breadcrumbs, search UI, responsive collapse, light/dark theme toggle — replaces the previous fully-mocked, unreachable `admin_dashboard.html`.
- Live dashboard: 7 summary cards backed by real queries (Total/Active Students, Current Semester Registrations, Total Payments, Active Courses, Departments, and a literal "Not yet available" placeholder for Support Tickets, since that module doesn't exist), plus a real activity feed merged from existing registration/payment/course/notification/admin-login data — no new event-logging system needed.
- `services/admin_audit.py`: every admin login/login-failure/logout/password-change/reset writes an `AdminAuditLog` row.
- Spec: `docs/superpowers/specs/2026-08-01-admin-foundation-design.md`
- Out of scope (deferred): MFA, admin self-service account management, real-time push, charts, Student Management, Payments admin UI, Course Management, Registration Oversight, Reports, Support Tickets.

## Next milestone

Admin Student Management — not yet started.
```

- [ ] **Step 5: Commit**
```bash
git add seed_dev_data.py DEVELOPMENT_PROGRESS.md
git commit -m "feat: seed admin RBAC (roles/permissions) and 2 demo admin accounts; record Admin Foundation as complete"
```
