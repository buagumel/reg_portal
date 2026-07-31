from models import db, Course


def get_available_courses(user, period, student_registration, search=None, course_type=None):
    """Return Course rows the student can still add: matching their
    department, matching their level (or level-agnostic), belonging to the
    active period's session/semester, and not already registered."""
    query = Course.query.filter(
        Course.department == user.department,
        Course.academic_session_id == period.academic_session_id,
        Course.semester_id == period.semester_id,
    )
    query = query.filter(db.or_(Course.level == user.level, Course.level.is_(None)))

    if student_registration is not None:
        registered_ids = [rc.course_id for rc in student_registration.registered_courses]
        if registered_ids:
            query = query.filter(~Course.id.in_(registered_ids))

    if search:
        like = f'%{search}%'
        query = query.filter(db.or_(Course.code.ilike(like), Course.title.ilike(like)))

    if course_type and course_type != 'all':
        query = query.filter(Course.course_type == course_type)

    return query.order_by(Course.code).all()


def get_course_details(course_id):
    return Course.query.get(course_id)
