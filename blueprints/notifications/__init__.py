from flask import Blueprint

notifications_bp = Blueprint('notifications', __name__)

from . import routes  # noqa: E402,F401 — registers routes on notifications_bp; imported last to avoid a circular import with routes.py
