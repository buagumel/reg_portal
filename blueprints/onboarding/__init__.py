from flask import Blueprint

onboarding_bp = Blueprint('onboarding', __name__)

from . import routes  # noqa: E402,F401 — registers routes on onboarding_bp; imported last to avoid a circular import with routes.py
