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


def get_onboarding_timeline(user):
    """Assembled from data that already exists — not a stored timeline.
    created_at/last_login_at/onboarding_completed_at plus this student's
    own AuditLog rows (profile/password changes, already logged since the
    Profile Management milestone)."""
    from models import AuditLog

    events = []
    if user.created_at:
        events.append({'label': 'Account created', 'timestamp': user.created_at})
    if user.last_login_at:
        events.append({'label': 'Most recent login', 'timestamp': user.last_login_at})
    if user.onboarding_completed_at:
        events.append({'label': 'Onboarding completed', 'timestamp': user.onboarding_completed_at})

    for log in AuditLog.query.filter_by(user_id=user.id).order_by(AuditLog.created_at.desc()).limit(10).all():
        events.append({'label': log.action.replace('_', ' ').title(), 'timestamp': log.created_at})

    events.sort(key=lambda e: e['timestamp'], reverse=True)
    return events


def reset_onboarding(user):
    user.onboarding_completed = False
    db.session.commit()


def manually_verify_email(user):
    user.email_verified = True
    db.session.commit()


def mark_onboarding_complete(user):
    from models import now_lagos

    user.onboarding_completed = True
    user.onboarding_completed_at = now_lagos()
    db.session.commit()
