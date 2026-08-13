from flask import Flask, request, redirect, url_for, flash, jsonify, session
from flask_login import current_user, logout_user
import time
from extensions import db, migrate, csrf, mail, login_manager
from models import User, AdminUser
from config import Config
from blueprints.notifications import notifications_bp
from blueprints.auth import auth_bp
from blueprints.onboarding import onboarding_bp
from blueprints.student import student_bp
from blueprints.registration import registration_bp
from blueprints.payments import payments_bp
from blueprints.admin import admin_bp
from auth_helpers import get_gate_redirect
from services.notification import get_summary_counts

ADMIN_SESSION_TIMEOUT_SECONDS = 15 * 60

_deferred_routes = []

def route(rule, **options):
    """Defers @app.route-style registration until create_app() builds the real
    app. Endpoint defaults to view_func.__name__, identical to what @app.route
    produces — so none of the existing url_for(...) call sites,
    login_manager.login_view, or endpoint-keyed test code need to change. (A
    real Blueprint can't do this: Flask unconditionally prefixes every
    blueprint route's endpoint with the blueprint's name.)"""
    def decorator(view_func):
        _deferred_routes.append((rule, view_func, options))
        return view_func
    return decorator

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

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'   # redirect to this view if not logged in
    login_manager.login_message = "Please log in to access this page."

    with app.app_context():
        db.create_all()

    app.before_request(enforce_onboarding_gate)
    app.before_request(enforce_admin_session_timeout)
    app.context_processor(inject_unread_notification_count)
    # Templates (the admin sidebar nav in particular) compare request.endpoint
    # against bare route names to highlight the current page — same problem
    # endpoint_name() already solves for the Python-side gates (Session 1),
    # exposed here so templates get the blueprint-prefix-proof version too.
    app.jinja_env.globals['endpoint_name'] = endpoint_name

    app.register_blueprint(notifications_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(onboarding_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(registration_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(admin_bp)

    for rule, view_func, options in _deferred_routes:
        app.add_url_rule(rule, view_func=view_func, **options)

    return app


if __name__ == '__main__':
    create_app().run(debug=True, port=4050)