from models import db, User, Department


def get_onboarding_summary(department_id=None, programme_id=None, session=None):
    """Five independent, non-exclusive bucket counts — a student can appear
    in more than one (e.g. never logged in AND email not verified)."""
    query = User.query
    if department_id:
        query = query.filter(User.department_id == department_id)
    if programme_id:
        query = query.filter(User.programme_id == programme_id)
    if session:
        query = query.filter(User.session == session)

    total = query.count()
    not_logged_in = query.filter(User.last_login_at.is_(None)).count()
    password_not_changed = query.filter(User.first_login.is_(True)).count()
    profile_incomplete = query.filter(User.onboarding_completed.is_(False)).count()
    email_not_verified = query.filter(User.email_verified.is_(False)).count()
    onboarding_completed = query.filter(User.onboarding_completed.is_(True)).count()
    completion_percentage = round((onboarding_completed / total) * 100, 1) if total else 0.0

    return {
        'total': total, 'not_logged_in': not_logged_in, 'password_not_changed': password_not_changed,
        'profile_incomplete': profile_incomplete, 'email_not_verified': email_not_verified,
        'onboarding_completed': onboarding_completed, 'completion_percentage': completion_percentage,
    }


def get_onboarding_analytics():
    """Average Completion Time uses only rows where both created_at and
    onboarding_completed_at are set — rows onboarded before this phase
    shipped have onboarding_completed_at=NULL and are excluded rather than
    guessed at."""
    completed_users = User.query.filter(
        User.onboarding_completed.is_(True), User.onboarding_completed_at.isnot(None), User.created_at.isnot(None),
    ).all()
    if completed_users:
        total_seconds = sum((u.onboarding_completed_at - u.created_at).total_seconds() for u in completed_users)
        avg_hours = round((total_seconds / len(completed_users)) / 3600, 1)
    else:
        avg_hours = None

    by_department = (
        db.session.query(Department.name, db.func.count(User.id))
        .join(User, User.department_id == Department.id)
        .filter(User.onboarding_completed.is_(True))
        .group_by(Department.name)
        .all()
    )
    by_session = (
        db.session.query(User.session, db.func.count(User.id))
        .filter(User.onboarding_completed.is_(True), User.session.isnot(None))
        .group_by(User.session)
        .all()
    )

    return {
        'average_completion_hours': avg_hours,
        'completion_by_department': [{'department': name, 'count': count} for name, count in by_department],
        'completion_by_session': [{'session': session_name, 'count': count} for session_name, count in by_session],
    }
