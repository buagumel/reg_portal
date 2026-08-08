from models import db, Course, CourseOffering, CourseImportJob, CourseImportError
from services.admin_import import parse_csv, create_import_job, record_import_error, finalize_import_job
from services.admin_validation import resolve_department, resolve_semester

REQUIRED_HEADERS = ['code', 'title', 'credits', 'department', 'semester', 'course_type']


def _validate_row(row, seen_dedup_keys):
    """Validate one CSV row against static rules. Returns (parsed_fields,
    error_message, category) — category is 'duplicate' or 'error', only
    meaningful when error_message is set. Read-only against the database."""
    code = (row.get('code') or '').strip().upper()
    title = (row.get('title') or '').strip()
    credits_raw = (row.get('credits') or '').strip()
    department_name = (row.get('department') or '').strip()
    level = (row.get('level') or '').strip()
    semester_name = (row.get('semester') or '').strip()
    course_type = (row.get('course_type') or '').strip().lower()
    description = (row.get('description') or '').strip()
    instructor = (row.get('instructor') or '').strip()
    schedule = (row.get('schedule') or '').strip()
    max_capacity_raw = (row.get('max_capacity') or '').strip()

    if not code or not title:
        return None, 'Missing code or title.', 'error'

    dedup_key = f'{code}|{semester_name}'
    if dedup_key in seen_dedup_keys:
        return None, f'Duplicate code "{code}" within this file.', 'duplicate'

    if not credits_raw.isdigit():
        return None, 'Missing or invalid credits.', 'error'
    credits = int(credits_raw)

    department = resolve_department(department_name)
    if not department:
        return None, f'Unknown department "{department_name}".', 'error'

    semester = resolve_semester(semester_name)
    if not semester:
        return None, f'Unknown semester "{semester_name}".', 'error'

    if course_type not in ('core', 'elective', 'lab'):
        return None, f'Invalid course_type "{course_type}" (expected core/elective/lab).', 'error'

    max_capacity = int(max_capacity_raw) if max_capacity_raw.isdigit() else None

    return {
        'dedup_key': dedup_key, 'code': code, 'title': title, 'credits': credits,
        'department': department, 'level': level, 'semester': semester, 'course_type': course_type,
        'description': description, 'instructor': instructor, 'schedule': schedule, 'max_capacity': max_capacity,
    }, None, None


def preview_courses_csv(file_storage):
    """Validate an uploaded CSV without writing anything to the database.
    Same summary shape as services/student_import.py's preview_students_csv."""
    rows, parse_error = parse_csv(file_storage, REQUIRED_HEADERS)
    if parse_error:
        return None, parse_error

    seen_dedup_keys = set()
    valid_count = duplicate_count = error_count = 0
    flagged_rows = []

    for row_number, row in enumerate(rows, start=2):
        fields, error, category = _validate_row(row, seen_dedup_keys)
        if error:
            if category == 'duplicate':
                duplicate_count += 1
            else:
                error_count += 1
            flagged_rows.append({'row_number': row_number, 'reason': error, 'raw_row': row})
            continue
        valid_count += 1
        seen_dedup_keys.add(fields['dedup_key'])

    return {
        'total_rows': len(rows), 'valid_count': valid_count,
        'duplicate_count': duplicate_count, 'error_count': error_count,
        'flagged_rows': flagged_rows,
    }, None


def import_courses_csv(file_storage, admin_user, academic_session_id):
    filename = file_storage.filename if file_storage else 'unknown.csv'
    job = create_import_job(CourseImportJob, admin_user, filename)

    rows, parse_error = parse_csv(file_storage, REQUIRED_HEADERS)
    if parse_error:
        record_import_error(CourseImportError, job, 0, {}, parse_error)
        finalize_import_job(job, 0, 0, 0, 0, 1)  # sets status='completed' — a file-level parse
        job.status = 'failed'                     # error isn't really "completed", so override it
        db.session.commit()
        return job

    created = updated = skipped = duplicates = errors = mismatched = 0
    seen_dedup_keys = set()

    for row_number, row in enumerate(rows, start=2):  # header is row 1
        fields, error, category = _validate_row(row, seen_dedup_keys)
        if error:
            record_import_error(CourseImportError, job, row_number, row, error)
            if category == 'duplicate':
                duplicates += 1
            else:
                errors += 1
            continue
        seen_dedup_keys.add(fields['dedup_key'])

        code, department, semester = fields['code'], fields['department'], fields['semester']
        title, credits, level, course_type = fields['title'], fields['credits'], fields['level'], fields['course_type']
        description, instructor, schedule, max_capacity = fields['description'], fields['instructor'], fields['schedule'], fields['max_capacity']

        master = Course.query.filter_by(code=code).first()
        if master is None:
            master = Course(code=code, title=title, credits=credits, course_type=course_type, description=description or None)
            db.session.add(master)
            db.session.flush()  # assigns master.id without committing yet
        else:
            mismatch = (
                master.title != title or master.credits != credits
                or master.course_type != course_type or (master.description or '') != description
            )
            if mismatch:
                record_import_error(
                    CourseImportError, job, row_number, row,
                    f'Row title/credits/course_type/description differs from existing master course "{code}" — master was not changed.',
                    severity='warning',
                )
                mismatched += 1

        existing = CourseOffering.query.filter_by(
            code=code, academic_session_id=academic_session_id, semester_id=semester.id,
        ).first()
        if existing:
            changed = (
                existing.department_id != department.id or existing.level != (level or None)
                or existing.instructor != (instructor or None) or existing.schedule != (schedule or None)
                or existing.max_capacity != max_capacity
            )
            if changed:
                existing.department_id = department.id
                existing.department = department.name
                existing.level = level or None
                existing.instructor = instructor or None
                existing.schedule = schedule or None
                existing.max_capacity = max_capacity
                updated += 1
            else:
                skipped += 1
            continue

        db.session.add(CourseOffering(
            code=master.code, title=master.title, credits=master.credits, course_type=master.course_type,
            description=master.description, course_id=master.id,
            department=department.name, department_id=department.id,
            level=level or None, academic_session_id=academic_session_id,
            semester_id=semester.id, instructor=instructor or None,
            schedule=schedule or None, max_capacity=max_capacity, status='active',
        ))
        created += 1

    db.session.commit()
    finalize_import_job(job, created, updated, skipped, duplicates, errors)
    job.mismatched_count = mismatched
    db.session.commit()
    return job
