import os
import random
import string
import time

from werkzeug.utils import secure_filename

MAX_OTP_ATTEMPTS = 3
OTP_EXPIRY_SECONDS = 300
ALLOWED_PICTURE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
MAX_PICTURE_SIZE_BYTES = 2 * 1024 * 1024


def start_otp_session(session, email):
    """Generate a new OTP, store it (with expiry + reset attempt count) in the session, return the code."""
    code = ''.join(random.choices(string.digits, k=6))
    session['email_verification_code'] = code
    session['email_verification_expiry'] = time.time() + OTP_EXPIRY_SECONDS
    session['pending_email'] = email
    session['email_verification_attempts'] = 0
    return code


def register_failed_otp_attempt(session):
    """Increment the failed-attempt counter, return the new count."""
    attempts = session.get('email_verification_attempts', 0) + 1
    session['email_verification_attempts'] = attempts
    return attempts


def otp_attempts_exceeded(session):
    return session.get('email_verification_attempts', 0) >= MAX_OTP_ATTEMPTS


def clear_otp_session(session):
    for key in ('email_verification_code', 'email_verification_expiry', 'pending_email', 'email_verification_attempts'):
        session.pop(key, None)


def save_profile_picture(file_storage, reg_no, upload_folder):
    """Validate and save an uploaded profile picture.

    Returns (relative_path, error_message) — exactly one of the two is None.
    relative_path is relative to the static/ folder, e.g. 'uploads/2308-2301-0001.jpg'.
    """
    if not file_storage or not file_storage.filename:
        return None, 'Profile picture is required'

    filename = secure_filename(file_storage.filename)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ALLOWED_PICTURE_EXTENSIONS:
        return None, 'Profile picture must be a PNG, JPG, or WEBP image'

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > MAX_PICTURE_SIZE_BYTES:
        return None, 'Profile picture must be smaller than 2MB'

    stored_filename = f"{secure_filename(reg_no)}.{ext}"
    file_storage.save(os.path.join(upload_folder, stored_filename))
    return f"uploads/{stored_filename}", None
