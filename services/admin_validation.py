from models import Department, Programme, Course, Semester


def is_department_code_unique(code, exclude_id=None):
    query = Department.query.filter(Department.code == code)
    if exclude_id is not None:
        query = query.filter(Department.id != exclude_id)
    return query.first() is None


def is_course_code_unique(code, academic_session_id, semester_id, exclude_id=None):
    query = Course.query.filter(
        Course.code == code,
        Course.academic_session_id == academic_session_id,
        Course.semester_id == semester_id,
    )
    if exclude_id is not None:
        query = query.filter(Course.id != exclude_id)
    return query.first() is None


def resolve_department(name_or_code):
    """Look up a Department by exact name or code match (case-insensitive).
    Returns None if nothing matches — callers decide whether that's an error."""
    if not name_or_code:
        return None
    value = name_or_code.strip()
    return Department.query.filter(
        (Department.name.ilike(value)) | (Department.code.ilike(value))
    ).first()


def resolve_programme(name_or_code):
    if not name_or_code:
        return None
    value = name_or_code.strip()
    return Programme.query.filter(
        (Programme.name.ilike(value)) | (Programme.code.ilike(value))
    ).first()


def resolve_semester(name):
    if not name:
        return None
    return Semester.query.filter(Semester.name.ilike(name.strip())).first()


def validate_credit_range(min_credits, max_credits):
    """Returns a list of human-readable error strings; empty list means valid."""
    errors = []
    if min_credits is None or max_credits is None:
        errors.append('Minimum and maximum credits are required.')
        return errors
    if min_credits < 0:
        errors.append('Minimum credits cannot be negative.')
    if max_credits < 0:
        errors.append('Maximum credits cannot be negative.')
    if min_credits > max_credits:
        errors.append('Minimum credits cannot exceed maximum credits.')
    return errors
