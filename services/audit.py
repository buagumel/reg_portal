from models import db, AuditLog


def log_action(user, action, details=None, ip_address=None):
    """Insert one AuditLog row. `details` must never contain a password or OTP code."""
    entry = AuditLog(
        user_id=user.id,
        action=action,
        details=details,
        ip_address=ip_address,
    )
    db.session.add(entry)
    db.session.commit()
    return entry
