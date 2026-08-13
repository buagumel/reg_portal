from flask import Blueprint

payments_bp = Blueprint('payments', __name__)

from . import routes  # noqa: E402,F401 — registers routes on payments_bp; imported last to avoid a circular import with routes.py
