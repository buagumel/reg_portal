from flask import Blueprint

student_bp = Blueprint('student', __name__)

from . import routes  # noqa: E402,F401 — registers routes on student_bp; imported last to avoid a circular import with routes.py
