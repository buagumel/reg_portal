from flask import request, jsonify, render_template, redirect, url_for
from flask_login import current_user

from blueprints.admin.students import admin_students_bp
from models import StudentImportJob
from services.admin_permission import permission_required
from services.student_import import import_students_csv, preview_students_csv
from services.admin_audit import log_admin_action


@admin_students_bp.route('/admin/students/import/preview', methods=['POST'])
@permission_required('students.manage')
def admin_students_import_preview():
    file_storage = request.files.get('file')
    summary, parse_error = preview_students_csv(file_storage)
    if parse_error:
        return jsonify({'success': False, 'message': parse_error}), 400
    return jsonify({'success': True, **summary})


@admin_students_bp.route('/admin/students/import', methods=['GET', 'POST'])
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
    return redirect(url_for('admin.students.admin_student_import_report', job_id=job.id))


@admin_students_bp.route('/admin/students/import/<int:job_id>')
@permission_required('students.manage')
def admin_student_import_report(job_id):
    job = StudentImportJob.query.get_or_404(job_id)
    return render_template('admin/student_import_report.html', job=job)


@admin_students_bp.route('/admin/students/import/admission-portal')
@permission_required('students.manage')
def admin_student_admission_portal():
    return render_template('admin/coming_soon.html', feature_name='Admission Portal Import')
