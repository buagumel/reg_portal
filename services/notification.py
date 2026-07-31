from datetime import timedelta

from models import db, now_lagos, Notification


def create_notification(user, title, message, category, priority='medium', related_url=None):
    """The single creation path — every other module that needs to notify a
    student calls this, never constructs a Notification row directly."""
    notification = Notification(
        user_id=user.id,
        title=title,
        message=message,
        category=category,
        priority=priority,
        related_url=related_url,
    )
    db.session.add(notification)
    db.session.commit()
    return notification


def get_notifications(user, category=None, priority=None, read_status=None,
                       date_from=None, date_to=None, search=None, archived=False):
    """Non-deleted notifications, newest first, with optional filters.
    archived=False (default) returns the main inbox (archived_at IS NULL);
    archived=True returns only archived rows (archived_at IS NOT NULL)."""
    query = Notification.query.filter_by(user_id=user.id, deleted_at=None)

    if archived:
        query = query.filter(Notification.archived_at.isnot(None))
    else:
        query = query.filter(Notification.archived_at.is_(None))

    if category:
        query = query.filter_by(category=category)
    if priority:
        query = query.filter_by(priority=priority)
    if read_status == 'unread':
        query = query.filter(Notification.read_at.is_(None))
    elif read_status == 'read':
        query = query.filter(Notification.read_at.isnot(None))
    if date_from:
        query = query.filter(Notification.created_at >= date_from)
    if date_to:
        query = query.filter(Notification.created_at <= date_to)
    if search:
        like = f'%{search}%'
        query = query.filter(db.or_(Notification.title.ilike(like), Notification.message.ilike(like)))

    return query.order_by(Notification.created_at.desc()).all()


def get_summary_counts(user):
    """Return {'total', 'unread', 'read', 'archived'}. total/unread/read are
    computed over non-deleted, non-archived rows; archived is its own bucket."""
    base = Notification.query.filter_by(user_id=user.id, deleted_at=None)
    total = base.filter(Notification.archived_at.is_(None)).count()
    unread = base.filter(Notification.archived_at.is_(None), Notification.read_at.is_(None)).count()
    read = total - unread
    archived = base.filter(Notification.archived_at.isnot(None)).count()
    return {'total': total, 'unread': unread, 'read': read, 'archived': archived}


def _get_owned(user, notification_id):
    return Notification.query.filter_by(id=notification_id, user_id=user.id, deleted_at=None).first()


def mark_read(user, notification_id):
    notification = _get_owned(user, notification_id)
    if notification is None:
        return None
    if notification.read_at is None:
        notification.read_at = now_lagos()
        db.session.commit()
    return notification


def mark_unread(user, notification_id):
    notification = _get_owned(user, notification_id)
    if notification is None:
        return None
    notification.read_at = None
    db.session.commit()
    return notification


def mark_all_read(user):
    now = now_lagos()
    Notification.query.filter_by(user_id=user.id, deleted_at=None, read_at=None).update({'read_at': now})
    db.session.commit()


def archive_notification(user, notification_id):
    notification = _get_owned(user, notification_id)
    if notification is None:
        return None
    notification.archived_at = now_lagos()
    db.session.commit()
    return notification


def delete_notification(user, notification_id):
    notification = _get_owned(user, notification_id)
    if notification is None:
        return None
    notification.deleted_at = now_lagos()
    db.session.commit()
    return notification


def notify_registration_window_events(user):
    """Opportunistic, idempotent per (user, period, trigger) — called once
    per dashboard/registration page load. No task scheduler exists in this
    codebase, so this is checked on-demand instead of via a background job.
    Uses a fixed related_url per (period, trigger) as the dedupe key, since
    it's a real navigable URL anyway and needs no separate tracking table."""
    from services.registration import get_active_period, get_window_status

    period = get_active_period()
    if period is None:
        return

    status = get_window_status(period)
    now = now_lagos()

    def already_notified(marker_url):
        return Notification.query.filter_by(user_id=user.id, related_url=marker_url).first() is not None

    if status == 'open':
        marker = f'/registration?opened={period.id}'
        if not already_notified(marker):
            create_notification(
                user, 'Registration is open',
                f'Registration for {period.academic_session.name} {period.semester.name} is now open.',
                category='registration', priority='high', related_url=marker,
            )
        if (period.closes_at - now) <= timedelta(days=3):
            closing_marker = f'/registration?closing={period.id}'
            if not already_notified(closing_marker):
                create_notification(
                    user, 'Registration closes soon',
                    f'Registration for {period.academic_session.name} {period.semester.name} closes on {period.closes_at.strftime("%d %b %Y")}.',
                    category='registration', priority='high', related_url=closing_marker,
                )
