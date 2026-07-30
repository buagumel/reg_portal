# Student Data Integration — Design Spec

Date: 2026-07-30
Status: Approved
Scope: Replace hardcoded/mock student identity and academic data across the dashboard, profile page, sidebar, and navbar with real values from the authenticated student's `User` record. Integration only — no redesign, no new pages, no new course/payment/registration/announcement features.

## Goal

Turn the existing prototype UI into a data-driven application for the pieces that already have a real data source (the authenticated student's own record), while being honest (empty states, never fabricated data) about the pieces that don't yet (courses, payments, registrations, notifications).

## Audit findings (baseline)

All ten student-facing routes in `app.py` (`dashboard`, `profile`, `announcements`, `pay_summary`, `registration`, `add_drop`, `add`, `my_courses`, `payments_history`, plus the stray `courses` route returning a raw string) currently call `render_template(...)` with **zero context variables**. The only real data reaching any template today is `current_user`, via Flask-Login's implicit Jinja global — already used correctly in `dashboard.html` and `profile.html` for name, reg_no, phone, email, state, LGA, student_type, address, email_verified, gender, DOB, nationality.

Hardcoded student/academic data still present:
- `dashboard.html`: profile picture (17, hardcoded to a static file instead of `current_user.profile_picture`), programme (26, "B.Sc. Comp. Sci."), semester/level (30, "2nd · Year 3").
- `profile.html`: programme (218, 222, 290 — three hardcoded copies), semester/level (223, 294), session (225, 305).
- `base.html`: notification badge (33, hardcoded "3").

Mock course/payment tables with no backing model (out of scope for this milestone, per explicit decision below):
- `dashboard.html`: "Registered Courses" table (108-171), "Recent payment history" table (185-247), a dead commented-out mock course-card block (73-104), and the announcement banner (63-64) — all left as-is.
- `registration.html`, `add_drop.html`, `add.html`, `my_courses.html`, `payments_history.html`, `payment_summary.html`, `announcements.html` — untouched; these belong to separate not-yet-built features (Registration, Payments, My Courses, Notifications).

Route bug found during audit: `profile()` has no `@login_required`, unlike every other gated route. An unauthenticated request would currently crash on `current_user.name` etc. against Flask-Login's `AnonymousUserMixin`. Fixed as part of this milestone since the route is already being touched.

Dead code found: `templates/add.html` and its `/add` route in `app.py` are an orphaned, unreferenced duplicate of `add_drop.html` — no template links to `/add` anywhere. Deleted as part of the "remove obsolete mock code" requirement.

## Scope decision (confirmed with user)

Two buckets of mock data exist: (A) student identity/academic fields, and (B) course/payment/registration/announcement tables with no backing model. This milestone covers:
- **All of bucket A**, everywhere it appears (dashboard, profile, sidebar, navbar).
- **From bucket B**: only the dashboard's "Registered Courses" table, "Recent payment history" table, and the navbar's notification badge — emptied to honest empty states, since they're the most prominent fabricated content on the main landing page.
- **Explicitly NOT in scope**: the dashboard's announcement banner (left as-is per user instruction — do not touch), and all six standalone pages (`registration.html`, `add_drop.html`, `add.html` beyond its deletion as dead code, `my_courses.html`, `payments_history.html`, `payment_summary.html`, `announcements.html`).

## Data model changes (`models.py`)

Add two nullable `String` columns to `User`, following the same pattern as the existing `semester`/`department`/`course` fields added in the previous milestone:
- `level` — e.g. "Year 1", "Year 2", populated for ND/HND students. Left `None` for International-program students, since `doc/Student Programs and Study Cycles.txt` describes them by Term + First/Second Semester rather than a year-level — there is no real "Level" concept for that program type, so the field is genuinely empty for them, not just unpopulated.
- `session` — e.g. "2024/2025".

No Alembic migration; the dev SQLite database continues to be deleted and rebuilt via the existing `db.create_all()` call, consistent with the previous milestone's approach.

## Service layer (`services/student_profile.py`)

New module, new `services/` package (with an `__init__.py`). One function:

```python
def get_profile_display(user):
    """Return a dict of derived, template-ready display strings for a student's
    profile/academic info. Centralizes the formatting logic (e.g. combining
    level + semester into one string, falling back to a placeholder when a
    field is unset) so templates don't do it themselves."""
```

Returns a dict with keys: `programme` (from `user.course`, falling back to a "Not set" placeholder if empty), `level_semester` (combines `user.level` and `user.semester` when both are present, e.g. "Year 2 · 2nd Semester"; omits the level segment entirely when `user.level` is `None`, e.g. just "2nd Semester"; falls back to a placeholder if neither is set), `session` (from `user.session`, falling back to a placeholder).

This keeps the existing pattern of templates reading `current_user.*` directly for the fields that need no derivation (name, reg_no, phone, email, address, etc.) — only the fields that need formatting/fallback logic get routed through the service, avoiding both duplicate queries (no new DB access — `user` is already `current_user`) and business logic embedded in Jinja.

## Route changes (`app.py`)

- `dashboard()` and `profile()`: import and call `get_profile_display(current_user)`, pass the result into `render_template(..., profile_display=...)`.
- `profile()`: add the missing `@login_required` decorator.
- Delete the `add()` route entirely (dead code, see above).

## Template changes

**`dashboard.html`**
- Line 17: profile picture → `current_user.profile_picture` if set (rendered as an `<img>`, matching the existing markup); if not set, fall back to the icon-based placeholder pattern `profile.html` already uses for this exact case (`<i class="fas fa-user-graduate">` in a circular container) via a Jinja `{% if %}`, rather than pointing at a static demo image. This reuses an existing convention instead of inventing a new one, and never renders a broken `<img src="">`.
- Line 26: programme → `profile_display.programme`.
- Line 30: semester/level → `profile_display.level_semester`.
- Lines 108-171 ("Registered Courses" table): replaced with an empty-state block ("No courses registered yet" + an icon, matching the visual weight of the existing table so the layout doesn't jump).
- Lines 185-247 ("Recent payment history" table): replaced with an empty-state block ("No payment history yet"), same treatment.
- Lines 73-104: delete the dead commented-out mock course-card block.
- Announcement banner (63-64): **left untouched**, per explicit user instruction.

**`profile.html`**
- Lines 218, 222, 290 (three programme copies) → `profile_display.programme`.
- Lines 223, 294 (semester/level copies) → `profile_display.level_semester`.
- Lines 225, 305 (session copies) → `profile_display.session`.

**`base.html`**
- Line 33: notification badge → only rendered (via a Jinja `{% if %}`) when a real unread count is available. Since no Notification model exists yet, this means the badge simply doesn't render — an honest absence rather than a fake "3". (If/when a Notification model exists, this becomes a one-line change to pass a real count in.)

## Cleanup

- Delete `templates/add.html`.
- Delete the `/add` route from `app.py`.
- Delete the dead commented-out mock course-card block in `dashboard.html` (lines 73-104).
- Delete `static/uploads/profile.jpeg` — the generic demo photo currently hardcoded into `dashboard.html`; once that line falls back to the icon placeholder instead, this file becomes unreferenced anywhere in the codebase. Real uploaded profile pictures use the `uploads/<reg_no>.<ext>` naming convention already established by the onboarding upload flow, which this file doesn't follow.

## Demo data (`seed_dev_data.py`)

Extend the 4 existing seed students with `level` and `session` values that match the real program structure from `Student Programs and Study Cycles.txt`:
- ND/HND students get a `level` (e.g. "Year 1", "Year 2") alongside their existing `semester`.
- International-program students get `level=None` (no year-level concept for that program type) — this also exercises the `get_profile_display` fallback path (level omitted from `level_semester`, showing just the semester).
- All four get a `session` value (e.g. "2024/2025").

## Testing approach

No automated test framework exists in this repo (established convention). Verification is manual, per the existing pattern: a throwaway `python -c` / Flask `test_client` script confirming `get_profile_display` produces the right fallback behavior for all four seeded students (level present vs. `None`, unset fields), followed by a browser walk-through of dashboard and profile pages for each of the 4 seeded students, confirming:
- Every identity/academic field shows the real seeded value, not a hardcoded one.
- A student with no `profile_picture` set shows the fallback avatar, not a broken image.
- The dashboard's two emptied tables show their empty-state message.
- The navbar shows no notification badge.
- `profile()` still requires login (a logged-out request redirects to `/login` rather than crashing).
