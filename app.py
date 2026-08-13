from flask import Flask, current_app, render_template, request, redirect, url_for, flash, jsonify, session, Response
from flask_login import current_user, logout_user
import time
from extensions import db, migrate, csrf, mail, login_manager, Message
from models import (
    User, AdminUser, Programme,
)
from config import Config
from blueprints.notifications import notifications_bp
from blueprints.auth import auth_bp
from blueprints.onboarding import onboarding_bp
from blueprints.student import student_bp
from blueprints.registration import registration_bp
from blueprints.payments import payments_bp
from blueprints.admin import admin_bp
from auth_helpers import get_gate_redirect
from services.registration import RegistrationError
from services.notification import create_notification, get_summary_counts
from services.admin_audit import log_admin_action
from services.admin_permission import permission_required
from services.admin_validation import valid_levels_for_programme
from services.admin_registration import (
    admin_add_course, admin_drop_course,
    set_registration_lock, extend_deadline, reopen_registration, approve_exception,
)
from services.admin_onboarding import (
    reset_onboarding, manually_verify_email, mark_onboarding_complete,
)
from services.admin_permission import has_permission
from services.admin_department import list_active_departments
from services.admin_student import (
    list_active_programmes, list_students, get_student, get_student_profile,
    create_student, update_student, set_account_status, reset_student_password, resend_verification,
    bulk_set_status, bulk_reset_password, bulk_assign_department, bulk_assign_programme,
)
from services.student_import import import_students_csv, preview_students_csv
from models import StudentImportJob

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

@route('/admin/students/import/preview', methods=['POST'])
@permission_required('students.manage')
def admin_students_import_preview():
    file_storage = request.files.get('file')
    summary, parse_error = preview_students_csv(file_storage)
    if parse_error:
        return jsonify({'success': False, 'message': parse_error}), 400
    return jsonify({'success': True, **summary})


@route('/admin/students/import', methods=['GET', 'POST'])
@permission_required('students.manage')
def admin_students_import():
    if request.method == 'GET':
        return render_template('admin/student_import.html')

    file_storage = request.files.get('file')
    job = import_students_csv(file_storage, current_user)
    log_admin_action(
        current_user, 'student_import_completed', target_type='student_import_job', target_id=job.id,
        details=f'created={job.created_count} updated={job.updated_count} skipped={job.skipped_count} '
                f'duplicates={job.duplicate_count} errors={job.error_count}',
        ip_address=request.remote_addr,
    )
    return redirect(url_for('admin_student_import_report', job_id=job.id))


@route('/admin/students/import/<int:job_id>')
@permission_required('students.manage')
def admin_student_import_report(job_id):
    job = StudentImportJob.query.get_or_404(job_id)
    return render_template('admin/student_import_report.html', job=job)


@route('/admin/students/import/admission-portal')
@permission_required('students.manage')
def admin_student_admission_portal():
    return render_template('admin/coming_soon.html', feature_name='Admission Portal Import')


@route('/admin/students')
@permission_required('students.manage')
def admin_students():
    return render_template(
        'admin/students.html', departments=list_active_departments(), programmes=list_active_programmes(),
    )


@route('/admin/students/data')
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


@route('/admin/students/<int:student_id>')
@permission_required('students.manage')
def admin_student_profile(student_id):
    profile = get_student_profile(student_id)
    can_override_onboarding = has_permission(current_user, 'onboarding.override')
    return render_template('admin/student_profile.html', can_override_onboarding=can_override_onboarding, **profile)


@route('/admin/students/new', methods=['GET', 'POST'])
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
    return redirect(url_for('admin_student_profile', student_id=student.id))


@route('/admin/students/<int:student_id>/registration/add-course', methods=['POST'])
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
        return redirect(url_for('admin_student_profile', student_id=student_id))
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin_student_profile', student_id=student_id))

    try:
        admin_add_course(student, period, student_registration, course_id, current_user, reason, override_capacity=override_capacity)
    except RegistrationError as e:
        flash(str(e))
        return redirect(url_for('admin_student_profile', student_id=student_id))

    log_admin_action(current_user, 'course_added_by_admin', target_type='student_registration', target_id=student_registration.id,
                      details=f'course_id={course_id} override_capacity={override_capacity} reason={reason}', ip_address=request.remote_addr)
    flash('Course added to student\'s registration.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@route('/admin/students/<int:student_id>/registration/drop-course', methods=['POST'])
@permission_required('registration.manage')
def admin_student_registration_drop_course(student_id):
    student = get_student(student_id)
    context = get_student_profile(student_id)['registration_context']
    period, student_registration = context['period'], context['student_registration']
    reason = request.form.get('reason', '').strip()
    course_id = request.form.get('course_id', type=int)

    if period is None or student_registration is None:
        flash('This student has no active registration to drop a course from.')
        return redirect(url_for('admin_student_profile', student_id=student_id))
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin_student_profile', student_id=student_id))

    try:
        admin_drop_course(student, period, student_registration, course_id, current_user, reason)
    except RegistrationError as e:
        flash(str(e))
        return redirect(url_for('admin_student_profile', student_id=student_id))

    log_admin_action(current_user, 'course_removed_by_admin', target_type='student_registration', target_id=student_registration.id,
                      details=f'course_id={course_id} reason={reason}', ip_address=request.remote_addr)
    flash('Course removed from student\'s registration.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@route('/admin/students/<int:student_id>/registration/lock', methods=['POST'])
@permission_required('registration.manage')
def admin_student_registration_lock(student_id):
    context = get_student_profile(student_id)['registration_context']
    student_registration = context['student_registration']
    reason = request.form.get('reason', '').strip()
    locked = request.form.get('locked') == 'true'

    if student_registration is None:
        flash('This student has no active registration.')
        return redirect(url_for('admin_student_profile', student_id=student_id))
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin_student_profile', student_id=student_id))

    set_registration_lock(student_registration, current_user, locked, reason)
    log_admin_action(current_user, 'registration_locked' if locked else 'registration_unlocked',
                      target_type='student_registration', target_id=student_registration.id,
                      details=reason, ip_address=request.remote_addr)
    flash(f'Registration {"locked" if locked else "unlocked"}.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@route('/admin/students/<int:student_id>/registration/extend-deadline', methods=['POST'])
@permission_required('registration.manage')
def admin_student_registration_extend_deadline(student_id):
    from datetime import datetime

    context = get_student_profile(student_id)['registration_context']
    student_registration = context['student_registration']
    reason = request.form.get('reason', '').strip()
    new_deadline_raw = request.form.get('new_deadline', '')

    if student_registration is None:
        flash('This student has no active registration.')
        return redirect(url_for('admin_student_profile', student_id=student_id))
    if not reason or not new_deadline_raw:
        flash('A reason and a new deadline are required.')
        return redirect(url_for('admin_student_profile', student_id=student_id))

    try:
        new_deadline = datetime.fromisoformat(new_deadline_raw)
    except ValueError:
        flash('Invalid deadline format.')
        return redirect(url_for('admin_student_profile', student_id=student_id))

    extend_deadline(student_registration, current_user, new_deadline, reason)
    log_admin_action(current_user, 'registration_deadline_extended', target_type='student_registration',
                      target_id=student_registration.id, details=f'new_deadline={new_deadline_raw} reason={reason}',
                      ip_address=request.remote_addr)
    flash('Deadline extended for this student.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@route('/admin/students/<int:student_id>/registration/reopen', methods=['POST'])
@permission_required('registration.manage')
def admin_student_registration_reopen(student_id):
    context = get_student_profile(student_id)['registration_context']
    student_registration = context['student_registration']
    reason = request.form.get('reason', '').strip()

    if student_registration is None:
        flash('This student has no active registration.')
        return redirect(url_for('admin_student_profile', student_id=student_id))
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin_student_profile', student_id=student_id))

    reopen_registration(student_registration, current_user, reason)
    log_admin_action(current_user, 'registration_reopened', target_type='student_registration',
                      target_id=student_registration.id, details=reason, ip_address=request.remote_addr)
    flash('Registration reopened — the student can resume course selection.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@route('/admin/students/<int:student_id>/registration/approve-exception', methods=['POST'])
@permission_required('registration.manage')
def admin_student_registration_approve_exception(student_id):
    context = get_student_profile(student_id)['registration_context']
    student_registration = context['student_registration']
    reason = request.form.get('reason', '').strip()

    if student_registration is None:
        flash('This student has no active registration.')
        return redirect(url_for('admin_student_profile', student_id=student_id))
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin_student_profile', student_id=student_id))

    approve_exception(student_registration, current_user, reason)
    log_admin_action(current_user, 'registration_exception_approved', target_type='student_registration',
                      target_id=student_registration.id, details=reason, ip_address=request.remote_addr)
    flash('Exception recorded for this student\'s registration.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@route('/admin/students/<int:student_id>/onboarding/reset', methods=['POST'])
@permission_required('students.manage')
def admin_student_onboarding_reset(student_id):
    student = get_student(student_id)
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin_student_profile', student_id=student_id))

    reset_onboarding(student)
    log_admin_action(current_user, 'onboarding_reset', target_type='user', target_id=student_id,
                      details=reason, ip_address=request.remote_addr)
    flash(f'Onboarding reset for {student.name}.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@route('/admin/students/<int:student_id>/onboarding/verify-email', methods=['POST'])
@permission_required('students.manage')
def admin_student_onboarding_verify_email(student_id):
    student = get_student(student_id)
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin_student_profile', student_id=student_id))

    manually_verify_email(student)
    log_admin_action(current_user, 'email_manually_verified', target_type='user', target_id=student_id,
                      details=reason, ip_address=request.remote_addr)
    flash(f'Email manually verified for {student.name}.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@route('/admin/students/<int:student_id>/onboarding/mark-complete', methods=['POST'])
@permission_required('onboarding.override')
def admin_student_onboarding_mark_complete(student_id):
    student = get_student(student_id)
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash('A reason is required.')
        return redirect(url_for('admin_student_profile', student_id=student_id))

    mark_onboarding_complete(student)
    log_admin_action(current_user, 'onboarding_marked_complete', target_type='user', target_id=student_id,
                      details=reason, ip_address=request.remote_addr)
    flash(f'Onboarding marked complete for {student.name}.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@route('/admin/students/<int:student_id>/edit', methods=['GET', 'POST'])
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
    return redirect(url_for('admin_student_profile', student_id=student_id))


@route('/admin/students/<int:student_id>/activate', methods=['POST'])
@permission_required('students.manage')
def admin_student_activate(student_id):
    set_account_status(student_id, 'active')
    log_admin_action(current_user, 'student_status_changed', target_type='user', target_id=student_id,
                      details='status=active', ip_address=request.remote_addr)
    flash('Student account activated.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@route('/admin/students/<int:student_id>/suspend', methods=['POST'])
@permission_required('students.manage')
def admin_student_suspend(student_id):
    set_account_status(student_id, 'suspended')
    log_admin_action(current_user, 'student_status_changed', target_type='user', target_id=student_id,
                      details='status=suspended', ip_address=request.remote_addr)
    flash('Student account suspended.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@route('/admin/students/<int:student_id>/deactivate', methods=['POST'])
@permission_required('students.manage')
def admin_student_deactivate(student_id):
    set_account_status(student_id, 'deactivated')
    log_admin_action(current_user, 'student_status_changed', target_type='user', target_id=student_id,
                      details='status=deactivated', ip_address=request.remote_addr)
    flash('Student account deactivated.')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@route('/admin/students/<int:student_id>/reset-password', methods=['POST'])
@permission_required('students.manage')
def admin_student_reset_password(student_id):
    temp_password = reset_student_password(student_id)
    log_admin_action(current_user, 'student_password_reset', target_type='user', target_id=student_id,
                      ip_address=request.remote_addr)
    flash(f'Password reset. Temporary password: {temp_password}')
    return redirect(url_for('admin_student_profile', student_id=student_id))


@route('/admin/students/<int:student_id>/resend-verification', methods=['POST'])
@permission_required('students.manage')
def admin_student_resend_verification(student_id):
    ok, error = resend_verification(student_id)
    if not ok:
        flash(error)
        return redirect(url_for('admin_student_profile', student_id=student_id))

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
    return redirect(url_for('admin_student_profile', student_id=student_id))


@route('/admin/students/bulk-status', methods=['POST'])
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


@route('/admin/students/bulk-reset-password', methods=['POST'])
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


@route('/admin/students/bulk-resend-email', methods=['POST'])
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


@route('/admin/students/bulk-assign-department', methods=['POST'])
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


@route('/admin/students/bulk-assign-programme', methods=['POST'])
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