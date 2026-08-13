import re

PASSWORD_RULES = [
    (lambda p: len(p) >= 8, 'at least 8 characters'),
    (lambda p: re.search(r'[A-Z]', p) is not None, 'an uppercase letter'),
    (lambda p: re.search(r'[a-z]', p) is not None, 'a lowercase letter'),
    (lambda p: re.search(r'[0-9]', p) is not None, 'a number'),
    (lambda p: re.search(r'[^A-Za-z0-9]', p) is not None, 'a special character'),
]

EMAIL_REGEX = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


def validate_password_strength(password):
    """Return a list of unmet rule descriptions. Empty list means the password is valid."""
    return [desc for check, desc in PASSWORD_RULES if not check(password)]


def is_valid_email(email):
    return bool(EMAIL_REGEX.match(email))


def get_gate_redirect(user):
    """Return the endpoint name the user must be redirected to before they can access
    any other page, or None if they're fully cleared for normal access.

    These are fed straight into url_for(...) by the gates and by the login
    view, so each one must stay in sync with wherever its route currently
    lives — update it in the same session that moves that route into a
    blueprint (the same rule login_manager.login_view follows)."""
    if user.first_login:
        return 'auth.force_password_change'
    if not user.onboarding_completed:
        return 'onboarding.onboarding'
    if not user.email_verified:
        return 'student.profile'
    return None
