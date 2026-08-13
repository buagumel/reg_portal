from flask import Blueprint

admin_students_bp = Blueprint('students', __name__)

# Split across three files given this blueprint's size (28 routes) -- the
# runbook's own suggestion for this session. Each sibling module registers
# its routes onto admin_students_bp (imported back from this package);
# imported here, in one place, after admin_students_bp is defined, to avoid
# a circular import.
from . import students_list  # noqa: E402,F401
from . import students_detail  # noqa: E402,F401
from . import students_import  # noqa: E402,F401

from blueprints.admin import admin_bp  # noqa: E402 — deferred import to avoid a circular import with blueprints/admin/__init__.py

admin_bp.register_blueprint(admin_students_bp)
