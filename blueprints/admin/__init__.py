from flask import Blueprint

admin_bp = Blueprint('admin', __name__)

# Imported last, and in one place, to avoid a circular import — each child
# module imports admin_bp back from this package to register itself.
from . import auth  # noqa: E402,F401
from . import core  # noqa: E402,F401
from . import academic  # noqa: E402,F401
