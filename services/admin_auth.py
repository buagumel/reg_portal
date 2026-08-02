from models import db, now_lagos, AdminUser
from services.admin_audit import log_admin_action


def authenticate_admin(email, password, ip_address=None):
    """Returns the AdminUser on a successful login, or None. Logs the
    attempt either way (a failed attempt against an unknown email logs
    with admin_user=None)."""
    admin = AdminUser.query.filter_by(email=email).first()

    if admin and admin.is_active and admin.check_password(password):
        admin.last_login_at = now_lagos()
        admin.last_login_ip = ip_address
        db.session.commit()
        log_admin_action(admin, 'login', ip_address=ip_address)
        return admin

    log_admin_action(admin, 'login_failed', details=f'attempted email: {email}', ip_address=ip_address)
    return None


def change_admin_password(admin, new_password):
    admin.set_password(new_password)
    admin.first_login = False
    db.session.commit()
