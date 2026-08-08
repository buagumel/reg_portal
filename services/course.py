from models import db, CourseOffering


def get_available_courses(user, period, student_registration, search=None, course_type=None):
    """Return CourseOffering rows the student can still add: matching their
    department, matching their level (or level-agnostic), belonging to the
    active period's session/semester, and not already registered."""
    query = CourseOffering.query.filter(
        CourseOffering.department == user.department,
        CourseOffering.academic_session_id == period.academic_session_id,
        CourseOffering.semester_id == period.semester_id,
    )
    query = query.filter(db.or_(CourseOffering.level == user.level, CourseOffering.level.is_(None)))

    if student_registration is not None:
        registered_ids = [rc.course_id for rc in student_registration.registered_courses]
        if registered_ids:
            query = query.filter(~CourseOffering.id.in_(registered_ids))

    if search:
        like = f'%{search}%'
        query = query.filter(db.or_(CourseOffering.code.ilike(like), CourseOffering.title.ilike(like)))

    if course_type and course_type != 'all':
        query = query.filter(CourseOffering.course_type == course_type)

    return query.order_by(CourseOffering.code).all()


def get_course_details(course_id):
    return CourseOffering.query.get(course_id)
