from flask import Blueprint

auth_bp = Blueprint('auth', __name__)

from . import routes  # noqa: E402,F401 — registers routes on auth_bp; imported last to avoid a circular import with routes.py
