from models import db, AdminAuditLog


def log_admin_action(admin_user, action, target_type=None, target_id=None, details=None, ip_address=None):
    """Insert one AdminAuditLog row. admin_user may be None (a failed login
    attempt against an email with no matching account). `details` must
    never contain a password or OTP code."""
    entry = AdminAuditLog(
        admin_user_id=admin_user.id if admin_user else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
        ip_address=ip_address,
    )
    db.session.add(entry)
    db.session.commit()
    return entry
