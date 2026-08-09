from sqlalchemy.orm import joinedload

from models import db, User, StudentRegistration, RegistrationPeriod, now_lagos
from services.registration import get_active_period, add_course, drop_course


def list_periods_for_selector():
    return (
        RegistrationPeriod.query
        .options(joinedload(RegistrationPeriod.academic_session), joinedload(RegistrationPeriod.semester))
        .order_by(RegistrationPeriod.id.desc())
        .all()
    )


def get_oversight_metrics(period, department_id=None, programme_id=None, level=None, status=None):
    """Registration Dashboard metrics for one RegistrationPeriod, optionally
    narrowed by student filters. 'Eligible' is defined as every active
    student matching the given filters — this codebase has no separate
    per-period eligibility concept beyond account_status; department/level
    credit-limit overrides already exist via DepartmentRegistrationRule but
    don't gate who CAN register, only how much they can take."""
    student_query = User.query.filter_by(account_status='active')
    if department_id:
        student_query = student_query.filter(User.department_id == department_id)
    if programme_id:
        student_query = student_query.filter(User.programme_id == programme_id)
    if level:
        student_query = student_query.filter(User.level == level)
    eligible_ids = [u.id for u in student_query.with_entities(User.id).all()]
    total_eligible = len(eligible_ids)

    reg_query = StudentRegistration.query.filter_by(registration_period_id=period.id)
    reg_query = reg_query.filter(StudentRegistration.user_id.in_(eligible_ids)) if eligible_ids else reg_query.filter(db.false())
    if status:
        reg_query = reg_query.filter(StudentRegistration.status == status)
    registrations = reg_query.all()

    registered_count = len(registrations)
    pending_count = sum(1 for r in registrations if r.payment_status != 'paid')
    incomplete_count = sum(1 for r in registrations if r.payment_status == 'paid' and not r.courses_submitted)
    completed_count = sum(1 for r in registrations if r.courses_submitted)
    total_credits = sum(r.credits_registered for r in registrations)
    completion_percentage = round((completed_count / total_eligible) * 100, 1) if total_eligible else 0.0

    now = now_lagos()
    seconds_remaining = max(0, (period.closes_at - now).total_seconds())

    return {
        'total_eligible': total_eligible,
        'registered_count': registered_count,
        'pending_count': pending_count,
        'incomplete_count': incomplete_count,
        'completed_count': completed_count,
        'completion_percentage': completion_percentage,
        'total_credits': total_credits,
        'closes_at_iso': period.closes_at.isoformat(),
        'seconds_remaining': seconds_remaining,
    }


def get_student_registration_context(user, period=None):
    """period defaults to this student's Programme-aware active
    RegistrationPeriod (see services.registration.get_active_period).
    Returns {'period', 'student_registration'} — student_registration is
    None if this student has no registration for that period yet."""
    if period is None:
        period = get_active_period(user)
    if period is None:
        return {'period': None, 'student_registration': None}
    student_registration = StudentRegistration.query.filter_by(
        user_id=user.id, registration_period_id=period.id
    ).first()
    return {'period': period, 'student_registration': student_registration}


def record_override(student_registration, admin_user, action, reason):
    from models import RegistrationOverride

    if not reason or not reason.strip():
        raise ValueError('A reason is required for every registration override.')
    override = RegistrationOverride(
        student_registration_id=student_registration.id, admin_user_id=admin_user.id,
        action=action, reason=reason.strip(),
    )
    db.session.add(override)
    db.session.commit()
    return override


def admin_add_course(user, period, student_registration, course_id, admin_user, reason, override_capacity=False):
    add_course(user, period, student_registration, course_id, admin_override=override_capacity)
    action = 'capacity_overridden' if override_capacity else 'course_added_by_admin'
    record_override(student_registration, admin_user, action, reason)


def admin_drop_course(user, period, student_registration, course_id, admin_user, reason):
    drop_course(user, period, student_registration, course_id)
    record_override(student_registration, admin_user, 'course_removed_by_admin', reason)


def set_registration_lock(student_registration, admin_user, locked, reason):
    student_registration.is_locked = locked
    db.session.commit()
    record_override(student_registration, admin_user, 'locked' if locked else 'unlocked', reason)


def extend_deadline(student_registration, admin_user, new_deadline, reason):
    student_registration.deadline_override = new_deadline
    db.session.commit()
    record_override(student_registration, admin_user, 'deadline_extended', reason)


def reopen_registration(student_registration, admin_user, reason):
    student_registration.courses_submitted = False
    db.session.commit()
    record_override(student_registration, admin_user, 'reopened', reason)


def approve_exception(student_registration, admin_user, reason):
    record_override(student_registration, admin_user, 'exception_approved', reason)
