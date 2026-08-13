from flask import Flask

from extensions import db, migrate, csrf, mail, login_manager
from config import Config
from blueprints.notifications import notifications_bp
from blueprints.auth import auth_bp
from blueprints.onboarding import onboarding_bp
from blueprints.student import student_bp
from blueprints.registration import registration_bp
from blueprints.payments import payments_bp
from blueprints.admin import admin_bp
from hooks import (
    load_user,  # noqa: F401 — imported for its @login_manager.user_loader registration side effect
    endpoint_name, enforce_onboarding_gate, enforce_admin_session_timeout, inject_unread_notification_count,
)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'   # redirect to this view if not logged in
    login_manager.login_message = "Please log in to access this page."

    with app.app_context():
        db.create_all()

    app.before_request(enforce_onboarding_gate)
    app.before_request(enforce_admin_session_timeout)
    app.context_processor(inject_unread_notification_count)
    # Templates (the admin sidebar nav in particular) compare request.endpoint
    # against bare route names to highlight the current page — same problem
    # endpoint_name() already solves for the Python-side gates (Session 1),
    # exposed here so templates get the blueprint-prefix-proof version too.
    app.jinja_env.globals['endpoint_name'] = endpoint_name

    app.register_blueprint(notifications_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(onboarding_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(registration_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(admin_bp)

    return app


if __name__ == '__main__':
    create_app().run(debug=True, port=4050)
