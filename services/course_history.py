from models import RegisteredCourse, StudentRegistration
from services.registration import get_active_period


def get_courses_by_semester(user):
    """Return the student's RegisteredCourse rows grouped by
    (academic_session, semester), newest registration first. Each group:
    {academic_session, semester, is_current, courses_submitted, courses}."""
    active_period = get_active_period()

    registrations = (
        StudentRegistration.query
        .filter_by(user_id=user.id)
        .order_by(StudentRegistration.registered_at.desc())
        .all()
    )

    groups = []
    for reg in registrations:
        courses = (
            RegisteredCourse.query
            .filter_by(student_registration_id=reg.id)
            .order_by(RegisteredCourse.added_at)
            .all()
        )
        if not courses:
            continue
        groups.append({
            'academic_session': reg.registration_period.academic_session.name,
            'semester': reg.registration_period.semester.name,
            'is_current': active_period is not None and reg.registration_period_id == active_period.id,
            'courses_submitted': reg.courses_submitted,
            'courses': courses,
        })
    return groups
