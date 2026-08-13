# reg_portal — Blueprint Migration Runbook

Goal: take `app.py` from 3,031 lines and 138 routes down to an application
factory of roughly 50 lines, without changing a single URL or template design.

**Rules for every session:**
- One session, one commit, tests green before committing.
- Never touch two blueprints in the same change.
- URLs stay identical. No `url_prefix` on any blueprint.
- If a diff starts spreading, stop and split the session.

---

## The one thing that will break this

Two `before_request` gates and your login manager compare against **bare
endpoint names**:

```python
exempt_endpoints = {'login', 'logout', 'onboarding', 'profile', ...}
if request.endpoint in exempt_endpoints:
login_manager.login_view = 'login'
if request.endpoint in ('admin_login', 'static'):
```

The moment `login` moves into a blueprint, `request.endpoint` becomes
`auth.login` and stops matching. The gate then redirects a user who is
already where they should be — a redirect loop, on a page that worked five
minutes ago.

Session 1 makes this immune before anything moves. Do not skip it or reorder it.

---

## Session 0 — Safety net

Without this you are clicking through 138 routes by hand after every change.

```
Add pytest and pytest-flask to requirements.txt.

Create tests/conftest.py with:
- an app fixture using an in-memory SQLite database and WTF_CSRF_ENABLED=False
- fixtures that seed one student and one admin using seed_dev_data.py logic
- a logged-in student client and a logged-in admin client

Create tests/test_smoke.py that walks app.url_map, and for every GET
route with no required parameters, asserts the response is 200, 302 or
403 — never 500. Parametrise so each route is its own test case.

Do not modify app.py.
```

**Done when:** `pytest` runs and every route is covered. Some will fail — that
is fine and useful. Fix or explicitly skip them now, before anything moves.

---

## Session 1 — Endpoint-name proofing

```
In app.py, the two before_request gates and login_manager compare
request.endpoint against bare function names. Once routes move into
blueprints these become 'blueprint.function' and will stop matching.

Add a helper `endpoint_name(request)` that returns the part of
request.endpoint after the last dot, and use it in
enforce_onboarding_gate and enforce_admin_session_timeout instead of
comparing request.endpoint directly.

Leave url_for calls alone for now. Change nothing else.

Run pytest.
```

**Done when:** tests pass and the gates work on both `login` and `auth.login`.
This one small change survives the entire migration.

---

## Session 2 — Config and secrets

Revoke the Gmail app password before this session. Deleting the file does not
undo the exposure.

```
Create config.py with a Config class reading from environment variables
via python-dotenv: SECRET_KEY, SQLALCHEMY_DATABASE_URI, MAIL_*,
PAYMENT_GATEWAY_MODE, and all REMITA_* values.

Move every value out of constants_file.py, delete that file, and add
.env.example with placeholder values. Add python-dotenv to
requirements.txt.

Update app.py to use app.config.from_object(Config).

Run pytest.
```

**Done when:** `constants_file.py` is gone and the app still starts.

Afterwards, separately: rewrite git history to purge the old credentials, or
create a fresh repo. Rotating is what closes the hole; history cleanup is
tidying.

---

## Session 3 — Application factory

```
Convert app.py to a create_app(config_class=Config) factory.

Move db, migrate, csrf, mail and login_manager into extensions.py as
uninitialised objects, and init_app them inside the factory.

Register the user_loader, both before_request gates, and the context
processor inside the factory or in a blueprint-free module it imports.

Keep every route in app.py for now, registered against the app inside
the factory or via a temporary blueprint — whichever is less disruptive.
Show me your plan before writing files.

Update tests/conftest.py to use the factory. Run pytest.
```

**Done when:** tests pass and `flask run` works.

---

## Session 4 — Notifications (the pattern-setter)

Smallest blueprint. Its only job is to establish the shape of every session
after it.

```
Create blueprints/notifications/__init__.py and routes.py.

Move the 6 notification routes out of app.py into it. Keep URLs exactly
as they are — no url_prefix. Register the blueprint in create_app.

Update url_for references to these endpoints across templates and
static/js. Run pytest.

Touch no other routes.
```

**Done when:** tests pass and `app.py` is 6 routes shorter. **Read this diff
carefully** — it is the template for the twelve sessions that follow. If the
shape is right here, the rest are repetition.

---

## Sessions 5–9 — Student side

Same prompt each time, swapping the names. Smallest first.

| Session | Blueprint | Routes to move |
|---|---|---|
| 5 | `auth` | login, logout, change-password, force-password-change, send-email-code, verify-email-code |
| 6 | `onboarding` | onboarding, onboarding_save_info, onboarding_complete |
| 7 | `student` | dashboard (`/`), profile, update-profile, announcements, courses |
| 8 | `registration` | registration, add_drop (5), my_courses |
| 9 | `payments` | payment (11), payments_history (2) |

```
Create blueprints/<name>/ and move the <name> routes out of app.py.
Keep URLs identical. Register in create_app.

Update url_for references in templates and static/js. Also check
login_manager.login_view and the exempt endpoint sets in the gates.

Run pytest. Touch no other routes.
```

Session 5 additionally needs `login_manager.login_view = 'auth.login'`.

---

## Sessions 10–15 — Admin side

93 routes. Six slices, largest last.

| Session | Blueprint | Routes |
|---|---|---|
| 10 | `admin.auth` | login, logout, forgot-password, reset-password, verify-reset-code, force-password-change |
| 11 | `admin.core` | dashboard, registration (3), onboarding (2), announcements |
| 12 | `admin.academic` | sessions (9), programmes (7), departments (7) |
| 13 | `admin.courses` | courses (12), course-catalog (8) |
| 14 | `admin.finance` | fee-structure (4), reports, export (2) |
| 15 | `admin.students` | students (29) |

Register these as nested blueprints on a parent `admin` blueprint so
`admin_required` and `permission_required` can be applied once at the parent
rather than repeated on 93 routes:

```
Create blueprints/admin/__init__.py exposing a parent 'admin' blueprint.
Move the <slice> routes into blueprints/admin/<slice>.py as a child
blueprint registered on the parent.

Apply admin_required at the blueprint level via before_request rather
than per-route, but keep per-route permission_required decorators.

Keep URLs identical. Update url_for in templates/admin/ and
static/js/admin/. Update enforce_admin_session_timeout's endpoint
references. Run pytest.
```

Session 15 is 29 routes and will be the longest. Consider splitting it into
students-list, students-detail, and students-import if the diff gets unwieldy.

---

## Session 16 — Cleanup

```
app.py should now contain only create_app and blueprint registration.
Move any leftover helpers into the blueprint or service they belong to.

Also: delete trialx.html from the repo root, and reconcile
requirements.py against requirements.txt — one of them is stale.

Run pytest and confirm app.py is under 100 lines.
```

---

## CLAUDE.md

Put this in the repo root before Session 0.

```markdown
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
```

---

## Expected shape at the end

```
app.py                    ~50 lines — create_app and registration
config.py                 environment-backed settings
extensions.py             db, migrate, csrf, mail, login_manager
blueprints/
  auth/  onboarding/  student/  registration/  payments/  notifications/
  admin/
    __init__.py  auth.py  core.py  academic.py  courses.py
    finance.py  students.py
services/                 unchanged — already correct
templates/                unchanged
static/                   unchanged
tests/                    conftest.py, test_smoke.py, then real tests
```

Sixteen sessions. None of them changes what a user sees. Every one of them
ends with a green test suite and a commit you can revert.
