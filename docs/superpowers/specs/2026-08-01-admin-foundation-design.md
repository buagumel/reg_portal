# Admin Portal Foundation Design

**Status:** Approved for planning
**Author:** Controller (Claude), approved by user 2026-08-01

## Goal

Build the admin infrastructure every future admin module (Student Management, Payments, Courses, Reports) will sit on top of: admin authentication, role-based access control, a reusable admin layout, a live dashboard, and audit logging. One Flask app, one deployment — not a second application.

Source: the user's pasted "STUDENT PORTAL SYSTEM - ADMIN" description (not a repo file — supplied directly in conversation) narrowed explicitly to a "Foundation" milestone; the fuller admin spec (Student Management, Payments processing, Course Management, Registration Oversight, Reports, Support Tickets, Admin User Management, MFA) is out of scope here.

## Current state (confirmed by codebase audit)

- `templates/admin/admin_login.html` and `templates/admin/admin_dashboard.html` exist but are fully mocked: hardcoded demo-credential JS, hardcoded stat numbers, hardcoded Chart.js data, all nav links `href="#"`. Neither is backed by a real route with logic — `/admin` renders `admin_login.html` with zero backend; `admin_dashboard.html` is rendered by nothing (orphaned, and would 500 today since it references a template variable no route supplies).
- `User.is_admin` exists on the model but is **completely unused** anywhere in the codebase — dead schema.
- No `AdminUser`/`AdminRole`/`Permission`/`RolePermission`/`AdminAuditLog` models exist.
- No admin-specific CSS/JS assets exist.
- No deployment config (Procfile/wsgi.py/etc.) exists — app is run directly, so there's no constraint against restructuring routes.

## Architecture

One Flask app (`app.py`), admin routes added under an `/admin/...` URL namespace directly into the existing file, matching this codebase's established flat-file convention (no Blueprint — no precedent for one here). One `SECRET_KEY`, one global `CSRFProtect` (already covers new admin forms automatically), one `LoginManager`.

Isolation from student auth comes from two things, not a second app or cookie:
1. **A separate identity table**, `AdminUser` — not a repurposed `User.is_admin` flag. Different password, different role/permission data, different table entirely.
2. **Route-level guards** (`@admin_required` / `@permission_required(code)`) that check `isinstance(current_user, AdminUser)` before allowing access to any `/admin/*` route — this is what actually stops a logged-in student, not the session mechanism.

**Accepted tradeoff**: one shared session cookie means a browser session is logged in as *either* a student *or* an admin at a time — logging into one replaces the other. `AdminUser.get_id()` returns a prefixed value (`f'admin:{self.id}'`); the single `user_loader` callback checks the prefix and loads from `AdminUser` or `User` accordingly. Admin-only 15-minute idle session timeout is scoped to only apply when `current_user` is an `AdminUser`, so it never touches existing student session behavior.

## Data model

```python
class AdminRole(db.Model):
    __tablename__ = 'admin_roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)   # "Super Administrator", "Academic Administrator"
    description = db.Column(db.Text, nullable=True)

class Permission(db.Model):
    __tablename__ = 'permissions'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), unique=True, nullable=False)   # "dashboard.view", "courses.manage", ...
    description = db.Column(db.Text, nullable=True)

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

    def set_password(self, password): ...   # mirrors User.set_password
    def check_password(self, password): ...  # mirrors User.check_password

class AdminAuditLog(db.Model):
    __tablename__ = 'admin_audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_users.id'), nullable=True)  # nullable: a failed login before we know who
    action = db.Column(db.String(50), nullable=False)     # 'login', 'login_failed', 'logout', 'password_reset', ...
    target_type = db.Column(db.String(50), nullable=True)  # future: 'student', 'course', ... (unused this milestone beyond the login/session actions)
    target_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
```

No `AdminSession` model — login history is `AdminAuditLog` rows (`action='login'`/`'login_failed'`) plus the denormalized `last_login_at`/`last_login_ip` on `AdminUser`. `User.is_admin` is left untouched (dead, but touching the student `users` table isn't necessary for this milestone).

## Auth

Routes (all under `/admin`): `/admin/login` (GET/POST), `/admin/logout`, `/admin/forgot-password` (GET/POST — request email), `/admin/verify-reset-code` (GET/POST — enter the emailed code), `/admin/reset-password` (GET/POST — set new password once the code is verified), `/admin/force-password-change` (first-login gate, mirrors the student `force_password_change` route/template), `/admin/dashboard`.

No logged-out "forgot password" flow exists anywhere on the student side today to mirror (only the first-login forced-change flow does, and a separate *logged-in* email-change OTP flow) — so this is new route surface, but it reuses the underlying OTP session mechanism (`onboarding_helpers.start_otp_session`/`register_failed_otp_attempt`/`otp_attempts_exceeded`/`clear_otp_session`) applied to `AdminUser` instead of `User`, rather than inventing a new OTP implementation.

- Password policy: reuse `auth_helpers.validate_password_strength` (same 8+/mixed-case/digit/special rule) — no separate 12-character policy, since the trimmed milestone doesn't call that out and reusing the established rule is simpler and consistent.
- Remember Me: standard Flask-Login `remember=True` on `login_user`.
- Session expiry: a `last_activity` timestamp stored in the Flask session dict, checked/refreshed on every request in a `before_request` hook that only runs its check when `current_user` is an `AdminUser`. Exceeding 15 minutes since the last check clears the session and redirects to `/admin/login` with a "session expired" flash. Any request naturally extends it — no separate "extend session" control needed.
- Failed logins are logged to `AdminAuditLog` (`action='login_failed'`, `admin_user_id=NULL` if the email didn't match any account, else the matched account's id) — no progressive lockout (not in the trimmed Security list).
- **No self-service admin account creation this milestone.** The only way an `AdminUser` row exists is via seed data, matching how demo students are seeded today. Building "create/manage other admin accounts" is User Management for Administrators — not in this milestone's objectives.

## RBAC

Two seeded roles: **Super Administrator** (all permissions) and **Academic Administrator** (a subset). Enforcement via `@admin_required` (any active `AdminUser`) and `@permission_required(code)` (role must have that permission) decorators; unauthorized access renders a real "Access Denied" page (not a silent redirect), reusing the admin layout.

**Concrete, testable proof point** (this is what makes RBAC real rather than two identical dashboards): the dashboard's 6 Quick Action buttons each link to their own tiny stub route, each gated by a specific permission code, each rendering a shared "Coming soon — this feature isn't built yet" page:

| Quick Action | Route | Permission | Super | Academic |
|---|---|---|---|---|
| Create Session | `/admin/sessions/new` | `sessions.manage` | ✅ | ❌ |
| Upload Students | `/admin/students/import` | `students.manage` | ✅ | ❌ |
| Manage Courses | `/admin/courses` | `courses.manage` | ✅ | ✅ |
| Open Registration | `/admin/registration/open` | `registration.manage` | ✅ | ✅ |
| Create Announcement | `/admin/announcements/new` | `announcements.manage` | ✅ | ✅ |
| Generate Reports | `/admin/reports` | `reports.view` | ✅ | ❌ |

`dashboard.view` is granted to both roles (required to load `/admin/dashboard` itself). This proves the decorator blocks a direct URL hit for an Academic Administrator on a Super-only route — not just a hidden button.

## Layout

One base admin template (`templates/admin/base_admin.html`) every future admin page extends: sidebar nav, top bar, admin profile menu (real `current_user.name`/role), a notification indicator (count sourced from real data — reusing the pattern from the student notification badge, scoped to admin-relevant events), breadcrumbs, a quick-search input (UI only — wired to nothing yet, real search is a future module), responsive/collapsible sidebar, light/dark theme toggle (CSS-variable-driven, matching the app's existing per-page `:root` variable pattern). This fully replaces `admin_dashboard.html`'s inline-style mock.

## Dashboard

Summary cards, each backed by a real query:

| Card | Source |
|---|---|
| Total Students | `User.query.count()` |
| Active Students | `User.query.filter_by(onboarding_completed=True).count()` |
| Current Semester Registrations | `StudentRegistration` count for the active `RegistrationPeriod` |
| Total Payments | count of `Payment` rows with `status='successful'` |
| Active Courses | `Course` count for the active academic session/semester |
| Departments | distinct `User.department` count |
| Pending Support Tickets | literal "Not yet available" placeholder — no ticket module exists |

**Activity feed**: real data merged from existing tables — `StudentRegistration.registered_at` ("Student Registered"), successful `Payment.verified_at` ("Payment Completed"), new `RegisteredCourse` rows ("Course Registration"), `AdminAuditLog` logins ("Admin Login"), student-side `AuditLog` profile-update actions ("Profile Updates"), `Notification` announcement-category rows ("Announcements") — sorted newest-first, capped at ~20. No WebSockets/live-push (not restated in the trimmed milestone; this codebase has no async stack) — populated on page load.

No charts (Reports/Analytics, explicitly excluded).

## Audit logging

Every admin auth action (`login`, `login_failed`, `logout`, password reset/change) writes an `AdminAuditLog` row via a new `services/admin_audit.py`'s `log_admin_action(admin_user, action, target_type=None, target_id=None, details=None, ip_address=None)` — mirrors the existing student `services/audit.py` shape.

## Services

- `services/admin_auth.py` — login/logout orchestration, password verification, first-login gate.
- `services/admin_permission.py` — `admin_required`/`permission_required(code)` decorators, permission-check helper.
- `services/admin_dashboard.py` — summary card queries, activity feed assembly.
- `services/admin_audit.py` — `log_admin_action(...)`.

## Global constraints for the plan

- No changes to `User`, student auth, or any completed student-facing module.
- `AdminUser`/`AdminAuditLog` are new tables — no `ALTER TABLE` needed at merge time, `db.create_all()` handles brand-new tables.
- Session timeout logic must not affect student sessions — the `before_request` hook checks `isinstance(current_user, AdminUser)` before applying idle-timeout logic.
- All datetime columns use `now_lagos()`.
- CSRF applies to every admin form (global `CSRFProtect` already covers this — no per-route opt-out).
- No admin account self-registration UI; two seeded admin accounts (one per role) for manual testing, following `seed_dev_data.py`'s existing pattern.
- Out of scope: MFA, admin user management UI, real-time push, charts, Student Management, Payments admin UI, Course Management, Registration Oversight, Reports, Support Tickets.
