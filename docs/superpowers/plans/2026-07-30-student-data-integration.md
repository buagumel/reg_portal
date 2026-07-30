# Student Data Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every hardcoded/mock student identity and academic field on the dashboard, profile page, and navbar with real data from the authenticated student's `User` record, while honestly empty-stating the two dashboard mock tables and the notification badge (no backing model exists for those yet).

**Architecture:** New `services/student_profile.py` module holds the one piece of derived/formatting logic this milestone needs (`get_profile_display(user)`); routes pass its output into templates alongside the existing `current_user` Jinja global (already used directly for fields that need no derivation). No new database queries — `current_user` is already loaded per-request by Flask-Login.

**Tech Stack:** Flask, Flask-SQLAlchemy, Jinja2 (no changes to existing stack).

## Global Constraints

- No redesign: template markup, CSS classes, and page structure stay as they are except where a hardcoded value is being swapped for a real one, or a mock table is being replaced with an empty state.
- Never fabricate data: if a field is genuinely unset, show a "Not set" placeholder (identity fields) or an empty-state message (tables/badge) — never a plausible-looking fake value.
- Out of scope (do not touch): `registration.html`, `add_drop.html`, `my_courses.html`, `payments_history.html`, `payment_summary.html`, `announcements.html`, and the dashboard's announcement banner (lines 57-68 of `dashboard.html`).
- No Alembic migration — the dev SQLite database is deleted and rebuilt via the existing `db.create_all()` call, consistent with the previous milestone.
- No test framework exists in this repo. Verification is manual: throwaway `python -c` / Flask `test_client` scripts, per the established project convention.

---

### Task 1: Add `level` and `session` columns to User, extend seed data

**Files:**
- Modify: `models.py:32-38` (User model column declarations)
- Modify: `seed_dev_data.py` (all 4 `DEMO_STUDENTS` dict entries)

**Interfaces:**
- Produces: `User.level` (str|None), `User.session` (str|None) — consumed by Task 2's `get_profile_display`.

- [ ] **Step 1: Add the two new columns**

In `models.py`, insert after the existing `profile_picture` column (currently the last column before the blank line and `set_password` method):

```python
    profile_picture = db.Column(db.String(300))
    level = db.Column(db.String(50))
    session = db.Column(db.String(20))
```

- [ ] **Step 2: Extend the seed data with realistic level/session values**

In `seed_dev_data.py`, update each of the 4 `DEMO_STUDENTS` dicts to add `level` and `session`. Per `doc/Student Programs and Study Cycles.txt`, ND/HND students have a year-level; International-program students do not (they're tracked by Term + Semester only), so leave `level=None` for the International student. Replace the full `DEMO_STUDENTS` list with:

```python
DEMO_STUDENTS = [
    dict(
        reg_no="2308-2301-0001", name="Amina Yusuf", first_login=True, onboarding_completed=False,
        student_type="National", state="Jigawa", lga="Kazaure", nationality="Nigeria",
        dob=date(2002, 3, 14), gender="Female", semester="1st Semester", level="Year 1",
        session="2025/2026", department="Computer Science", course="ND Computer Science",
        email=None, phone=None, address=None,
    ),
    dict(
        reg_no="2308-2301-0002", name="Bello Ibrahim", first_login=False, onboarding_completed=False,
        student_type="National", state="Jigawa", lga="Kazaure", nationality="Nigeria",
        dob=date(2001, 11, 2), gender="Male", semester="1st Semester", level="Year 1",
        session="2025/2026", department="Computer Science", course="ND Computer Science",
        email=None, phone=None, address=None,
    ),
    dict(
        reg_no="2308-2301-0003", name="Chiamaka Okafor", first_login=False, onboarding_completed=True,
        email_verified=True,
        student_type="International", state="Anambra", lga="Awka South", nationality="Nigeria",
        dob=date(2000, 7, 22), gender="Female", semester="2nd Semester", level=None,
        session="2025/2026", department="Information Technology", course="International Diploma",
        email="chiamaka.demo@example.com", phone="08012345678", address="12 Unity Road, Kazaure",
    ),
    dict(
        reg_no="2308-2301-0004", name="David Adeyemi", first_login=True, onboarding_completed=True,
        email_verified=True,
        student_type="National", state="Oyo", lga="Ibadan North", nationality="Nigeria",
        dob=date(1999, 5, 9), gender="Male", semester="2nd Semester", level="Year 2",
        session="2025/2026", department="Information Technology", course="HND Information Technology",
        email="david.demo@example.com", phone="08087654321", address="4 Freedom Ave, Ibadan",
    ),
]
```

- [ ] **Step 3: Reset the dev database and reseed**

Run: `rm -f instance/database.db && python seed_dev_data.py`

Expected: 4 "Created ..." lines, ending with "Done. 4 student(s) created. ...".

- [ ] **Step 4: Verify the new columns and values**

Run:
```bash
python -c "
from app import app
from models import User
with app.app_context():
    for u in User.query.all():
        print(u.reg_no, repr(u.level), u.session)
"
```
Expected: `2308-2301-0001 'Year 1' 2025/2026`, `2308-2301-0002 'Year 1' 2025/2026`, `2308-2301-0003 None 2025/2026`, `2308-2301-0004 'Year 2' 2025/2026`.

- [ ] **Step 5: Commit**

```bash
git add models.py seed_dev_data.py
git commit -m "feat: add level and session fields to User, seed realistic demo values"
```

---

### Task 2: Profile display service (`services/student_profile.py`)

**Files:**
- Create: `services/__init__.py` (empty — makes `services` a package)
- Create: `services/student_profile.py`

**Interfaces:**
- Produces: `get_profile_display(user) -> dict` with keys `programme` (str), `level_semester` (str), `session` (str). Consumed by Tasks 3 and 4.

- [ ] **Step 1: Write a throwaway verification script and confirm it fails**

Run:
```bash
python -c "
from services.student_profile import get_profile_display
print('OK')
"
```
Expected: `ModuleNotFoundError: No module named 'services'`

- [ ] **Step 2: Create the package marker**

Create `services/__init__.py` (empty file).

- [ ] **Step 3: Create `services/student_profile.py`**

```python
def get_profile_display(user):
    """Return derived, template-ready display strings for a student's
    programme/level/semester/session, with placeholders for unset fields."""
    programme = user.course or "Not set"

    if user.level and user.semester:
        level_semester = f"{user.level} · {user.semester}"
    elif user.semester:
        level_semester = user.semester
    elif user.level:
        level_semester = user.level
    else:
        level_semester = "Not set"

    session_display = user.session or "Not set"

    return {
        "programme": programme,
        "level_semester": level_semester,
        "session": session_display,
    }
```

- [ ] **Step 4: Re-run the verification script with real assertions**

Run:
```bash
python -c "
from services.student_profile import get_profile_display

class FakeUser:
    def __init__(self, course, level, semester, session):
        self.course = course
        self.level = level
        self.semester = semester
        self.session = session

# ND student: level + semester both present
r = get_profile_display(FakeUser('ND Computer Science', 'Year 1', '1st Semester', '2025/2026'))
assert r == {'programme': 'ND Computer Science', 'level_semester': 'Year 1 · 1st Semester', 'session': '2025/2026'}, r

# International student: no level
r = get_profile_display(FakeUser('International Diploma', None, '2nd Semester', '2025/2026'))
assert r == {'programme': 'International Diploma', 'level_semester': '2nd Semester', 'session': '2025/2026'}, r

# Nothing set at all
r = get_profile_display(FakeUser(None, None, None, None))
assert r == {'programme': 'Not set', 'level_semester': 'Not set', 'session': 'Not set'}, r

print('OK')
"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add services/__init__.py services/student_profile.py
git commit -m "feat: add student profile display service"
```

---

### Task 3: Wire `dashboard.html` to real data, empty-state the two mock tables

**Files:**
- Modify: `app.py` (import + `dashboard()` route)
- Modify: `templates/dashboard.html`
- Modify: `static/css/dashboard.css` (add empty-state styling)

**Interfaces:**
- Consumes: `get_profile_display` from Task 2.

- [ ] **Step 1: Add the import and wire the route**

In `app.py`, add near the other local imports (after the `onboarding_helpers` import block):

```python
from services.student_profile import get_profile_display
```

Update the `dashboard()` view:

```python
@app.route('/')
@login_required
def dashboard():
    return render_template('dashboard.html', profile_display=get_profile_display(current_user))
```

- [ ] **Step 2: Wire the profile picture with a fallback**

In `templates/dashboard.html`, replace lines 15-18:

```html
                    <div class="profile-pic">
                        <!-- <i class="fas fa-user-graduate"></i> -->
                         <img id="profile-pic" src="{{ url_for('static', filename='uploads/profile.jpeg') }}" alt="Profile Picture">
                    </div>
```

with:

```html
                    <div class="profile-pic">
                        {% if current_user.profile_picture %}
                        <img id="profile-pic" src="{{ url_for('static', filename=current_user.profile_picture) }}" alt="Profile Picture">
                        {% else %}
                        <i class="fas fa-user-graduate"></i>
                        {% endif %}
                    </div>
```

(`.profile-pic` in `dashboard.css:59-71` is already flex-centered with `font-size: 5rem; color: #1a4b74;` — sized for exactly this icon fallback, no CSS change needed here.)

- [ ] **Step 3: Wire programme and semester/level**

Replace line 26:
```html
                        <span class="info-value">B.Sc. Comp. Sci.</span>
```
with:
```html
                        <span class="info-value">{{ profile_display.programme }}</span>
```

Replace line 30:
```html
                        <span class="info-value">2nd · Year 3</span>
```
with:
```html
                        <span class="info-value">{{ profile_display.level_semester }}</span>
```

- [ ] **Step 4: Delete the dead commented-out mock course-card block**

Delete lines 73-104 (the `<!-- <div class="course-card"> ... -->` block, four fake course cards, entirely commented out and never rendered) along with the blank lines immediately following it (105-107), so `<div class="courses-grid">` (line 72) is immediately followed by the "Registered Courses" `<div class="payment-section">` (currently line 108).

- [ ] **Step 5: Empty-state the "Registered Courses" table**

Replace the `<div class="table-wrapper">...</div>` block currently at lines 114-169 (containing the `<table>` with the 5 fake rows: Tuition, Lab fee, ID card renewal, Library fee, Accommodation) with:

```html
            <div class="table-wrapper">
                <div class="empty-state-row">
                    <i class="fas fa-book-open"></i>
                    <p>No courses registered yet.</p>
                </div>
            </div>
```

- [ ] **Step 6: Empty-state the "Recent payment history" table**

Replace the `<div class="table-wrapper">...</div>` block currently at lines 190-245 (containing the `<table>` with the 5 fake payment rows) with:

```html
            <div class="table-wrapper">
                <div class="empty-state-row">
                    <i class="fas fa-receipt"></i>
                    <p>No payment history yet.</p>
                </div>
            </div>
```

- [ ] **Step 7: Add empty-state CSS**

In `static/css/dashboard.css`, add (near the `.table-wrapper` rules, or at the end of the file — either is fine, this repo doesn't enforce strict rule ordering):

```css
.empty-state-row {
    text-align: center;
    padding: 2.5rem 1rem;
    color: var(--text-muted);
}

.empty-state-row i {
    font-size: 1.8rem;
    display: block;
    margin-bottom: 0.6rem;
    opacity: 0.6;
}

.empty-state-row p {
    margin: 0;
    font-size: 0.95rem;
}
```

- [ ] **Step 8: Verify the app still boots**

Run: `python -c "import app; print('OK')"`
Expected: `OK`

- [ ] **Step 9: Commit**

```bash
git add app.py templates/dashboard.html static/css/dashboard.css
git commit -m "feat: wire dashboard to real student data, empty-state mock course/payment tables"
```

(Full visual verification against seeded accounts happens in Task 7.)

---

### Task 4: Wire `profile.html` to real data, add missing `@login_required`

**Files:**
- Modify: `app.py` (`profile()` route)
- Modify: `templates/profile.html`

**Interfaces:**
- Consumes: `get_profile_display` from Task 2.

- [ ] **Step 1: Fix the route**

In `app.py`, update the `profile()` view (currently missing `@login_required`, unlike every other gated route):

```python
@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', profile_display=get_profile_display(current_user))
```

- [ ] **Step 2: Wire the avatar with a fallback (matching the existing placeholder pattern)**

Replace lines 208-216:

```html
                <div class="avatar-wrapper">
                    <div class="avatar-placeholder" id="avatarDisplay">
                        <i class="fas fa-user-graduate fa-3x"></i>
                    </div>
                    <div class="edit-avatar-btn" id="editAvatarBtn">
                        <i class="fas fa-camera"></i>
                    </div>
                </div>
```

with:

```html
                <div class="avatar-wrapper">
                    <div class="avatar-placeholder" id="avatarDisplay">
                        {% if current_user.profile_picture %}
                        <img src="{{ url_for('static', filename=current_user.profile_picture) }}" alt="Profile Picture" style="width:100%;height:100%;object-fit:cover;border-radius:50%;">
                        {% else %}
                        <i class="fas fa-user-graduate fa-3x"></i>
                        {% endif %}
                    </div>
                    <div class="edit-avatar-btn" id="editAvatarBtn">
                        <i class="fas fa-camera"></i>
                    </div>
                </div>
```

- [ ] **Step 3: Wire the left card's programme/semester/session**

Replace line 218:
```html
                <div class="student-badge"><i class="fas fa-id-card"></i> <span id="profileMatric">{{ current_user.reg_no }}</span> · <span id="profileProgram">Computer Science</span></div>
```
with:
```html
                <div class="student-badge"><i class="fas fa-id-card"></i> <span id="profileMatric">{{ current_user.reg_no }}</span> · <span id="profileProgram">{{ profile_display.programme }}</span></div>
```

Replace line 222:
```html
                <div class="detail-item"><i class="fas fa-graduation-cap"></i> <span><strong>Program:</strong> <span id="displayProgram">B.Sc. Computer Science</span></span></div>
```
with:
```html
                <div class="detail-item"><i class="fas fa-graduation-cap"></i> <span><strong>Program:</strong> <span id="displayProgram">{{ profile_display.programme }}</span></span></div>
```

Replace line 223:
```html
                <div class="detail-item"><i class="fas fa-calendar-week"></i> <span><strong>Semester:</strong> <span id="displaySemester">Year 3 · Semester 2</span></span></div>
```
with:
```html
                <div class="detail-item"><i class="fas fa-calendar-week"></i> <span><strong>Semester:</strong> <span id="displaySemester">{{ profile_display.level_semester }}</span></span></div>
```

Replace line 225:
```html
                <div class="detail-item"><i class="fas fa-chalkboard"></i> <span><strong>Session:</strong> <span id="displaySession">2024/2025</span></span></div>
```
with:
```html
                <div class="detail-item"><i class="fas fa-chalkboard"></i> <span><strong>Session:</strong> <span id="displaySession">{{ profile_display.session }}</span></span></div>
```

- [ ] **Step 4: Wire the settings tab's programme/semester/session**

Replace line 290:
```html
                            <span class="field-display" id="displayProgramField">B.Sc. Computer Science</span>
```
with:
```html
                            <span class="field-display" id="displayProgramField">{{ profile_display.programme }}</span>
```

Replace line 294:
```html
                            <span class="field-display" id="displaySemesterField">Year 3 · Semester 2</span>
```
with:
```html
                            <span class="field-display" id="displaySemesterField">{{ profile_display.level_semester }}</span>
```

Replace line 305:
```html
                            <span class="field-display" id="displaySessionField">2024/2025</span>
```
with:
```html
                            <span class="field-display" id="displaySessionField">{{ profile_display.session }}</span>
```

- [ ] **Step 5: Verify the app still boots**

Run: `python -c "import app; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add app.py templates/profile.html
git commit -m "feat: wire profile page to real student data, fix missing login_required"
```

(Full visual verification against seeded accounts happens in Task 7.)

---

### Task 5: Empty-state the navbar notification badge

**Files:**
- Modify: `templates/base.html`

**Interfaces:** none (no route currently provides an unread count; Jinja's default `Undefined` is falsy in an `{% if %}`, so this is safe without any route change, and becomes a one-line hookup point once a real Notification model exists).

- [ ] **Step 1: Guard the badge**

In `templates/base.html`, replace line 33:

```html
                <a href="{{ url_for('announcements') }}"><i class="fas fa-bell"></i> Notifications <span class="notif-badge">3</span></a>
```

with:

```html
                <a href="{{ url_for('announcements') }}"><i class="fas fa-bell"></i> Notifications {% if unread_notification_count %}<span class="notif-badge">{{ unread_notification_count }}</span>{% endif %}</a>
```

- [ ] **Step 2: Verify the app still boots and the badge is absent**

Run: `python -c "import app; print('OK')"`
Expected: `OK`

(Visual confirmation that no badge renders happens in Task 7 — no route passes `unread_notification_count`, so it's undefined on every page, which Jinja treats as falsy without raising.)

- [ ] **Step 3: Commit**

```bash
git add templates/base.html
git commit -m "fix: stop showing a fabricated notification count in the navbar"
```

---

### Task 6: Remove dead code (`add.html`, `/add` route, unused demo photo)

**Files:**
- Delete: `templates/add.html`
- Delete: `static/uploads/profile.jpeg`
- Modify: `app.py` (remove the `add()` route)

**Interfaces:** none.

- [ ] **Step 1: Confirm `add.html`/`/add` are truly unreferenced**

Run: `grep -rn "url_for('add')" templates/` (search templates only — `app.py` itself defines the route being deleted in Step 2, so it's expected to reference `add` there; this check is about whether any *other* code links to it).
Expected: no matches. (Be careful reading results if you broaden the search pattern — `add_drop` and `url_for('add_drop')` contain the substring `add` but are a different, unrelated endpoint that must NOT be touched.)

- [ ] **Step 2: Delete the route**

In `app.py`, delete the `add()` view entirely:

```python
@app.route('/add')
def add():
    return render_template('add.html')
```

- [ ] **Step 3: Delete the files**

```bash
rm templates/add.html
rm static/uploads/profile.jpeg
```

- [ ] **Step 4: Verify the app still boots**

Run: `python -c "import app; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add -A app.py templates/add.html static/uploads/profile.jpeg
git commit -m "chore: remove dead /add route and unused demo profile photo"
```

---

### Task 7: End-to-end manual verification

**Files:** none (verification only)

- [ ] **Step 1: Start the app**

Run: `python app.py`
Expected: server starts on `http://localhost:4050` with no tracebacks.

- [ ] **Step 2: Verify each of the 4 seeded students on dashboard + profile**

`seed_dev_data.py` calls `user.set_password(DEFAULT_PASSWORD)` unconditionally for all 4 accounts regardless of `first_login`. Since Task 1 Step 3 reseeded the database fresh (and nothing between Task 1 and here logs in and changes a password), all 4 accounts still authenticate with reg_no / `Default@123` right now.

First, confirm the underlying data directly:

```bash
python -c "
from app import app
from models import User

with app.app_context():
    for reg_no in ['2308-2301-0001', '2308-2301-0002', '2308-2301-0003', '2308-2301-0004']:
        u = User.query.filter_by(reg_no=reg_no).first()
        print(reg_no, '| name:', u.name, '| course:', u.course, '| level:', u.level, '| semester:', u.semester, '| session:', u.session, '| picture:', u.profile_picture)
"
```

Then, with the server running, log in as each of the 4 accounts (reg_no / `Default@123`) in turn:

- [ ] Log in as a `first_login=True` account (0001 or 0004), complete/skip to dashboard as appropriate for that account's `onboarding_completed` state.
- [ ] On the dashboard: confirm Programme shows the real `course` value (e.g. "ND Computer Science"), Semester shows the real `level_semester` value (e.g. "Year 1 · 1st Semester"), profile picture shows the icon fallback (no `profile_picture` set for 0001) or the real uploaded photo (if the account has one from onboarding).
- [ ] Confirm the "Registered Courses" and "Recent payment history" sections show their empty-state messages, not fake tables.
- [ ] Confirm the navbar shows no notification badge next to "Notifications".
- [ ] On the profile page: confirm Programme/Semester/Session show real values in both the left card and the settings tab, consistently.
- [ ] Repeat the dashboard/profile checks for Student 0003 (International program — confirm `level_semester` shows just the semester, e.g. "2nd Semester", with no level segment, since `level=None`).

- [ ] **Step 3: Verify the `profile()` login fix**

Run:
```bash
python -c "
from app import app
with app.test_client() as c:
    r = c.get('/profile', follow_redirects=False)
    assert r.status_code == 302 and '/login' in r.headers.get('Location', ''), (r.status_code, r.headers.get('Location'))
    print('PASS: /profile redirects to login when not authenticated')
"
```
Expected: `PASS: /profile redirects to login when not authenticated` (before this milestone, this would have 500'd instead).

- [ ] **Step 4: Verify `/add` is gone**

Run:
```bash
python -c "
from app import app
with app.test_client() as c:
    r = c.get('/add')
    assert r.status_code == 404, r.status_code
    print('PASS: /add route removed')
"
```
Expected: `PASS: /add route removed`

- [ ] **Step 5: Confirm untouched pages are still untouched**

Spot-check that `registration.html`, `add_drop.html`, `my_courses.html`, `payments_history.html`, `payment_summary.html`, `announcements.html`, and the dashboard's announcement banner still show their original mock content, unchanged (per the explicit out-of-scope decision) — a quick `git diff main -- templates/registration.html templates/add_drop.html templates/my_courses.html templates/payments_history.html templates/payment_summary.html templates/announcements.html` should show no changes.

- [ ] **Step 6: Record results**

No commit needed — verification only. If any step fails, fix the relevant earlier task's code and re-run that task's own verification before re-running this task's affected step.
