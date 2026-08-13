"""Regression coverage for auth_helpers.get_gate_redirect(): the
before_request gates and the login view all pass its return value straight
into url_for(...), so each entry must stay in sync with wherever that route
currently lives. Session 5 broke the first_login case — get_gate_redirect
still returned the bare 'force_password_change' after that route moved into
the auth blueprint, so url_for(...) raised a BuildError and any first-login
student got a 500 the instant they logged in.

tests/test_smoke.py didn't catch this: its student fixture always seeds an
already-onboarded student (first_login=False, onboarding_completed=True,
email_verified=True), so this code path was never exercised. These tests
seed the three "not yet cleared" states directly, so a future blueprint move
that forgets to update get_gate_redirect fails loudly here instead of
silently 500ing in production.
"""
from extensions import db
from conftest import _new_student, DEFAULT_PASSWORD


def _login(client, student):
    return client.post('/login', data={'studentId': student.reg_no, 'password': DEFAULT_PASSWORD})


def test_first_login_student_redirects_to_force_password_change(app):
    student = _new_student(
        reg_no='GATE-001', email='gate1@example.test',
        first_login=True, onboarding_completed=False, email_verified=False,
    )
    db.session.add(student)
    db.session.commit()

    client = app.test_client()
    resp = _login(client, student)
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/force-password-change'

    resp2 = client.get('/courses')
    assert resp2.status_code == 302
    assert resp2.headers['Location'] == '/force-password-change'


def test_incomplete_onboarding_student_redirects_to_onboarding(app):
    student = _new_student(
        reg_no='GATE-002', email='gate2@example.test',
        first_login=False, onboarding_completed=False, email_verified=False,
    )
    db.session.add(student)
    db.session.commit()

    client = app.test_client()
    resp = _login(client, student)
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/onboarding'

    resp2 = client.get('/courses')
    assert resp2.status_code == 302
    assert resp2.headers['Location'] == '/onboarding'


def test_unverified_email_student_redirects_to_profile(app):
    student = _new_student(
        reg_no='GATE-003', email='gate3@example.test',
        first_login=False, onboarding_completed=True, email_verified=False,
    )
    db.session.add(student)
    db.session.commit()

    client = app.test_client()
    resp = _login(client, student)
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/profile'

    resp2 = client.get('/courses')
    assert resp2.status_code == 302
    assert resp2.headers['Location'] == '/profile'
