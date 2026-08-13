# JSPICT Registration Portal

Flask + SQLAlchemy + Flask-Login + Alembic. SQLite in dev.
Run: `flask run`. Tests: `pytest`.

## Architecture
Routes parse requests and pick templates. All business logic lives in
services/. Never put a query or a rule in a route.

## Current work: extracting blueprints from app.py
- One blueprint per session. Never touch two in the same change.
- URLs must not change. No url_prefix on any blueprint.
- After moving routes, update url_for in templates AND static/js.
- Check the before_request gates and login_manager.login_view for
  endpoint names that need a blueprint prefix.
- Run pytest before proposing a commit.

## Never
- Rewrite a template's CSS or DOM to "improve" it. The design is final.
- Regenerate migrations that have already run.
- Use float for money. Numeric only.
- Put secrets in tracked files. .env only.