from models import RegisteredCourse
from services.errors import RegistrationError


def validate_course_eligible(course, user, period):
    """Raise RegistrationError unless the course matches the student's own
    department/level and belongs to the active registration period's
    session/semester. A course with level=None is level-agnostic and
    matches any student's level."""
    if course.department != user.department:
        raise RegistrationError('This course is not offered in your department.')
    if course.level is not None and course.level != user.level:
        raise RegistrationError('This course is not offered at your level.')
    if course.academic_session_id != period.academic_session_id or course.semester_id != period.semester_id:
        raise RegistrationError('This course is not offered this semester.')


def validate_credit_ceiling(current_credits, course_credits, max_credits):
    """Raise RegistrationError if adding course_credits would exceed max_credits."""
    if current_credits + course_credits > max_credits:
        raise RegistrationError(f'Adding this course would exceed the maximum of {max_credits} credits.')


def validate_not_duplicate(student_registration, course):
    """Raise RegistrationError if the course is already registered."""
    existing = RegisteredCourse.query.filter_by(
        student_registration_id=student_registration.id, course_id=course.id
    ).first()
    if existing:
        raise RegistrationError('You have already added this course.')


def validate_can_submit(student_registration, window_status, min_credits, max_credits):
    """Raise RegistrationError unless the registration is ready to be
    finalized. Duplicate courses are not re-checked here — the DB unique
    constraint plus validate_not_duplicate at add-time make duplicates
    structurally impossible by the time submission happens."""
    if window_status != 'open':
        raise RegistrationError('Registration is not currently open.')
    if student_registration.payment_status != 'paid':
        raise RegistrationError('Payment must be completed before submitting course selection.')
    if student_registration.courses_submitted:
        raise RegistrationError('Course selection has already been submitted.')
    if student_registration.credits_registered < min_credits:
        raise RegistrationError(f'You must register at least {min_credits} credits before submitting.')
    if student_registration.credits_registered > max_credits:
        raise RegistrationError(f'You cannot exceed {max_credits} credits.')
