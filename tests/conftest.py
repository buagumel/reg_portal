"""Shared pytest fixtures for the smoke-test safety net (migration-runbook
Session 0), updated for the create_app() factory (Session 3). Each test gets
its own fresh app + isolated in-memory SQLite database via create_app(TestConfig)
— no more reaching into Flask-SQLAlchemy internals to repoint a shared engine.
"""
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app  # noqa: E402
from config import Config  # noqa: E402
from extensions import db  # noqa: E402
from models import User, AdminUser, AdminRole, Permission  # noqa: E402

DEFAULT_PASSWORD = "Default@123"


class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite://"


@pytest.fixture()
def app():
    """A fresh app for this test only, with its own in-memory database."""
    application = create_app(TestConfig)
    with application.app_context():
        yield application
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
