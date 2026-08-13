import time

from flask import Blueprint, redirect, url_for, request, render_template, jsonify, session
from flask_login import current_user, login_user, logout_user

from extensions import mail, Message
from models import AdminUser
from auth_helpers import validate_password_strength
from onboarding_helpers import (
    start_otp_session, register_failed_otp_attempt, otp_attempts_exceeded, clear_otp_session,
)
from services.admin_auth import authenticate_admin, change_admin_password
from services.admin_audit import log_admin_action
from services.admin_permission import admin_required

admin_auth_bp = Blueprint('auth', __name__)


@admin_auth_bp.route('/admin')
def admin():
    return redirect(url_for('admin.auth.admin_login'))


@admin_auth_bp.route('/admin/login', methods=['GET', 'POST'])
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
                return redirect(url_for('admin.auth.admin_force_password_change'))
            return redirect(url_for('admin_dashboard'))

        return render_template('admin/admin_login.html', error='Invalid email or password.', email=email, remember=remember)

    return render_template('admin/admin_login.html')


@admin_auth_bp.route('/admin/forgot-password', methods=['GET', 'POST'])
def admin_forgot_password():
    if request.method == 'GET':
        return render_template('admin/admin_forgot_password.html')

    email = request.form.get('email', '').strip()
    admin_user = AdminUser.query.filter_by(email=email).first()

    # Start the OTP session unconditionally so the code-entry page is
    # reached the same way whether or not the email matched an account —
    # otherwise the code-entry page's own session guard would bounce
    # non-matching emails straight back, revealing which emails are admins.
    code = start_otp_session(session, email)

    branch_started_at = time.time()

    if admin_user:
        session['admin_reset_admin_id'] = admin_user.id
        try:
            msg = Message('Admin Password Reset Code', recipients=[email])
            msg.body = f'Your password reset code is: {code}\nThis code expires in 5 minutes.'
            mail.send(msg)
        except Exception:
            current_app.logger.warning('Failed to send admin password reset email to %s', email)

    # Pad the response to a fixed minimum duration so the presence/absence of
    # the network-bound mail.send() call above can't be inferred from response
    # timing — a flat sleep on only the non-match branch doesn't work, since
    # mail.send() itself varies well beyond any small fixed delay. This isn't a
    # perfect fix (a slow mail.send() can still exceed the floor), but it closes
    # the channel for the common case without needing a background task queue.
    MIN_RESPONSE_SECONDS = 1.5
    elapsed = time.time() - branch_started_at
    if elapsed < MIN_RESPONSE_SECONDS:
        time.sleep(MIN_RESPONSE_SECONDS - elapsed)

    # Always redirect the same way regardless of whether the email matched
    # an account, so this endpoint never reveals which emails are admins.
    return redirect(url_for('admin.auth.admin_verify_reset_code'))


@admin_auth_bp.route('/admin/verify-reset-code', methods=['GET', 'POST'])
def admin_verify_reset_code():
    if 'email_verification_code' not in session:
        return redirect(url_for('admin.auth.admin_forgot_password'))

    if request.method == 'GET':
        return render_template('admin/admin_verify_reset_code.html', email=session.get('pending_email'))

    data = request.get_json()
    code = (data.get('code', '') if data else '').strip()

    if otp_attempts_exceeded(session):
        clear_otp_session(session)
        session.pop('admin_reset_admin_id', None)
        return jsonify({'success': False, 'message': 'Too many attempts. Please request a new code.'}), 400

    if time.time() > session.get('email_verification_expiry', 0):
        clear_otp_session(session)
        session.pop('admin_reset_admin_id', None)
        return jsonify({'success': False, 'message': 'This code has expired. Please request a new one.'}), 400

    if code != session.get('email_verification_code'):
        register_failed_otp_attempt(session)
        return jsonify({'success': False, 'message': 'Incorrect code.'}), 400

    session['admin_reset_verified'] = True
    return jsonify({'success': True, 'redirect': url_for('admin.auth.admin_reset_password')})


@admin_auth_bp.route('/admin/reset-password', methods=['GET', 'POST'])
def admin_reset_password():
    if not session.get('admin_reset_verified') or 'admin_reset_admin_id' not in session:
        return redirect(url_for('admin.auth.admin_forgot_password'))

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
        'redirect': url_for('admin.auth.admin_login'),
    })


@admin_auth_bp.route('/admin/logout')
@admin_required
def admin_logout():
    log_admin_action(current_user, 'logout', ip_address=request.remote_addr)
    logout_user()
    session.pop('admin_last_activity', None)
    return redirect(url_for('admin.auth.admin_login'))


@admin_auth_bp.route('/admin/force-password-change', methods=['GET', 'POST'])
@admin_required
def admin_force_password_change():
    if request.method == 'GET':
        if not current_user.first_login:
            return redirect(url_for('admin_dashboard'))
        return render_template('admin/admin_force_password_change.html')

    if not current_user.first_login:
        return jsonify({'success': False, 'message': 'Use the profile settings to change your password.'}), 403

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


from blueprints.admin import admin_bp  # noqa: E402 — deferred import to avoid a circular import with blueprints/admin/__init__.py

admin_bp.register_blueprint(admin_auth_bp)
