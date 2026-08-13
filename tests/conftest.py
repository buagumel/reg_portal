"""Shared pytest fixtures for the smoke-test safety net (migration-runbook
Session 0). app.py is a module-level Flask app (no application factory
yet — that's Session 3), so `app`, `db`, `login_manager` etc. are all
singletons created once at import time. These fixtures reuse that same
singleton (it owns all 138 registered routes) but repoint its database
engine at an isolated in-memory SQLite database, so tests never touch the
real database.db.
"""
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import app as flask_app  # noqa: E402
from models import db, User, AdminUser, AdminRole  # noqa: E402

DEFAULT_PASSWORD = "Default@123"

flask_app.config.update(
    TESTING=True,
    WTF_CSRF_ENABLED=False,
)

# db.init_app(flask_app) already ran once at import time, bound to the real
# sqlite:///database.db (and Flask-SQLAlchemy refuses to init_app() twice on
# the same app, and ignores config changes made after the first init_app
# anyway). db.engines resolves the engine for the current app fresh out of
# this dict on every access though (see
# flask_sqlalchemy.extension.SQLAlchemy.engines), so swapping the entry
# directly repoints every db.session query at the in-memory engine below
# without needing a second init_app call.
_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
db._app_engines[flask_app][None] = _test_engine


@pytest.fixture()
def app():
    """The shared Flask app, with fresh tables for this test only."""
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def _new_student(**overrides):
    data = dict(
        reg_no="2308-2301-9001",
        email="test.student@example.test",
        name="Test Student",
        student_type="National",
        state="Jigawa",
        lga="Kazaure",
        nationality="Nigeria",
        gender="Female",
        semester="1st Semester",
        level="Year 1",
        session="2025/2026",
        department="Computer Science",
        course="ND Computer Science",
        phone="08000000000",
        address="1 Test Street, Kazaure",
        first_login=False,
        onboarding_completed=True,
        email_verified=True,
    )
    data.update(overrides)
    user = User(**data)
    user.set_password(DEFAULT_PASSWORD)
    return user


def _new_admin(**overrides):
    role = AdminRole.query.filter_by(name="Test Super Administrator").first()
    if role is None:
        role = AdminRole(name="Test Super Administrator", description="Seeded for tests — every permission granted.")
        db.session.add(role)
        db.session.flush()
        from services.admin_permission import has_permission  # noqa: F401  (sanity import)
        from models import Permission
        codes = [
            "dashboard.view", "sessions.manage", "students.manage", "courses.manage",
            "registration.manage", "announcements.manage", "reports.view",
            "departments.manage", "onboarding.override", "programmes.manage",
        ]
        for code in codes:
            perm = Permission.query.filter_by(code=code).first()
            if perm is None:
                perm = Permission(code=code, description=code)
                db.session.add(perm)
                db.session.flush()
            role.permissions.append(perm)

    data = dict(
        email="test.admin@example.test",
        name="Test Admin",
        role_id=role.id,
        is_active=True,
        first_login=False,
    )
    data.update(overrides)
    admin = AdminUser(**data)
    admin.set_password(DEFAULT_PASSWORD)
    return admin


@pytest.fixture()
def student(app):
    """A seeded, fully-onboarded student — same shape as seed_dev_data.py's
    demo students, minus the extra registration/course/payment fixtures
    that script builds (not needed for route smoke coverage)."""
    user = _new_student()
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def admin_user(app):
    """A seeded admin with every permission code granted, mirroring
    seed_dev_data.py's 'Super Administrator' role."""
    admin = _new_admin()
    db.session.add(admin)
    db.session.commit()
    return admin


@pytest.fixture()
def student_client(app, student):
    client = app.test_client()
    resp = client.post(
        "/login",
        data={"studentId": student.reg_no, "password": DEFAULT_PASSWORD},
    )
    assert resp.status_code == 302, f"student login failed unexpectedly: {resp.status_code}"
    return client


@pytest.fixture()
def admin_client(app, admin_user):
    client = app.test_client()
    resp = client.post(
        "/admin/login",
        data={"email": admin_user.email, "password": DEFAULT_PASSWORD},
    )
    assert resp.status_code == 302, f"admin login failed unexpectedly: {resp.status_code}"
    return client
