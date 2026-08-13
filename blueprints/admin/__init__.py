from flask import Blueprint

admin_bp = Blueprint('admin', __name__)

from . import auth  # noqa: E402,F401 — registers the auth child blueprint onto admin_bp; imported last to avoid a circular import
