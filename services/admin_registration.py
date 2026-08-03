from sqlalchemy.orm import joinedload

from models import db, User, StudentRegistration, RegistrationPeriod, now_lagos


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
