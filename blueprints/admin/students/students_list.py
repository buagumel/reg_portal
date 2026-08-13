from flask import request, jsonify, render_template, redirect, url_for, flash, current_app
from flask_login import current_user

from blueprints.admin.students import admin_students_bp
from extensions import mail, Message
from models import User, Programme
from services.admin_permission import permission_required
from services.admin_validation import valid_levels_for_programme
from services.admin_department import list_active_departments
from services.admin_student import (
    list_active_programmes, list_students, create_student,
    bulk_set_status, bulk_reset_password, bulk_assign_department, bulk_assign_programme,
)
from services.admin_student import resend_verification
from services.notification import create_notification
from services.admin_audit import log_admin_action


@admin_students_bp.route('/admin/students')
@permission_required('students.manage')
def admin_students():
    return render_template(
        'admin/students.html', departments=list_active_departments(), programmes=list_active_programmes(),
    )


@admin_students_bp.route('/admin/students/data')
@permission_required('students.manage')
def admin_students_data():
    search = request.args.get('search', '').strip() or None
    department_id = request.args.get('department_id', type=int)
    programme_id = request.args.get('programme_id', type=int)
    level = request.args.get('level', '').strip() or None
    semester = request.args.get('semester', '').strip() or None
    status = request.args.get('status', '').strip() or None
    enrolled_from = request.args.get('enrolled_from') or None
    enrolled_to = request.args.get('enrolled_to') or None
    page = request.args.get('page', 1, type=int)
    sort = request.args.get('sort', 'name')

    result = list_students(
        search=search, department_id=department_id, programme_id=programme_id, level=level, semester=semester,
        status=status, enrolled_from=enrolled_from, enrolled_to=enrolled_to, page=page, sort=sort,
    )
    return jsonify({
        'success': True,
        'students': [{
            'id': s.id, 'reg_no': s.reg_no, 'name': s.name,
            'department': s.department or '—', 'programme': s.course or '—',
            'level': s.level or '—', 'semester': s.semester or '—', 'status': s.account_status,
            'profile_picture_url': url_for('static', filename=s.profile_picture) if s.profile_picture else None,
        } for s in result['items']],
        'total': result['total'], 'page': result['page'], 'per_page': result['per_page'],
    })


@admin_students_bp.route('/admin/students/new', methods=['GET', 'POST'])
@permission_required('students.manage')
def admin_student_new():
    departments = list_active_departments()
    programmes = list_active_programmes()
    if request.method == 'GET':
        return render_template('admin/student_form.html', student=None, departments=departments, programmes=programmes)

    from datetime import date

    reg_no = request.form.get('reg_no', '').strip()
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    if not reg_no or not name:
        flash('Registration number and name are required.')
        return render_template('admin/student_form.html', student=None, departments=departments, programmes=programmes, form=request.form)
    if User.query.filter_by(reg_no=reg_no).first():
        flash(f'A student with registration number "{reg_no}" already exists.')
        return render_template('admin/student_form.html', student=None, departments=departments, programmes=programmes, form=request.form)
    if email and User.query.filter_by(email=email).first():
        flash(f'A student with email "{email}" already exists.')
        return render_template('admin/student_form.html', student=None, departments=departments, programmes=programmes, form=request.form)

    programme_id = request.form.get('programme_id', type=int)
    level = request.form.get('level', '').strip()
    if programme_id and level:
        programme = Programme.query.get(programme_id)
        valid_levels = valid_levels_for_programme(programme)
        if valid_levels is not None and level not in valid_levels:
            flash(f'"{level}" is not a valid level for {programme.name} (expected one of: {", ".join(valid_levels)}).')
            return render_template('admin/student_form.html', student=None, departments=departments, programmes=programmes, form=request.form)

    dob_raw = request.form.get('dob') or None
    student, temp_password = create_student(
        reg_no=reg_no, name=name,
        email=email, phone=request.form.get('phone', '').strip(),
        department_id=request.form.get('department_id', type=int), programme_id=programme_id,
        level=level, semester=request.form.get('semester', '').strip(),
        session=request.form.get('session', '').strip(),
        nationality=request.form.get('nationality', '').strip(), state=request.form.get('state', '').strip(),
        lga=request.form.get('lga', '').strip(), dob=date.fromisoformat(dob_raw) if dob_raw else None,
        gender=request.form.get('gender', '').strip(), student_type=request.form.get('student_type', '').strip(),
    )
    log_admin_action(current_user, 'student_created', target_type='user', target_id=student.id,
                      details=f'reg_no={reg_no}', ip_address=request.remote_addr)

    if student.email:
        try:
            msg = Message('Welcome to the Student Portal — Complete Your Onboarding', recipients=[student.email])
            msg.body = (
                f'Hello {student.name},\n\n'
                'An administrator has created your Student Portal account. Use the credentials below to log in '
                'and complete your onboarding:\n\n'
                f'Registration Number: {student.reg_no}\n'
                f'Temporary Password: {temp_password}\n\n'
                'You will be asked to set a new password and complete your profile on first login.'
            )
            mail.send(msg)
        except Exception:
            current_app.logger.warning('Failed to send onboarding email to %s', student.email)

    flash(f'Student "{name}" ({reg_no}) created. Temporary password: {temp_password}')
    return redirect(url_for('admin.students.admin_student_profile', student_id=student.id))


@admin_students_bp.route('/admin/students/bulk-status', methods=['POST'])
@permission_required('students.manage')
def admin_students_bulk_status():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    student_ids = data.get('student_ids', [])
    status = data.get('status')
    if not student_ids or status not in ('active', 'suspended', 'deactivated'):
        return jsonify({'success': False, 'message': 'student_ids and a valid status are required.'}), 400

    count = bulk_set_status(student_ids, status)
    log_admin_action(current_user, 'student_bulk_status_changed', target_type='user', target_id=None,
                      details=f'status={status} count={count} ids={student_ids}', ip_address=request.remote_addr)
    return jsonify({'success': True, 'message': f'{count} student(s) updated to {status}.', 'count': count})


@admin_students_bp.route('/admin/students/bulk-reset-password', methods=['POST'])
@permission_required('students.manage')
def admin_students_bulk_reset_password():
    data = request.get_json()
    if not data or not data.get('student_ids'):
        return jsonify({'success': False, 'message': 'student_ids is required.'}), 400

    student_ids = data['student_ids']
    results = bulk_reset_password(student_ids)
    log_admin_action(current_user, 'student_bulk_password_reset', target_type='user', target_id=None,
                      details=f'count={len(results)} ids={student_ids}', ip_address=request.remote_addr)
    return jsonify({'success': True, 'message': f'{len(results)} password(s) reset.', 'results': results})


@admin_students_bp.route('/admin/students/bulk-resend-email', methods=['POST'])
@permission_required('students.manage')
def admin_students_bulk_resend_email():
    data = request.get_json()
    if not data or not data.get('student_ids'):
        return jsonify({'success': False, 'message': 'student_ids is required.'}), 400

    student_ids = data['student_ids']
    sent = skipped = 0
    for student_id in student_ids:
        student = User.query.get(student_id)
        if student is None:
            skipped += 1
            continue
        ok, _ = resend_verification(student_id)
        if not ok:
            skipped += 1
            continue
        try:
            msg = Message('Complete Your Email Verification', recipients=[student.email])
            msg.body = (
                f'Hello {student.name},\n\n'
                'An administrator noticed your email address on the Student Portal hasn\'t been verified yet. '
                'Please log in and complete your onboarding to verify it.\n\n'
                'If you did not request this, you can safely ignore this email.'
            )
            mail.send(msg)
            sent += 1
        except Exception:
            current_app.logger.warning('Failed to send verification reminder to %s', student.email)
            skipped += 1
        create_notification(
            student, 'Verify your email', 'Please log in and complete your onboarding to verify your email address.',
            category='profile', priority='medium',
        )

    log_admin_action(current_user, 'student_bulk_verification_resent', target_type='user', target_id=None,
                      details=f'sent={sent} skipped={skipped} ids={student_ids}', ip_address=request.remote_addr)
    return jsonify({'success': True, 'message': f'{sent} email(s) sent, {skipped} skipped (no email on file).'})


@admin_students_bp.route('/admin/students/bulk-assign-department', methods=['POST'])
@permission_required('students.manage')
def admin_students_bulk_assign_department():
    data = request.get_json()
    if not data or not data.get('student_ids') or not data.get('department_id'):
        return jsonify({'success': False, 'message': 'student_ids and department_id are required.'}), 400

    student_ids = data['student_ids']
    count = bulk_assign_department(student_ids, data['department_id'])
    log_admin_action(current_user, 'student_bulk_department_assigned', target_type='user', target_id=None,
                      details=f'department_id={data["department_id"]} count={count} ids={student_ids}',
                      ip_address=request.remote_addr)
    return jsonify({'success': True, 'message': f'{count} student(s) assigned.', 'count': count})


@admin_students_bp.route('/admin/students/bulk-assign-programme', methods=['POST'])
@permission_required('students.manage')
def admin_students_bulk_assign_programme():
    data = request.get_json()
    if not data or not data.get('student_ids') or not data.get('programme_id'):
        return jsonify({'success': False, 'message': 'student_ids and programme_id are required.'}), 400

    student_ids = data['student_ids']
    count = bulk_assign_programme(student_ids, data['programme_id'])
    log_admin_action(current_user, 'student_bulk_programme_assigned', target_type='user', target_id=None,
                      details=f'programme_id={data["programme_id"]} count={count} ids={student_ids}',
                      ip_address=request.remote_addr)
    return jsonify({'success': True, 'message': f'{count} student(s) assigned.', 'count': count})
