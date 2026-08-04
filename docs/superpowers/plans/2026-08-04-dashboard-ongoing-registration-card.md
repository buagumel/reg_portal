# Dashboard Ongoing Registration Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show an "ongoing registration" card on the student dashboard, directly above the "Registered Courses (Current)" card, whenever a student has a registration for the active period that hasn't yet reached course-submission — and add the "Complete Registration" next-step action that today doesn't exist anywhere once payment succeeds.

**Architecture:** Purely additive template/route work — no new backend logic. `services/registration.py`'s existing `get_registration_status_context(user)` (already used by `/registration`) already returns everything needed (`existing_registration.payment_status`, `.courses_submitted`); `dashboard()` just needs to call it and pass the result through, same as `registration()` already does.

**Tech Stack:** Flask, Jinja2, vanilla CSS (no new dependencies).

## Global Constraints

- No automated test framework in this repo — verification is manual via throwaway `test_client`/`app_context` scripts, created, run, and deleted, never committed.
- The show/hide rule is a single expression, evaluated server-side on every page load: `status.existing_registration is not None and not status.existing_registration.courses_submitted`. No client-side state, no polling.
- This is a narrow, explicitly-requested change to two already-completed student-facing pages (`dashboard.html`, `registration.html`) — touch only what's specified below, nothing else on either page.
- Reuse existing CSS variables (`--primary`, `--primary-dark`, `--success`, `--warning`, all already defined in `static/css/dashboard.css`) and existing class conventions (`.payment-section`/`.payment-header` shell, `.btn-primary` on the registration page) — no new CSS component system.

---

### Task 1: Dashboard Ongoing Registration Card

**Files:**
- Modify: `app.py` (`dashboard()`, line ~413)
- Modify: `templates/dashboard.html`
- Modify: `static/css/dashboard.css`

**Interfaces:**
- Consumes: `services.registration.get_registration_status_context(user)` (already exists, already imported in `app.py`) → `{'period', 'window_status', 'min_credits', 'max_credits', 'registration_fee', 'existing_registration'}`. `existing_registration` is a `StudentRegistration` ORM object or `None`, with `.payment_status` (`'pending'`/`'paid'`), `.courses_submitted` (bool), `.id` directly accessible.
- Produces: `status` template variable available in `dashboard.html`, matching the same variable name/shape `registration.html` already uses.

- [ ] **Step 1: Pass `status` into the dashboard render**

In `app.py`, find:

```python
def dashboard():
    notify_registration_window_events(current_user)
    recent_payments, _ = get_payment_history(current_user, page=1, per_page=5)
    return render_template(
        'dashboard.html',
        profile_display=get_profile_display(current_user),
        recent_payments=recent_payments,
    )
```

Replace with:

```python
def dashboard():
    notify_registration_window_events(current_user)
    recent_payments, _ = get_payment_history(current_user, page=1, per_page=5)
    return render_template(
        'dashboard.html',
        profile_display=get_profile_display(current_user),
        recent_payments=recent_payments,
        status=get_registration_status_context(current_user),
    )
```

`get_registration_status_context` is already imported at the top of `app.py` (`from services.registration import (get_registration_status_context, ...)`) — no new import needed.

- [ ] **Step 2: Add the new card to `templates/dashboard.html`**

Find (the end of the announcement banner, immediately before the wrapper `<div>` that holds the courses grid):

```html
                    <a href="#" class="announcement-btn">View details <i class="fas fa-arrow-right"></i></a>
                </div>

                <div>
            
                    <div class="courses-grid">
```

Replace with:

```html
                    <a href="#" class="announcement-btn">View details <i class="fas fa-arrow-right"></i></a>
                </div>

                {% if status.existing_registration and not status.existing_registration.courses_submitted %}
                <div class="payment-section ongoing-reg-card">
                    <div class="payment-header">
                        <h3><i class="fas fa-hourglass-half" style="background: none; padding:0;"></i> Ongoing Registration</h3>
                        {% if status.existing_registration.payment_status == 'paid' %}
                        <span class="reg-status-pill reg-status-paid"><i class="fas fa-check-circle"></i> Paid — Complete Registration</span>
                        {% else %}
                        <span class="reg-status-pill reg-status-pending"><i class="fas fa-clock"></i> Payment Pending</span>
                        {% endif %}
                    </div>
                    <div class="ongoing-reg-body">
                        <p class="ongoing-reg-period">{{ status.period.academic_session.name }} {{ status.period.semester.name }}</p>
                        {% if status.existing_registration.payment_status == 'paid' %}
                        <a class="ongoing-reg-btn" href="{{ url_for('add_drop') }}"><i class="fas fa-arrow-right"></i> Complete Registration</a>
                        {% else %}
                        <a class="ongoing-reg-btn" href="{{ url_for('payment_registration_summary', registration_id=status.existing_registration.id) }}"><i class="fas fa-credit-card"></i> Complete Payment</a>
                        {% endif %}
                    </div>
                </div>
                {% endif %}

                <div>
            
                    <div class="courses-grid">
```

This card is a sibling of (not nested inside) `.courses-grid`, so it stacks vertically above the "Registered Courses (Current)" card rather than sharing its grid row.

- [ ] **Step 3: Add the new CSS to `static/css/dashboard.css`**

Find the end of the `.course-badge` rule (immediately before the `/* ----- BOTTOM SECTION: recent payment history table ----- */` comment):

```css
        .course-badge {
            background: var(--primary-light);
            color: var(--primary-dark);
            border-radius: 60px;
            padding: 0.25rem 0.9rem;
            font-size: 0.75rem;
            font-weight: 700;
            display: inline-block;
            margin-top: 0.6rem;
            align-self: flex-start;
        }

        /* ----- BOTTOM SECTION: recent payment history table ----- */
```

Replace with:

```css
        .course-badge {
            background: var(--primary-light);
            color: var(--primary-dark);
            border-radius: 60px;
            padding: 0.25rem 0.9rem;
            font-size: 0.75rem;
            font-weight: 700;
            display: inline-block;
            margin-top: 0.6rem;
            align-self: flex-start;
        }

        /* ----- Ongoing registration card ----- */
        .ongoing-reg-card {
            margin-bottom: 1.5rem;
        }
        .reg-status-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            padding: 0.35rem 1rem;
            border-radius: 60px;
            font-size: 0.8rem;
            font-weight: 700;
        }
        .reg-status-pending {
            background: #fff0d9;
            color: var(--warning);
        }
        .reg-status-paid {
            background: #e3f5ec;
            color: var(--success);
        }
        .ongoing-reg-body {
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 1rem;
        }
        .ongoing-reg-period {
            font-size: 1.1rem;
            font-weight: 650;
            color: var(--primary-dark);
            margin: 0;
        }
        .ongoing-reg-btn {
            background: var(--primary);
            color: white;
            padding: 0.7rem 1.5rem;
            border-radius: 60px;
            font-weight: 600;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            transition: 0.2s;
            white-space: nowrap;
        }
        .ongoing-reg-btn:hover {
            background: var(--primary-dark);
        }

        /* ----- BOTTOM SECTION: recent payment history table ----- */
```

- [ ] **Step 4: Manual verification**

```bash
python -c "
import re
from datetime import timedelta
from app import app
from models import db, User, RegistrationPeriod, StudentRegistration, now_lagos

with app.app_context():
    student = User.query.filter_by(reg_no='2308-2301-0002').first()
    assert student is not None, 'seed_dev_data.py must have run first'
    period = RegistrationPeriod.query.filter_by(is_active=True).first()
    assert period is not None

    sr = StudentRegistration.query.filter_by(user_id=student.id, registration_period_id=period.id).first()
    if sr is not None:
        db.session.delete(sr)
        db.session.commit()

    sr = StudentRegistration(user_id=student.id, registration_period_id=period.id, payment_status='pending', credits_registered=0)
    db.session.add(sr)
    db.session.commit()

    client = app.test_client()
    login_page = client.get('/login')
    csrf = re.search(rb'name=\"csrf_token\" value=\"([^\"]+)\"', login_page.data)
    data = {'studentId': student.reg_no, 'password': 'Default@123'}
    if csrf:
        data['csrf_token'] = csrf.group(1).decode()
    client.post('/login', data=data)

    # State 1: payment pending
    resp = client.get('/')
    assert b'Payment Pending' in resp.data and b'Complete Payment' in resp.data
    assert b'Complete Registration' not in resp.data
    print('State 1 (payment pending): OK')

    # State 2: paid, not submitted
    sr.payment_status = 'paid'
    db.session.commit()
    resp = client.get('/')
    assert b'Paid \xe2\x80\x94 Complete Registration' in resp.data or b'Complete Registration' in resp.data
    assert b'Payment Pending' not in resp.data
    print('State 2 (paid, not submitted): OK')

    # State 3: submitted — card must disappear
    sr.courses_submitted = True
    db.session.commit()
    resp = client.get('/')
    assert b'Ongoing Registration' not in resp.data
    print('State 3 (submitted): card correctly hidden')

    db.session.delete(sr)
    db.session.commit()
    print('cleanup done')
"
```

Expected: "State 1 (payment pending): OK", "State 2 (paid, not submitted): OK", "State 3 (submitted): card correctly hidden", "cleanup done".

- [ ] **Step 5: Commit**

```bash
git add app.py templates/dashboard.html static/css/dashboard.css
git commit -m "feat: show ongoing-registration card on dashboard above Registered Courses, with Complete Payment/Complete Registration actions"
```

---

### Task 2: "Complete Registration" CTA on the Registration Page

**Files:**
- Modify: `templates/registration.html`

**Interfaces:** None new — this task only extends the existing `registered-card` branch's conditionals using the same `status.existing_registration` object Task 1 uses.

- [ ] **Step 1: Add the CTA and the submitted-confirmation state**

Find (the entire `registered-card` branch):

```html
        {% elif status.existing_registration %}
        <div class="ongoing-card registered-card" id="registeredCard">
            <div class="card-content">
                <div class="ongoing-info">
                    {% if status.existing_registration.payment_status == 'paid' %}
                    <div class="ongoing-badge registered-badge"><i class="fas fa-check-circle"></i> Registered</div>
                    {% else %}
                    <div class="ongoing-badge registered-badge"><i class="fas fa-check-circle"></i> Registered — Payment Pending</div>
                    {% endif %}
                    <h2>{{ status.period.academic_session.name }} {{ status.period.semester.name }}</h2>
                    <div class="reg-details">
                        <span class="detail-item"><i class="fas fa-receipt"></i> Ref: {{ status.existing_registration.payment_reference }}</span>
                        <span class="detail-item"><i class="fas fa-calendar-check"></i> Registered: {{ status.existing_registration.registered_at.strftime('%d %b %Y') }}</span>
                        <span class="detail-item"><i class="fas fa-money-bill-wave"></i> Payment: {{ status.existing_registration.payment_status|capitalize }}</span>
                    </div>
                    <p class="course-selection-note"><i class="fas fa-info-circle"></i> Course selection will open separately once available.</p>
                </div>
                {% if status.existing_registration.payment_status != 'paid' %}
                <div class="ongoing-action">
                    <a class="btn-primary" href="{{ url_for('payment_registration_summary', registration_id=status.existing_registration.id) }}">
                        <i class="fas fa-credit-card"></i> Complete Payment
                    </a>
                </div>
                {% endif %}
            </div>
        </div>
```

Replace with:

```html
        {% elif status.existing_registration %}
        <div class="ongoing-card registered-card" id="registeredCard">
            <div class="card-content">
                <div class="ongoing-info">
                    {% if status.existing_registration.payment_status == 'paid' %}
                    <div class="ongoing-badge registered-badge"><i class="fas fa-check-circle"></i> Registered</div>
                    {% else %}
                    <div class="ongoing-badge registered-badge"><i class="fas fa-check-circle"></i> Registered — Payment Pending</div>
                    {% endif %}
                    <h2>{{ status.period.academic_session.name }} {{ status.period.semester.name }}</h2>
                    <div class="reg-details">
                        <span class="detail-item"><i class="fas fa-receipt"></i> Ref: {{ status.existing_registration.payment_reference }}</span>
                        <span class="detail-item"><i class="fas fa-calendar-check"></i> Registered: {{ status.existing_registration.registered_at.strftime('%d %b %Y') }}</span>
                        <span class="detail-item"><i class="fas fa-money-bill-wave"></i> Payment: {{ status.existing_registration.payment_status|capitalize }}</span>
                    </div>
                    {% if status.existing_registration.payment_status == 'paid' and status.existing_registration.courses_submitted %}
                    <p class="course-selection-note"><i class="fas fa-check-circle"></i> Course selection submitted.</p>
                    {% elif status.existing_registration.payment_status != 'paid' %}
                    <p class="course-selection-note"><i class="fas fa-info-circle"></i> Course selection will open once payment is complete.</p>
                    {% endif %}
                </div>
                {% if status.existing_registration.payment_status != 'paid' %}
                <div class="ongoing-action">
                    <a class="btn-primary" href="{{ url_for('payment_registration_summary', registration_id=status.existing_registration.id) }}">
                        <i class="fas fa-credit-card"></i> Complete Payment
                    </a>
                </div>
                {% elif not status.existing_registration.courses_submitted %}
                <div class="ongoing-action">
                    <a class="btn-primary" href="{{ url_for('add_drop') }}">
                        <i class="fas fa-arrow-right"></i> Complete Registration
                    </a>
                </div>
                {% endif %}
            </div>
        </div>
```

This produces exactly three states:
- `payment_status != 'paid'`: unchanged from before — "Registered — Payment Pending" badge, "Course selection will open once payment is complete" note, "Complete Payment" button.
- `payment_status == 'paid'` and `not courses_submitted`: "Registered" badge, no note, new "Complete Registration" button → `/add_drop`.
- `payment_status == 'paid'` and `courses_submitted`: "Registered" badge, "Course selection submitted." note, no button.

- [ ] **Step 2: Manual verification**

```bash
python -c "
import re
from app import app
from models import db, User, RegistrationPeriod, StudentRegistration

with app.app_context():
    student = User.query.filter_by(reg_no='2308-2301-0002').first()
    assert student is not None
    period = RegistrationPeriod.query.filter_by(is_active=True).first()
    assert period is not None

    sr = StudentRegistration.query.filter_by(user_id=student.id, registration_period_id=period.id).first()
    if sr is not None:
        db.session.delete(sr)
        db.session.commit()

    sr = StudentRegistration(user_id=student.id, registration_period_id=period.id, payment_status='paid', credits_registered=0, courses_submitted=False)
    db.session.add(sr)
    db.session.commit()

    client = app.test_client()
    login_page = client.get('/login')
    csrf = re.search(rb'name=\"csrf_token\" value=\"([^\"]+)\"', login_page.data)
    data = {'studentId': student.reg_no, 'password': 'Default@123'}
    if csrf:
        data['csrf_token'] = csrf.group(1).decode()
    client.post('/login', data=data)

    resp = client.get('/registration')
    assert b'Complete Registration' in resp.data
    assert b'Complete Payment' not in resp.data
    print('Paid, not submitted: Complete Registration button present')

    sr.courses_submitted = True
    db.session.commit()
    resp = client.get('/registration')
    assert b'Course selection submitted.' in resp.data
    assert b'Complete Registration' not in resp.data
    print('Submitted: confirmation text shown, no button')

    db.session.delete(sr)
    db.session.commit()
    print('cleanup done')
"
```

Expected: "Paid, not submitted: Complete Registration button present", "Submitted: confirmation text shown, no button", "cleanup done".

- [ ] **Step 3: Commit**

```bash
git add templates/registration.html
git commit -m "feat: add Complete Registration CTA and submitted-confirmation state to the registration page's registered card"
```
