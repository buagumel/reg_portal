import os

from flask import request, jsonify, render_template, url_for, current_app
from flask_login import current_user, login_required

from blueprints.student import student_bp
from services.student_profile import get_profile_display
from services.registration import get_registration_status_context
from services.notification import notify_registration_window_events, get_notifications, get_summary_counts
from services.profile import update_contact_info, update_profile_picture, delete_profile_picture
from services.payment import get_payment_history


@student_bp.route('/update-profile', methods=['POST'])
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

@student_bp.route('/profile/picture', methods=['POST'])
@login_required
def profile_picture_upload():
    file_storage = request.files.get('profile_picture')
    if not file_storage:
        return jsonify({'success': False, 'message': 'No file provided.'}), 400

    upload_folder = os.path.join(current_app.static_folder, 'uploads')
    try:
        update_profile_picture(current_user, file_storage, upload_folder)
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({
        'success': True,
        'message': 'Profile picture updated.',
        'profile_picture': url_for('static', filename=current_user.profile_picture),
    })


@student_bp.route('/profile/picture/delete', methods=['POST'])
@login_required
def profile_picture_delete():
    try:
        delete_profile_picture(current_user, current_app.static_folder)
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    return jsonify({'success': True, 'message': 'Profile picture removed.'})


@student_bp.route('/')
@login_required
def dashboard():
    notify_registration_window_events(current_user)
    recent_payments, _ = get_payment_history(current_user, page=1, per_page=5)
    return render_template(
        'dashboard.html',
        profile_display=get_profile_display(current_user),
        recent_payments=recent_payments,
        status=get_registration_status_context(current_user),
    )


@student_bp.route('/profile')
@login_required
def profile():
    return render_template('profile.html', profile_display=get_profile_display(current_user))

@student_bp.route('/announcements')
@login_required
def announcements():
    return render_template(
        'announcements.html',
        summary=get_summary_counts(current_user),
        notifications=get_notifications(current_user),
    )


@student_bp.route('/courses')
def courses():
    return "This is the courses page.";
