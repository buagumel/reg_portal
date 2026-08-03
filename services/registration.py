from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from models import db, now_lagos, RegistrationPeriod, DepartmentRegistrationRule, StudentRegistration, PaymentCategory
from models import Course, RegisteredCourse
from services.payment import create_payment
from services.errors import RegistrationError, PaymentError
from services.notification import create_notification
from services.validation import validate_course_eligible, validate_credit_ceiling, validate_not_duplicate, validate_can_submit


def get_active_period():
    """Return the RegistrationPeriod the admin has marked as current, or None
    if none is configured. If more than one is ever marked active (shouldn't
    happen, but nothing enforces it at the DB level), the most recently
    created one wins."""
    return (
        RegistrationPeriod.query
        .filter_by(is_active=True)
        .order_by(RegistrationPeriod.id.desc())
        .first()
    )


def get_window_status(period, student_registration=None):
    """Return 'not_yet_open', 'open', or 'closed' for the given period,
    based on now_lagos() vs. period.opens_at / period.closes_at. If
    student_registration has a deadline_override set (Registration
    Oversight's per-student deadline extension), that value replaces
    period.closes_at for this one student only — every other student
    keeps using the period's own closes_at unchanged. student_registration
    defaults to None so every pre-Phase-3 call site keeps working exactly
    as before."""
    now = now_lagos()
    effective_closes_at = period.closes_at
    if student_registration is not None and student_registration.deadline_override is not None:
        effective_closes_at = student_registration.deadline_override
    if now < period.opens_at:
        return 'not_yet_open'
    if now > effective_closes_at:
        return 'closed'
    return 'open'


def get_add_drop_window_status(period, student_registration=None):
    """Same three-value contract as get_window_status, but checks the
    period's add_drop_opens_at/add_drop_closes_at when both are set —
    falls back to get_window_status (main window, including its own
    deadline_override handling) when either is unset. A per-student
    deadline_override does NOT affect an explicitly-configured add/drop
    window — those are two independent override mechanisms; only the
    fallback path inherits the extension."""
    if period.add_drop_opens_at is None or period.add_drop_closes_at is None:
        return get_window_status(period, student_registration)

    now = now_lagos()
    if now < period.add_drop_opens_at:
        return 'not_yet_open'
    if now > period.add_drop_closes_at:
        return 'closed'
    return 'open'


def get_credit_limits(period, department):
    """Return (min_credits, max_credits, registration_fee) for a department,
    applying any DepartmentRegistrationRule override field-by-field over the
    period's defaults."""
    min_credits = period.min_credits
    max_credits = period.max_credits
    registration_fee = period.registration_fee

    rule = DepartmentRegistrationRule.query.filter_by(
        registration_period_id=period.id, department=department
    ).first()
    if rule:
        if rule.min_credits is not None:
            min_credits = rule.min_credits
        if rule.max_credits is not None:
            max_credits = rule.max_credits
        if rule.registration_fee is not None:
            registration_fee = rule.registration_fee

    return min_credits, max_credits, registration_fee


def get_registration_status_context(user):
    """Assemble everything the registration page needs for the current
    student: the active period (or None), its window status, the student's
    resolved credit limits/fee, and their existing StudentRegistration for
    that period (or None)."""
    period = get_active_period()
    if period is None:
        return {
            'period': None,
            'window_status': None,
            'min_credits': None,
            'max_credits': None,
            'registration_fee': None,
            'existing_registration': None,
        }

    min_credits, max_credits, registration_fee = get_credit_limits(period, user.department)
    existing_registration = StudentRegistration.query.filter_by(
        user_id=user.id, registration_period_id=period.id
    ).first()

    return {
        'period': period,
        'window_status': get_window_status(period),
        'min_credits': min_credits,
        'max_credits': max_credits,
        'registration_fee': registration_fee,
        'existing_registration': existing_registration,
    }


def register_student(user, period):
    """Validate and create a StudentRegistration for the given period, with
    payment left pending — the caller redirects to the payment summary page,
    where the student clicks Pay Now to actually initiate payment through
    the real gateway."""
    if get_window_status(period) != 'open':
        raise RegistrationError('Registration is not currently open for this period.')

    existing = StudentRegistration.query.filter_by(
        user_id=user.id, registration_period_id=period.id
    ).first()
    if existing:
        raise RegistrationError('You are already registered for this period.')

    registration = StudentRegistration(
        user_id=user.id,
        registration_period_id=period.id,
        status='registered',
        payment_status='pending',
        credits_registered=0,
    )
    try:
        db.session.add(registration)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise RegistrationError('You are already registered for this period.')

    _, _, registration_fee = get_credit_limits(period, user.department)
    category = PaymentCategory.query.filter_by(code='registration_fee').first()
    if category is not None:
        try:
            payment = create_payment(
                user, [(category, 1, registration_fee)],
                idempotency_key=f'registration-{registration.id}',
                registration_id=registration.id,
            )
            registration.payment_reference = payment.reference
            db.session.commit()
        except PaymentError as e:
            from flask import current_app
            current_app.logger.warning(
                'Registration %s created without a payable Payment (create_payment raised: %s)',
                registration.id, e,
            )

    create_notification(
        user, 'Registration created - payment required',
        f'Your registration for {period.academic_session.name} {period.semester.name} has been created. Complete payment to activate it.',
        category='registration', priority='high', related_url='/registration',
    )
    return registration


def get_registration_history(user):
    """Return all of the student's StudentRegistration records, newest first."""
    return (
        StudentRegistration.query
        .options(
            joinedload(StudentRegistration.registration_period).joinedload(RegistrationPeriod.academic_session),
            joinedload(StudentRegistration.registration_period).joinedload(RegistrationPeriod.semester),
        )
        .filter_by(user_id=user.id)
        .order_by(StudentRegistration.registered_at.desc())
        .all()
    )


def _recompute_credits(student_registration):
    """Recompute and store credits_registered from the current
    RegisteredCourse rows — always re-queried (not read from an in-memory
    relationship collection) so it's correct regardless of add/drop order."""
    total = (
        db.session.query(db.func.coalesce(db.func.sum(Course.credits), 0))
        .join(RegisteredCourse, RegisteredCourse.course_id == Course.id)
        .filter(RegisteredCourse.student_registration_id == student_registration.id)
        .scalar()
    )
    student_registration.credits_registered = total


def get_course_enrollment_count(course_id):
    """Current number of students registered for this course (this exact
    Course row, already scoped to one session/semester by its own unique
    constraint)."""
    return RegisteredCourse.query.filter_by(course_id=course_id).count()


def add_course(user, period, student_registration, course_id, admin_override=False):
    """Validate and add a course to the student's registration. Raises
    RegistrationError on any business-rule violation. admin_override=True
    (only ever passed by the admin Registration Oversight action) bypasses
    the capacity check — every other check still applies."""
    course = Course.query.get(course_id)
    if course is None:
        raise RegistrationError('Course not found.')

    if student_registration.is_locked:
        raise RegistrationError('This registration is locked by an administrator.')

    if student_registration.courses_submitted:
        raise RegistrationError('Course selection has already been submitted.')

    if get_add_drop_window_status(period, student_registration) != 'open':
        raise RegistrationError('Add/Drop is not currently open.')

    validate_course_eligible(course, user, period)
    validate_not_duplicate(student_registration, course)

    _, max_credits, _ = get_credit_limits(period, user.department)
    validate_credit_ceiling(student_registration.credits_registered, course.credits, max_credits)

    if not admin_override and course.max_capacity is not None:
        current_enrollment = get_course_enrollment_count(course.id)
        if current_enrollment >= course.max_capacity:
            raise RegistrationError(f'{course.code} is at full capacity ({course.max_capacity}).')

    registered_course = RegisteredCourse(
        student_registration_id=student_registration.id,
        course_id=course.id,
    )
    db.session.add(registered_course)

    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise RegistrationError('You have already added this course.')

    _recompute_credits(student_registration)
    db.session.commit()
    return student_registration


def drop_course(user, period, student_registration, course_id):
    """Remove a course from the student's registration. Raises
    RegistrationError if not found, already submitted, locked, or the
    registration window is no longer open."""
    if student_registration.is_locked:
        raise RegistrationError('This registration is locked by an administrator.')

    if student_registration.courses_submitted:
        raise RegistrationError('Course selection has already been submitted.')

    if get_add_drop_window_status(period, student_registration) != 'open':
        raise RegistrationError('Add/Drop is not currently open.')

    registered_course = RegisteredCourse.query.filter_by(
        student_registration_id=student_registration.id, course_id=course_id
    ).first()
    if registered_course is None:
        raise RegistrationError('Course not found in your registration.')

    db.session.delete(registered_course)
    db.session.flush()
    _recompute_credits(student_registration)
    db.session.commit()
    return student_registration


def submit_registration(user, period, student_registration):
    """Validate and finalize the student's course selection. Raises
    RegistrationError on any business-rule violation."""
    if student_registration.is_locked:
        raise RegistrationError('This registration is locked by an administrator.')

    window_status = get_window_status(period, student_registration)
    min_credits, max_credits, _ = get_credit_limits(period, user.department)
    validate_can_submit(student_registration, window_status, min_credits, max_credits)

    student_registration.courses_submitted = True
    db.session.commit()

    create_notification(
        user, 'Course registration submitted',
        f'Your course selection for {period.academic_session.name} {period.semester.name} has been submitted successfully.',
        category='courses', priority='high', related_url='/my_courses',
    )
    return student_registration


def get_add_drop_context(user):
    """Assemble everything the Add/Drop page needs. period/student_registration
    are None if there's nothing eligible to add courses against."""
    period = get_active_period()
    if period is None:
        return {'period': None, 'student_registration': None, 'min_credits': None, 'max_credits': None}

    student_registration = StudentRegistration.query.filter_by(
        user_id=user.id, registration_period_id=period.id
    ).first()
    if student_registration is None:
        return {'period': period, 'student_registration': None, 'min_credits': None, 'max_credits': None}

    min_credits, max_credits, _ = get_credit_limits(period, user.department)
    return {
        'period': period,
        'student_registration': student_registration,
        'min_credits': min_credits,
        'max_credits': max_credits,
    }
