from flask import Blueprint

registration_bp = Blueprint('registration', __name__)

from . import routes  # noqa: E402,F401 — registers routes on registration_bp; imported last to avoid a circular import with routes.py
