from models import db, Course, CourseImportJob, CourseImportError
from services.admin_import import parse_csv, create_import_job, record_import_error, finalize_import_job
from services.admin_validation import resolve_department, resolve_semester

REQUIRED_HEADERS = ['code', 'title', 'credits', 'department', 'semester', 'course_type']


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

    created = updated = skipped = duplicates = errors = 0
    seen_in_file = set()

    for row_number, row in enumerate(rows, start=2):  # header is row 1
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
            record_import_error(CourseImportError, job, row_number, row, 'Missing code or title.')
            errors += 1
            continue

        dedup_key = f'{code}|{semester_name}'
        if dedup_key in seen_in_file:
            record_import_error(CourseImportError, job, row_number, row, f'Duplicate code "{code}" within this file.')
            duplicates += 1
            continue
        seen_in_file.add(dedup_key)

        if not credits_raw.isdigit():
            record_import_error(CourseImportError, job, row_number, row, 'Missing or invalid credits.')
            errors += 1
            continue
        credits = int(credits_raw)

        department = resolve_department(department_name)
        if not department:
            record_import_error(CourseImportError, job, row_number, row, f'Unknown department "{department_name}".')
            errors += 1
            continue

        semester = resolve_semester(semester_name)
        if not semester:
            record_import_error(CourseImportError, job, row_number, row, f'Unknown semester "{semester_name}".')
            errors += 1
            continue

        if course_type not in ('core', 'elective', 'lab'):
            record_import_error(CourseImportError, job, row_number, row,
                                 f'Invalid course_type "{course_type}" (expected core/elective/lab).')
            errors += 1
            continue

        max_capacity = int(max_capacity_raw) if max_capacity_raw.isdigit() else None

        existing = Course.query.filter_by(
            code=code, academic_session_id=academic_session_id, semester_id=semester.id,
        ).first()
        if existing:
            changed = (
                existing.title != title or existing.credits != credits or existing.department_id != department.id
                or existing.level != (level or None) or existing.course_type != course_type
                or existing.description != (description or None) or existing.instructor != (instructor or None)
                or existing.schedule != (schedule or None) or existing.max_capacity != max_capacity
            )
            if changed:
                existing.title = title
                existing.credits = credits
                existing.department_id = department.id
                existing.department = department.name
                existing.level = level or None
                existing.course_type = course_type
                existing.description = description or None
                existing.instructor = instructor or None
                existing.schedule = schedule or None
                existing.max_capacity = max_capacity
                updated += 1
            else:
                skipped += 1
            continue

        db.session.add(Course(
            code=code, title=title, credits=credits, department=department.name, department_id=department.id,
            level=level or None, course_type=course_type, academic_session_id=academic_session_id,
            semester_id=semester.id, description=description or None, instructor=instructor or None,
            schedule=schedule or None, max_capacity=max_capacity, status='active',
        ))
        created += 1

    db.session.commit()
    finalize_import_job(job, created, updated, skipped, duplicates, errors)
    return job
