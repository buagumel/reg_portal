from models import db, User, StudentImportJob, StudentImportError
from services.admin_import import parse_csv, create_import_job, record_import_error, finalize_import_job
from services.admin_validation import resolve_department, resolve_programme, valid_levels_for_programme

REQUIRED_HEADERS = ['reg_no', 'name']


def _validate_row(row, seen_reg_nos, seen_emails):
    """Validate one CSV row against static rules and existing DB duplicates.
    Returns (parsed_fields, error_message, category) — parsed_fields is None
    unless the row is fully valid; category is 'duplicate' or 'error' (only
    meaningful when error_message is set) and tells the caller which counter
    to increment. Read-only against the database — safe to call from both
    the preview endpoint and the real import."""
    reg_no = (row.get('reg_no') or '').strip()
    name = (row.get('name') or '').strip()
    email = (row.get('email') or '').strip()
    phone = (row.get('phone') or '').strip()
    department_name = (row.get('department') or '').strip()
    programme_name = (row.get('programme') or '').strip()
    level = (row.get('level') or '').strip()
    semester = (row.get('semester') or '').strip()
    session_value = (row.get('session') or '').strip()
    nationality = (row.get('nationality') or '').strip()
    state = (row.get('state') or '').strip()
    lga = (row.get('lga') or '').strip()
    gender = (row.get('gender') or '').strip()
    student_type = (row.get('student_type') or '').strip()

    if not reg_no or not name:
        return None, 'Missing reg_no or name.', 'error'

    if reg_no in seen_reg_nos:
        return None, f'Duplicate reg_no "{reg_no}" within this file.', 'duplicate'

    if email:
        if email in seen_emails:
            return None, f'Duplicate email "{email}" within this file.', 'duplicate'
        existing_email_owner = User.query.filter(User.email == email, User.reg_no != reg_no).first()
        if existing_email_owner:
            return None, f'Email "{email}" already belongs to another student ({existing_email_owner.reg_no}).', 'error'

    department = resolve_department(department_name) if department_name else None
    if department_name and not department:
        return None, f'Unknown department "{department_name}".', 'error'

    programme = resolve_programme(programme_name) if programme_name else None
    if programme_name and not programme:
        return None, f'Unknown programme "{programme_name}".', 'error'

    if programme and level:
        valid_levels = valid_levels_for_programme(programme)
        if valid_levels is not None and level not in valid_levels:
            return None, f'"{level}" is not a valid level for {programme.name} (expected one of: {", ".join(valid_levels)}).', 'error'

    return {
        'reg_no': reg_no, 'name': name, 'email': email, 'phone': phone,
        'department': department, 'programme': programme, 'level': level, 'semester': semester,
        'session': session_value, 'nationality': nationality, 'state': state, 'lga': lga,
        'gender': gender, 'student_type': student_type,
    }, None, None


def preview_students_csv(file_storage):
    """Validate an uploaded CSV without writing anything to the database.
    Returns (summary, error) — error is a file-level parse error (missing
    headers, empty file, etc.), summary is None in that case. On success,
    summary is {'total_rows', 'valid_count', 'duplicate_count', 'error_count',
    'flagged_rows': [{'row_number', 'reason', 'raw_row'}, ...]}."""
    rows, parse_error = parse_csv(file_storage, REQUIRED_HEADERS)
    if parse_error:
        return None, parse_error

    seen_reg_nos = set()
    seen_emails = set()
    valid_count = duplicate_count = error_count = 0
    flagged_rows = []

    for row_number, row in enumerate(rows, start=2):
        fields, error, category = _validate_row(row, seen_reg_nos, seen_emails)
        if error:
            if category == 'duplicate':
                duplicate_count += 1
            else:
                error_count += 1
            flagged_rows.append({'row_number': row_number, 'reason': error, 'raw_row': row})
            continue
        valid_count += 1
        seen_reg_nos.add(fields['reg_no'])
        if fields['email']:
            seen_emails.add(fields['email'])

    return {
        'total_rows': len(rows), 'valid_count': valid_count,
        'duplicate_count': duplicate_count, 'error_count': error_count,
        'flagged_rows': flagged_rows,
    }, None


def import_students_csv(file_storage, admin_user):
    import random
    import string

    filename = file_storage.filename if file_storage else 'unknown.csv'
    job = create_import_job(StudentImportJob, admin_user, filename)

    rows, parse_error = parse_csv(file_storage, REQUIRED_HEADERS)
    if parse_error:
        record_import_error(StudentImportError, job, 0, {}, parse_error)
        finalize_import_job(job, 0, 0, 0, 0, 1)  # sets status='completed' — a file-level parse
        job.status = 'failed'                     # error isn't really "completed", so override it
        db.session.commit()
        return job

    created = updated = skipped = duplicates = errors = 0
    seen_reg_nos = set()
    seen_emails = set()

    for row_number, row in enumerate(rows, start=2):  # header is row 1
        fields, error, category = _validate_row(row, seen_reg_nos, seen_emails)
        if error:
            record_import_error(StudentImportError, job, row_number, row, error)
            if category == 'duplicate':
                duplicates += 1
            else:
                errors += 1
            continue
        seen_reg_nos.add(fields['reg_no'])
        if fields['email']:
            seen_emails.add(fields['email'])

        reg_no = fields['reg_no']
        department = fields['department']
        programme = fields['programme']

        existing = User.query.filter_by(reg_no=reg_no).first()
        if existing:
            new_values = {
                'name': fields['name'],
                'department': department.name if department else existing.department,
                'department_id': department.id if department else existing.department_id,
                'course': programme.name if programme else existing.course,
                'programme_id': programme.id if programme else existing.programme_id,
                'level': fields['level'] or existing.level, 'semester': fields['semester'] or existing.semester,
                'session': fields['session'] or existing.session, 'nationality': fields['nationality'] or existing.nationality,
                'state': fields['state'] or existing.state, 'lga': fields['lga'] or existing.lga,
                'gender': fields['gender'] or existing.gender, 'student_type': fields['student_type'] or existing.student_type,
            }
            changed = any(getattr(existing, key) != value for key, value in new_values.items())
            if changed:
                for key, value in new_values.items():
                    setattr(existing, key, value)
                updated += 1
            else:
                skipped += 1
            continue

        temp_password = f'Temp{"".join(random.choices(string.digits, k=4))}!'
        student = User(
            reg_no=reg_no, name=fields['name'], email=fields['email'] or None, phone=fields['phone'] or None,
            department=department.name if department else None, department_id=department.id if department else None,
            course=programme.name if programme else None, programme_id=programme.id if programme else None,
            level=fields['level'] or None, semester=fields['semester'] or None, session=fields['session'] or None,
            nationality=fields['nationality'] or None, state=fields['state'] or None, lga=fields['lga'] or None,
            gender=fields['gender'] or None, student_type=fields['student_type'] or None,
            first_login=True, onboarding_completed=False, email_verified=False, account_status='active',
        )
        student.set_password(temp_password)
        db.session.add(student)
        created += 1

    db.session.commit()
    finalize_import_job(job, created, updated, skipped, duplicates, errors)
    return job
