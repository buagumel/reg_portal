from functools import wraps

from flask import redirect, url_for, render_template
from flask_login import current_user

from models import AdminUser

QUICK_ACTIONS = [
    ('admin.academic.admin_sessions_new', 'sessions.manage', 'Create Session', 'fa-calendar-plus'),
    ('admin.students.admin_students_import', 'students.manage', 'Upload Students', 'fa-file-import'),
    ('admin.courses.admin_courses', 'courses.manage', 'Manage Courses', 'fa-book'),
    ('admin.core.admin_registration_open', 'registration.manage', 'Open Registration', 'fa-door-open'),
    ('admin.core.admin_stub_announcements_new', 'announcements.manage', 'Create Announcement', 'fa-bullhorn'),
    ('admin.finance.admin_stub_reports', 'reports.view', 'Generate Reports', 'fa-chart-bar'),
]


def has_permission(admin_user, code):
    if admin_user is None or admin_user.role is None:
        return False
    return any(p.code == code for p in admin_user.role.permissions)


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not isinstance(current_user, AdminUser):
            return redirect(url_for('admin.auth.admin_login'))
        if not current_user.is_active:
            return redirect(url_for('admin.auth.admin_login'))
        return view(*args, **kwargs)
    return wrapped


def enforce_admin_required():
    """before_request-compatible sibling of admin_required, for child
    blueprints under admin/ where every route is uniformly admin-gated
    (unlike admin.auth, which mixes public and admin-only routes and so
    can't use a blanket before_request — see blueprints/admin/auth.py).
    Register with `some_admin_child_bp.before_request(enforce_admin_required)`.
    Same two checks as admin_required, just shaped as a before_request
    (no view to wrap, returns None to continue or a redirect to stop)."""
    if not current_user.is_authenticated or not isinstance(current_user, AdminUser):
        return redirect(url_for('admin.auth.admin_login'))
    if not current_user.is_active:
        return redirect(url_for('admin.auth.admin_login'))
    return None


def permission_required(code):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated or not isinstance(current_user, AdminUser):
                return redirect(url_for('admin.auth.admin_login'))
            if not current_user.is_active:
                return redirect(url_for('admin.auth.admin_login'))
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
