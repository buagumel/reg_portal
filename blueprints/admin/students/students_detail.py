from flask import request, jsonify, render_template, redirect, url_for, flash, current_app
from flask_login import current_user

from blueprints.admin.students import admin_students_bp
from extensions import mail, Message
from models import User, Programme
from services.registration import RegistrationError
from services.admin_permission import permission_required, has_permission
from services.admin_validation import valid_levels_for_programme
from services.admin_department import list_active_departments
from services.admin_student import (
    list_active_programmes, get_student, get_student_profile,
    update_student, set_account_status, reset_student_password, resend_verification,
)
from services.admin_registration import (
    admin_add_course, admin_drop_course,
    set_registration_lock, extend_deadline, reopen_registration, approve_exception,
)
from services.admin_onboarding import reset_onboarding, manually_verify_email, mark_onboarding_complete
from services.notification import create_notification
from services.admin_audit import log_admin_action


@admin_students_bp.route('/admin/students/<int:student_id>')
@permission_required('students.manage')
def admin_student_profile(student_id):
    profile = get_student_profile(student_id)
    can_override_onboarding = has_permission(current_user, 'onboarding.override')
    return render_template('admin/student_profile.html', can_override_onboarding=can_override_onboarding, **profile)


@admin_students_bp.route('/admin/students/<int:student_id>/registration/add-course', methods=['POST'])
@permission_required('registration.manage')
def admin_student_registration_add_course(student_id):
    student = get_student(student_id)
    context = get_student_profile(student_id)['registration_context']
    period, student_registration = context['period'], context['student_registration']
    reason = request.form.get('reason', '').strip()
    course_id = request.form.get('course_id', type=int)
    override_capacity = request.form.get('override_capacity') == 'on'

    if period is None or student_registration is None:
        flash('This student has no active registration to add a course to.')
        return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))

    try:
        admin_add_course(student, period, student_registration, course_id, current_user, reason, override_capacity=override_capacity)
    except RegistrationError as e:
        flash(str(e))
        return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))

    log_admin_action(current_user, 'course_added_by_admin', target_type='student_registration', target_id=student_registration.id,
                      details=f'course_id={course_id} override_capacity={override_capacity} reason={reason}', ip_address=request.remote_addr)
    flash('Course added to student\'s registration.')
    return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))


@admin_students_bp.route('/admin/students/<int:student_id>/registration/drop-course', methods=['POST'])
@permission_required('registration.manage')
def admin_student_registration_drop_course(student_id):
    student = get_student(student_id)
    context = get_student_profile(student_id)['registration_context']
    period, student_registration = context['period'], context['student_registration']
    reason = request.form.get('reason', '').strip()
    course_id = request.form.get('course_id', type=int)

    if period is None or student_registration is None:
        flash('This student has no active registration to drop a course from.')
        return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))

    try:
        admin_drop_course(student, period, student_registration, course_id, current_user, reason)
    except RegistrationError as e:
        flash(str(e))
        return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))

    log_admin_action(current_user, 'course_removed_by_admin', target_type='student_registration', target_id=student_registration.id,
                      details=f'course_id={course_id} reason={reason}', ip_address=request.remote_addr)
    flash('Course removed from student\'s registration.')
    return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))


@admin_students_bp.route('/admin/students/<int:student_id>/registration/lock', methods=['POST'])
@permission_required('registration.manage')
def admin_student_registration_lock(student_id):
    context = get_student_profile(student_id)['registration_context']
    student_registration = context['student_registration']
    reason = request.form.get('reason', '').strip()
    locked = request.form.get('locked') == 'true'

    if student_registration is None:
        flash('This student has no active registration.')
        return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))

    set_registration_lock(student_registration, current_user, locked, reason)
    log_admin_action(current_user, 'registration_locked' if locked else 'registration_unlocked',
                      target_type='student_registration', target_id=student_registration.id,
                      details=reason, ip_address=request.remote_addr)
    flash(f'Registration {"locked" if locked else "unlocked"}.')
    return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))


@admin_students_bp.route('/admin/students/<int:student_id>/registration/extend-deadline', methods=['POST'])
@permission_required('registration.manage')
def admin_student_registration_extend_deadline(student_id):
    from datetime import datetime

    context = get_student_profile(student_id)['registration_context']
    student_registration = context['student_registration']
    reason = request.form.get('reason', '').strip()
    new_deadline_raw = request.form.get('new_deadline', '')

    if student_registration is None:
        flash('This student has no active registration.')
        return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))
    if not reason or not new_deadline_raw:
        flash('A reason and a new deadline are required.')
        return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))

    try:
        new_deadline = datetime.fromisoformat(new_deadline_raw)
    except ValueError:
        flash('Invalid deadline format.')
        return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))

    extend_deadline(student_registration, current_user, new_deadline, reason)
    log_admin_action(current_user, 'registration_deadline_extended', target_type='student_registration',
                      target_id=student_registration.id, details=f'new_deadline={new_deadline_raw} reason={reason}',
                      ip_address=request.remote_addr)
    flash('Deadline extended for this student.')
    return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))


@admin_students_bp.route('/admin/students/<int:student_id>/registration/reopen', methods=['POST'])
@permission_required('registration.manage')
def admin_student_registration_reopen(student_id):
    context = get_student_profile(student_id)['registration_context']
    student_registration = context['student_registration']
    reason = request.form.get('reason', '').strip()

    if student_registration is None:
        flash('This student has no active registration.')
        return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))

    reopen_registration(student_registration, current_user, reason)
    log_admin_action(current_user, 'registration_reopened', target_type='student_registration',
                      target_id=student_registration.id, details=reason, ip_address=request.remote_addr)
    flash('Registration reopened — the student can resume course selection.')
    return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))


@admin_students_bp.route('/admin/students/<int:student_id>/registration/approve-exception', methods=['POST'])
@permission_required('registration.manage')
def admin_student_registration_approve_exception(student_id):
    context = get_student_profile(student_id)['registration_context']
    student_registration = context['student_registration']
    reason = request.form.get('reason', '').strip()

    if student_registration is None:
        flash('This student has no active registration.')
        return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))

    approve_exception(student_registration, current_user, reason)
    log_admin_action(current_user, 'registration_exception_approved', target_type='student_registration',
                      target_id=student_registration.id, details=reason, ip_address=request.remote_addr)
    flash('Exception recorded for this student\'s registration.')
    return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))


@admin_students_bp.route('/admin/students/<int:student_id>/onboarding/reset', methods=['POST'])
@permission_required('students.manage')
def admin_student_onboarding_reset(student_id):
    student = get_student(student_id)
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))

    reset_onboarding(student)
    log_admin_action(current_user, 'onboarding_reset', target_type='user', target_id=student_id,
                      details=reason, ip_address=request.remote_addr)
    flash(f'Onboarding reset for {student.name}.')
    return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))


@admin_students_bp.route('/admin/students/<int:student_id>/onboarding/verify-email', methods=['POST'])
@permission_required('students.manage')
def admin_student_onboarding_verify_email(student_id):
    student = get_student(student_id)
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))

    manually_verify_email(student)
    log_admin_action(current_user, 'email_manually_verified', target_type='user', target_id=student_id,
                      details=reason, ip_address=request.remote_addr)
    flash(f'Email manually verified for {student.name}.')
    return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))


@admin_students_bp.route('/admin/students/<int:student_id>/onboarding/mark-complete', methods=['POST'])
@permission_required('onboarding.override')
def admin_student_onboarding_mark_complete(student_id):
    student = get_student(student_id)
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))

    mark_onboarding_complete(student)
    log_admin_action(current_user, 'onboarding_marked_complete', target_type='user', target_id=student_id,
                      details=reason, ip_address=request.remote_addr)
    flash(f'Onboarding marked complete for {student.name}.')
    return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))


@admin_students_bp.route('/admin/students/<int:student_id>/edit', methods=['GET', 'POST'])
@permission_required('students.manage')
def admin_student_edit(student_id):
    student = get_student(student_id)
    departments = list_active_departments()
    programmes = list_active_programmes()
    if request.method == 'GET':
        return render_template('admin/student_form.html', student=student, departments=departments, programmes=programmes)

    from datetime import date

    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip() or None
    if not name:
        flash('Name is required.')
        return render_template('admin/student_form.html', student=student, departments=departments, programmes=programmes, form=request.form)
    if email and User.query.filter(User.email == email, User.id != student_id).first():
        flash(f'A student with email "{email}" already exists.')
        return render_template('admin/student_form.html', student=student, departments=departments, programmes=programmes, form=request.form)

    programme_id = request.form.get('programme_id', type=int)
    level = request.form.get('level', '').strip() or None
    if programme_id and level:
        programme = Programme.query.get(programme_id)
        valid_levels = valid_levels_for_programme(programme)
        if valid_levels is not None and level not in valid_levels:
            flash(f'"{level}" is not a valid level for {programme.name} (expected one of: {", ".join(valid_levels)}).')
            return render_template('admin/student_form.html', student=student, departments=departments, programmes=programmes, form=request.form)

    dob_raw = request.form.get('dob') or None
    update_student(
        student_id, name=name,
        email=email, phone=request.form.get('phone', '').strip() or None,
        department_id=request.form.get('department_id', type=int), programme_id=programme_id,
        level=level, semester=request.form.get('semester', '').strip() or None,
        session=request.form.get('session', '').strip() or None,
        nationality=request.form.get('nationality', '').strip() or None, state=request.form.get('state', '').strip() or None,
        lga=request.form.get('lga', '').strip() or None, dob=date.fromisoformat(dob_raw) if dob_raw else None,
        gender=request.form.get('gender', '').strip() or None, student_type=request.form.get('student_type', '').strip() or None,
    )
    log_admin_action(current_user, 'student_updated', target_type='user', target_id=student_id,
                      details=f'reg_no={student.reg_no}', ip_address=request.remote_addr)
    flash(f'Student "{name}" updated.')
    return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))


@admin_students_bp.route('/admin/students/<int:student_id>/activate', methods=['POST'])
@permission_required('students.manage')
def admin_student_activate(student_id):
    set_account_status(student_id, 'active')
    log_admin_action(current_user, 'student_status_changed', target_type='user', target_id=student_id,
                      details='status=active', ip_address=request.remote_addr)
    flash('Student account activated.')
    return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))


@admin_students_bp.route('/admin/students/<int:student_id>/suspend', methods=['POST'])
@permission_required('students.manage')
def admin_student_suspend(student_id):
    set_account_status(student_id, 'suspended')
    log_admin_action(current_user, 'student_status_changed', target_type='user', target_id=student_id,
                      details='status=suspended', ip_address=request.remote_addr)
    flash('Student account suspended.')
    return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))


@admin_students_bp.route('/admin/students/<int:student_id>/deactivate', methods=['POST'])
@permission_required('students.manage')
def admin_student_deactivate(student_id):
    set_account_status(student_id, 'deactivated')
    log_admin_action(current_user, 'student_status_changed', target_type='user', target_id=student_id,
                      details='status=deactivated', ip_address=request.remote_addr)
    flash('Student account deactivated.')
    return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))


@admin_students_bp.route('/admin/students/<int:student_id>/reset-password', methods=['POST'])
@permission_required('students.manage')
def admin_student_reset_password(student_id):
    temp_password = reset_student_password(student_id)
    log_admin_action(current_user, 'student_password_reset', target_type='user', target_id=student_id,
                      ip_address=request.remote_addr)
    flash(f'Password reset. Temporary password: {temp_password}')
    return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))


@admin_students_bp.route('/admin/students/<int:student_id>/resend-verification', methods=['POST'])
@permission_required('students.manage')
def admin_student_resend_verification(student_id):
    ok, error = resend_verification(student_id)
    if not ok:
        flash(error)
        return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))

    student = get_student(student_id)
    try:
        msg = Message('Complete Your Email Verification', recipients=[student.email])
        msg.body = (
            f'Hello {student.name},\n\n'
            'An administrator noticed your email address on the Student Portal hasn\'t been verified yet. '
            'Please log in and complete your onboarding to verify it.\n\n'
            'If you did not request this, you can safely ignore this email.'
        )
        mail.send(msg)
    except Exception:
        current_app.logger.warning('Failed to send verification reminder to %s', student.email)

    create_notification(
        student, 'Verify your email', 'Please log in and complete your onboarding to verify your email address.',
        category='profile', priority='medium',
    )
    log_admin_action(current_user, 'student_verification_resent', target_type='user', target_id=student_id,
                      ip_address=request.remote_addr)
    flash('Verification reminder sent.')
    return redirect(url_for('admin.students.admin_student_profile', student_id=student_id))
