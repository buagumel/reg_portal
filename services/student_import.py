from models import db, User, StudentImportJob, StudentImportError
from services.admin_import import parse_csv, create_import_job, record_import_error, finalize_import_job
from services.admin_validation import resolve_department, resolve_programme

REQUIRED_HEADERS = ['reg_no', 'name']


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
    seen_in_file = set()

    for row_number, row in enumerate(rows, start=2):  # header is row 1
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
            record_import_error(StudentImportError, job, row_number, row, 'Missing reg_no or name.')
            errors += 1
            continue

        if reg_no in seen_in_file:
            record_import_error(StudentImportError, job, row_number, row, f'Duplicate reg_no "{reg_no}" within this file.')
            duplicates += 1
            continue
        seen_in_file.add(reg_no)

        department = resolve_department(department_name) if department_name else None
        if department_name and not department:
            record_import_error(StudentImportError, job, row_number, row, f'Unknown department "{department_name}".')
            errors += 1
            continue

        programme = resolve_programme(programme_name) if programme_name else None
        if programme_name and not programme:
            record_import_error(StudentImportError, job, row_number, row, f'Unknown programme "{programme_name}".')
            errors += 1
            continue

        existing = User.query.filter_by(reg_no=reg_no).first()
        if existing:
            new_values = {
                'name': name,
                'department': department.name if department else existing.department,
                'department_id': department.id if department else existing.department_id,
                'course': programme.name if programme else existing.course,
                'programme_id': programme.id if programme else existing.programme_id,
                'level': level or existing.level, 'semester': semester or existing.semester,
                'session': session_value or existing.session, 'nationality': nationality or existing.nationality,
                'state': state or existing.state, 'lga': lga or existing.lga,
                'gender': gender or existing.gender, 'student_type': student_type or existing.student_type,
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
            reg_no=reg_no, name=name, email=email or None, phone=phone or None,
            department=department.name if department else None, department_id=department.id if department else None,
            course=programme.name if programme else None, programme_id=programme.id if programme else None,
            level=level or None, semester=semester or None, session=session_value or None,
            nationality=nationality or None, state=state or None, lga=lga or None,
            gender=gender or None, student_type=student_type or None,
            first_login=True, onboarding_completed=False, email_verified=False, account_status='active',
        )
        student.set_password(temp_password)
        db.session.add(student)
        created += 1

    db.session.commit()
    finalize_import_job(job, created, updated, skipped, duplicates, errors)
    return job
