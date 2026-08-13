import os

from flask import request, jsonify, render_template, redirect, url_for, current_app
from flask_login import current_user, login_required

from blueprints.onboarding import onboarding_bp
from extensions import db, mail, Message
from models import User, now_lagos
from auth_helpers import get_gate_redirect, is_valid_email
from onboarding_helpers import save_profile_picture
from services.notification import create_notification


@onboarding_bp.route('/onboarding')
@login_required
def onboarding():
    target = get_gate_redirect(current_user)
    if target != 'onboarding.onboarding':
        return redirect(url_for(target or 'dashboard'))
    return render_template('onboarding.html')


@onboarding_bp.route('/onboarding/save-info', methods=['POST'])
@login_required
def onboarding_save_info():
    if get_gate_redirect(current_user) != 'onboarding.onboarding':
        return jsonify({'success': False, 'message': 'Onboarding is already complete.'}), 403

    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()
    address = request.form.get('address', '').strip()
    picture = request.files.get('profile_picture')

    errors = {}
    if not email:
        errors['email'] = 'Email is required'
    elif not is_valid_email(email):
        errors['email'] = 'Invalid email format'
    else:
        existing = User.query.filter(User.email == email, User.id != current_user.id).first()
        if existing:
            errors['email'] = 'Email already in use'

    if not phone:
        errors['phone'] = 'Phone number is required'
    if not address:
        errors['address'] = 'Address is required'

    picture_path, picture_error = save_profile_picture(
        picture, current_user.reg_no,
        os.path.join(current_app.static_folder, 'uploads')
    )
    if picture_error:
        errors['profile_picture'] = picture_error

    if errors:
        return jsonify({'success': False, 'message': 'Please correct the highlighted fields.', 'errors': errors}), 400

    if email != current_user.email:
        current_user.email_verified = False
    current_user.email = email
    current_user.phone = phone
    current_user.address = address
    current_user.profile_picture = picture_path
    db.session.commit()

    return jsonify({'success': True, 'message': 'Information saved.'})


@onboarding_bp.route('/onboarding/complete', methods=['POST'])
@login_required
def onboarding_complete():
    if get_gate_redirect(current_user) != 'onboarding.onboarding':
        return jsonify({'success': False, 'message': 'Onboarding is already complete.'}), 403

    if not current_user.email_verified:
        return jsonify({'success': False, 'message': 'Please verify your email before completing onboarding.'}), 400

    current_user.onboarding_completed = True
    current_user.onboarding_completed_at = now_lagos()
    db.session.commit()

    create_notification(
        current_user, 'Welcome to the Student Portal',
        'Your profile setup is complete. Welcome aboard!',
        category='profile', priority='medium',
    )

    try:
        msg = Message('Welcome to JSPICT Student Portal', recipients=[current_user.email])
        msg.body = f'Hi {current_user.name},\n\nYour profile setup is complete. Welcome to the JSPICT Student Portal!'
        mail.send(msg)
    except Exception:
        current_app.logger.warning('Failed to send welcome email to %s', current_user.email)

    return jsonify({'success': True, 'message': 'Onboarding complete!', 'redirect': url_for('dashboard')})
