import time

from flask import request, jsonify, render_template, redirect, url_for, session
from flask_login import login_user, logout_user, current_user, login_required

from blueprints.auth import auth_bp
from extensions import db, mail, Message
from models import User, now_lagos
from auth_helpers import get_gate_redirect, validate_password_strength, is_valid_email
from onboarding_helpers import (
    start_otp_session, register_failed_otp_attempt, otp_attempts_exceeded,
    clear_otp_session, MAX_OTP_ATTEMPTS,
)
from services.profile import change_password as profile_change_password
from services.audit import log_action
from services.notification import create_notification


@auth_bp.route('/change-password', methods=['POST'])
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


@auth_bp.route('/force-password-change', methods=['GET', 'POST'])
@login_required
def force_password_change():
    if request.method == 'GET':
        if not current_user.first_login:
            return redirect(url_for(get_gate_redirect(current_user) or 'student.dashboard'))
        return render_template('force_password_change.html')

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

    current_user.set_password(new_pass)
    current_user.first_login = False
    db.session.commit()

    redirect_endpoint = get_gate_redirect(current_user) or 'student.dashboard'
    return jsonify({'success': True, 'message': 'Password changed successfully.', 'redirect': url_for(redirect_endpoint)})


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        redirect_endpoint = get_gate_redirect(current_user) or 'student.dashboard'
        return redirect(url_for(redirect_endpoint))

    if request.method == 'POST':
        identifier = request.form.get('studentId', '').strip()
        password = request.form.get('password', '').strip()
        remember = True if request.form.get('rememberCheck') else False
        show_password = True if request.form.get('show_password') == 'on' else False

        user = User.query.filter(
            (User.reg_no == identifier) | (User.email == identifier)
        ).first()

        if user and user.check_password(password):
            if user.account_status != 'active':
                status_messages = {
                    'suspended': 'Your account has been suspended. Please contact administration.',
                    'deactivated': 'Your account has been deactivated. Please contact administration.',
                }
                return render_template(
                    'login.html',
                    error=status_messages.get(user.account_status, 'Your account is not active. Please contact administration.'),
                    studentId=identifier,
                    password=password,
                    remember=remember,
                    show_password=show_password
                )
            user.last_login_at = now_lagos()
            db.session.commit()
            login_user(user, remember=remember)
            next_page = request.args.get('next')
            redirect_endpoint = get_gate_redirect(current_user) or 'student.dashboard'
            return redirect(next_page or url_for(redirect_endpoint))
        else:
            # Render again with the submitted values
            return render_template(
                'login.html',
                error="Invalid registration number/email or password.",
                studentId=identifier,
                password=password,
                remember=remember,
                show_password=show_password
            )

    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.route('/send-email-code', methods=['POST'])
@login_required
def send_email_code():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    new_email = data.get('new_email', '').strip()
    if not new_email:
        return jsonify({'success': False, 'message': 'Email is required'}), 400
    if not is_valid_email(new_email):
        return jsonify({'success': False, 'message': 'Invalid email format'}), 400

    existing = User.query.filter(User.email == new_email, User.id != current_user.id).first()
    if existing:
        return jsonify({'success': False, 'message': 'Email already in use'}), 400

    code = start_otp_session(session, new_email)

    try:
        msg = Message('Email Verification Code', recipients=[new_email])
        msg.body = f'Your verification code is: {code}\nThis code expires in 5 minutes.'
        mail.send(msg)
    except Exception:
        clear_otp_session(session)
        return jsonify({'success': False, 'message': 'Failed to send email. Please try again.'}), 500

    return jsonify({'success': True, 'message': 'Verification code sent to your email.'})


@auth_bp.route('/verify-email-code', methods=['POST'])
@login_required
def verify_email_code():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    code = data.get('code', '').strip()
    new_email = data.get('new_email', '').strip()
    if not code:
        return jsonify({'success': False, 'message': 'Verification code is required'}), 400

    stored_code = session.get('email_verification_code')
    expiry = session.get('email_verification_expiry')
    pending_email = session.get('pending_email')

    if not stored_code or not expiry or not pending_email:
        return jsonify({'success': False, 'message': 'No pending verification. Please request a new code.'}), 400

    if time.time() > expiry:
        clear_otp_session(session)
        return jsonify({'success': False, 'message': 'Verification code expired. Please request a new one.'}), 400

    if stored_code != code:
        attempts = register_failed_otp_attempt(session)
        if otp_attempts_exceeded(session):
            clear_otp_session(session)
            return jsonify({
                'success': False,
                'message': 'Maximum attempts exceeded. Please request a new code.',
                'max_attempts_reached': True
            }), 400
        remaining = MAX_OTP_ATTEMPTS - attempts
        return jsonify({'success': False, 'message': f'Invalid verification code. {remaining} attempt(s) remaining.'}), 400

    if new_email and new_email != pending_email:
        return jsonify({'success': False, 'message': 'Email mismatch. Please request a new code.'}), 400

    current_user.email = pending_email
    current_user.email_verified = True
    db.session.commit()

    log_action(current_user, 'email_changed', details=f'Email changed to {pending_email}')
    create_notification(
        current_user, 'Email address changed',
        f'Your account email was changed to {pending_email}.',
        category='profile', priority='medium',
    )

    clear_otp_session(session)

    return jsonify({
        'success': True,
        'message': 'Email updated and verified successfully.',
        'email': current_user.email,
        'email_verified': current_user.email_verified
    })
