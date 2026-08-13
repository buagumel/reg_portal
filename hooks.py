"""Cross-cutting request hooks registered by create_app(): the user_loader,
both before_request gates, and the context processor. None of these belong
to a single blueprint — they run for every request (or every admin/student
request) regardless of which blueprint eventually handles it — so per the
runbook's Session 3 ("inside the factory or in a blueprint-free module it
imports") they live here rather than in app.py itself.
"""
import time

from flask import request, redirect, url_for, flash, jsonify, session
from flask_login import current_user, logout_user

from extensions import db, login_manager
from models import User, AdminUser
from auth_helpers import get_gate_redirect
from services.notification import get_summary_counts

ADMIN_SESSION_TIMEOUT_SECONDS = 15 * 60


@login_manager.user_loader
def load_user(idn):
    if idn.startswith('admin:'):
        try:
            return AdminUser.query.get(int(idn.split(':', 1)[1]))
        except (ValueError, IndexError):
            return None
    return db.get_or_404(User, idn)


def endpoint_name(request):
    """The bare view-function name from request.endpoint, with any
    'blueprint.' prefix stripped. Once routes move into blueprints,
    request.endpoint becomes 'blueprint.function' instead of 'function' —
    comparing against this instead of request.endpoint directly keeps the
    before_request gates (and, exposed as a Jinja global, template nav-
    highlighting) working before and after each route's move.

    Returns '' (not None) when request.endpoint itself is None (e.g. a 404) —
    every caller only ever checks membership/equality/startswith against this,
    and '' is falsy and matches nothing, same as None would, but doesn't
    blow up a bare .startswith() call in a template."""
    if request.endpoint is None:
        return ''
    return request.endpoint.rsplit('.', 1)[-1]


def enforce_onboarding_gate():
    if not current_user.is_authenticated:
        return None
    if isinstance(current_user, AdminUser):
        return None

    exempt_endpoints = {
        'login', 'logout', 'static', 'admin',
        'force_password_change',
        'onboarding', 'onboarding_save_info', 'onboarding_complete',
        'send_email_code', 'verify_email_code',
        'profile',
    }
    if endpoint_name(request) in exempt_endpoints:
        return None

    redirect_endpoint = get_gate_redirect(current_user)
    if redirect_endpoint is None:
        return None

    if request.method == 'GET':
        return redirect(url_for(redirect_endpoint))

    return jsonify({'success': False, 'message': 'Please complete the required step before continuing.'}), 403


def enforce_admin_session_timeout():
    if not current_user.is_authenticated or not isinstance(current_user, AdminUser):
        return None
    if endpoint_name(request) in ('admin_login', 'static'):
        return None

    now_ts = time.time()
    last_activity = session.get('admin_last_activity')
    if last_activity is not None and (now_ts - last_activity) > ADMIN_SESSION_TIMEOUT_SECONDS:
        logout_user()
        session.pop('admin_last_activity', None)
        flash('Your admin session expired due to inactivity. Please log in again.')
        return redirect(url_for('admin.auth.admin_login'))

    session['admin_last_activity'] = now_ts

    onboarding_exempt_endpoints = {'admin_force_password_change', 'admin_logout', 'static'}
    if current_user.first_login and endpoint_name(request) not in onboarding_exempt_endpoints:
        return redirect(url_for('admin.auth.admin_force_password_change'))

    return None


def inject_unread_notification_count():
    if current_user.is_authenticated:
        return {'unread_notification_count': get_summary_counts(current_user)['unread']}
    return {}
