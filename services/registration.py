import random
import string

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from models import db, now_lagos, RegistrationPeriod, DepartmentRegistrationRule, StudentRegistration
from services.errors import RegistrationError


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


def get_window_status(period):
    """Return 'not_yet_open', 'open', or 'closed' for the given period,
    based on now_lagos() vs. period.opens_at / period.closes_at."""
    now = now_lagos()
    if now < period.opens_at:
        return 'not_yet_open'
    if now > period.closes_at:
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


def _generate_payment_reference():
    # TODO: replace with the real Remita payment reference once the Remita
    # integration is built (initiate payment -> webhook/callback verifies
    # the transaction -> only then create/confirm this record).
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
    return f'SIMULATED-{suffix}'


def register_student(user, period):
    """Validate and create a StudentRegistration for the given period, with
    payment simulated as immediately successful. Raises RegistrationError on
    any business-rule violation."""
    if get_window_status(period) != 'open':
        raise RegistrationError('Registration is not currently open for this period.')

    existing = StudentRegistration.query.filter_by(
        user_id=user.id, registration_period_id=period.id
    ).first()
    if existing:
        raise RegistrationError('You are already registered for this period.')

    # TODO: this is where real Remita payment initiation would happen instead
    # of immediately marking payment_status='paid'. For now the full workflow
    # (record creation + "successful payment") is simulated so downstream
    # features (Add/Drop, payment history) can be built against a real record.
    registration = StudentRegistration(
        user_id=user.id,
        registration_period_id=period.id,
        status='registered',
        payment_status='paid',
        payment_reference=_generate_payment_reference(),
        credits_registered=0,
    )
    try:
        db.session.add(registration)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise RegistrationError('You are already registered for this period.')
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
