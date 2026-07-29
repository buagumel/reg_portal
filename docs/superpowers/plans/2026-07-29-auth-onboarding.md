# Authentication & Onboarding Stepper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Force new students through a strong-password change and a 3-step onboarding wizard (student info, email OTP verification, review & confirm) before they can reach the dashboard, while returning students go straight in.

**Architecture:** Flask stays a single `app.py` route file (existing project convention — confirmed with the user, not switching to Blueprints). New pure-logic helper modules (`auth_helpers.py`, `onboarding_helpers.py`) keep validation/gate/OTP logic out of the route bodies and independently testable. Frontend stays plain Jinja2 + vanilla JS with no bundler, using native ES modules (`<script type="module">`, `import`/`export`) for real file separation (`static/js/shared/`, `static/js/onboarding/`, `static/js/auth/`).

**Tech Stack:** Flask 3, Flask-SQLAlchemy, Flask-Login, Flask-Mail, Flask-WTF (CSRF), SQLite (dev), vanilla JS (ES modules), Jinja2.

## Global Constraints

- Password policy: minimum 8 characters, at least one uppercase, one lowercase, one number, one special character. Enforced identically by `/force-password-change` and `/change-password`.
- OTP: 6-digit code, 5-minute expiry, maximum 3 verification attempts before the code is invalidated and a resend is required. State lives in the Flask `session`, not the database.
- Profile picture: required at onboarding; PNG/JPG/JPEG/WEBP only; max 2MB.
- All JSON endpoints return `{'success': bool, 'message': str, ...}` with an appropriate HTTP status code, matching the existing project convention.
- No new pip dependencies. No Alembic migration — the dev database (`instance/database.db`, gitignored) is deleted and rebuilt via the existing `db.create_all()` call in `app.py`.
- Out of scope: login-attempt lockout/progressive delays, JWT session tokens, dashboard/registration/payments/admin features. Do not touch those.
- No test framework exists in this repo. Pure-logic helper functions are verified with throwaway `python -c` assertions (no new dependency). Routes and UI are verified manually via curl and the browser, per the approved spec's testing approach.

---

### Task 1: Add onboarding columns to the User model and reset the dev database

**Files:**
- Modify: `models.py:16-32` (User model column declarations)

**Interfaces:**
- Produces: `User.first_login` (bool, default `True`), `User.onboarding_completed` (bool, default `False`), `User.semester` (str|None), `User.department` (str|None), `User.course` (str|None), `User.profile_picture` (str|None) — consumed by every later task.

- [ ] **Step 1: Add the new columns**

Edit `models.py`, inserting after the existing `is_admin` column (currently the last column before the blank line and `set_password` method):

```python
    is_admin = db.Column(db.Boolean, default=False) # False = Student, True = Admin
    first_login = db.Column(db.Boolean, default=True, nullable=False)
    onboarding_completed = db.Column(db.Boolean, default=False, nullable=False)
    semester = db.Column(db.String(50))
    department = db.Column(db.String(150))
    course = db.Column(db.String(150))
    profile_picture = db.Column(db.String(300))
```

- [ ] **Step 2: Delete the dev database so it rebuilds with the new columns**

Run: `rm "c:\Users\buagu\OneDrive\Documents\reg_portal\instance\database.db"`

(If the file doesn't exist yet, that's fine — `db.create_all()` will create it fresh on next app start.)

- [ ] **Step 3: Verify the model imports and the new columns exist**

Run: `python -c "from app import app; from models import User; print([c.name for c in User.__table__.columns])"`

Expected: prints a column list including `first_login`, `onboarding_completed`, `semester`, `department`, `course`, `profile_picture`, and no errors/tracebacks. (This also confirms `db.create_all()` ran and rebuilt `instance/database.db` without errors.)

- [ ] **Step 4: Commit**

```bash
git add models.py
git commit -m "feat: add onboarding fields to User model"
```

---

### Task 2: Password strength validator and access-gate logic (`auth_helpers.py`)

**Files:**
- Create: `auth_helpers.py`

**Interfaces:**
- Produces: `validate_password_strength(password: str) -> list[str]` (empty list = valid; otherwise a list of unmet-rule descriptions), `is_valid_email(email: str) -> bool`, `get_gate_redirect(user) -> str | None` (endpoint name the user must be sent to, or `None` if fully cleared). Consumed by Tasks 3, 5, 6, 9, 11.

- [ ] **Step 1: Write a throwaway verification script and confirm it fails (module doesn't exist yet)**

Run:
```bash
python -c "
from auth_helpers import validate_password_strength, is_valid_email, get_gate_redirect
assert validate_password_strength('weak') != []
assert validate_password_strength('Str0ng!Pass') == []
assert is_valid_email('a@b.com') is True
assert is_valid_email('not-an-email') is False
print('OK')
"
```
Expected: `ModuleNotFoundError: No module named 'auth_helpers'`

- [ ] **Step 2: Create `auth_helpers.py`**

```python
import re

PASSWORD_RULES = [
    (lambda p: len(p) >= 8, 'at least 8 characters'),
    (lambda p: re.search(r'[A-Z]', p) is not None, 'an uppercase letter'),
    (lambda p: re.search(r'[a-z]', p) is not None, 'a lowercase letter'),
    (lambda p: re.search(r'[0-9]', p) is not None, 'a number'),
    (lambda p: re.search(r'[^A-Za-z0-9]', p) is not None, 'a special character'),
]

EMAIL_REGEX = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


def validate_password_strength(password):
    """Return a list of unmet rule descriptions. Empty list means the password is valid."""
    return [desc for check, desc in PASSWORD_RULES if not check(password)]


def is_valid_email(email):
    return bool(EMAIL_REGEX.match(email))


def get_gate_redirect(user):
    """Return the endpoint name the user must be redirected to before they can access
    any other page, or None if they're fully cleared for normal access."""
    if user.first_login:
        return 'force_password_change'
    if not user.onboarding_completed:
        return 'onboarding'
    if not user.email_verified:
        return 'profile'
    return None
```

- [ ] **Step 3: Re-run the verification script, and add gate-logic checks**

Run:
```bash
python -c "
from auth_helpers import validate_password_strength, is_valid_email, get_gate_redirect

assert validate_password_strength('weak') != []
assert validate_password_strength('Str0ng!Pass') == []
assert is_valid_email('a@b.com') is True
assert is_valid_email('not-an-email') is False

class FakeUser:
    def __init__(self, first_login, onboarding_completed, email_verified):
        self.first_login = first_login
        self.onboarding_completed = onboarding_completed
        self.email_verified = email_verified

assert get_gate_redirect(FakeUser(True, False, False)) == 'force_password_change'
assert get_gate_redirect(FakeUser(False, False, False)) == 'onboarding'
assert get_gate_redirect(FakeUser(False, True, False)) == 'profile'
assert get_gate_redirect(FakeUser(False, True, True)) is None
print('OK')
"
```
Expected: `OK` with no assertion errors.

- [ ] **Step 4: Commit**

```bash
git add auth_helpers.py
git commit -m "feat: add password strength validator and access-gate logic"
```

---

### Task 3: Wire the access gate into `app.py` and remove the dead `/reg` route

**Files:**
- Modify: `app.py:1-19` (imports)
- Modify: `app.py:47-70` (before_request hook)
- Modify: `app.py:72-104` (delete `/reg` route)
- Modify: `app.py:162-193` (login route)

**Interfaces:**
- Consumes: `get_gate_redirect(user)` from Task 2.

- [ ] **Step 1: Add the import**

In `app.py`, add near the other local imports (after `from constants_file import ...`):

```python
from auth_helpers import get_gate_redirect
```

- [ ] **Step 2: Replace the before_request hook**

Replace the existing `check_email_verification` function (`app.py:47-70`) with:

```python
@app.before_request
def enforce_onboarding_gate():
    if not current_user.is_authenticated:
        return None

    exempt_endpoints = {
        'login', 'logout', 'static', 'admin',
        'force_password_change',
        'onboarding', 'onboarding_save_info', 'onboarding_complete',
        'send_email_code', 'verify_email_code',
        'profile',
    }
    if request.endpoint in exempt_endpoints:
        return None

    redirect_endpoint = get_gate_redirect(current_user)
    if redirect_endpoint is None:
        return None

    if request.method == 'GET':
        return redirect(url_for(redirect_endpoint))

    return jsonify({'success': False, 'message': 'Please complete the required step before continuing.'}), 403
```

- [ ] **Step 3: Delete the `/reg` route**

Remove the entire `@app.route('/reg', ...)` function (`app.py:72-104`), including its `"""Dev mode only"""` docstring. It's superseded by `seed_dev_data.py` in Task 12 and would fail on a second hit anyway due to the unique constraints on `reg_no`/`email`.

- [ ] **Step 4: Update the login route to use the gate**

Replace the two `current_user.is_authenticated` / post-login redirect blocks in the `login()` view (`app.py:162-193`):

```python
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        redirect_endpoint = get_gate_redirect(current_user) or 'dashboard'
        return redirect(url_for(redirect_endpoint))

    if request.method == 'POST':
        identifier = request.form.get('studentId', '').strip()
        password = request.form.get('password', '').strip()
        remember = True if request.form.get('rememberCheck') else False
        show_password = True if request.form.get('show_password') == 'on' else False

        user = User.query.filter(
            (User.reg_no == identifier) | (User.email == identifier)
        ).first()

        if user and user.check_password(password):
            login_user(user, remember=remember)
            next_page = request.args.get('next')
            redirect_endpoint = get_gate_redirect(current_user) or 'dashboard'
            return redirect(next_page or url_for(redirect_endpoint))
        else:
            return render_template(
                'login.html',
                error="Invalid registration number/email or password.",
                studentId=identifier,
                password=password,
                remember=remember,
                show_password=show_password
            )

    return render_template('login.html')
```

- [ ] **Step 5: Verify the app still boots**

Run: `python -c "import app; print('OK')"`
Expected: `OK`, no tracebacks (confirms no syntax errors and `/reg` removal didn't break other references — there are none, per the earlier codebase search).

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "refactor: route login/before_request through the shared access gate, drop dead /reg route"
```

---

### Task 4: Shared frontend utilities (toast, API wrapper, validation)

**Files:**
- Create: `static/js/shared/toast.js`
- Create: `static/js/shared/api.js`
- Create: `static/js/shared/validation.js`

**Interfaces:**
- Produces: `showToast(message, isError=false)`, `postJson(url, body) -> Promise<object>`, `postForm(url, formData) -> Promise<object>`, `PASSWORD_RULES`, `checkPasswordRules(password) -> [{key, met}]`, `isPasswordValid(password) -> bool`, `isValidEmail(email) -> bool`. Consumed by Tasks 5, 9, 10, 11.

- [ ] **Step 1: Create `static/js/shared/toast.js`**

```js
export function showToast(message, isError = false) {
    const toast = document.getElementById('toastMsg');
    if (!toast) return;
    toast.textContent = message;
    toast.style.backgroundColor = isError ? '#b13e3e' : '#1f4d6e';
    toast.style.display = 'block';
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(() => {
        toast.style.display = 'none';
    }, 3000);
}
```

- [ ] **Step 2: Create `static/js/shared/api.js`**

```js
function getCsrfToken() {
    const el = document.getElementById('csrf_token');
    return el ? el.value : '';
}

export async function postJson(url, body) {
    let response;
    try {
        response = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify(body)
        });
    } catch (err) {
        return { success: false, message: 'Network error. Please check your connection and try again.' };
    }
    try {
        return await response.json();
    } catch (err) {
        return { success: false, message: 'Unexpected server response.' };
    }
}

export async function postForm(url, formData) {
    let response;
    try {
        response = await fetch(url, {
            method: 'POST',
            headers: { 'X-CSRFToken': getCsrfToken() },
            body: formData
        });
    } catch (err) {
        return { success: false, message: 'Network error. Please check your connection and try again.' };
    }
    try {
        return await response.json();
    } catch (err) {
        return { success: false, message: 'Unexpected server response.' };
    }
}
```

- [ ] **Step 3: Create `static/js/shared/validation.js`**

```js
export const PASSWORD_RULES = [
    { key: 'length', test: (p) => p.length >= 8, label: 'At least 8 characters' },
    { key: 'uppercase', test: (p) => /[A-Z]/.test(p), label: 'An uppercase letter' },
    { key: 'lowercase', test: (p) => /[a-z]/.test(p), label: 'A lowercase letter' },
    { key: 'number', test: (p) => /[0-9]/.test(p), label: 'A number' },
    { key: 'special', test: (p) => /[^A-Za-z0-9]/.test(p), label: 'A special character' }
];

export function checkPasswordRules(password) {
    return PASSWORD_RULES.map((rule) => ({ key: rule.key, met: rule.test(password) }));
}

export function isPasswordValid(password) {
    return PASSWORD_RULES.every((rule) => rule.test(password));
}

export function isValidEmail(email) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}
```

- [ ] **Step 4: Verify with Node (syntax/export sanity check only — the browser is the real runtime)**

Run: `node -e "import('./static/js/shared/validation.js').then(m => { console.log(m.isPasswordValid('Str0ng!Pass'), m.isPasswordValid('weak'), m.isValidEmail('a@b.com')); })"`
Expected: `true false true`

- [ ] **Step 5: Commit**

```bash
git add static/js/shared/toast.js static/js/shared/api.js static/js/shared/validation.js
git commit -m "feat: add shared frontend toast/api/validation modules"
```

---

### Task 5: Forced password-change page (route + template + CSS + JS)

**Files:**
- Modify: `app.py` (add route, after the `check_password` route)
- Create: `templates/force_password_change.html`
- Create: `static/css/force_password_change.css`
- Create: `static/js/auth/password-change.js`

**Interfaces:**
- Consumes: `validate_password_strength`, `get_gate_redirect` from Task 2; `showToast`, `postJson`, `checkPasswordRules`, `isPasswordValid` from Task 4.
- Produces: `GET/POST /force-password-change` (endpoint `force_password_change`) — consumed by the gate in Task 3 and by Task 12's manual verification.

- [ ] **Step 1: Add the route to `app.py`**

Add after the `/change-password` route:

```python
@app.route('/force-password-change', methods=['GET', 'POST'])
@login_required
def force_password_change():
    if request.method == 'GET':
        if not current_user.first_login:
            return redirect(url_for(get_gate_redirect(current_user) or 'dashboard'))
        return render_template('force_password_change.html')

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    new_pass = data.get('new', '').strip()
    confirm = data.get('confirm', '').strip()

    if not new_pass:
        return jsonify({'success': False, 'message': 'New password is required'}), 400
    if new_pass != confirm:
        return jsonify({'success': False, 'message': 'Passwords do not match'}), 400

    failed_rules = validate_password_strength(new_pass)
    if failed_rules:
        return jsonify({'success': False, 'message': 'Password must contain ' + ', '.join(failed_rules) + '.'}), 400

    current_user.set_password(new_pass)
    current_user.first_login = False
    db.session.commit()

    redirect_endpoint = get_gate_redirect(current_user) or 'dashboard'
    return jsonify({'success': True, 'message': 'Password changed successfully.', 'redirect': url_for(redirect_endpoint)})
```

Update the import line from Task 3 to also bring in `validate_password_strength`:

```python
from auth_helpers import get_gate_redirect, validate_password_strength
```

- [ ] **Step 2: Create `templates/force_password_change.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Set a New Password | JSPICT</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,300;14..32,400;14..32,500;14..32,600;14..32,700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/login.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/force_password_change.css') }}">
</head>
<body>
    <div class="giant-bg"></div>

    <div class="login-container">
        <div class="login-left">
            <div class="school-logo">
                <img class="school-logo-img" src="{{ url_for('static', filename='img/jspict-logo.png') }}" alt="JSPICT Logo">
            </div>
            <div class="school-name">JSPICT</div>
            <div class="school-tagline">Jigawa State Polytechnic for Information Communication Technology, Kazaure</div>
            <div class="welcome-text">
                <p><i class="fas fa-quote-left"></i> For your security, set a new password before continuing.</p>
            </div>
        </div>

        <div class="login-right">
            <div class="form-header">
                <h2>Set a new password</h2>
                <p>This is your first login &mdash; choose a new password to continue</p>
            </div>

            <form id="passwordChangeForm">
                <input type="hidden" id="csrf_token" value="{{ csrf_token() }}">

                <div class="input-group">
                    <label>New Password</label>
                    <div class="input-icon">
                        <i class="fas fa-key"></i>
                        <input type="password" id="newPassword" required>
                    </div>
                </div>

                <div class="input-group">
                    <label>Confirm Password</label>
                    <div class="input-icon">
                        <i class="fas fa-key"></i>
                        <input type="password" id="confirmPassword" required>
                    </div>
                </div>

                <ul class="password-rules" id="passwordRules">
                    <li data-rule="length"><i class="fas fa-circle"></i> At least 8 characters</li>
                    <li data-rule="uppercase"><i class="fas fa-circle"></i> An uppercase letter</li>
                    <li data-rule="lowercase"><i class="fas fa-circle"></i> A lowercase letter</li>
                    <li data-rule="number"><i class="fas fa-circle"></i> A number</li>
                    <li data-rule="special"><i class="fas fa-circle"></i> A special character</li>
                </ul>

                <button type="submit" class="login-btn" id="submitBtn">
                    <i class="fas fa-arrow-right-to-bracket"></i> Continue
                </button>
            </form>
        </div>
    </div>

    <div id="toastMsg" class="alert-toast"></div>

    <script type="module" src="{{ url_for('static', filename='js/auth/password-change.js') }}"></script>
</body>
</html>
```

- [ ] **Step 3: Create `static/css/force_password_change.css`**

```css
.password-rules {
    list-style: none;
    padding: 0;
    margin: 0 0 1.5rem;
    max-width: 420px;
    margin-left: auto;
    margin-right: auto;
}

.password-rules li {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.85rem;
    color: #8a97a8;
    padding: 0.2rem 0;
    transition: color 0.2s;
}

.password-rules li i {
    font-size: 0.5rem;
}

.password-rules li.met {
    color: #1f7840;
}

.password-rules li.met i {
    font-family: "Font Awesome 6 Free";
    font-weight: 900;
}

.password-rules li.met i::before {
    content: "\f00c";
}

.login-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
}
```

- [ ] **Step 4: Create `static/js/auth/password-change.js`**

```js
import { showToast } from '../shared/toast.js';
import { postJson } from '../shared/api.js';
import { checkPasswordRules, isPasswordValid } from '../shared/validation.js';

const form = document.getElementById('passwordChangeForm');
const newPasswordInput = document.getElementById('newPassword');
const confirmPasswordInput = document.getElementById('confirmPassword');
const submitBtn = document.getElementById('submitBtn');
const rulesList = document.getElementById('passwordRules');

function updateRuleChecklist() {
    const results = checkPasswordRules(newPasswordInput.value);
    results.forEach(({ key, met }) => {
        const item = rulesList.querySelector(`[data-rule="${key}"]`);
        if (item) item.classList.toggle('met', met);
    });
}

newPasswordInput.addEventListener('input', updateRuleChecklist);

form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const newPassword = newPasswordInput.value;
    const confirmPassword = confirmPasswordInput.value;

    if (!isPasswordValid(newPassword)) {
        showToast('Password does not meet all requirements', true);
        return;
    }
    if (newPassword !== confirmPassword) {
        showToast('Passwords do not match', true);
        return;
    }

    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';

    const result = await postJson('/force-password-change', { new: newPassword, confirm: confirmPassword });

    if (result.success) {
        showToast(result.message, false);
        window.location.href = result.redirect;
    } else {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="fas fa-arrow-right-to-bracket"></i> Continue';
        showToast(result.message, true);
    }
});
```

- [ ] **Step 5: Verify the app still boots**

Run: `python -c "import app; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add app.py templates/force_password_change.html static/css/force_password_change.css static/js/auth/password-change.js
git commit -m "feat: add forced first-login password change page"
```

(Full end-to-end verification of this page against a seeded account happens in Task 13, once demo data exists.)

---

### Task 6: Upgrade `/change-password` to the shared strength rule

**Files:**
- Modify: `app.py:133-160` (existing `/change-password` route)
- Modify: `templates/profile.html:350` (the "Minimum 6 characters" placeholder hint, now stale)

**Interfaces:**
- Consumes: `validate_password_strength` from Task 2 (already imported in Task 5's step).

- [ ] **Step 1: Update the route**

Replace the body of `change_password()` in `app.py`:

```python
@app.route('/change-password', methods=['POST'])
@login_required
def change_password():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    current = data.get('current', '').strip()
    new_pass = data.get('new', '').strip()
    confirm = data.get('confirm', '').strip()

    if not current:
        return jsonify({'success': False, 'message': 'Current password is required'}), 400

    failed_rules = validate_password_strength(new_pass)
    if failed_rules:
        return jsonify({'success': False, 'message': 'Password must contain ' + ', '.join(failed_rules) + '.'}), 400
    if new_pass != confirm:
        return jsonify({'success': False, 'message': 'Passwords do not match'}), 400

    if not current_user.check_password(current):
        return jsonify({'success': False, 'message': 'Current password is incorrect'}), 400

    current_user.set_password(new_pass)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Password changed successfully'})
```

- [ ] **Step 2: Update the stale placeholder text in `templates/profile.html`**

Change:
```html
<input type="text" id="newPass" placeholder="Minimum 6 characters" class="masked">
```
to:
```html
<input type="text" id="newPass" placeholder="Min. 8 chars, upper, lower, number, symbol" class="masked">
```

- [ ] **Step 3: Verify the app still boots**

Run: `python -c "import app; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app.py templates/profile.html
git commit -m "fix: enforce one password policy across change-password and force-password-change"
```

---

### Task 7: OTP attempt-limit + profile picture upload helpers (`onboarding_helpers.py`), wired into the email-code routes

**Files:**
- Create: `onboarding_helpers.py`
- Modify: `app.py:267-301` (`/send-email-code`)
- Modify: `app.py:303-349` (`/verify-email-code`)

**Interfaces:**
- Produces: `start_otp_session(session, email) -> str` (returns the code), `register_failed_otp_attempt(session) -> int` (returns new attempt count), `otp_attempts_exceeded(session) -> bool`, `clear_otp_session(session) -> None`, `save_profile_picture(file_storage, reg_no, upload_folder) -> (path_or_None, error_or_None)`, `MAX_OTP_ATTEMPTS` (int). Consumed by Task 9 (picture upload) and this task's route updates; `otp.js` in Task 10 consumes the resulting JSON shape.

- [ ] **Step 1: Write a throwaway verification script and confirm it fails**

Run:
```bash
python -c "
from onboarding_helpers import start_otp_session, register_failed_otp_attempt, otp_attempts_exceeded, clear_otp_session, MAX_OTP_ATTEMPTS
print('OK')
"
```
Expected: `ModuleNotFoundError: No module named 'onboarding_helpers'`

- [ ] **Step 2: Create `onboarding_helpers.py`**

```python
import os
import random
import string
import time

from werkzeug.utils import secure_filename

MAX_OTP_ATTEMPTS = 3
OTP_EXPIRY_SECONDS = 300
ALLOWED_PICTURE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
MAX_PICTURE_SIZE_BYTES = 2 * 1024 * 1024


def start_otp_session(session, email):
    """Generate a new OTP, store it (with expiry + reset attempt count) in the session, return the code."""
    code = ''.join(random.choices(string.digits, k=6))
    session['email_verification_code'] = code
    session['email_verification_expiry'] = time.time() + OTP_EXPIRY_SECONDS
    session['pending_email'] = email
    session['email_verification_attempts'] = 0
    return code


def register_failed_otp_attempt(session):
    """Increment the failed-attempt counter, return the new count."""
    attempts = session.get('email_verification_attempts', 0) + 1
    session['email_verification_attempts'] = attempts
    return attempts


def otp_attempts_exceeded(session):
    return session.get('email_verification_attempts', 0) >= MAX_OTP_ATTEMPTS


def clear_otp_session(session):
    for key in ('email_verification_code', 'email_verification_expiry', 'pending_email', 'email_verification_attempts'):
        session.pop(key, None)


def save_profile_picture(file_storage, reg_no, upload_folder):
    """Validate and save an uploaded profile picture.

    Returns (relative_path, error_message) — exactly one of the two is None.
    relative_path is relative to the static/ folder, e.g. 'uploads/2308-2301-0001.jpg'.
    """
    if not file_storage or not file_storage.filename:
        return None, 'Profile picture is required'

    filename = secure_filename(file_storage.filename)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ALLOWED_PICTURE_EXTENSIONS:
        return None, 'Profile picture must be a PNG, JPG, or WEBP image'

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > MAX_PICTURE_SIZE_BYTES:
        return None, 'Profile picture must be smaller than 2MB'

    stored_filename = f"{secure_filename(reg_no)}.{ext}"
    file_storage.save(os.path.join(upload_folder, stored_filename))
    return f"uploads/{stored_filename}", None
```

- [ ] **Step 3: Re-run the verification script with real assertions**

Run:
```bash
python -c "
from onboarding_helpers import start_otp_session, register_failed_otp_attempt, otp_attempts_exceeded, clear_otp_session, MAX_OTP_ATTEMPTS

session = {}
code = start_otp_session(session, 'a@b.com')
assert len(code) == 6 and code.isdigit()
assert session['pending_email'] == 'a@b.com'
assert session['email_verification_attempts'] == 0

assert otp_attempts_exceeded(session) is False
register_failed_otp_attempt(session)
register_failed_otp_attempt(session)
assert otp_attempts_exceeded(session) is False
register_failed_otp_attempt(session)
assert otp_attempts_exceeded(session) is True
assert MAX_OTP_ATTEMPTS == 3

clear_otp_session(session)
assert session == {}
print('OK')
"
```
Expected: `OK`

- [ ] **Step 4: Wire the helpers into `/send-email-code`**

Replace the body of `send_email_code()` in `app.py`:

```python
@app.route('/send-email-code', methods=['POST'])
@login_required
def send_email_code():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    new_email = data.get('new_email', '').strip()
    if not new_email:
        return jsonify({'success': False, 'message': 'Email is required'}), 400
    if not is_valid_email(new_email):
        return jsonify({'success': False, 'message': 'Invalid email format'}), 400

    existing = User.query.filter(User.email == new_email, User.id != current_user.id).first()
    if existing:
        return jsonify({'success': False, 'message': 'Email already in use'}), 400

    code = start_otp_session(session, new_email)

    try:
        msg = Message('Email Verification Code', recipients=[new_email])
        msg.body = f'Your verification code is: {code}\nThis code expires in 5 minutes.'
        mail.send(msg)
    except Exception:
        clear_otp_session(session)
        return jsonify({'success': False, 'message': 'Failed to send email. Please try again.'}), 500

    return jsonify({'success': True, 'message': 'Verification code sent to your email.'})
```

- [ ] **Step 5: Wire the helpers into `/verify-email-code`**

Replace the body of `verify_email_code()` in `app.py`:

```python
@app.route('/verify-email-code', methods=['POST'])
@login_required
def verify_email_code():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request'}), 400

    code = data.get('code', '').strip()
    new_email = data.get('new_email', '').strip()
    if not code:
        return jsonify({'success': False, 'message': 'Verification code is required'}), 400

    stored_code = session.get('email_verification_code')
    expiry = session.get('email_verification_expiry')
    pending_email = session.get('pending_email')

    if not stored_code or not expiry or not pending_email:
        return jsonify({'success': False, 'message': 'No pending verification. Please request a new code.'}), 400

    if time.time() > expiry:
        clear_otp_session(session)
        return jsonify({'success': False, 'message': 'Verification code expired. Please request a new one.'}), 400

    if stored_code != code:
        attempts = register_failed_otp_attempt(session)
        if attempts >= MAX_OTP_ATTEMPTS:
            clear_otp_session(session)
            return jsonify({
                'success': False,
                'message': 'Maximum attempts exceeded. Please request a new code.',
                'max_attempts_reached': True
            }), 400
        remaining = MAX_OTP_ATTEMPTS - attempts
        return jsonify({'success': False, 'message': f'Invalid verification code. {remaining} attempt(s) remaining.'}), 400

    if new_email and new_email != pending_email:
        return jsonify({'success': False, 'message': 'Email mismatch. Please request a new code.'}), 400

    current_user.email = pending_email
    current_user.email_verified = True
    db.session.commit()

    clear_otp_session(session)

    return jsonify({
        'success': True,
        'message': 'Email updated and verified successfully.',
        'email': current_user.email,
        'email_verified': current_user.email_verified
    })
```

- [ ] **Step 6: Add the new imports to `app.py`**

Update the import lines from Tasks 3/5:

```python
from auth_helpers import get_gate_redirect, validate_password_strength, is_valid_email
from onboarding_helpers import (
    start_otp_session, register_failed_otp_attempt, otp_attempts_exceeded,
    clear_otp_session, save_profile_picture, MAX_OTP_ATTEMPTS
)
```

- [ ] **Step 7: Verify the app still boots**

Run: `python -c "import app; print('OK')"`
Expected: `OK`

- [ ] **Step 8: Commit**

```bash
git add onboarding_helpers.py app.py
git commit -m "feat: add OTP attempt limit and profile picture validation helpers"
```

(End-to-end OTP verification against a running server happens in Task 13, once the onboarding UI exists to exercise it — `/send-email-code` and `/verify-email-code` are also usable standalone via curl for a quick sanity check at this point if desired, using a logged-in session cookie.)

---

### Task 8: Shared stepper module (progress indicator + step navigation)

**Files:**
- Create: `static/js/shared/stepper.js`

**Interfaces:**
- Produces: `class Stepper` with constructor `{ steps: string[], container: Element, onStepChange?: (step: string) => void }`, methods `next()`, `back()`, `goTo(stepKey)`, `init()`, getter `currentStep`. Consumed by Task 9's `onboarding.js`.

- [ ] **Step 1: Create `static/js/shared/stepper.js`**

```js
export class Stepper {
    constructor({ steps, container, onStepChange }) {
        this.steps = steps;
        this.container = container;
        this.onStepChange = onStepChange || (() => {});
        this.currentIndex = 0;
    }

    get currentStep() {
        return this.steps[this.currentIndex];
    }

    goTo(stepKey) {
        const index = this.steps.indexOf(stepKey);
        if (index === -1) return;
        this.currentIndex = index;
        this._render();
    }

    next() {
        if (this.currentIndex < this.steps.length - 1) {
            this.currentIndex += 1;
            this._render();
        }
    }

    back() {
        if (this.currentIndex > 0) {
            this.currentIndex -= 1;
            this._render();
        }
    }

    init() {
        this._render();
    }

    _render() {
        this.container.querySelectorAll('[data-step-panel]').forEach((panel) => {
            panel.style.display = panel.dataset.stepPanel === this.currentStep ? 'block' : 'none';
        });
        this.container.querySelectorAll('[data-progress-step]').forEach((node) => {
            const stepIndex = this.steps.indexOf(node.dataset.progressStep);
            node.classList.toggle('active', stepIndex === this.currentIndex);
            node.classList.toggle('completed', stepIndex < this.currentIndex);
        });
        this.onStepChange(this.currentStep);
    }
}
```

- [ ] **Step 2: Verify with Node (syntax/export sanity check)**

Run: `node -e "import('./static/js/shared/stepper.js').then(m => console.log(typeof m.Stepper))"`
Expected: `function`

- [ ] **Step 3: Commit**

```bash
git add static/js/shared/stepper.js
git commit -m "feat: add generic stepper module for multi-step wizards"
```

---

### Task 9: Onboarding Step 1 — student info form, page scaffold, and `/onboarding/save-info`

**Files:**
- Modify: `app.py` (add `GET /onboarding`, `POST /onboarding/save-info`)
- Create: `templates/onboarding.html`
- Create: `static/css/onboarding.css`
- Create: `static/js/onboarding/onboarding.js`

**Interfaces:**
- Consumes: `get_gate_redirect` (Task 2/3), `is_valid_email`, `save_profile_picture` (Task 7), `Stepper` (Task 8), `showToast`/`postJson`/`postForm`/`isValidEmail` (Task 4).
- Produces: `GET /onboarding` (endpoint `onboarding`), `POST /onboarding/save-info` (endpoint `onboarding_save_info`) returning `{success, message, errors?: {field: message}}`. `onboarding.js` exposes an in-memory `collected` object (`{email, phone, address, pictureFile}`) and a module-level `stepper` — both consumed by Tasks 10 and 11, which are appended to this same file.

- [ ] **Step 1: Add the `GET /onboarding` route**

Add to `app.py`, after the `force_password_change` route:

```python
@app.route('/onboarding')
@login_required
def onboarding():
    target = get_gate_redirect(current_user)
    if target != 'onboarding':
        return redirect(url_for(target or 'dashboard'))
    return render_template('onboarding.html')
```

(This reuses `get_gate_redirect` rather than re-deriving the same priority order inline, so the gate logic has exactly one source of truth — matching the pattern already used in `force_password_change()`'s GET handler.)

- [ ] **Step 2: Add the `POST /onboarding/save-info` route**

```python
@app.route('/onboarding/save-info', methods=['POST'])
@login_required
def onboarding_save_info():
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()
    address = request.form.get('address', '').strip()
    picture = request.files.get('profile_picture')

    errors = {}
    if not email:
        errors['email'] = 'Email is required'
    elif not is_valid_email(email):
        errors['email'] = 'Invalid email format'
    else:
        existing = User.query.filter(User.email == email, User.id != current_user.id).first()
        if existing:
            errors['email'] = 'Email already in use'

    if not phone:
        errors['phone'] = 'Phone number is required'
    if not address:
        errors['address'] = 'Address is required'

    picture_path, picture_error = save_profile_picture(
        picture, current_user.reg_no,
        os.path.join(app.static_folder, 'uploads')
    )
    if picture_error:
        errors['profile_picture'] = picture_error

    if errors:
        return jsonify({'success': False, 'message': 'Please correct the highlighted fields.', 'errors': errors}), 400

    current_user.email = email
    current_user.phone = phone
    current_user.address = address
    current_user.profile_picture = picture_path
    db.session.commit()

    return jsonify({'success': True, 'message': 'Information saved.'})
```

- [ ] **Step 3: Create `templates/onboarding.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Complete Your Profile | JSPICT</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,300;14..32,400;14..32,500;14..32,600;14..32,700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/onboarding.css') }}">
</head>
<body>
    <div class="onboarding-topbar">
        <img src="{{ url_for('static', filename='img/jspict-logo.png') }}" alt="JSPICT Logo" class="onboarding-logo">
        <span>JSPICT Portal Onboarding</span>
        <a href="{{ url_for('logout') }}" class="onboarding-logout"><i class="fas fa-sign-out-alt"></i> Logout</a>
    </div>

    <div class="onboarding-wrap">
        <ol class="progress-bar" id="progressBar">
            <li data-progress-step="info"><span class="progress-dot">1</span> Student Info</li>
            <li data-progress-step="otp"><span class="progress-dot">2</span> Verify Email</li>
            <li data-progress-step="review"><span class="progress-dot">3</span> Review & Confirm</li>
        </ol>

        <div class="onboarding-card" id="onboardingCard">
            <input type="hidden" id="csrf_token" value="{{ csrf_token() }}">

            <!-- STEP 1: STUDENT INFO -->
            <section data-step-panel="info" class="step-panel">
                <h2>Your Student Information</h2>
                <p class="step-subtitle">These details are on file and can't be changed here.</p>

                <div class="readonly-grid">
                    <div class="readonly-field"><label>Registration Number</label><span>{{ current_user.reg_no }}</span></div>
                    <div class="readonly-field"><label>Full Name</label><span>{{ current_user.name }}</span></div>
                    <div class="readonly-field"><label>Nationality</label><span>{{ current_user.nationality }}</span></div>
                    <div class="readonly-field"><label>State</label><span>{{ current_user.state }}</span></div>
                    <div class="readonly-field"><label>Local Government</label><span>{{ current_user.lga }}</span></div>
                    <div class="readonly-field"><label>Date of Birth</label><span>{{ current_user.formatted_dob }}</span></div>
                    <div class="readonly-field"><label>Semester</label><span>{{ current_user.semester }}</span></div>
                    <div class="readonly-field"><label>Department</label><span>{{ current_user.department }}</span></div>
                    <div class="readonly-field"><label>Course</label><span>{{ current_user.course }}</span></div>
                </div>

                <h3>Complete Your Profile</h3>
                <form id="infoForm">
                    <div class="input-group">
                        <label>Email</label>
                        <input type="email" id="infoEmail" name="email" required>
                        <span class="field-error" id="infoEmailError"></span>
                    </div>
                    <div class="input-group">
                        <label>Phone Number</label>
                        <input type="tel" id="infoPhone" name="phone" required>
                        <span class="field-error" id="infoPhoneError"></span>
                    </div>
                    <div class="input-group">
                        <label>Residential Address</label>
                        <input type="text" id="infoAddress" name="address" required>
                        <span class="field-error" id="infoAddressError"></span>
                    </div>
                    <div class="input-group">
                        <label>Profile Picture</label>
                        <input type="file" id="infoPicture" name="profile_picture" accept="image/png,image/jpeg,image/webp" required>
                        <span class="field-error" id="infoPictureError"></span>
                        <img id="picturePreview" class="picture-preview" style="display:none;" alt="Preview">
                    </div>

                    <div class="step-actions">
                        <button type="submit" class="onboarding-btn" id="infoNextBtn">
                            Next <i class="fas fa-arrow-right"></i>
                        </button>
                    </div>
                </form>
            </section>

            <!-- STEP 2: EMAIL VERIFICATION -->
            <section data-step-panel="otp" class="step-panel" style="display:none;">
                <h2>Verify Your Email</h2>
                <p class="step-subtitle">We've sent a 6-digit code to <strong id="otpEmailTarget"></strong></p>

                <div class="input-group otp-input-group">
                    <label>Verification Code</label>
                    <input type="text" id="otpCode" maxlength="6" inputmode="numeric" autocomplete="one-time-code">
                    <span class="field-error" id="otpError"></span>
                </div>

                <div class="otp-meta">
                    <span id="otpTimer">Code expires in 5:00</span>
                    <button type="button" class="link-btn" id="resendOtpBtn" disabled>Resend code</button>
                </div>

                <div class="step-actions">
                    <button type="button" class="onboarding-btn-outline" id="otpBackBtn"><i class="fas fa-arrow-left"></i> Back</button>
                    <button type="button" class="onboarding-btn" id="otpVerifyBtn">Verify <i class="fas fa-arrow-right"></i></button>
                </div>
            </section>

            <!-- STEP 3: REVIEW & CONFIRM -->
            <section data-step-panel="review" class="step-panel" style="display:none;">
                <h2>Review Your Information</h2>
                <p class="step-subtitle">Please confirm everything looks correct before saving.</p>

                <div class="review-grid" id="reviewGrid"></div>

                <div class="step-actions">
                    <button type="button" class="onboarding-btn-outline" id="reviewEditBtn"><i class="fas fa-pencil-alt"></i> Edit</button>
                    <button type="button" class="onboarding-btn" id="reviewConfirmBtn"><i class="fas fa-check"></i> Confirm & Save</button>
                </div>
            </section>
        </div>
    </div>

    <div id="toastMsg" class="alert-toast"></div>

    <script type="module" src="{{ url_for('static', filename='js/onboarding/onboarding.js') }}"></script>
</body>
</html>
```

- [ ] **Step 4: Create `static/css/onboarding.css`**

```css
* { box-sizing: border-box; }

body {
    margin: 0;
    font-family: 'Inter', sans-serif;
    background: #f0f5fc;
    min-height: 100vh;
}

.onboarding-topbar {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 1rem 1.5rem;
    background: #0f3150;
    color: white;
    font-weight: 600;
}

.onboarding-logo {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    object-fit: cover;
}

.onboarding-logout {
    margin-left: auto;
    color: #cfe0f0;
    text-decoration: none;
    font-size: 0.9rem;
    font-weight: 500;
}

.onboarding-logout:hover {
    color: white;
}

.onboarding-wrap {
    max-width: 760px;
    margin: 2.5rem auto;
    padding: 0 1.25rem 3rem;
}

.progress-bar {
    display: flex;
    justify-content: space-between;
    list-style: none;
    padding: 0;
    margin: 0 0 2rem;
}

.progress-bar li {
    flex: 1;
    text-align: center;
    font-size: 0.85rem;
    color: #8a97a8;
    font-weight: 600;
    position: relative;
}

.progress-bar li:not(:last-child)::after {
    content: "";
    position: absolute;
    top: 15px;
    left: 55%;
    width: 90%;
    height: 2px;
    background: #dce5f0;
    z-index: 0;
}

.progress-bar li.completed:not(:last-child)::after {
    background: #1f7840;
}

.progress-dot {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: #dce5f0;
    color: #5a7b99;
    margin: 0 auto 0.4rem;
    position: relative;
    z-index: 1;
    font-weight: 700;
}

.progress-bar li.active .progress-dot {
    background: #1f6392;
    color: white;
}

.progress-bar li.completed .progress-dot {
    background: #1f7840;
    color: white;
}

.onboarding-card {
    background: white;
    border-radius: 1.5rem;
    padding: 2rem 2.25rem;
    box-shadow: 0 10px 30px rgba(0,0,0,0.06);
}

.step-panel h2 {
    margin: 0 0 0.25rem;
    color: #0f3150;
    font-size: 1.5rem;
}

.step-subtitle {
    color: #5a7b99;
    margin: 0 0 1.5rem;
    font-size: 0.95rem;
}

.readonly-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 0.9rem;
    margin-bottom: 1.75rem;
}

.readonly-field label {
    display: block;
    font-size: 0.75rem;
    font-weight: 600;
    color: #8a97a8;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    margin-bottom: 0.2rem;
}

.readonly-field span {
    display: block;
    background: #f1f3f5;
    border: 1px solid #dee2e6;
    border-radius: 8px;
    padding: 0.5rem 0.75rem;
    color: #2d3748;
    font-weight: 500;
    font-size: 0.9rem;
}

.step-panel h3 {
    color: #0f3150;
    font-size: 1.1rem;
    margin: 0 0 1rem;
}

.input-group {
    margin-bottom: 1.25rem;
}

.input-group label {
    display: block;
    font-weight: 600;
    font-size: 0.85rem;
    margin-bottom: 0.4rem;
    color: #1e4668;
}

.input-group input[type="text"],
.input-group input[type="email"],
.input-group input[type="tel"],
.input-group input[type="file"] {
    width: 100%;
    padding: 0.75rem 1rem;
    border: 1.5px solid #dce5f0;
    border-radius: 10px;
    font-size: 0.95rem;
    font-family: inherit;
}

.input-group input:focus {
    outline: none;
    border-color: #1f6392;
    box-shadow: 0 0 0 3px rgba(31, 99, 146, 0.15);
}

.field-error {
    display: block;
    color: #c23d3d;
    font-size: 0.8rem;
    margin-top: 0.3rem;
    min-height: 1em;
}

.picture-preview {
    display: block;
    margin-top: 0.75rem;
    width: 96px;
    height: 96px;
    object-fit: cover;
    border-radius: 50%;
    border: 2px solid #dce5f0;
}

.step-actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.75rem;
    margin-top: 1.5rem;
}

.onboarding-btn {
    background: #0f3a5f;
    color: white;
    border: none;
    padding: 0.75rem 1.5rem;
    border-radius: 60px;
    font-weight: 700;
    font-size: 0.95rem;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
}

.onboarding-btn:hover {
    background: #0c2d48;
}

.onboarding-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
}

.onboarding-btn-outline {
    background: transparent;
    color: #1e4668;
    border: 1.5px solid #dce5f0;
    padding: 0.75rem 1.5rem;
    border-radius: 60px;
    font-weight: 600;
    font-size: 0.95rem;
    cursor: pointer;
}

.onboarding-btn-outline:hover {
    background: #f1f3f5;
}

.link-btn {
    background: none;
    border: none;
    color: #1b5e8c;
    font-weight: 600;
    cursor: pointer;
    font-size: 0.85rem;
}

.link-btn:disabled {
    color: #b8c4d1;
    cursor: not-allowed;
}

.otp-input-group input {
    max-width: 220px;
    letter-spacing: 0.3em;
    font-size: 1.2rem;
    text-align: center;
}

.otp-meta {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.85rem;
    color: #5a7b99;
    margin-bottom: 1rem;
}

.review-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 0.9rem;
    margin-bottom: 1.5rem;
}

.review-item label {
    display: block;
    font-size: 0.75rem;
    font-weight: 600;
    color: #8a97a8;
    text-transform: uppercase;
    margin-bottom: 0.2rem;
}

.review-item span {
    display: block;
    background: #f1f3f5;
    border-radius: 8px;
    padding: 0.5rem 0.75rem;
    font-weight: 500;
    color: #2d3748;
}

.alert-toast {
    position: fixed;
    bottom: 25px;
    left: 50%;
    transform: translateX(-50%);
    background: #1f4d6e;
    color: white;
    padding: 0.7rem 1.5rem;
    border-radius: 60px;
    font-size: 0.85rem;
    z-index: 999;
    display: none;
    white-space: nowrap;
    box-shadow: 0 8px 20px rgba(0,0,0,0.2);
    font-weight: 500;
}

@media (max-width: 600px) {
    .onboarding-card {
        padding: 1.5rem 1.25rem;
        border-radius: 1rem;
    }
    .progress-bar li {
        font-size: 0.7rem;
    }
    .step-actions {
        flex-direction: column-reverse;
    }
    .step-actions button {
        width: 100%;
        justify-content: center;
    }
}
```

- [ ] **Step 5: Create `static/js/onboarding/onboarding.js` (Step 1 wiring only — Steps 2/3 are appended in Tasks 10/11)**

```js
import { showToast } from '../shared/toast.js';
import { postJson, postForm } from '../shared/api.js';
import { isValidEmail } from '../shared/validation.js';
import { Stepper } from '../shared/stepper.js';

export const collected = { email: '', phone: '', address: '', pictureFile: null };

const FIELD_ERROR_IDS = {
    email: 'infoEmailError',
    phone: 'infoPhoneError',
    address: 'infoAddressError',
    profile_picture: 'infoPictureError',
};

export const stepper = new Stepper({
    steps: ['info', 'otp', 'review'],
    container: document.querySelector('.onboarding-wrap'),
});

// ---- Step 1: Student Info ----
const infoForm = document.getElementById('infoForm');
const infoNextBtn = document.getElementById('infoNextBtn');
const pictureInput = document.getElementById('infoPicture');
const picturePreview = document.getElementById('picturePreview');

pictureInput.addEventListener('change', () => {
    const file = pictureInput.files[0];
    if (!file) { picturePreview.style.display = 'none'; return; }
    picturePreview.src = URL.createObjectURL(file);
    picturePreview.style.display = 'block';
});

function clearFieldErrors() {
    ['infoEmailError', 'infoPhoneError', 'infoAddressError', 'infoPictureError'].forEach((id) => {
        document.getElementById(id).textContent = '';
    });
}

infoForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearFieldErrors();

    const email = document.getElementById('infoEmail').value.trim();
    const phone = document.getElementById('infoPhone').value.trim();
    const address = document.getElementById('infoAddress').value.trim();
    const pictureFile = pictureInput.files[0];

    let hasError = false;
    if (!email || !isValidEmail(email)) {
        document.getElementById('infoEmailError').textContent = 'Enter a valid email address';
        hasError = true;
    }
    if (!phone) {
        document.getElementById('infoPhoneError').textContent = 'Phone number is required';
        hasError = true;
    }
    if (!address) {
        document.getElementById('infoAddressError').textContent = 'Address is required';
        hasError = true;
    }
    if (!pictureFile) {
        document.getElementById('infoPictureError').textContent = 'Profile picture is required';
        hasError = true;
    }
    if (hasError) return;

    infoNextBtn.disabled = true;
    infoNextBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';

    const formData = new FormData();
    formData.append('email', email);
    formData.append('phone', phone);
    formData.append('address', address);
    formData.append('profile_picture', pictureFile);

    const result = await postForm('/onboarding/save-info', formData);

    infoNextBtn.disabled = false;
    infoNextBtn.innerHTML = 'Next <i class="fas fa-arrow-right"></i>';

    if (!result.success) {
        if (result.errors) {
            Object.entries(result.errors).forEach(([field, msg]) => {
                const el = document.getElementById(FIELD_ERROR_IDS[field]);
                if (el) el.textContent = msg;
            });
        }
        showToast(result.message, true);
        return;
    }

    collected.email = email;
    collected.phone = phone;
    collected.address = address;
    collected.pictureFile = pictureFile;

    stepper.next();
});

stepper.init();
```

- [ ] **Step 6: Verify the app still boots**

Run: `python -c "import app; print('OK')"`
Expected: `OK`

- [ ] **Step 7: Manual browser check of Step 1 only**

Run: `python app.py`, then in a browser go to `http://localhost:4050/onboarding` while logged in as a `first_login=False, onboarding_completed=False` user (no seed data exists yet at this point in the plan — this check can be deferred to Task 13 once Task 12's seed script exists; skip this step for now if no such user is available yet).

- [ ] **Step 8: Commit**

```bash
git add app.py templates/onboarding.html static/css/onboarding.css static/js/onboarding/onboarding.js
git commit -m "feat: add onboarding Step 1 (student info form)"
```

---

### Task 10: Onboarding Step 2 — OTP verification wiring

**Files:**
- Create: `static/js/onboarding/otp.js`
- Modify: `static/js/onboarding/onboarding.js` (wire in the OTP controller)

**Interfaces:**
- Consumes: `showToast`, `postJson` (Task 4); `stepper`, `collected` (Task 9, same file being extended).
- Produces: `createOtpController({ getEmail, onVerified, onBack }) -> { onEnter() }`, consumed by `onboarding.js`.

- [ ] **Step 1: Create `static/js/onboarding/otp.js`**

```js
import { showToast } from '../shared/toast.js';
import { postJson } from '../shared/api.js';

const OTP_DURATION_SECONDS = 300;

export function createOtpController({ getEmail, onVerified, onBack }) {
    const codeInput = document.getElementById('otpCode');
    const errorEl = document.getElementById('otpError');
    const timerEl = document.getElementById('otpTimer');
    const resendBtn = document.getElementById('resendOtpBtn');
    const verifyBtn = document.getElementById('otpVerifyBtn');
    const backBtn = document.getElementById('otpBackBtn');
    const emailTarget = document.getElementById('otpEmailTarget');

    let countdownHandle = null;
    let secondsLeft = 0;
    let hasSentOnce = false;

    function formatTime(total) {
        const m = Math.floor(total / 60);
        const s = total % 60;
        return `${m}:${String(s).padStart(2, '0')}`;
    }

    function startCountdown() {
        clearInterval(countdownHandle);
        secondsLeft = OTP_DURATION_SECONDS;
        resendBtn.disabled = true;
        timerEl.textContent = `Code expires in ${formatTime(secondsLeft)}`;
        countdownHandle = setInterval(() => {
            secondsLeft -= 1;
            if (secondsLeft <= 0) {
                clearInterval(countdownHandle);
                timerEl.textContent = 'Code expired';
                resendBtn.disabled = false;
                return;
            }
            timerEl.textContent = `Code expires in ${formatTime(secondsLeft)}`;
        }, 1000);
    }

    async function sendCode() {
        errorEl.textContent = '';
        resendBtn.disabled = true;
        resendBtn.textContent = 'Sending...';

        const result = await postJson('/send-email-code', { new_email: getEmail() });

        resendBtn.textContent = 'Resend code';

        if (result.success) {
            emailTarget.textContent = getEmail();
            codeInput.value = '';
            startCountdown();
            showToast('Verification code sent', false);
        } else {
            errorEl.textContent = result.message;
            resendBtn.disabled = false;
        }
    }

    resendBtn.addEventListener('click', sendCode);

    backBtn.addEventListener('click', () => {
        clearInterval(countdownHandle);
        onBack();
    });

    verifyBtn.addEventListener('click', async () => {
        errorEl.textContent = '';
        const code = codeInput.value.trim();
        if (!code) {
            errorEl.textContent = 'Enter the code sent to your email';
            return;
        }

        verifyBtn.disabled = true;
        verifyBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Verifying...';

        const result = await postJson('/verify-email-code', { code, new_email: getEmail() });

        verifyBtn.disabled = false;
        verifyBtn.innerHTML = 'Verify <i class="fas fa-arrow-right"></i>';

        if (result.success) {
            clearInterval(countdownHandle);
            onVerified();
            return;
        }

        errorEl.textContent = result.message;
        if (result.max_attempts_reached) {
            resendBtn.disabled = false;
            codeInput.value = '';
        }
    });

    return {
        onEnter() {
            if (!hasSentOnce) {
                hasSentOnce = true;
                sendCode();
            }
        },
    };
}
```

- [ ] **Step 2: Wire the OTP controller into `onboarding.js`**

In `static/js/onboarding/onboarding.js`, add the import at the top:

```js
import { createOtpController } from './otp.js';
```

Replace the `export const stepper = new Stepper({...})` block (currently constructed with no `onStepChange`) with:

```js
let otpController;

export const stepper = new Stepper({
    steps: ['info', 'otp', 'review'],
    container: document.querySelector('.onboarding-wrap'),
    onStepChange: (step) => {
        if (step === 'otp') otpController.onEnter();
    },
});

otpController = createOtpController({
    getEmail: () => collected.email,
    onVerified: () => stepper.next(),
    onBack: () => stepper.back(),
});
```

(Note: `collected` must be declared above this block — it already is, from Task 9. Keep `stepper.init()` at the bottom of the file, after this block and after Task 11's Step 3 wiring is appended.)

- [ ] **Step 3: Verify the app still boots**

Run: `python -c "import app; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add static/js/onboarding/otp.js static/js/onboarding/onboarding.js
git commit -m "feat: add onboarding Step 2 (OTP verification with 3-attempt limit)"
```

(Full manual verification of the OTP flow — send, wrong code x3, expiry, resend — happens in Task 13 against seeded accounts.)

---

### Task 11: Onboarding Step 3 — review & confirm, `/onboarding/complete`

**Files:**
- Modify: `app.py` (add `POST /onboarding/complete`)
- Modify: `static/js/onboarding/onboarding.js` (append Step 3 wiring)

**Interfaces:**
- Consumes: `collected`, `stepper` (Task 9/10, same file).
- Produces: `POST /onboarding/complete` (endpoint `onboarding_complete`) returning `{success, message, redirect}`.

- [ ] **Step 1: Add the route to `app.py`**

```python
@app.route('/onboarding/complete', methods=['POST'])
@login_required
def onboarding_complete():
    if not current_user.email_verified:
        return jsonify({'success': False, 'message': 'Please verify your email before completing onboarding.'}), 400

    current_user.onboarding_completed = True
    db.session.commit()

    try:
        msg = Message('Welcome to JSPICT Student Portal', recipients=[current_user.email])
        msg.body = f'Hi {current_user.name},\n\nYour profile setup is complete. Welcome to the JSPICT Student Portal!'
        mail.send(msg)
    except Exception:
        app.logger.warning('Failed to send welcome email to %s', current_user.email)

    return jsonify({'success': True, 'message': 'Onboarding complete!', 'redirect': url_for('dashboard')})
```

- [ ] **Step 2: Append Step 3 wiring to `static/js/onboarding/onboarding.js`**

Add at the end of the file (after `stepper.init()` — move `stepper.init()` to be the very last line if it isn't already):

```js
// ---- Step 3: Review & Confirm ----
function renderReview() {
    const grid = document.getElementById('reviewGrid');
    grid.innerHTML = `
        <div class="review-item"><label>Email</label><span>${collected.email}</span></div>
        <div class="review-item"><label>Phone</label><span>${collected.phone}</span></div>
        <div class="review-item"><label>Address</label><span>${collected.address}</span></div>
        <div class="review-item"><label>Profile Picture</label><span>${collected.pictureFile ? collected.pictureFile.name : ''}</span></div>
    `;
}

document.getElementById('reviewEditBtn').addEventListener('click', () => stepper.goTo('info'));

document.getElementById('reviewConfirmBtn').addEventListener('click', async () => {
    const btn = document.getElementById('reviewConfirmBtn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';

    const result = await postJson('/onboarding/complete', {});

    if (result.success) {
        showToast('Welcome! Your profile is complete.', false);
        window.location.href = result.redirect;
    } else {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-check"></i> Confirm & Save';
        showToast(result.message, true);
    }
});
```

Update the `otpController` construction from Task 10 so `onVerified` also renders the review before advancing:

```js
otpController = createOtpController({
    getEmail: () => collected.email,
    onVerified: () => {
        renderReview();
        stepper.next();
    },
    onBack: () => stepper.back(),
});
```

Ensure `stepper.init();` remains the final line of the file.

- [ ] **Step 3: Verify the app still boots**

Run: `python -c "import app; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app.py static/js/onboarding/onboarding.js
git commit -m "feat: add onboarding Step 3 (review, confirm, welcome email)"
```

---

### Task 12: Demo seed data (`seed_dev_data.py`)

**Files:**
- Create: `seed_dev_data.py`

**Interfaces:**
- Consumes: `app` (Flask instance), `db`, `User` from `app.py`/`models.py`.
- Produces: 4 demo student rows in `instance/database.db`, consumed by Task 13's manual verification.

- [ ] **Step 1: Create `seed_dev_data.py`**

```python
"""Dev-only script: seeds demo students for manual testing of the
auth + onboarding flow. Safe to re-run; skips students that already exist.

Usage: python seed_dev_data.py
"""
from datetime import date

from app import app
from models import db, User

DEFAULT_PASSWORD = "Default@123"

DEMO_STUDENTS = [
    dict(
        reg_no="2308-2301-0001", name="Amina Yusuf", first_login=True, onboarding_completed=False,
        student_type="National", state="Jigawa", lga="Kazaure", nationality="Nigeria",
        dob=date(2002, 3, 14), gender="Female", semester="1st Semester",
        department="Computer Science", course="ND Computer Science",
        email=None, phone=None, address=None,
    ),
    dict(
        reg_no="2308-2301-0002", name="Bello Ibrahim", first_login=False, onboarding_completed=False,
        student_type="National", state="Jigawa", lga="Kazaure", nationality="Nigeria",
        dob=date(2001, 11, 2), gender="Male", semester="1st Semester",
        department="Computer Science", course="ND Computer Science",
        email=None, phone=None, address=None,
    ),
    dict(
        reg_no="2308-2301-0003", name="Chiamaka Okafor", first_login=False, onboarding_completed=True,
        student_type="International", state="Anambra", lga="Awka South", nationality="Nigeria",
        dob=date(2000, 7, 22), gender="Female", semester="2nd Semester",
        department="Information Technology", course="International Diploma",
        email="chiamaka.demo@example.com", phone="08012345678", address="12 Unity Road, Kazaure",
    ),
    dict(
        reg_no="2308-2301-0004", name="David Adeyemi", first_login=True, onboarding_completed=True,
        student_type="National", state="Oyo", lga="Ibadan North", nationality="Nigeria",
        dob=date(1999, 5, 9), gender="Male", semester="2nd Semester",
        department="Information Technology", course="HND Information Technology",
        email="david.demo@example.com", phone="08087654321", address="4 Freedom Ave, Ibadan",
    ),
]


def seed():
    with app.app_context():
        db.create_all()
        created = 0
        for data in DEMO_STUDENTS:
            if User.query.filter_by(reg_no=data["reg_no"]).first():
                print(f"Skipping {data['reg_no']} (already exists)")
                continue
            user = User(**data)
            user.set_password(DEFAULT_PASSWORD)
            db.session.add(user)
            created += 1
            print(
                f"Created {data['reg_no']} ({data['name']}) — "
                f"first_login={data['first_login']}, onboarding_completed={data['onboarding_completed']}"
            )
        db.session.commit()
        print(f"\nDone. {created} student(s) created. Default password for first_login=True accounts: {DEFAULT_PASSWORD}")


if __name__ == "__main__":
    seed()
```

- [ ] **Step 2: Run it and verify the students were created**

Run: `python seed_dev_data.py`
Expected: 4 "Created ..." lines (or "Skipping ..." if re-run), ending with "Done. 4 student(s) created. ...".

Run: `python -c "
from app import app
from models import User
with app.app_context():
    for u in User.query.all():
        print(u.reg_no, u.first_login, u.onboarding_completed)
"`
Expected: 4 rows matching the table in the spec (`0001`: True/False, `0002`: False/False, `0003`: False/True, `0004`: True/True).

- [ ] **Step 3: Commit**

```bash
git add seed_dev_data.py
git commit -m "chore: add dev seed script for demo student accounts"
```

---

### Task 13: End-to-end manual verification

**Files:** none (verification only)

**Interfaces:** none — this task exercises every route and gate wired in Tasks 1–12 together.

- [ ] **Step 1: Start the app**

Run: `python app.py`
Expected: server starts on `http://localhost:4050` with no tracebacks.

- [ ] **Step 2: Student A (`2308-2301-0001`, first_login=True, onboarding_completed=False) — full flow**

In a browser: log in with reg no `2308-2301-0001` / password `Default@123`.
- Expected: redirected to `/force-password-change`.
- Try a weak password (e.g. `abc`) → rejected with a clear message; checklist items stay unmet.
- Enter a strong password (e.g. `Str0ng!Pass1`) with matching confirm → succeeds, redirected to `/onboarding`.
- Step 1: try clicking Next with empty fields → blocked with per-field errors. Fill email/phone/address, choose an image file → preview appears → Next succeeds → advances to Step 2.
- Step 2: confirm a code arrives (check Flask console / configured mail account) and the 5-minute countdown is running. Enter a wrong code 3 times → after the 3rd, the message indicates max attempts reached and Resend becomes available before the countdown would normally allow it. Click Resend, enter the correct code → advances to Step 3.
- Step 3: review shows the entered email/phone/address/picture filename. Click Edit → returns to Step 1 with the stepper's progress dots reflecting the change. Navigate back to Step 3 (re-verify OTP isn't re-sent a second time redundantly — acceptable if it is, since `hasSentOnce` only guards the very first entry) and click Confirm & Save.
- Expected: redirected to `/`, dashboard loads normally, no further redirects on refresh.

Run: `python -c "
from app import app
from models import User
with app.app_context():
    u = User.query.filter_by(reg_no='2308-2301-0001').first()
    print(u.first_login, u.onboarding_completed, u.email_verified, u.email, u.profile_picture)
"`
Expected: `False True True <the email you entered> uploads/2308-2301-0001.<ext>`

- [ ] **Step 3: Student B (`2308-2301-0002`, first_login=False, onboarding_completed=False) — resumes mid-flow**

Log in with reg no `2308-2301-0002` / password `Default@123`.
Expected: no forced password-change screen — redirected straight to `/onboarding` at Step 1.

- [ ] **Step 4: Student C (`2308-2301-0003`, fully set up)**

Log in with reg no `2308-2301-0003` / password `Default@123`.
Expected: redirected straight to the dashboard (`/`), no password-change or onboarding screens.

- [ ] **Step 5: Student D (`2308-2301-0004`, first_login=True, onboarding_completed=True — admin-reset edge case)**

Log in with reg no `2308-2301-0004` / password `Default@123`.
Expected: forced to `/force-password-change` only. After setting a new password, redirected straight to the dashboard — **not** back into the onboarding wizard.

- [ ] **Step 6: Regression check — existing `/change-password` on the profile page**

Log in as Student C (already fully onboarded), go to Profile → Security tab, try changing password with a weak new password.
Expected: rejected with the same strength-rule message format as `/force-password-change`. A strong password succeeds.

- [ ] **Step 7: Regression check — direct navigation attempts don't bypass the gate**

While logged in as Student B (mid-onboarding), manually navigate the browser to `/registration`, `/my_courses`, and `/profile`.
Expected: every one of them redirects back to `/onboarding`.

- [ ] **Step 8: Record results**

No commit needed for this task — it's verification only. If any step fails, fix the relevant earlier task's code, re-run that task's own verification step, then re-run this task's affected step before proceeding.
