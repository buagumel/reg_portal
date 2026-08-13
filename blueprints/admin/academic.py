from flask import Blueprint, request, flash, redirect, url_for, render_template
from flask_login import current_user

from services.admin_permission import permission_required, enforce_admin_required
from services.admin_department import (
    list_departments, get_department, get_department_detail,
    create_department, update_department, set_department_status,
)
from services.admin_programme import (
    list_programmes, get_programme, get_programme_detail,
    create_programme, update_programme, set_programme_status,
    get_programme_department_ids, set_programme_departments,
    list_departments_for_programme_checkboxes,
)
from services.admin_validation import (
    is_department_code_unique, is_programme_code_unique, validate_credit_range,
    LEVELS_BY_PROGRAM_TYPE, is_session_name_unique,
)
from services.admin_session import (
    list_sessions, get_session, create_session, update_session, archive_session, clone_session,
    list_semesters_for_programme, list_periods, get_period, create_period, update_period, activate_period,
    list_holidays, create_holiday,
)
from services.admin_student import list_active_programmes
from services.admin_audit import log_admin_action

admin_academic_bp = Blueprint('academic', __name__)
admin_academic_bp.before_request(enforce_admin_required)


@admin_academic_bp.route('/admin/departments')
@permission_required('departments.manage')
def admin_departments():
    search = request.args.get('search', '').strip() or None
    status = request.args.get('status', '').strip() or None
    page = request.args.get('page', 1, type=int)
    result = list_departments(search=search, status=status, page=page)
    return render_template(
        'admin/departments.html', result=result, search=search or '', status=status or '',
    )


@admin_academic_bp.route('/admin/departments/new', methods=['GET', 'POST'])
@permission_required('departments.manage')
def admin_department_new():
    if request.method == 'GET':
        return render_template('admin/department_form.html', department=None)

    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip().upper()
    faculty = request.form.get('faculty', '').strip()
    head_name = request.form.get('head_name', '').strip()

    if not name or not code:
        flash('Name and code are required.')
        return render_template('admin/department_form.html', department=None, form=request.form)
    if not is_department_code_unique(code):
        flash(f'Department code "{code}" is already in use.')
        return render_template('admin/department_form.html', department=None, form=request.form)

    department = create_department(name, code, faculty, head_name)
    log_admin_action(current_user, 'department_created', target_type='department', target_id=department.id,
                      details=f'name={name} code={code}', ip_address=request.remote_addr)
    flash(f'Department "{name}" created.')
    return redirect(url_for('admin.academic.admin_departments'))


@admin_academic_bp.route('/admin/departments/<int:department_id>')
@permission_required('departments.manage')
def admin_department_detail(department_id):
    detail = get_department_detail(department_id)
    return render_template('admin/departments.html', detail=detail, result=None)


@admin_academic_bp.route('/admin/departments/<int:department_id>/edit', methods=['GET', 'POST'])
@permission_required('departments.manage')
def admin_department_edit(department_id):
    department = get_department(department_id)
    if request.method == 'GET':
        return render_template('admin/department_form.html', department=department)

    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip().upper()
    faculty = request.form.get('faculty', '').strip()
    head_name = request.form.get('head_name', '').strip()

    if not name or not code:
        flash('Name and code are required.')
        return render_template('admin/department_form.html', department=department, form=request.form)
    if not is_department_code_unique(code, exclude_id=department_id):
        flash(f'Department code "{code}" is already in use.')
        return render_template('admin/department_form.html', department=department, form=request.form)

    update_department(department_id, name, code, faculty, head_name)
    log_admin_action(current_user, 'department_updated', target_type='department', target_id=department_id,
                      details=f'name={name} code={code}', ip_address=request.remote_addr)
    flash(f'Department "{name}" updated.')
    return redirect(url_for('admin.academic.admin_departments'))


@admin_academic_bp.route('/admin/departments/<int:department_id>/activate', methods=['POST'])
@permission_required('departments.manage')
def admin_department_activate(department_id):
    set_department_status(department_id, 'active')
    log_admin_action(current_user, 'department_status_changed', target_type='department', target_id=department_id,
                      details='status=active', ip_address=request.remote_addr)
    flash('Department activated.')
    return redirect(url_for('admin.academic.admin_departments'))


@admin_academic_bp.route('/admin/departments/<int:department_id>/deactivate', methods=['POST'])
@permission_required('departments.manage')
def admin_department_deactivate(department_id):
    set_department_status(department_id, 'inactive')
    log_admin_action(current_user, 'department_status_changed', target_type='department', target_id=department_id,
                      details='status=inactive', ip_address=request.remote_addr)
    flash('Department deactivated.')
    return redirect(url_for('admin.academic.admin_departments'))


@admin_academic_bp.route('/admin/departments/<int:department_id>/archive', methods=['POST'])
@permission_required('departments.manage')
def admin_department_archive(department_id):
    set_department_status(department_id, 'archived')
    log_admin_action(current_user, 'department_status_changed', target_type='department', target_id=department_id,
                      details='status=archived', ip_address=request.remote_addr)
    flash('Department archived.')
    return redirect(url_for('admin.academic.admin_departments'))


@admin_academic_bp.route('/admin/programmes')
@permission_required('programmes.manage')
def admin_programmes():
    search = request.args.get('search', '').strip() or None
    status = request.args.get('status', '').strip() or None
    page = request.args.get('page', 1, type=int)
    result = list_programmes(search=search, status=status, page=page)
    return render_template(
        'admin/programmes.html', result=result, search=search or '', status=status or '',
    )


@admin_academic_bp.route('/admin/programmes/new', methods=['GET', 'POST'])
@permission_required('programmes.manage')
def admin_programme_new():
    if request.method == 'GET':
        return render_template('admin/programme_form.html', programme=None)

    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip().upper()
    program_type = request.form.get('program_type', '').strip()
    description = request.form.get('description', '').strip()
    uses_semesters = request.form.get('uses_semesters') == 'on'
    uses_terms = request.form.get('uses_terms') == 'on'
    duration = request.form.get('duration', '').strip()

    if not name or not code or not program_type:
        flash('Name, code, and programme type are required.')
        return render_template('admin/programme_form.html', programme=None, form=request.form)
    if program_type not in LEVELS_BY_PROGRAM_TYPE:
        flash('Invalid programme type.')
        return render_template('admin/programme_form.html', programme=None, form=request.form)
    if not is_programme_code_unique(code):
        flash(f'Programme code "{code}" is already in use.')
        return render_template('admin/programme_form.html', programme=None, form=request.form)

    programme = create_programme(name, code, program_type, description, uses_semesters, uses_terms, duration)
    log_admin_action(current_user, 'programme_created', target_type='programme', target_id=programme.id,
                      details=f'name={name} code={code}', ip_address=request.remote_addr)
    flash(f'Programme "{name}" created.')
    return redirect(url_for('admin.academic.admin_programmes'))


@admin_academic_bp.route('/admin/programmes/<int:programme_id>')
@permission_required('programmes.manage')
def admin_programme_detail(programme_id):
    detail = get_programme_detail(programme_id)
    linked_ids = set(get_programme_department_ids(programme_id))
    all_departments = list_departments_for_programme_checkboxes(programme_id)
    return render_template(
        'admin/programmes.html', detail=detail, result=None,
        all_departments=all_departments, linked_ids=linked_ids,
    )


@admin_academic_bp.route('/admin/programmes/<int:programme_id>/edit', methods=['GET', 'POST'])
@permission_required('programmes.manage')
def admin_programme_edit(programme_id):
    programme = get_programme(programme_id)
    if request.method == 'GET':
        return render_template('admin/programme_form.html', programme=programme)

    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip().upper()
    program_type = request.form.get('program_type', '').strip()
    description = request.form.get('description', '').strip()
    uses_semesters = request.form.get('uses_semesters') == 'on'
    uses_terms = request.form.get('uses_terms') == 'on'
    duration = request.form.get('duration', '').strip()

    if not name or not code or not program_type:
        flash('Name, code, and programme type are required.')
        return render_template('admin/programme_form.html', programme=programme, form=request.form)
    if program_type not in LEVELS_BY_PROGRAM_TYPE:
        flash('Invalid programme type.')
        return render_template('admin/programme_form.html', programme=programme, form=request.form)
    if not is_programme_code_unique(code, exclude_id=programme_id):
        flash(f'Programme code "{code}" is already in use.')
        return render_template('admin/programme_form.html', programme=programme, form=request.form)

    update_programme(programme_id, name, code, program_type, description, uses_semesters, uses_terms, duration)
    log_admin_action(current_user, 'programme_updated', target_type='programme', target_id=programme_id,
                      details=f'name={name} code={code}', ip_address=request.remote_addr)
    flash(f'Programme "{name}" updated.')
    return redirect(url_for('admin.academic.admin_programmes'))


@admin_academic_bp.route('/admin/programmes/<int:programme_id>/departments', methods=['POST'])
@permission_required('programmes.manage')
def admin_programme_departments(programme_id):
    try:
        department_ids = [int(v) for v in request.form.getlist('department_ids')]
    except ValueError:
        flash('Invalid department selection.')
        return redirect(url_for('admin.academic.admin_programme_detail', programme_id=programme_id))
    set_programme_departments(programme_id, department_ids)
    log_admin_action(current_user, 'programme_departments_updated', target_type='programme', target_id=programme_id,
                      details=f'department_ids={department_ids}', ip_address=request.remote_addr)
    flash('Programme departments updated.')
    return redirect(url_for('admin.academic.admin_programme_detail', programme_id=programme_id))


@admin_academic_bp.route('/admin/programmes/<int:programme_id>/activate', methods=['POST'])
@permission_required('programmes.manage')
def admin_programme_activate(programme_id):
    set_programme_status(programme_id, 'active')
    log_admin_action(current_user, 'programme_status_changed', target_type='programme', target_id=programme_id,
                      details='status=active', ip_address=request.remote_addr)
    flash('Programme activated.')
    return redirect(url_for('admin.academic.admin_programmes'))


@admin_academic_bp.route('/admin/programmes/<int:programme_id>/archive', methods=['POST'])
@permission_required('programmes.manage')
def admin_programme_archive(programme_id):
    set_programme_status(programme_id, 'archived')
    log_admin_action(current_user, 'programme_status_changed', target_type='programme', target_id=programme_id,
                      details='status=archived', ip_address=request.remote_addr)
    flash('Programme archived.')
    return redirect(url_for('admin.academic.admin_programmes'))


@admin_academic_bp.route('/admin/sessions')
@permission_required('sessions.manage')
def admin_sessions():
    programme_id = request.args.get('programme_id', type=int)
    sessions = list_sessions(programme_id=programme_id)
    return render_template(
        'admin/sessions.html', sessions=sessions,
        programmes=list_active_programmes(), selected_programme_id=programme_id,
    )


@admin_academic_bp.route('/admin/sessions/new', methods=['GET', 'POST'])
@permission_required('sessions.manage')
def admin_sessions_new():
    if request.method == 'GET':
        return render_template('admin/session_form.html', session=None, programmes=list_active_programmes())

    name = request.form.get('name', '').strip()
    start_date = request.form.get('start_date') or None
    end_date = request.form.get('end_date') or None
    programme_id = request.form.get('programme_id', type=int) or None
    if not name:
        flash('Session name is required.')
        return render_template('admin/session_form.html', session=None, form=request.form, programmes=list_active_programmes())
    if not is_session_name_unique(name, programme_id):
        flash(f'A session named "{name}" already exists for this programme.')
        return render_template('admin/session_form.html', session=None, form=request.form, programmes=list_active_programmes())

    from datetime import date
    start_date = date.fromisoformat(start_date) if start_date else None
    end_date = date.fromisoformat(end_date) if end_date else None

    session_obj = create_session(name, start_date, end_date, programme_id=programme_id)
    log_admin_action(current_user, 'session_created', target_type='academic_session', target_id=session_obj.id,
                      details=f'name={name} programme_id={programme_id}', ip_address=request.remote_addr)
    flash(f'Session "{name}" created.')
    return redirect(url_for('admin.academic.admin_session_edit', session_id=session_obj.id))


@admin_academic_bp.route('/admin/sessions/<int:session_id>/edit', methods=['GET', 'POST'])
@permission_required('sessions.manage')
def admin_session_edit(session_id):
    session_obj = get_session(session_id)
    # A session's programme_id can reference a Programme that has since been
    # archived (list_active_programmes() only returns active ones). If we
    # dropped it from the dropdown, an admin who edits the session without
    # touching the Programme field would submit no matching <option>, and the
    # browser would fall back to the blank "Shared / Legacy" choice — silently
    # stripping the archived programme's link on an otherwise-unrelated edit.
    # Union it back in (and label it non-active in the template) so a no-op
    # resubmit round-trips correctly.
    programmes = list_active_programmes()
    if session_obj.programme_id and session_obj.programme_id not in {p.id for p in programmes}:
        programmes = programmes + [session_obj.programme]
    if request.method == 'GET':
        return render_template(
            'admin/session_form.html', session=session_obj, programmes=programmes,
            periods=list_periods(session_id), holidays=list_holidays(session_id),
        )

    name = request.form.get('name', '').strip()
    start_date = request.form.get('start_date') or None
    end_date = request.form.get('end_date') or None
    programme_id = request.form.get('programme_id', type=int) or None
    if not name:
        flash('Session name is required.')
        return render_template('admin/session_form.html', session=session_obj, form=request.form, programmes=programmes)
    if not is_session_name_unique(name, programme_id, exclude_id=session_id):
        flash(f'A session named "{name}" already exists for this programme.')
        return render_template('admin/session_form.html', session=session_obj, form=request.form, programmes=programmes)

    from datetime import date
    start_date = date.fromisoformat(start_date) if start_date else None
    end_date = date.fromisoformat(end_date) if end_date else None

    update_session(session_id, name, start_date, end_date, programme_id=programme_id)
    log_admin_action(current_user, 'session_updated', target_type='academic_session', target_id=session_id,
                      details=f'name={name} programme_id={programme_id}', ip_address=request.remote_addr)
    flash(f'Session "{name}" updated.')
    return redirect(url_for('admin.academic.admin_sessions'))


@admin_academic_bp.route('/admin/sessions/<int:session_id>/archive', methods=['POST'])
@permission_required('sessions.manage')
def admin_session_archive(session_id):
    session_obj, error = archive_session(session_id)
    if error:
        flash(error)
    else:
        log_admin_action(current_user, 'session_archived', target_type='academic_session', target_id=session_id,
                          ip_address=request.remote_addr)
        flash(f'Session "{session_obj.name}" archived.')
    return redirect(url_for('admin.academic.admin_sessions'))


@admin_academic_bp.route('/admin/sessions/<int:session_id>/clone', methods=['POST'])
@permission_required('sessions.manage')
def admin_session_clone(session_id):
    source_session = get_session(session_id)
    new_name = request.form.get('new_name', '').strip()
    start_date = request.form.get('start_date') or None
    end_date = request.form.get('end_date') or None
    if not new_name:
        flash('New session name is required to clone.')
        return redirect(url_for('admin.academic.admin_sessions'))
    if not is_session_name_unique(new_name, source_session.programme_id):
        flash(f'A session named "{new_name}" already exists for this programme.')
        return redirect(url_for('admin.academic.admin_sessions'))

    from datetime import date
    start_date = date.fromisoformat(start_date) if start_date else None
    end_date = date.fromisoformat(end_date) if end_date else None

    new_session = clone_session(session_id, new_name, start_date, end_date)
    log_admin_action(current_user, 'session_cloned', target_type='academic_session', target_id=new_session.id,
                      details=f'cloned_from={session_id}', ip_address=request.remote_addr)
    flash(f'Cloned into new session "{new_name}".')
    return redirect(url_for('admin.academic.admin_session_edit', session_id=new_session.id))


@admin_academic_bp.route('/admin/sessions/<int:session_id>/periods/new', methods=['GET', 'POST'])
@permission_required('sessions.manage')
def admin_period_new(session_id):
    session_obj = get_session(session_id)
    semesters = list_semesters_for_programme(session_obj.programme)
    if request.method == 'GET':
        return render_template('admin/period_form.html', session=session_obj, period=None, semesters=semesters, mismatched_semester_id=None)

    from datetime import datetime

    def parse_dt(value):
        return datetime.fromisoformat(value) if value else None

    semester_id = request.form.get('semester_id', type=int)
    opens_at = parse_dt(request.form.get('opens_at') or None)
    closes_at = parse_dt(request.form.get('closes_at') or None)
    min_credits = request.form.get('min_credits', type=int)
    max_credits = request.form.get('max_credits', type=int)
    registration_fee = request.form.get('registration_fee', type=float) or 0

    errors = validate_credit_range(min_credits, max_credits)
    if not semester_id or not opens_at or not closes_at:
        errors.append('Semester, opens-at, and closes-at are required.')
    elif semester_id not in {s.id for s in semesters}:
        # Backstop against a crafted/stale request posting a semester_id outside
        # what this session's Programme scope actually offers — see the matching
        # comment in admin_period_edit for the full rationale.
        errors.append('Selected semester is not valid for this session\'s programme.')
    if errors:
        for e in errors:
            flash(e)
        return render_template('admin/period_form.html', session=session_obj, period=None, semesters=semesters, form=request.form, mismatched_semester_id=None)

    period = create_period(
        session_id, semester_id, opens_at, closes_at, min_credits, max_credits, registration_fee,
        late_registration_ends_at=parse_dt(request.form.get('late_registration_ends_at') or None),
        late_registration_fee=request.form.get('late_registration_fee', type=float) or None,
        exam_starts_at=parse_dt(request.form.get('exam_starts_at') or None),
        exam_ends_at=parse_dt(request.form.get('exam_ends_at') or None),
        result_release_at=parse_dt(request.form.get('result_release_at') or None),
        add_drop_opens_at=parse_dt(request.form.get('add_drop_opens_at') or None),
        add_drop_closes_at=parse_dt(request.form.get('add_drop_closes_at') or None),
    )
    log_admin_action(current_user, 'registration_period_created', target_type='registration_period', target_id=period.id,
                      details=f'session_id={session_id} semester_id={semester_id}', ip_address=request.remote_addr)
    flash('Registration period created.')
    return redirect(url_for('admin.academic.admin_session_edit', session_id=session_id))


@admin_academic_bp.route('/admin/sessions/<int:session_id>/periods/<int:period_id>/edit', methods=['GET', 'POST'])
@permission_required('sessions.manage')
def admin_period_edit(session_id, period_id):
    session_obj = get_session(session_id)
    period = get_period(period_id)
    # A RegistrationPeriod's semester_id can reference a Semester that's no
    # longer in this session's Programme's filtered calendar shape (e.g. the
    # session was scoped to a Programme, or the Programme's
    # uses_semesters/uses_terms flags were toggled, after this period was
    # already created against a different semester). If we dropped it from the
    # dropdown, an admin who edits the period without touching the Semester
    # field would have the browser silently default to selecting the *first*
    # option — silently reassigning the period to a completely different
    # semester on an otherwise-unrelated edit (e.g. date-only change). Union
    # it back in (and label it distinctly in the template) so a no-op resubmit
    # round-trips correctly. Same pattern as c797c91's session-Programme fix.
    semesters = list_semesters_for_programme(session_obj.programme)
    mismatched_semester_id = None
    if period.semester_id not in {s.id for s in semesters}:
        semesters = semesters + [period.semester]
        mismatched_semester_id = period.semester_id
    if request.method == 'GET':
        return render_template('admin/period_form.html', session=session_obj, period=period, semesters=semesters, mismatched_semester_id=mismatched_semester_id)

    from datetime import datetime

    def parse_dt(value):
        return datetime.fromisoformat(value) if value else None

    semester_id = request.form.get('semester_id', type=int)
    opens_at = parse_dt(request.form.get('opens_at') or None)
    closes_at = parse_dt(request.form.get('closes_at') or None)
    min_credits = request.form.get('min_credits', type=int)
    max_credits = request.form.get('max_credits', type=int)
    registration_fee = request.form.get('registration_fee', type=float) or 0

    errors = validate_credit_range(min_credits, max_credits)
    if not semester_id or not opens_at or not closes_at:
        errors.append('Semester, opens-at, and closes-at are required.')
    elif semester_id not in {s.id for s in semesters}:
        # Backstop against a crafted/stale request posting a semester_id outside
        # what's actually offered (the Programme-filtered set, plus the period's
        # own current semester if it was unioned back in above) — don't just
        # trust whatever the client posts even if the template ever regresses.
        errors.append('Selected semester is not valid for this session\'s programme.')
    if errors:
        for e in errors:
            flash(e)
        return render_template('admin/period_form.html', session=session_obj, period=period, semesters=semesters, form=request.form, mismatched_semester_id=mismatched_semester_id)

    update_period(
        period_id, semester_id=semester_id, opens_at=opens_at, closes_at=closes_at,
        min_credits=min_credits, max_credits=max_credits, registration_fee=registration_fee,
        late_registration_ends_at=parse_dt(request.form.get('late_registration_ends_at') or None),
        late_registration_fee=request.form.get('late_registration_fee', type=float) or None,
        exam_starts_at=parse_dt(request.form.get('exam_starts_at') or None),
        exam_ends_at=parse_dt(request.form.get('exam_ends_at') or None),
        result_release_at=parse_dt(request.form.get('result_release_at') or None),
        add_drop_opens_at=parse_dt(request.form.get('add_drop_opens_at') or None),
        add_drop_closes_at=parse_dt(request.form.get('add_drop_closes_at') or None),
    )
    log_admin_action(current_user, 'registration_period_updated', target_type='registration_period', target_id=period_id,
                      ip_address=request.remote_addr)
    flash('Registration period updated.')
    return redirect(url_for('admin.academic.admin_session_edit', session_id=session_id))


@admin_academic_bp.route('/admin/sessions/<int:session_id>/periods/<int:period_id>/activate', methods=['POST'])
@permission_required('registration.manage')
def admin_period_activate(session_id, period_id):
    activate_period(period_id)
    log_admin_action(current_user, 'registration_period_activated', target_type='registration_period', target_id=period_id,
                      ip_address=request.remote_addr)
    flash('Registration period activated.')
    return redirect(request.referrer or url_for('admin.academic.admin_sessions'))


@admin_academic_bp.route('/admin/sessions/<int:session_id>/holidays', methods=['POST'])
@permission_required('sessions.manage')
def admin_holiday_new(session_id):
    from datetime import date

    name = request.form.get('name', '').strip()
    starts_on = request.form.get('starts_on')
    ends_on = request.form.get('ends_on')
    if not name or not starts_on or not ends_on:
        flash('Holiday name, start date, and end date are required.')
        return redirect(url_for('admin.academic.admin_session_edit', session_id=session_id))

    holiday = create_holiday(session_id, name, date.fromisoformat(starts_on), date.fromisoformat(ends_on))
    log_admin_action(current_user, 'holiday_created', target_type='academic_holiday', target_id=holiday.id,
                      details=f'session_id={session_id} name={name}', ip_address=request.remote_addr)
    flash(f'Holiday "{name}" added.')
    return redirect(url_for('admin.academic.admin_session_edit', session_id=session_id))


from blueprints.admin import admin_bp  # noqa: E402 — deferred import to avoid a circular import with blueprints/admin/__init__.py

admin_bp.register_blueprint(admin_academic_bp)
