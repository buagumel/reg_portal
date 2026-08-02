from functools import wraps

from flask import redirect, url_for, render_template
from flask_login import current_user

from models import AdminUser

QUICK_ACTIONS = [
    ('admin_sessions_new', 'sessions.manage', 'Create Session', 'fa-calendar-plus'),
    ('admin_stub_students_import', 'students.manage', 'Upload Students', 'fa-file-import'),
    ('admin_stub_courses', 'courses.manage', 'Manage Courses', 'fa-book'),
    ('admin_registration_open', 'registration.manage', 'Open Registration', 'fa-door-open'),
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
