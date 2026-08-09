from models import db, AcademicSession, PaymentCategory, FeeStructure
from services.registration import get_active_period


def get_current_session(user=None):
    """AcademicSession-level analog of get_active_period(): returns the
    is_current=True session in user's Programme's scope group, falling
    back to the shared/legacy is_current session if the user has no
    programme_id or their Programme has no current session of its own.
    user=None (or a user whose scope group and the legacy group both lack
    a current session) returns the shared/legacy current session, or None
    if even that doesn't exist."""
    if user is not None and user.programme_id is not None:
        programme_session = AcademicSession.query.filter(
            AcademicSession.is_current == True,
            AcademicSession.programme_id == user.programme_id,
        ).order_by(AcademicSession.id.desc()).first()
        if programme_session is not None:
            return programme_session

    return AcademicSession.query.filter(
        AcademicSession.is_current == True,
        AcademicSession.programme_id.is_(None),
    ).order_by(AcademicSession.id.desc()).first()


def resolve_fee_context(user):
    """Returns (session, semester_id). session is always
    get_current_session(user) — independent of whether a registration
    period is currently open, since general fee payment isn't gated on
    registration. semester_id comes from get_active_period(user) only
    when that period's academic_session_id matches the resolved session
    (so a period active in a DIFFERENT scope group's session never leaks
    its semester into this one); otherwise None (session-wide)."""
    session = get_current_session(user)
    semester_id = None
    if session is not None:
        period = get_active_period(user)
        if period is not None and period.academic_session_id == session.id:
            semester_id = period.semester_id
    return session, semester_id


def resolve_amount(user, category):
    """Returns the Decimal amount to charge `user` for `category`: the
    most specific matching FeeStructure row, tried in order
    (session, semester, dept) -> (session, semester, NULL) ->
    (session, NULL, dept) -> (session, NULL, NULL), falling back to
    category.default_amount when no row matches (or the user has no
    resolvable current session at all). A user with no department_id can
    only match NULL-department rows — never silently charged a
    department-specific amount without a resolved department."""
    session, semester_id = resolve_fee_context(user)
    if session is not None:
        department_id = user.department_id
        candidates = [(semester_id, department_id), (semester_id, None)]
        if department_id is not None:
            candidates.append((None, department_id))
        candidates.append((None, None))
        seen = set()
        for sem, dept in candidates:
            key = (sem, dept)
            if key in seen:
                continue
            seen.add(key)
            row = FeeStructure.query.filter_by(
                academic_session_id=session.id, semester_id=sem,
                department_id=dept, category_id=category.id,
            ).first()
            if row is not None:
                return row.amount
    return category.default_amount


def get_payable_categories(user):
    """Returns [(category, amount), ...] for every active PaymentCategory
    with a resolvable, non-None amount for this user — powers
    /payment/create. A category with neither a default_amount nor a
    matching FeeStructure row (e.g. registration_fee, handled by
    DepartmentRegistrationRule instead) is excluded, exactly matching the
    pre-existing `if category.default_amount is not None` filter.

    registration_fee is additionally excluded unconditionally, even if a
    FeeStructure row targeting it exists (the admin UI no longer allows
    creating one, but this is a defensive backstop for any pre-existing
    stray row or direct DB access). registration_fee is charged and
    reconciled exclusively through register_student()/
    DepartmentRegistrationRule (which links payment_status back to a
    specific StudentRegistration via registration_id) — the general
    /payment/create flow never sets registration_id, so a payment made
    through it would charge real money without ever being able to mark a
    registration as paid."""
    result = []
    categories = PaymentCategory.query.filter_by(is_active=True).filter(
        PaymentCategory.code != 'registration_fee'
    ).order_by(PaymentCategory.name).all()
    for category in categories:
        amount = resolve_amount(user, category)
        if amount is not None:
            result.append((category, amount))
    return result
