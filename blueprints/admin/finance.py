import math

from flask import Blueprint, request, flash, redirect, url_for, render_template, jsonify, abort
from flask_login import current_user

from services.admin_permission import permission_required, enforce_admin_required
from services.admin_fee_structure import (
    list_fee_structures, get_fee_structure, create_fee_structure,
    update_fee_structure, delete_fee_structure,
)
from services.fee_structure import list_general_flow_categories
from services.admin_export import export_csv, export_excel, VALID_DATA_TYPES
from services.admin_session import list_sessions, get_session, list_semesters_for_programme
from services.admin_department import list_active_departments
from services.admin_validation import is_fee_structure_scope_unique
from services.admin_audit import log_admin_action

admin_finance_bp = Blueprint('finance', __name__)
admin_finance_bp.before_request(enforce_admin_required)


@admin_finance_bp.route('/admin/fee-structure')
@permission_required('sessions.manage')
def admin_fee_structures():
    session_id = request.args.get('session_id', type=int)
    rows = list_fee_structures(session_id=session_id)
    return render_template(
        'admin/fee_structures.html', rows=rows,
        sessions=list_sessions(), selected_session_id=session_id,
    )


@admin_finance_bp.route('/admin/fee-structure/new', methods=['GET', 'POST'])
@permission_required('sessions.manage')
def admin_fee_structure_new():
    sessions = list_sessions()
    session_id = request.args.get('session_id', type=int) or request.form.get('academic_session_id', type=int)
    selected_session = get_session(session_id) if session_id else None
    semesters = list_semesters_for_programme(selected_session.programme) if selected_session else []
    departments = list_active_departments()
    # registration_fee is excluded from this list — see
    # NON_GENERAL_FLOW_CATEGORY_CODES in services/fee_structure.py: it's
    # charged and reconciled exclusively through register_student()/
    # DepartmentRegistrationRule (registration_id-linked), never through the
    # general /payment/create flow. A FeeStructure row targeting it would
    # still resolve a real amount and surface as payable there, but paying
    # it would never mark any StudentRegistration as paid — an
    # unreconcilable charge.
    categories = list_general_flow_categories()

    if request.method == 'GET' or selected_session is None:
        return render_template(
            'admin/fee_structure_form.html', row=None, sessions=sessions,
            selected_session=selected_session, semesters=semesters,
            departments=departments, categories=categories,
        )

    semester_id = request.form.get('semester_id', type=int) or None
    department_id = request.form.get('department_id', type=int) or None
    category_id = request.form.get('category_id', type=int)
    amount = request.form.get('amount', type=float)

    if not category_id or amount is None or not math.isfinite(amount) or amount <= 0:
        flash('Category and a positive amount are required.')
        return render_template(
            'admin/fee_structure_form.html', row=None, sessions=sessions,
            selected_session=selected_session, semesters=semesters,
            departments=departments, categories=categories, form=request.form,
        )
    if semester_id is not None and semester_id not in {s.id for s in semesters}:
        # Backstop against a crafted/stale request posting a semester_id
        # outside what's actually offered (the Programme-filtered set) —
        # same pattern as admin_fee_structure_edit and admin_period_new.
        flash("Selected semester is not valid for this session's programme.")
        return render_template(
            'admin/fee_structure_form.html', row=None, sessions=sessions,
            selected_session=selected_session, semesters=semesters,
            departments=departments, categories=categories, form=request.form,
        )
    if department_id is not None and department_id not in {d.id for d in departments}:
        # Same backstop for department_id.
        flash('Selected department is not valid.')
        return render_template(
            'admin/fee_structure_form.html', row=None, sessions=sessions,
            selected_session=selected_session, semesters=semesters,
            departments=departments, categories=categories, form=request.form,
        )
    if category_id not in {c.id for c in categories}:
        # Backstop against a crafted request posting a category_id outside
        # the offered (active, general-flow-payable) set — e.g.
        # registration_fee's id. This is what actually prevents such a row
        # from being creatable; payment_create_submit's matching exclusion
        # is only the second line of defense.
        flash('Selected category is not valid.')
        return render_template(
            'admin/fee_structure_form.html', row=None, sessions=sessions,
            selected_session=selected_session, semesters=semesters,
            departments=departments, categories=categories, form=request.form,
        )
    if not is_fee_structure_scope_unique(selected_session.id, semester_id, department_id, category_id):
        flash('A fee structure row for this exact session/semester/department/category combination already exists.')
        return render_template(
            'admin/fee_structure_form.html', row=None, sessions=sessions,
            selected_session=selected_session, semesters=semesters,
            departments=departments, categories=categories, form=request.form,
        )

    row = create_fee_structure(selected_session.id, semester_id, department_id, category_id, amount)
    log_admin_action(current_user, 'fee_structure_created', target_type='fee_structure', target_id=row.id,
                      details=f'session_id={selected_session.id} semester_id={semester_id} department_id={department_id} category_id={category_id} amount={amount}',
                      ip_address=request.remote_addr)
    flash('Fee structure row created.')
    return redirect(url_for('admin.finance.admin_fee_structures', session_id=selected_session.id))


@admin_finance_bp.route('/admin/fee-structure/<int:fee_structure_id>/edit', methods=['GET', 'POST'])
@permission_required('sessions.manage')
def admin_fee_structure_edit(fee_structure_id):
    row = get_fee_structure(fee_structure_id)
    # A FeeStructure row's semester_id/department_id can reference a Semester
    # that's no longer in this session's Programme-filtered calendar shape, or
    # a Department that's since been deactivated. If we dropped it from the
    # dropdown, an admin who edits the row without touching that one field
    # (e.g. just changing the amount) would have the browser silently submit
    # the blank "All semesters"/"All departments" option — silently widening
    # the row's scope on an otherwise-unrelated edit. Union the row's current
    # value back in (labeled distinctly in the template) so a no-op resubmit
    # round-trips correctly, plus a server-side backstop rejecting any posted
    # value not among the actually-offered options. Same pattern as
    # admin_period_edit's Semester-dropdown fix.
    semesters = list_semesters_for_programme(row.academic_session.programme)
    mismatched_semester_id = None
    if row.semester_id is not None and row.semester_id not in {s.id for s in semesters}:
        semesters = semesters + [row.semester]
        mismatched_semester_id = row.semester_id

    departments = list_active_departments()
    mismatched_department_id = None
    if row.department_id is not None and row.department_id not in {d.id for d in departments}:
        departments = departments + [row.department]
        mismatched_department_id = row.department_id

    # registration_fee is excluded from this list — see
    # NON_GENERAL_FLOW_CATEGORY_CODES in services/fee_structure.py, and the
    # matching exclusion in admin_fee_structure_new.
    categories = list_general_flow_categories()

    if request.method == 'GET':
        return render_template(
            'admin/fee_structure_form.html', row=row, sessions=None,
            selected_session=row.academic_session, semesters=semesters,
            departments=departments, categories=categories,
            mismatched_semester_id=mismatched_semester_id,
            mismatched_department_id=mismatched_department_id,
        )

    semester_id = request.form.get('semester_id', type=int) or None
    department_id = request.form.get('department_id', type=int) or None
    category_id = request.form.get('category_id', type=int)
    amount = request.form.get('amount', type=float)

    if not category_id or amount is None or not math.isfinite(amount) or amount <= 0:
        flash('Category and a positive amount are required.')
        return render_template(
            'admin/fee_structure_form.html', row=row, sessions=None,
            selected_session=row.academic_session, semesters=semesters,
            departments=departments, categories=categories, form=request.form,
            mismatched_semester_id=mismatched_semester_id,
            mismatched_department_id=mismatched_department_id,
        )
    if semester_id is not None and semester_id not in {s.id for s in semesters}:
        # Backstop against a crafted/stale request posting a semester_id
        # outside what's actually offered (the Programme-filtered set, plus
        # the row's own current semester if it was unioned back in above).
        flash("Selected semester is not valid for this session's programme.")
        return render_template(
            'admin/fee_structure_form.html', row=row, sessions=None,
            selected_session=row.academic_session, semesters=semesters,
            departments=departments, categories=categories, form=request.form,
            mismatched_semester_id=mismatched_semester_id,
            mismatched_department_id=mismatched_department_id,
        )
    if department_id is not None and department_id not in {d.id for d in departments}:
        # Same backstop for department_id.
        flash('Selected department is not valid.')
        return render_template(
            'admin/fee_structure_form.html', row=row, sessions=None,
            selected_session=row.academic_session, semesters=semesters,
            departments=departments, categories=categories, form=request.form,
            mismatched_semester_id=mismatched_semester_id,
            mismatched_department_id=mismatched_department_id,
        )
    if category_id not in {c.id for c in categories}:
        # Backstop against a crafted request posting a category_id outside
        # the offered (active, general-flow-payable) set — e.g.
        # registration_fee's id. Same reasoning as admin_fee_structure_new.
        flash('Selected category is not valid.')
        return render_template(
            'admin/fee_structure_form.html', row=row, sessions=None,
            selected_session=row.academic_session, semesters=semesters,
            departments=departments, categories=categories, form=request.form,
            mismatched_semester_id=mismatched_semester_id,
            mismatched_department_id=mismatched_department_id,
        )
    if not is_fee_structure_scope_unique(row.academic_session_id, semester_id, department_id, category_id, exclude_id=row.id):
        flash('A fee structure row for this exact session/semester/department/category combination already exists.')
        return render_template(
            'admin/fee_structure_form.html', row=row, sessions=None,
            selected_session=row.academic_session, semesters=semesters,
            departments=departments, categories=categories, form=request.form,
            mismatched_semester_id=mismatched_semester_id,
            mismatched_department_id=mismatched_department_id,
        )

    update_fee_structure(fee_structure_id, semester_id, department_id, category_id, amount)
    log_admin_action(current_user, 'fee_structure_updated', target_type='fee_structure', target_id=fee_structure_id,
                      details=f'semester_id={semester_id} department_id={department_id} category_id={category_id} amount={amount}',
                      ip_address=request.remote_addr)
    flash('Fee structure row updated.')
    return redirect(url_for('admin.finance.admin_fee_structures', session_id=row.academic_session_id))


@admin_finance_bp.route('/admin/fee-structure/<int:fee_structure_id>/delete', methods=['POST'])
@permission_required('sessions.manage')
def admin_fee_structure_delete(fee_structure_id):
    row = get_fee_structure(fee_structure_id)
    # Capture the full scope/amount before delete_fee_structure() destroys
    # the row — otherwise the audit trail can never reconstruct what
    # override existed before this deletion (unlike the create/update log
    # entries, which capture all of it).
    session_id = row.academic_session_id
    details = (f'session_id={session_id} semester_id={row.semester_id} '
               f'department_id={row.department_id} category_id={row.category_id} amount={row.amount}')
    delete_fee_structure(fee_structure_id)
    log_admin_action(current_user, 'fee_structure_deleted', target_type='fee_structure', target_id=fee_structure_id,
                      details=details, ip_address=request.remote_addr)
    flash('Fee structure row deleted.')
    return redirect(url_for('admin.finance.admin_fee_structures', session_id=session_id))


@admin_finance_bp.route('/admin/export')
@permission_required('reports.view')
def admin_export_center():
    return render_template('admin/export_center.html')


@admin_finance_bp.route('/admin/export/<data_type>/<fmt>')
@permission_required('reports.view')
def admin_export_download(data_type, fmt):
    if data_type not in VALID_DATA_TYPES:
        abort(404)
    if fmt == 'csv':
        response = export_csv(data_type)
    elif fmt == 'xlsx':
        response = export_excel(data_type)
    else:
        abort(404)
    log_admin_action(current_user, 'data_exported', target_type=data_type, details=f'format={fmt}',
                      ip_address=request.remote_addr)
    return response


@admin_finance_bp.route('/admin/students/bulk-export', methods=['POST'])
@permission_required('reports.view')
def admin_students_bulk_export():
    data = request.get_json()
    if not data or not data.get('student_ids') or not data.get('format'):
        return jsonify({'success': False, 'message': 'student_ids and format are required.'}), 400

    fmt = data['format']
    student_ids = data['student_ids']
    if fmt == 'csv':
        response = export_csv('students', student_ids=student_ids)
    elif fmt == 'xlsx':
        response = export_excel('students', student_ids=student_ids)
    else:
        return jsonify({'success': False, 'message': 'format must be csv or xlsx.'}), 400

    log_admin_action(current_user, 'student_bulk_exported', target_type='user', target_id=None,
                      details=f'format={fmt} count={len(student_ids)} ids={student_ids}', ip_address=request.remote_addr)
    return response


@admin_finance_bp.route('/admin/reports')
@permission_required('reports.view')
def admin_stub_reports():
    return render_template('admin/coming_soon.html', feature_name='Generate Reports')


from blueprints.admin import admin_bp  # noqa: E402 — deferred import to avoid a circular import with blueprints/admin/__init__.py

admin_bp.register_blueprint(admin_finance_bp)
