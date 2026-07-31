import os

from models import db
from auth_helpers import validate_password_strength
from onboarding_helpers import save_profile_picture
from services.audit import log_action
from services.notification import create_notification


def update_contact_info(user, phone=None, address=None, emergency_contact=None, blood_group=None):
    """Update whichever fields are passed. None means 'not being changed' —
    callers that want to clear a field must pass an explicit empty string,
    not omit the argument."""
    changes = []
    if phone is not None:
        user.phone = phone
        changes.append('phone')
    if address is not None:
        user.address = address
        changes.append('address')
    if emergency_contact is not None:
        user.emergency_contact = emergency_contact
        changes.append('emergency contact')
    if blood_group is not None:
        user.blood_group = blood_group
        changes.append('blood group')

    if not changes:
        return user

    db.session.commit()

    log_action(user, 'profile_updated', details=f"Updated: {', '.join(changes)}")
    create_notification(
        user, 'Profile updated',
        f"Your {', '.join(changes)} {'was' if len(changes) == 1 else 'were'} updated.",
        category='profile', priority='low',
    )
    return user


def change_password(user, current_password, new_password, confirm_password):
    if not current_password:
        raise ValueError('Current password is required')
    if not user.check_password(current_password):
        raise ValueError('Current password is incorrect')

    failed_rules = validate_password_strength(new_password)
    if failed_rules:
        raise ValueError('Password must contain ' + ', '.join(failed_rules) + '.')
    if new_password != confirm_password:
        raise ValueError('Passwords do not match')

    user.set_password(new_password)
    db.session.commit()

    log_action(user, 'password_changed')
    create_notification(
        user, 'Password changed', 'Your account password was changed successfully.',
        category='profile', priority='medium',
    )
    return user


def update_profile_picture(user, file_storage, upload_folder):
    old_picture = user.profile_picture
    picture_path, error = save_profile_picture(file_storage, user.reg_no, upload_folder)
    if error:
        raise ValueError(error)

    user.profile_picture = picture_path
    db.session.commit()

    if old_picture and old_picture != picture_path:
        old_full_path = os.path.join(os.path.dirname(upload_folder), old_picture)
        if os.path.exists(old_full_path):
            os.remove(old_full_path)

    log_action(
        user, 'profile_picture_updated',
        details='profile picture replaced' if old_picture else 'profile picture uploaded',
    )
    create_notification(
        user, 'Profile picture updated', 'Your profile picture was updated successfully.',
        category='profile', priority='low',
    )
    return user


def delete_profile_picture(user, static_folder):
    if not user.profile_picture:
        raise ValueError('No profile picture to remove')

    full_path = os.path.join(static_folder, user.profile_picture)
    if os.path.exists(full_path):
        os.remove(full_path)

    user.profile_picture = None
    db.session.commit()

    log_action(user, 'profile_picture_deleted')
    create_notification(
        user, 'Profile picture removed', 'Your profile picture was removed.',
        category='profile', priority='low',
    )
    return user
