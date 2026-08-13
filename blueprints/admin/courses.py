from flask import Blueprint, request, flash, redirect, url_for, render_template, jsonify
from flask_login import current_user

from models import CourseImportJob
from services.admin_permission import permission_required, enforce_admin_required
from services.admin_course import (
    list_courses, get_course, create_course, update_course, set_course_status,
    get_course_detail, set_assessment_components, get_enrollment_count,
)
from services.admin_course_catalog import (
    list_master_courses, get_master_course, get_master_course_detail,
    create_master_course, update_master_course, set_master_course_status,
    list_master_courses_for_picker, set_prerequisites, set_corequisites,
)
from services.admin_validation import is_course_code_unique, is_course_catalog_code_unique
from services.course_import import import_courses_csv, preview_courses_csv
from services.admin_department import list_active_departments
from services.admin_session import list_sessions, list_semesters
from services.admin_audit import log_admin_action

admin_courses_bp = Blueprint('courses', __name__)
admin_courses_bp.before_request(enforce_admin_required)


@admin_courses_bp.route('/admin/course-catalog')
@permission_required('courses.manage')
def admin_course_catalog():
    search = request.args.get('search', '').strip() or None
    status = request.args.get('status', '').strip() or None
    page = request.args.get('page', 1, type=int)
    result = list_master_courses(search=search, status=status, page=page)
    return render_template(
        'admin/course_catalog.html', result=result, search=search or '', status=status or '',
    )


@admin_courses_bp.route('/admin/course-catalog/new', methods=['GET', 'POST'])
@permission_required('courses.manage')
def admin_course_catalog_new():
    if request.method == 'GET':
        return render_template('admin/course_catalog_form.html', course=None)

    code = request.form.get('code', '').strip().upper()
    title = request.form.get('title', '').strip()
    credits = request.form.get('credits', type=int)
    course_type = request.form.get('course_type', '').strip()
    description = request.form.get('description', '').strip()

    errors = []
    if not code or not title or not credits or not course_type:
        errors.append('Code, title, credits, and course type are required.')
    elif not is_course_catalog_code_unique(code):
        errors.append(f'Course code "{code}" already exists in the catalog.')
    if errors:
        for e in errors:
            flash(e)
        return render_template('admin/course_catalog_form.html', course=None, form=request.form)

    course = create_master_course(code, title, credits, course_type, description=description)
    log_admin_action(current_user, 'course_catalog_created', target_type='course', target_id=course.id,
                      details=f'code={code}', ip_address=request.remote_addr)
    flash(f'Course "{code}" added to the catalog.')
    return redirect(url_for('admin.courses.admin_course_catalog_detail', course_id=course.id))


@admin_courses_bp.route('/admin/course-catalog/<int:course_id>')
@permission_required('courses.manage')
def admin_course_catalog_detail(course_id):
    detail = get_master_course_detail(course_id)
    other_courses = list_master_courses_for_picker(exclude_id=course_id)
    return render_template('admin/course_catalog.html', detail=detail, result=None, other_courses=other_courses)


@admin_courses_bp.route('/admin/course-catalog/<int:course_id>/edit', methods=['GET', 'POST'])
@permission_required('courses.manage')
def admin_course_catalog_edit(course_id):
    course = get_master_course(course_id)
    if request.method == 'GET':
        return render_template('admin/course_catalog_form.html', course=course)

    code = request.form.get('code', '').strip().upper()
    title = request.form.get('title', '').strip()
    credits = request.form.get('credits', type=int)
    course_type = request.form.get('course_type', '').strip()
    description = request.form.get('description', '').strip()

    errors = []
    if not code or not title or not credits or not course_type:
        errors.append('Code, title, credits, and course type are required.')
    elif not is_course_catalog_code_unique(code, exclude_id=course_id):
        errors.append(f'Course code "{code}" already exists in the catalog.')
    if errors:
        for e in errors:
            flash(e)
        return render_template('admin/course_catalog_form.html', course=course, form=request.form)

    update_master_course(course_id, code, title, credits, course_type, description=description)
    log_admin_action(current_user, 'course_catalog_updated', target_type='course', target_id=course_id,
                      details=f'code={code}', ip_address=request.remote_addr)
    flash(f'Course "{code}" updated.')
    return redirect(url_for('admin.courses.admin_course_catalog_detail', course_id=course_id))


@admin_courses_bp.route('/admin/course-catalog/<int:course_id>/prerequisites', methods=['POST'])
@permission_required('courses.manage')
def admin_course_catalog_prerequisites(course_id):
    prereq_ids = request.form.getlist('prerequisite_ids', type=int)
    set_prerequisites(course_id, prereq_ids)
    log_admin_action(current_user, 'course_catalog_prerequisites_updated', target_type='course', target_id=course_id,
                      details=f'count={len(prereq_ids)}', ip_address=request.remote_addr)
    flash('Prerequisites updated.')
    return redirect(url_for('admin.courses.admin_course_catalog_detail', course_id=course_id))


@admin_courses_bp.route('/admin/course-catalog/<int:course_id>/corequisites', methods=['POST'])
@permission_required('courses.manage')
def admin_course_catalog_corequisites(course_id):
    coreq_ids = request.form.getlist('corequisite_ids', type=int)
    set_corequisites(course_id, coreq_ids)
    log_admin_action(current_user, 'course_catalog_corequisites_updated', target_type='course', target_id=course_id,
                      details=f'count={len(coreq_ids)}', ip_address=request.remote_addr)
    flash('Corequisites updated.')
    return redirect(url_for('admin.courses.admin_course_catalog_detail', course_id=course_id))


@admin_courses_bp.route('/admin/course-catalog/<int:course_id>/activate', methods=['POST'])
@permission_required('courses.manage')
def admin_course_catalog_activate(course_id):
    set_master_course_status(course_id, 'active')
    log_admin_action(current_user, 'course_catalog_status_changed', target_type='course', target_id=course_id,
                      details='status=active', ip_address=request.remote_addr)
    flash('Course activated.')
    return redirect(url_for('admin.courses.admin_course_catalog_detail', course_id=course_id))


@admin_courses_bp.route('/admin/course-catalog/<int:course_id>/archive', methods=['POST'])
@permission_required('courses.manage')
def admin_course_catalog_archive(course_id):
    set_master_course_status(course_id, 'archived')
    log_admin_action(current_user, 'course_catalog_status_changed', target_type='course', target_id=course_id,
                      details='status=archived', ip_address=request.remote_addr)
    flash('Course archived.')
    return redirect(url_for('admin.courses.admin_course_catalog_detail', course_id=course_id))


@admin_courses_bp.route('/admin/courses')
@permission_required('courses.manage')
def admin_courses():
    return render_template('admin/courses.html', departments=list_active_departments(), semesters=list_semesters())


@admin_courses_bp.route('/admin/courses/data')
@permission_required('courses.manage')
def admin_courses_data():
    search = request.args.get('search', '').strip() or None
    department_id = request.args.get('department_id', type=int)
    level = request.args.get('level', '').strip() or None
    semester_id = request.args.get('semester_id', type=int)
    min_credits = request.args.get('min_credits', type=int)
    max_credits = request.args.get('max_credits', type=int)
    status = request.args.get('status', '').strip() or None
    page = request.args.get('page', 1, type=int)
    sort = request.args.get('sort', 'code')

    result = list_courses(
        search=search, department_id=department_id, level=level, semester_id=semester_id,
        min_credits=min_credits, max_credits=max_credits, status=status, page=page, sort=sort,
    )
    def course_json(c):
        enrolled = get_enrollment_count(c.id)
        remaining = (c.max_capacity - enrolled) if c.max_capacity is not None else None
        return {
            'id': c.id, 'code': c.code, 'title': c.title, 'department': c.department,
            'level': c.level or '—', 'semester': c.semester.name, 'credits': c.credits, 'status': c.status,
            'enrolled': enrolled, 'max_capacity': c.max_capacity if c.max_capacity is not None else '—',
            'remaining': remaining if remaining is not None else '—',
        }

    return jsonify({
        'success': True,
        'courses': [course_json(c) for c in result['items']],
        'total': result['total'], 'page': result['page'], 'per_page': result['per_page'],
    })


@admin_courses_bp.route('/admin/courses/new', methods=['GET', 'POST'])
@permission_required('courses.manage')
def admin_course_new():
    departments = list_active_departments()
    sessions = list_sessions()
    semesters = list_semesters()
    master_courses = list_master_courses_for_picker()
    if request.method == 'GET':
        return render_template('admin/course_form.html', course=None, departments=departments, sessions=sessions, semesters=semesters, master_courses=master_courses)

    master_course_id = request.form.get('master_course_id', type=int)
    department_id = request.form.get('department_id', type=int)
    max_capacity = request.form.get('max_capacity', type=int)
    level = request.form.get('level', '').strip()
    academic_session_id = request.form.get('academic_session_id', type=int)
    semester_id = request.form.get('semester_id', type=int)
    instructor = request.form.get('instructor', '').strip()
    schedule = request.form.get('schedule', '').strip()

    errors = []
    if not master_course_id or not department_id or not academic_session_id or not semester_id:
        errors.append('Master course, department, session, and semester are required.')
    elif master_course_id not in {mc.id for mc in master_courses}:
        # Backstop against a crafted/stale request posting a master_course_id
        # outside what's actually offered — don't just trust whatever the
        # client posts even if the template ever regresses. See the matching
        # comment in admin_course_edit for the fuller rationale (that route
        # additionally protects a pre-existing offering's link).
        errors.append('Selected master course is not valid.')
    else:
        master = get_master_course(master_course_id)
        if not is_course_code_unique(master.code, academic_session_id, semester_id):
            errors.append(f'"{master.code}" already has an offering for that session/semester.')
    if errors:
        for e in errors:
            flash(e)
        return render_template('admin/course_form.html', course=None, departments=departments, sessions=sessions, semesters=semesters, master_courses=master_courses, form=request.form)

    offering = create_course(
        master_course_id, department_id, level, academic_session_id, semester_id,
        instructor=instructor, schedule=schedule, max_capacity=max_capacity,
    )
    log_admin_action(current_user, 'course_created', target_type='course', target_id=offering.id,
                      details=f'code={offering.code} master_course_id={master_course_id}', ip_address=request.remote_addr)
    flash(f'Course offering "{offering.code}" created.')
    return redirect(url_for('admin.courses.admin_course_detail', course_id=offering.id))


@admin_courses_bp.route('/admin/courses/<int:course_id>')
@permission_required('courses.manage')
def admin_course_detail(course_id):
    detail = get_course_detail(course_id)
    enrolled = get_enrollment_count(course_id)
    return render_template('admin/course_detail.html', enrolled=enrolled, **detail)


@admin_courses_bp.route('/admin/courses/<int:course_id>/assessment', methods=['POST'])
@permission_required('courses.manage')
def admin_course_assessment(course_id):
    names = request.form.getlist('component_name')
    weights = request.form.getlist('component_weight')
    components = []
    for name, weight in zip(names, weights):
        name = name.strip()
        if name and weight:
            try:
                components.append({'name': name, 'weight_percent': int(weight)})
            except ValueError:
                continue

    set_assessment_components(course_id, components)
    total_weight = sum(c['weight_percent'] for c in components)
    if components and total_weight != 100:
        flash(f'Assessment components saved, but weights total {total_weight}% (expected 100%) — double-check before relying on this.')
    else:
        flash('Assessment components updated.')
    log_admin_action(current_user, 'course_assessment_updated', target_type='course', target_id=course_id,
                      details=f'count={len(components)} total_weight={total_weight}', ip_address=request.remote_addr)
    return redirect(url_for('admin.courses.admin_course_detail', course_id=course_id))


@admin_courses_bp.route('/admin/courses/<int:course_id>/edit', methods=['GET', 'POST'])
@permission_required('courses.manage')
def admin_course_edit(course_id):
    offering = get_course(course_id)
    departments = list_active_departments()
    sessions = list_sessions()
    semesters = list_semesters()
    # The offering's currently-linked master Course can be archived at any
    # time via the Course Catalog module, dropping it out of the plain
    # active-only picker. If we didn't union it back in, an admin who edits
    # this offering without touching the Master Course field would have the
    # browser silently default to selecting the *first* option — silently
    # re-linking (and re-mirroring code/title/credits/course_type/description
    # from) an unrelated master on an otherwise-unrelated edit. Union it back
    # in (labeled distinctly in the template) so a no-op resubmit round-trips
    # correctly. Same pattern as the period-edit Semester-dropdown fix.
    master_courses = list_master_courses_for_picker(include_id=offering.course_id)
    if request.method == 'GET':
        return render_template('admin/course_form.html', course=offering, departments=departments, sessions=sessions, semesters=semesters, master_courses=master_courses)

    master_course_id = request.form.get('master_course_id', type=int)
    department_id = request.form.get('department_id', type=int)
    max_capacity = request.form.get('max_capacity', type=int)
    level = request.form.get('level', '').strip()
    academic_session_id = request.form.get('academic_session_id', type=int)
    semester_id = request.form.get('semester_id', type=int)
    instructor = request.form.get('instructor', '').strip()
    schedule = request.form.get('schedule', '').strip()

    errors = []
    if not master_course_id or not department_id or not academic_session_id or not semester_id:
        errors.append('Master course, department, session, and semester are required.')
    elif master_course_id not in {mc.id for mc in master_courses}:
        # Backstop against a crafted/stale request posting a master_course_id
        # outside what's actually offered (the active set, plus the
        # offering's own current master if it was unioned back in above) —
        # don't just trust whatever the client posts even if the template
        # ever regresses. Same shape as the period-edit Semester backstop.
        errors.append('Selected master course is not valid.')
    else:
        master = get_master_course(master_course_id)
        if not is_course_code_unique(master.code, academic_session_id, semester_id, exclude_id=course_id):
            errors.append(f'"{master.code}" already has an offering for that session/semester.')
    if errors:
        for e in errors:
            flash(e)
        return render_template('admin/course_form.html', course=offering, departments=departments, sessions=sessions, semesters=semesters, master_courses=master_courses, form=request.form)

    update_course(
        course_id, master_course_id=master_course_id, department_id=department_id,
        level=level or None, academic_session_id=academic_session_id, semester_id=semester_id,
        instructor=instructor or None, schedule=schedule or None, max_capacity=max_capacity,
    )
    log_admin_action(current_user, 'course_updated', target_type='course', target_id=course_id,
                      details=f'master_course_id={master_course_id}', ip_address=request.remote_addr)
    flash('Course offering updated.')
    return redirect(url_for('admin.courses.admin_course_detail', course_id=course_id))


@admin_courses_bp.route('/admin/courses/<int:course_id>/activate', methods=['POST'])
@permission_required('courses.manage')
def admin_course_activate(course_id):
    set_course_status(course_id, 'active')
    log_admin_action(current_user, 'course_status_changed', target_type='course', target_id=course_id,
                      details='status=active', ip_address=request.remote_addr)
    flash('Course activated.')
    return redirect(url_for('admin.courses.admin_course_detail', course_id=course_id))


@admin_courses_bp.route('/admin/courses/<int:course_id>/deactivate', methods=['POST'])
@permission_required('courses.manage')
def admin_course_deactivate(course_id):
    set_course_status(course_id, 'inactive')
    log_admin_action(current_user, 'course_status_changed', target_type='course', target_id=course_id,
                      details='status=inactive', ip_address=request.remote_addr)
    flash('Course deactivated for the current offering.')
    return redirect(url_for('admin.courses.admin_course_detail', course_id=course_id))


@admin_courses_bp.route('/admin/courses/<int:course_id>/archive', methods=['POST'])
@permission_required('courses.manage')
def admin_course_archive(course_id):
    set_course_status(course_id, 'archived')
    log_admin_action(current_user, 'course_status_changed', target_type='course', target_id=course_id,
                      details='status=archived', ip_address=request.remote_addr)
    flash('Course archived.')
    return redirect(url_for('admin.courses.admin_course_detail', course_id=course_id))


@admin_courses_bp.route('/admin/courses/import/preview', methods=['POST'])
@permission_required('courses.manage')
def admin_course_import_preview():
    file_storage = request.files.get('file')
    summary, parse_error = preview_courses_csv(file_storage)
    if parse_error:
        return jsonify({'success': False, 'message': parse_error}), 400
    return jsonify({'success': True, **summary})


@admin_courses_bp.route('/admin/courses/import', methods=['GET', 'POST'])
@permission_required('courses.manage')
def admin_course_import():
    if request.method == 'GET':
        return render_template('admin/course_import.html', sessions=list_sessions())

    academic_session_id = request.form.get('academic_session_id', type=int)
    file_storage = request.files.get('file')
    if not academic_session_id:
        flash('Please choose an academic session.')
        return redirect(url_for('admin.courses.admin_course_import'))

    job = import_courses_csv(file_storage, current_user, academic_session_id)
    log_admin_action(
        current_user, 'course_import_completed', target_type='course_import_job', target_id=job.id,
        details=f'created={job.created_count} updated={job.updated_count} skipped={job.skipped_count} '
                f'duplicates={job.duplicate_count} errors={job.error_count}',
        ip_address=request.remote_addr,
    )
    return redirect(url_for('admin.courses.admin_course_import_report', job_id=job.id))


@admin_courses_bp.route('/admin/courses/import/<int:job_id>')
@permission_required('courses.manage')
def admin_course_import_report(job_id):
    job = CourseImportJob.query.get_or_404(job_id)
    return render_template('admin/course_import_report.html', job=job)


from blueprints.admin import admin_bp  # noqa: E402 — deferred import to avoid a circular import with blueprints/admin/__init__.py

admin_bp.register_blueprint(admin_courses_bp)
