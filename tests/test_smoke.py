"""Session 0 safety net (migration-runbook): walks app.url_map and hits
every parameter-free GET route, once anonymously and once with a
role-appropriate logged-in client, asserting the response is never a 500.

This says nothing about business correctness — only "the route doesn't
crash." That's exactly what's needed as a regression net while routes move
into blueprints: a 500 here after a later session means that session broke
something; a redirect loop (repeated 302s) or 403 is expected for some
role/route combinations and is not itself a failure.
"""
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app  # noqa: E402
from conftest import TestConfig  # noqa: E402

# A throwaway app just to read its route table at collection time. Must use
# TestConfig (in-memory DB), not the default Config — create_app() always
# runs db.create_all() against whatever SQLALCHEMY_DATABASE_URI is
# configured, and this module is imported on every pytest run.
flask_app = create_app(TestConfig)

ALLOWED_STATUSES = {200, 302, 403}

ROLE_FIXTURES = {"anon": "client", "student": "student_client", "admin": "admin_client"}

# Endpoints that are known to fail for reasons unrelated to the blueprint
# migration itself. Skipped now, on record, per the runbook: "Fix or
# explicitly skip them now, before anything moves."
KNOWN_FAILURES = {
    "add_drop_data-student": (
        "Route returns a deliberate 400 ('No active registration found.') when "
        "there is no active RegistrationPeriod — the fixture student has none. "
        "Not a crash; not in scope for this safety net."
    ),
    "admin_registration_oversight_data-admin": (
        "Route returns a deliberate 400 ('No registration period selected or "
        "active.') when there is no active RegistrationPeriod — the smoke "
        "fixtures seed no registration data. Not a crash; not in scope for "
        "this safety net."
    ),
}


def _smoke_routes():
    """(endpoint, path) for every GET route on the app that takes no URL
    arguments — i.e. is reachable at a fixed path with no <converter:name>
    segments, so it needs no per-route setup to call."""
    routes = []
    seen = set()
    for rule in flask_app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        if "GET" not in rule.methods:
            continue
        if rule.arguments:
            continue
        if rule.endpoint in seen:
            continue
        seen.add(rule.endpoint)
        routes.append((rule.endpoint, rule.rule))
    routes.sort()
    return routes


def _cases():
    for endpoint, path in _smoke_routes():
        yield pytest.param(endpoint, path, "anon", id=f"{endpoint}-anon")
        role = "admin" if path.startswith("/admin") else "student"
        yield pytest.param(endpoint, path, role, id=f"{endpoint}-{role}")


@pytest.mark.parametrize("endpoint,path,role", list(_cases()))
def test_route_never_500s(request, endpoint, path, role):
    case_id = f"{endpoint}-{role}"
    if case_id in KNOWN_FAILURES:
        pytest.skip(KNOWN_FAILURES[case_id])

    test_client = request.getfixturevalue(ROLE_FIXTURES[role])
    response = test_client.get(path)

    assert response.status_code != 500, (
        f"{endpoint} ({role}) GET {path} returned 500:\n"
        f"{response.get_data(as_text=True)[:2000]}"
    )
    assert response.status_code in ALLOWED_STATUSES, (
        f"{endpoint} ({role}) GET {path} returned unexpected status {response.status_code}"
    )
