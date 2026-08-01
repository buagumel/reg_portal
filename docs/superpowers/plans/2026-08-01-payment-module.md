# Payment Module Implementation Plan (Features 9, 10 & 11)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two hardcoded payment pages and the simulated always-succeeds registration payment with a real, database-backed Payment Module — Payment History (search/filter/pagination), independent payment creation against an admin-configurable catalog, and a full initiate → redirect → gateway callback → verify → receipt → notify workflow, integrated with the real Remita payment gateway in test mode.

**Architecture:** Five payment tables (`Payment` extended from its existing stub, plus `PaymentCategory`, `PaymentItem`, `PaymentReceipt`, `GatewayResponse`); a `PaymentGateway` abstraction with a real `RemitaGateway` (Remita's published test/demo sandbox) and an offline `SimulatedGateway` used only by manual verification scripts; `PaymentService`/`PaymentValidationService`/`ReceiptService` following the established `services/` pattern; `services/registration.py`'s `register_student()` refactored to create a pending payment instead of instantly marking `payment_status='paid'`; `payments_history.html`/`payment_summary.html` wired to real data (same visual structure, no redesign); a new `/payment/create` page for independent payments.

**Tech Stack:** Flask, Flask-SQLAlchemy (SQLite dev DB), `requests` (already a dependency) for the Remita HTTP calls, `reportlab` (new dependency) for PDF receipts, vanilla ES module JS, Jinja2.

Full design rationale: `docs/superpowers/specs/2026-08-01-payment-module-design.md`.

## Global Constraints

- No automated test framework in this repo — verification is manual via throwaway `test_client`/`render_template`/service-call scripts, created, run, and deleted, never committed.
- All datetime columns use `now_lagos()` — never a tz-aware `datetime`.
- The `payments` table already exists in the dev DB as a one-column stub (`id` only) and is confirmed unused/empty. Task 1 drops and recreates it (after verifying it is empty) rather than `ALTER TABLE`-ing 10 new columns onto it — the other 4 new tables are brand new and `db.create_all()` handles them normally.
- Every `Payment`/`PaymentItem`/`PaymentReceipt` query scoped to the acting user must filter by `user_id == user.id` (or join through a `Payment` that is) — never trust a payment reference alone as authorization for a state-changing action; `payment_callback` (the Remita-facing route) is the one deliberate exception, since it must work without a session, and is scoped by the unique unguessable `reference` token instead.
- `PaymentGateway` selection is config-driven (`app.config['PAYMENT_GATEWAY_MODE']`, default `'remita'`); `SimulatedGateway` exists solely so failure/timeout/cancel scenarios can be exercised without depending on Remita's demo server being reachable — it is never the default.
- Remita demo credentials (`REMITA_MERCHANT_ID`, `REMITA_API_KEY`, `REMITA_SERVICE_TYPE_ID`, `REMITA_PUBLIC_KEY`, `REMITA_BASE_URL`, `REMITA_CHECKOUT_BASE_URL`) live in `constants_file.py` next to the existing `SECRET_KEY`/`MAIL_*` constants — matching this repo's established (if imperfect, already flagged in `CLAUDE.md`) config pattern. Do not introduce a new secrets-management scheme in this milestone.
- Do not gate Add/Drop, My Courses, course submission, or any other already-completed module on `payment_status` — nothing does today, and adding that gate is out of scope. "Update registration status if applicable" is satisfied by updating `StudentRegistration.payment_status` itself.
- Do not build an admin UI for managing `PaymentCategory` — Admin Portal has not started yet. Categories are seeded via `seed_dev_data.py`.
- Do not redesign `payments_history.html` or `payment_summary.html`'s visual structure/CSS — reuse the existing cards/tables/classes, replacing hardcoded content with real data. Two label fixes are required because the existing tabs don't correspond to any real status in this domain: "Overdue" → "Cancelled", and the hardcoded "2025" tab → a real date-range filter.
- `PaymentItem.amount` / `Payment.total_amount` are SQLAlchemy `Numeric` columns and come back as `decimal.Decimal` in Python — cast to `float` before passing to `jsonify()` (Decimal is not JSON-serializable); leave them as `Decimal` when rendering directly in Jinja (that works fine).
- Expected mid-plan gap: `services/payment.py`'s `initiate_payment()` (Task 3) calls `url_for('payment_callback', ...)`, but the `payment_callback` endpoint isn't defined until Task 6. Task 5 adds the `/payment/<reference>/initiate` route that reaches this code path, but Task 5's own manual verification never calls it (it only exercises `register_student` creating the pending registration + Payment, not initiating it) — so this doesn't break Task 5's verification. It would only surface if someone clicks "Pay Now" in a live browser between Tasks 5 and 6; this is intentional sequencing, not a defect, and is fully closed by Task 6. Don't flag it as broken in Task 5's review — verify it's actually closed once Task 6 lands.

---

### Task 1: Data Models, Config, Dependencies

**Files:**
- Modify: `models.py`
- Modify: `constants_file.py`
- Modify: `requirements.txt`
- Modify: `services/errors.py`

**Interfaces:**
- Produces: `Payment(id, user_id, reference, idempotency_key, rrr, registration_id, status, total_amount, gateway_status, initiated_at, verified_at)`; `PaymentCategory(id, name, code, description, default_amount, is_active, created_at)`; `PaymentItem(id, payment_id, category_id, description, amount, quantity)` with `payment.items` backref; `PaymentReceipt(id, payment_id, receipt_number, generated_at)`; `GatewayResponse(id, payment_id, raw_payload, received_at)`; `PaymentError(Exception)` in `services/errors.py`; Remita config constants.

- [ ] **Step 1: Verify the existing `payments` table is empty**

```bash
python -c "
import sqlite3
con = sqlite3.connect('instance/database.db')
count = con.execute('SELECT COUNT(*) FROM payments').fetchone()[0]
print('payments row count:', count)
con.close()
"
```
Expected: `payments row count: 0`. If it's anything else, STOP and report BLOCKED — do not drop a table with data in it.

- [ ] **Step 2: Replace the `Payment` stub and add the four new model classes**

In `models.py`, replace the existing stub:
```python
class Payment(db.Model):
    __tablename__ = 'payments'
    id = db.Column(db.Integer, primary_key=True)
```
with:
```python
class Payment(db.Model):
    __tablename__ = 'payments'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reference = db.Column(db.String(50), unique=True, nullable=False)
    idempotency_key = db.Column(db.String(64), unique=True, nullable=False)
    rrr = db.Column(db.String(50), nullable=True)
    registration_id = db.Column(db.Integer, db.ForeignKey('student_registrations.id'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending')
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    gateway_status = db.Column(db.String(100), nullable=True)
    initiated_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
    verified_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User')
    registration = db.relationship('StudentRegistration')
```

At the end of `models.py` (after the `AuditLog` class), append:
```python


class PaymentCategory(db.Model):
    __tablename__ = 'payment_categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    code = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    default_amount = db.Column(db.Numeric(10, 2), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)


class PaymentItem(db.Model):
    __tablename__ = 'payment_items'
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payments.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('payment_categories.id'), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)

    payment = db.relationship('Payment', backref='items')
    category = db.relationship('PaymentCategory')


class PaymentReceipt(db.Model):
    __tablename__ = 'payment_receipts'
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payments.id'), unique=True, nullable=False)
    receipt_number = db.Column(db.String(50), unique=True, nullable=False)
    generated_at = db.Column(db.DateTime, default=now_lagos, nullable=False)


class GatewayResponse(db.Model):
    __tablename__ = 'gateway_responses'
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payments.id'), nullable=False)
    raw_payload = db.Column(db.Text, nullable=False)
    received_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
```

- [ ] **Step 3: Add `PaymentError` to `services/errors.py`**

Read the current file first, then add alongside `RegistrationError`:
```python
class PaymentError(Exception):
    """Raised for any payment business-rule violation (validation, duplicate
    detection, cancellation of a non-cancellable payment, etc.)."""
```

- [ ] **Step 4: Add Remita config to `constants_file.py`**

Read the current file first (it has 4 lines: `SECRET_KEY`, `MAIL_SERVER`, `MAIL_USERNAME`, `MAIL_PASSWORD`), then append:
```python

# Remita test/demo sandbox — published sandbox values, not production secrets.
REMITA_MERCHANT_ID = "2547916"
REMITA_API_KEY = "1946"
REMITA_SERVICE_TYPE_ID = "4430731"
REMITA_PUBLIC_KEY = "QzAwMDAyNzEyNTl8MTEwNjE4NjF8OWZjOWYwNmMyZDk3MDRhYWM3YThiOThlNTNjZTE3ZjYxOTY5NDdmZWE1YzU3NDc0ZjE2ZDZjNTg1YWYxNWY3NWM4ZjMzNzZhNjNhZWZlOWQwNmJhNTFkMjIxYTRiMjYzZDkzNGQ3NTUxNDIxYWNlOGY4ZWEyODY3ZjlhNGUwYTY="
REMITA_BASE_URL = "https://remitademo.net/remita/exapp/api/v1/send/api"
REMITA_CHECKOUT_BASE_URL = "https://demo.remita.net/remita/onepage/payment/init.reg"
```

- [ ] **Step 5: Add `reportlab` to `requirements.txt`**

Insert `reportlab==4.2.5` alphabetically, between `MarkupSafe==3.0.3` and `requests==2.31.0`. Install it:
```bash
pip install reportlab==4.2.5
```

- [ ] **Step 6: Drop the stub `payments` table, recreate schema, verify**

```bash
python -c "
import sqlite3
con = sqlite3.connect('instance/database.db')
con.execute('DROP TABLE payments')
con.commit()
con.close()
print('stub payments table dropped')
"
python -c "import app; print('OK')"
python -c "
from app import app
from models import db
with app.app_context():
    tables = db.inspect(db.engine).get_table_names()
    for t in ('payments', 'payment_categories', 'payment_items', 'payment_receipts', 'gateway_responses'):
        assert t in tables, f'{t} missing'
    cols = [c['name'] for c in db.inspect(db.engine).get_columns('payments')]
    for c in ('user_id', 'reference', 'idempotency_key', 'rrr', 'registration_id', 'status', 'total_amount', 'gateway_status', 'initiated_at', 'verified_at'):
        assert c in cols, f'{c} missing from payments'
    print('Schema verified')
"
```

- [ ] **Step 7: Commit**
```bash
git add models.py constants_file.py requirements.txt services/errors.py
git commit -m "feat: add Payment/PaymentCategory/PaymentItem/PaymentReceipt/GatewayResponse models, Remita config, PaymentError"
```

---

### Task 2: Payment Gateway Service

**Files:**
- Create: `services/payment_gateway.py`

**Interfaces:**
- Consumes: `Payment` (Task 1), `GatewayResponse` (Task 1), `REMITA_*` constants (Task 1).
- Produces: `class PaymentGateway` (ABC: `initiate(payment, payer)`, `verify(payment)`), `class RemitaGateway(PaymentGateway)`, `class SimulatedGateway(PaymentGateway)`, `class GatewayError(Exception)`, `get_gateway(app)`, `build_checkout_url(rrr)`.

- [ ] **Step 1: Write `services/payment_gateway.py`**

```python
import hashlib
import json

import requests

from models import db, GatewayResponse
from constants_file import (
    REMITA_MERCHANT_ID, REMITA_API_KEY, REMITA_SERVICE_TYPE_ID,
    REMITA_BASE_URL, REMITA_CHECKOUT_BASE_URL,
)


class GatewayError(Exception):
    """Raised when the gateway cannot be reached, times out, or returns an
    unusable response. Callers decide whether that means 'timeout' or
    'leave pending and let the student retry'."""


class PaymentGateway:
    def initiate(self, payment, payer):
        raise NotImplementedError

    def verify(self, payment):
        raise NotImplementedError


def _log_response(payment, raw_payload):
    entry = GatewayResponse(payment_id=payment.id, raw_payload=json.dumps(raw_payload))
    db.session.add(entry)
    db.session.commit()


def build_checkout_url(rrr):
    return f'{REMITA_CHECKOUT_BASE_URL}?rrr={rrr}&channel=CARD,USSD,ENAIRA,TRANSFER'


class RemitaGateway(PaymentGateway):
    """Real integration against Remita's published test/demo sandbox
    (remitademo.net / demo.remita.net). The exact response shape isn't
    fully documented publicly, so both request functions read the RRR /
    status defensively and always log the raw response to GatewayResponse
    so a mismatch is debuggable rather than silently swallowed."""

    def initiate(self, payment, payer):
        order_id = payment.reference
        amount = str(payment.total_amount)
        hash_input = f'{REMITA_MERCHANT_ID}{REMITA_SERVICE_TYPE_ID}{order_id}{amount}{REMITA_API_KEY}'
        api_hash = hashlib.sha512(hash_input.encode('utf-8')).hexdigest()

        payload = {
            'serviceTypeId': REMITA_SERVICE_TYPE_ID,
            'amount': amount,
            'orderId': order_id,
            'payerName': payer['name'],
            'payerEmail': payer['email'],
            'payerPhone': payer['phone'],
            'description': payer['description'],
            'responseurl': payer['response_url'],
        }
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': f'remitaConsumerKey={REMITA_MERCHANT_ID},remitaConsumerToken={api_hash}',
        }

        try:
            response = requests.post(
                f'{REMITA_BASE_URL}/echannelsvc/merchant/api/paymentinit',
                json=payload, headers=headers, timeout=10,
            )
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            _log_response(payment, {'error': str(exc)})
            raise GatewayError(f'Could not reach the payment gateway: {exc}') from exc

        _log_response(payment, data)

        rrr = data.get('RRR') or data.get('data', {}).get('RRR') if isinstance(data.get('data'), dict) else data.get('RRR')
        if not rrr:
            raise GatewayError(f'Gateway did not return an RRR: {data}')

        return {'rrr': rrr, 'checkout_url': build_checkout_url(rrr), 'raw': data}

    def verify(self, payment):
        hash_input = f'{payment.rrr}{REMITA_API_KEY}{REMITA_MERCHANT_ID}'
        api_hash = hashlib.sha512(hash_input.encode('utf-8')).hexdigest()
        url = f'{REMITA_BASE_URL}/echannelsvc/{REMITA_MERCHANT_ID}/{payment.rrr}/{api_hash}/status.reg'

        try:
            response = requests.get(url, timeout=10)
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            _log_response(payment, {'error': str(exc)})
            raise GatewayError(f'Could not reach the payment gateway: {exc}') from exc

        _log_response(payment, data)

        status_code = str(data.get('status', ''))
        if status_code == '00':
            resolved = 'successful'
        elif status_code in ('021', '025'):
            resolved = 'pending'
        else:
            resolved = 'failed'

        return {'status': resolved, 'gateway_status': data.get('message', status_code), 'raw': data}


class SimulatedGateway(PaymentGateway):
    """Offline, deterministic gateway used only by manual verification
    scripts (selected via app.config['PAYMENT_GATEWAY_MODE'] = 'simulated').
    The desired outcome is set on payment.gateway_status *before* calling
    verify(): 'successful', 'failed', 'cancelled', or 'verify_timeout'
    (raises GatewayError). Set it to 'init_timeout' before calling
    initiate() to simulate a timeout during RRR generation."""

    def initiate(self, payment, payer):
        if payment.gateway_status == 'init_timeout':
            raise GatewayError('Simulated gateway timeout during initiate.')
        rrr = f'SIMRRR{payment.id:08d}'
        raw = {'RRR': rrr, 'status': '025', 'message': 'RRR generated (simulated)'}
        _log_response(payment, raw)
        return {'rrr': rrr, 'checkout_url': f'/payment/simulate/{payment.reference}', 'raw': raw}

    def verify(self, payment):
        outcome = payment.gateway_status or 'successful'
        if outcome == 'verify_timeout':
            raise GatewayError('Simulated gateway timeout during verify.')
        status_map = {'successful': '00', 'failed': '021', 'cancelled': '021', 'pending': '025'}
        raw = {'status': status_map.get(outcome, '021'), 'message': outcome}
        _log_response(payment, raw)
        return {'status': outcome, 'gateway_status': outcome, 'raw': raw}


def get_gateway(app):
    mode = app.config.get('PAYMENT_GATEWAY_MODE', 'remita')
    if mode == 'simulated':
        return SimulatedGateway()
    return RemitaGateway()
```

- [ ] **Step 2: Manual verification (SimulatedGateway, no network)**

```bash
python -c "
from app import app
from models import db, Payment
from services.payment_gateway import SimulatedGateway, GatewayError

with app.app_context():
    p = Payment(user_id=1, reference='TESTREF001', idempotency_key='idem-test-1', status='pending', total_amount=1000)
    db.session.add(p)
    db.session.commit()

    gw = SimulatedGateway()
    result = gw.initiate(p, {'name': 'Test', 'email': 't@example.com', 'phone': '08000000000', 'description': 'Test', 'response_url': 'http://localhost/payment/callback'})
    print('initiate:', result)
    p.rrr = result['rrr']
    db.session.commit()

    p.gateway_status = 'successful'
    print('verify (successful):', gw.verify(p))

    p.gateway_status = 'verify_timeout'
    try:
        gw.verify(p)
        print('FAIL: expected GatewayError')
    except GatewayError as e:
        print('verify timeout raised correctly:', e)

    db.session.delete(p)
    db.session.commit()
    print('cleanup done')
"
```
Expected: `initiate` prints a dict with a `SIMRRR...` reference and a `checkout_url`; `verify (successful)` prints `{'status': 'successful', ...}`; the timeout case prints the "raised correctly" line. This script is throwaway — do not commit it.

- [ ] **Step 3: Commit**
```bash
git add services/payment_gateway.py
git commit -m "feat: add PaymentGateway abstraction with real RemitaGateway (test-mode) and offline SimulatedGateway"
```

---

### Task 3: Payment Validation and Core Payment Service

**Files:**
- Create: `services/payment_validation.py`
- Create: `services/payment.py`

**Interfaces:**
- Consumes: `services.errors.PaymentError`, `services.payment_gateway.GatewayError`/`build_checkout_url`, `services.notification.create_notification`, `services.audit.log_action`, `Payment`/`PaymentItem`/`PaymentCategory`/`StudentRegistration` models.
- Produces: `get_active_categories()`, `create_payment(user, item_specs, idempotency_key, registration_id=None)`, `initiate_payment(gateway, payment, user)`, `verify_payment(gateway, payment)`, `retry_verification(gateway, payment)`, `cancel_payment(payment)`, `get_payment_history(user, status=None, search=None, date_from=None, date_to=None, page=1, per_page=10)`, `get_summary_counts(user)`. `item_specs` is a list of `(category, quantity, amount)` tuples.

- [ ] **Step 1: Write `services/payment_validation.py`**

```python
from services.errors import PaymentError
from models import Payment


def validate_items_selected(item_specs):
    if not item_specs:
        raise PaymentError('Select at least one item to pay for.')


def validate_no_duplicate_pending(user, registration_id=None):
    """One pending payment at a time per concern: for a registration fee,
    keyed to that specific registration; for independent payments, only one
    pending independent payment at a time (simplest workable rule — avoids
    tracking category-level overlap for a catalog that's just a handful of
    flat fees). Blocks creation and points the caller at the Resume flow
    instead of letting a second pending Payment pile up."""
    query = Payment.query.filter_by(user_id=user.id, status='pending')
    if registration_id is not None:
        existing = query.filter_by(registration_id=registration_id).first()
    else:
        existing = query.filter_by(registration_id=None).first()
    if existing:
        raise PaymentError(
            f'You already have a pending payment (reference {existing.reference}). '
            'Resume it from Payment History instead of starting a new one.'
        )
```

- [ ] **Step 2: Write `services/payment.py`**

```python
import random
import string

from flask import url_for

from models import db, now_lagos, Payment, PaymentItem, PaymentCategory
from services.errors import PaymentError
from services.payment_validation import validate_items_selected, validate_no_duplicate_pending
from services.payment_gateway import GatewayError
from services.notification import create_notification
from services.audit import log_action


def _generate_reference():
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
    return f'PAY-{suffix}'


def get_active_categories():
    return PaymentCategory.query.filter_by(is_active=True).order_by(PaymentCategory.name).all()


def create_payment(user, item_specs, idempotency_key, registration_id=None):
    """Returns the Payment. If idempotency_key was already used, returns the
    existing row instead of creating a duplicate (double-submit guard)."""
    existing = Payment.query.filter_by(idempotency_key=idempotency_key).first()
    if existing:
        return existing

    validate_items_selected(item_specs)
    validate_no_duplicate_pending(user, registration_id=registration_id)

    total = sum(amount * quantity for _, quantity, amount in item_specs)
    payment = Payment(
        user_id=user.id,
        reference=_generate_reference(),
        idempotency_key=idempotency_key,
        registration_id=registration_id,
        status='pending',
        total_amount=total,
    )
    db.session.add(payment)
    db.session.flush()

    for category, quantity, amount in item_specs:
        db.session.add(PaymentItem(
            payment_id=payment.id, category_id=category.id,
            description=category.name, amount=amount, quantity=quantity,
        ))
    db.session.commit()
    return payment


def initiate_payment(gateway, payment, user):
    """Calls the gateway to obtain an RRR + checkout URL. On a gateway
    timeout, marks the payment 'timeout' (never leaves it silently stuck as
    'pending' with no way for the student to tell what happened) and
    re-raises so the route can show a retry option."""
    payer = {
        'name': user.name,
        'email': user.email,
        'phone': user.phone or '00000000000',
        'description': ', '.join(item.description for item in payment.items) or 'Payment',
        'response_url': url_for('payment_callback', _external=True),
    }
    try:
        result = gateway.initiate(payment, payer)
    except GatewayError:
        payment.status = 'timeout'
        db.session.commit()
        raise

    payment.rrr = result['rrr']
    if payment.status == 'timeout':
        payment.status = 'pending'
    db.session.commit()
    return result['checkout_url']


def verify_payment(gateway, payment):
    """Idempotent — re-verifying an already-terminal payment just returns
    its current state without re-running any side effect (notification,
    email, registration update) a second time."""
    if payment.status in ('successful', 'failed', 'cancelled'):
        return payment

    try:
        result = gateway.verify(payment)
    except GatewayError:
        return payment  # leave as-is (pending/timeout); caller can retry later

    payment.gateway_status = result['gateway_status']

    if result['status'] == 'successful':
        payment.status = 'successful'
        payment.verified_at = now_lagos()
        db.session.commit()
        _on_payment_successful(payment)
    elif result['status'] == 'failed':
        payment.status = 'failed'
        db.session.commit()
        create_notification(
            payment.user, 'Payment failed',
            f'Your payment of ₦{payment.total_amount:,.2f} (reference {payment.reference}) was not successful. You can retry from Payment History.',
            category='payments', priority='high', related_url='/payments_history',
        )
        log_action(payment.user, 'payment_failed', details=f'reference={payment.reference}')
    else:
        db.session.commit()  # still pending — gateway_status updated, no state change

    return payment


def _on_payment_successful(payment):
    from services.receipt import get_or_create_receipt, send_receipt_email

    if payment.registration_id:
        payment.registration.payment_status = 'paid'
        db.session.commit()

    receipt = get_or_create_receipt(payment)

    create_notification(
        payment.user, 'Payment successful',
        f'Your payment of ₦{payment.total_amount:,.2f} (reference {payment.reference}) was successful. Receipt: {receipt.receipt_number}.',
        category='payments', priority='high', related_url=f'/payment/{payment.reference}/receipt',
    )
    log_action(payment.user, 'payment_successful', details=f'reference={payment.reference} amount={payment.total_amount}')
    send_receipt_email(payment, receipt)


def retry_verification(gateway, payment):
    return verify_payment(gateway, payment)


def cancel_payment(payment):
    if payment.status in ('successful', 'failed', 'cancelled'):
        raise PaymentError('This payment cannot be cancelled.')
    payment.status = 'cancelled'
    db.session.commit()
    log_action(payment.user, 'payment_cancelled', details=f'reference={payment.reference}')
    return payment


def get_payment_history(user, status=None, search=None, date_from=None, date_to=None, page=1, per_page=10):
    from datetime import datetime, timedelta

    query = Payment.query.filter_by(user_id=user.id)
    if status:
        if status == 'cancelled':
            query = query.filter(Payment.status.in_(('cancelled', 'failed', 'timeout')))
        else:
            query = query.filter_by(status=status)
    if search:
        like = f'%{search}%'
        query = query.filter(db.or_(Payment.reference.ilike(like), Payment.rrr.ilike(like)))
    if date_from:
        try:
            query = query.filter(Payment.initiated_at >= datetime.strptime(date_from, '%Y-%m-%d'))
        except ValueError:
            pass
    if date_to:
        try:
            parsed_to = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(Payment.initiated_at < parsed_to)
        except ValueError:
            pass

    query = query.order_by(Payment.initiated_at.desc())
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return items, total


def get_summary_counts(user):
    payments = Payment.query.filter_by(user_id=user.id).all()
    return {
        'total': len(payments),
        'total_amount_paid': sum((p.total_amount for p in payments if p.status == 'successful'), start=0),
        'pending': sum(1 for p in payments if p.status == 'pending'),
        'cancelled': sum(1 for p in payments if p.status in ('cancelled', 'failed', 'timeout')),
    }
```

- [ ] **Step 3: Manual verification**

```bash
python -c "
from app import app
from models import db, User, PaymentCategory
from services.payment import create_payment, get_summary_counts
from services.errors import PaymentError

with app.app_context():
    user = User.query.first()
    cat = PaymentCategory(name='Test Fee', code='test_fee', default_amount=1500, is_active=True)
    db.session.add(cat)
    db.session.commit()

    p1 = create_payment(user, [(cat, 1, 1500)], idempotency_key='idem-a')
    print('created:', p1.reference, p1.total_amount, p1.status)

    p1_again = create_payment(user, [(cat, 1, 1500)], idempotency_key='idem-a')
    assert p1_again.id == p1.id, 'idempotency failed'
    print('idempotency OK: same payment returned')

    try:
        create_payment(user, [(cat, 1, 1500)], idempotency_key='idem-b')
        print('FAIL: expected duplicate-pending PaymentError')
    except PaymentError as e:
        print('duplicate detection OK:', e)

    print('summary:', get_summary_counts(user))

    from models import PaymentItem
    PaymentItem.query.filter_by(payment_id=p1.id).delete()
    db.session.delete(p1)
    db.session.delete(cat)
    db.session.commit()
    print('cleanup done')
"
```
Expected: idempotency and duplicate-detection lines print OK; summary shows `'pending': 1` before cleanup. This script is throwaway — do not commit it.

- [ ] **Step 4: Commit**
```bash
git add services/payment_validation.py services/payment.py
git commit -m "feat: add PaymentValidationService and PaymentService (create/initiate/verify/retry/cancel/history)"
```

---

### Task 4: Receipt Service

**Files:**
- Create: `services/receipt.py`

**Interfaces:**
- Consumes: `PaymentReceipt` model, `payment.items`, `extensions.mail`/`Message`.
- Produces: `get_or_create_receipt(payment)`, `render_pdf(payment, receipt)` (returns `bytes`), `send_receipt_email(payment, receipt)`.

- [ ] **Step 1: Write `services/receipt.py`**

```python
import io
import random
import string

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas

from extensions import mail, Message
from models import db, PaymentReceipt


def _generate_receipt_number():
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
    return f'RCT-{suffix}'


def get_or_create_receipt(payment):
    existing = PaymentReceipt.query.filter_by(payment_id=payment.id).first()
    if existing:
        return existing
    receipt = PaymentReceipt(payment_id=payment.id, receipt_number=_generate_receipt_number())
    db.session.add(receipt)
    db.session.commit()
    return receipt


def render_pdf(payment, receipt):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 30 * mm

    try:
        c.drawImage('static/img/jspict-logo.png', 20 * mm, y - 5 * mm, width=20 * mm, height=20 * mm, mask='auto')
    except Exception:
        pass

    c.setFont('Helvetica-Bold', 16)
    c.drawString(50 * mm, y, 'JSPICT Student Portal - Payment Receipt')
    y -= 15 * mm

    c.setFont('Helvetica', 11)
    c.drawString(20 * mm, y, f'Receipt Number: {receipt.receipt_number}')
    y -= 7 * mm
    c.drawString(20 * mm, y, f'Reference: {payment.reference}    RRR: {payment.rrr or "-"}')
    y -= 7 * mm
    c.drawString(20 * mm, y, f'Student: {payment.user.name} ({payment.user.reg_no})')
    y -= 7 * mm
    paid_at = payment.verified_at.strftime('%d %b %Y, %I:%M %p') if payment.verified_at else '-'
    c.drawString(20 * mm, y, f'Payment Date: {paid_at}')
    y -= 7 * mm
    c.drawString(20 * mm, y, f'Gateway Status: {payment.gateway_status or "-"}')
    y -= 12 * mm

    c.setFont('Helvetica-Bold', 11)
    c.drawString(20 * mm, y, 'Description')
    c.drawString(120 * mm, y, 'Qty')
    c.drawString(145 * mm, y, 'Amount (NGN)')
    y -= 6 * mm
    c.line(20 * mm, y, 190 * mm, y)
    y -= 6 * mm

    c.setFont('Helvetica', 10)
    for item in payment.items:
        c.drawString(20 * mm, y, item.description[:60])
        c.drawString(120 * mm, y, str(item.quantity))
        c.drawRightString(190 * mm, y, f'{item.amount * item.quantity:,.2f}')
        y -= 6 * mm

    y -= 4 * mm
    c.line(20 * mm, y, 190 * mm, y)
    y -= 8 * mm
    c.setFont('Helvetica-Bold', 12)
    c.drawString(20 * mm, y, 'Total')
    c.drawRightString(190 * mm, y, f'NGN {payment.total_amount:,.2f}')
    y -= 20 * mm

    c.setStrokeColor(colors.grey)
    c.rect(20 * mm, y - 25 * mm, 25 * mm, 25 * mm)
    c.setFont('Helvetica', 8)
    c.drawCentredString(32.5 * mm, y - 13.5 * mm, 'QR')

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()


def send_receipt_email(payment, receipt):
    try:
        msg = Message('Payment Receipt', recipients=[payment.user.email])
        msg.body = (
            f'Hi {payment.user.name},\n\n'
            f'Your payment of NGN {payment.total_amount:,.2f} (reference {payment.reference}) was successful.\n'
            f'Receipt number: {receipt.receipt_number}\n\n'
            'You can view or download your receipt any time from Payment History.'
        )
        mail.send(msg)
    except Exception:
        from flask import current_app
        current_app.logger.warning('Failed to send receipt email to %s', payment.user.email)
```

- [ ] **Step 2: Manual verification**

```bash
python -c "
from app import app
from models import db, User, Payment, PaymentItem, PaymentCategory
from services.receipt import get_or_create_receipt, render_pdf

with app.app_context():
    user = User.query.first()
    cat = PaymentCategory(name='Test Fee', code='rcpt_test_fee', default_amount=2000, is_active=True)
    db.session.add(cat)
    db.session.commit()
    p = Payment(user_id=user.id, reference='RCPTTEST01', idempotency_key='idem-rcpt-1', status='successful', total_amount=2000, gateway_status='00')
    db.session.add(p)
    db.session.commit()
    db.session.add(PaymentItem(payment_id=p.id, category_id=cat.id, description='Test Fee', amount=2000, quantity=1))
    db.session.commit()

    receipt = get_or_create_receipt(p)
    print('receipt number:', receipt.receipt_number)
    pdf_bytes = render_pdf(p, receipt)
    assert pdf_bytes[:4] == b'%PDF', 'not a valid PDF'
    print('PDF generated, size:', len(pdf_bytes), 'bytes')

    PaymentItem.query.filter_by(payment_id=p.id).delete()
    db.session.delete(receipt)
    db.session.delete(p)
    db.session.delete(cat)
    db.session.commit()
    print('cleanup done')
"
```
Expected: prints a receipt number, confirms the PDF starts with `%PDF`, prints a size in bytes. This script is throwaway — do not commit it.

- [ ] **Step 3: Commit**
```bash
git add services/receipt.py
git commit -m "feat: add ReceiptService (reportlab PDF generation, resend email)"
```

---

### Task 5: Registration-Fee Payment Flow

**Files:**
- Modify: `services/registration.py`
- Modify: `app.py`
- Modify: `templates/payment_summary.html`
- Create: `static/js/payment_summary/payment_summary.js`
- Modify: `static/js/registration/registration.js`

**Interfaces:**
- Consumes: `services.payment.create_payment`/`initiate_payment`, `services.payment_gateway.get_gateway`, `PaymentCategory`.
- Produces: route `payment_registration_summary(registration_id)` at `/payment/registration/<int:registration_id>`; route `payment_initiate(reference)` (POST) at `/payment/<reference>/initiate`.

- [ ] **Step 1: Refactor `register_student()` in `services/registration.py`**

Remove the `_generate_payment_reference()` function entirely (lines 90-95) — it's replaced by `services/payment.py`'s own reference generator.

Add to the imports at the top of the file:
```python
from models import db, now_lagos, RegistrationPeriod, DepartmentRegistrationRule, StudentRegistration, PaymentCategory
from services.payment import create_payment
from services.errors import RegistrationError, PaymentError
```
(This replaces the existing `from models import db, now_lagos, RegistrationPeriod, DepartmentRegistrationRule, StudentRegistration` line and the existing `from services.errors import RegistrationError` line — merge them as shown, don't duplicate imports.)

Replace the `register_student` function body with:
```python
def register_student(user, period):
    """Validate and create a StudentRegistration for the given period, with
    payment left pending — the caller redirects to the payment summary page,
    where the student clicks Pay Now to actually initiate payment through
    the real gateway."""
    if get_window_status(period) != 'open':
        raise RegistrationError('Registration is not currently open for this period.')

    existing = StudentRegistration.query.filter_by(
        user_id=user.id, registration_period_id=period.id
    ).first()
    if existing:
        raise RegistrationError('You are already registered for this period.')

    registration = StudentRegistration(
        user_id=user.id,
        registration_period_id=period.id,
        status='registered',
        payment_status='pending',
        credits_registered=0,
    )
    try:
        db.session.add(registration)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise RegistrationError('You are already registered for this period.')

    _, _, registration_fee = get_credit_limits(period, user.department)
    category = PaymentCategory.query.filter_by(code='registration_fee').first()
    if category is not None:
        try:
            payment = create_payment(
                user, [(category, 1, registration_fee)],
                idempotency_key=f'registration-{registration.id}',
                registration_id=registration.id,
            )
            registration.payment_reference = payment.reference
            db.session.commit()
        except PaymentError:
            pass  # a pending payment already exists for this registration — shouldn't happen for a brand-new one, but never block registration creation on this

    create_notification(
        user, 'Registration created - payment required',
        f'Your registration for {period.academic_session.name} {period.semester.name} has been created. Complete payment to activate it.',
        category='registration', priority='high', related_url='/registration',
    )
    return registration
```

- [ ] **Step 2: Update `app.py` imports**

Add to the `from services.registration import (...)` block: no changes needed there. Add new imports:
```python
from services.payment import (
    get_active_categories, create_payment, initiate_payment, verify_payment,
    retry_verification, cancel_payment, get_payment_history,
    get_summary_counts as get_payment_summary_counts,
)
from services.payment_gateway import get_gateway, GatewayError
from services.errors import PaymentError
from models import (
    db, User, RegisteredCourse, StudentRegistration, Payment, PaymentCategory,
)
```
(Merge the `models` import with the existing one at the top of `app.py` — don't create a second `from models import ...` line.)

Also add `PAYMENT_GATEWAY_MODE` to the app config block, right after `app.config['SQLALCHEMY_DATABASE_URI']`:
```python
app.config['PAYMENT_GATEWAY_MODE'] = 'remita'
```

- [ ] **Step 3: Replace the `pay_summary` route and update `registration_register`**

Replace:
```python
@app.route('/pay_summary')
def pay_summary():
    return render_template('payment_summary.html')
```
with:
```python
@app.route('/payment/registration/<int:registration_id>')
@login_required
def payment_registration_summary(registration_id):
    registration = StudentRegistration.query.filter_by(id=registration_id, user_id=current_user.id).first_or_404()
    if registration.payment_status == 'paid':
        flash('This registration has already been paid for.')
        return redirect(url_for('registration'))
    payment = (
        Payment.query
        .filter_by(registration_id=registration.id, status='pending')
        .order_by(Payment.id.desc())
        .first()
    )
    return render_template('payment_summary.html', registration=registration, payment=payment)


@app.route('/payment/<reference>/initiate', methods=['POST'])
@login_required
def payment_initiate(reference):
    payment = Payment.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    if payment.status != 'pending':
        return jsonify({'success': False, 'message': 'This payment is no longer pending.'}), 400
    gateway = get_gateway(app)
    try:
        checkout_url = initiate_payment(gateway, payment, current_user)
    except GatewayError as e:
        return jsonify({'success': False, 'message': str(e)}), 502
    return jsonify({'success': True, 'redirect': checkout_url})
```

Update the `registration_register` route's return statement — replace:
```python
    return jsonify({
        'success': True,
        'message': 'Registration successful.',
        'registration': {
            'session': reg.registration_period.academic_session.name,
            'semester': reg.registration_period.semester.name,
            'payment_reference': reg.payment_reference,
            'registered_at': reg.registered_at.strftime('%d %b %Y, %I:%M %p'),
            'credits_registered': reg.credits_registered,
        },
    })
```
with:
```python
    return jsonify({
        'success': True,
        'message': 'Registration created. Redirecting to payment...',
        'redirect': url_for('payment_registration_summary', registration_id=reg.id),
    })
```

- [ ] **Step 4: Rewrite `templates/payment_summary.html`**

```html
{% extends "base.html" %}

{% block head %}
    <title>Payment Summary · Course Registration</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/pay_summary.css') }}">
{% endblock %}

{% block content %}
<div class="payment-summary-container">
    <input type="hidden" id="csrf_token" value="{{ csrf_token() }}">

    <div class="page-header">
        <a href="{{ url_for('registration') }}" class="back-link"><i class="fas fa-arrow-left"></i> Back to Registration</a>
        <h1><i class="fas fa-receipt"></i> Payment Summary</h1>
        <div></div>
    </div>

    <div class="summary-card">
        <div class="summary-header">
            <h2><i class="fas fa-credit-card"></i> Registration Fee Summary</h2>
            <p>Please review your details before proceeding to payment</p>
        </div>
        <div class="summary-body">
            <div class="info-section">
                <div class="section-title"><i class="fas fa-user-graduate"></i> Student Information</div>
                <div class="info-grid">
                    <div class="info-item"><span class="info-label">Full Name</span><span class="info-value">{{ current_user.name }}</span></div>
                    <div class="info-item"><span class="info-label">Registration Number</span><span class="info-value">{{ current_user.reg_no }}</span></div>
                    <div class="info-item"><span class="info-label">Programme</span><span class="info-value">{{ current_user.course }}</span></div>
                    <div class="info-item"><span class="info-label">Level / Year</span><span class="info-value">{{ current_user.level }}</span></div>
                    <div class="info-item"><span class="info-label">Email</span><span class="info-value">{{ current_user.email }}</span></div>
                    <div class="info-item"><span class="info-label">Phone</span><span class="info-value">{{ current_user.formatted_phone }}</span></div>
                </div>
            </div>

            <div class="section-title"><i class="fas fa-calendar-alt"></i> {{ registration.registration_period.academic_session.name }} {{ registration.registration_period.semester.name }}</div>

            <div class="fee-summary" style="background: #0f3150; color: white; margin-top: 1rem;">
                <span class="fee-label" style="color: white;">Registration Fee Due</span>
                <span class="fee-amount" style="color: #ffd966;">₦{{ '{:,.2f}'.format(payment.total_amount) if payment else '0.00' }}</span>
            </div>

            {% if payment %}
            <button class="pay-now-btn" id="payNowBtn" data-reference="{{ payment.reference }}">
                <i class="fas fa-credit-card"></i> Pay Now
            </button>
            {% else %}
            <p style="text-align:center; color: var(--text-muted);">No pending payment found for this registration. It may already be paid — check <a href="{{ url_for('payments_history') }}">Payment History</a>.</p>
            {% endif %}
            <div class="secure-note">
                <i class="fas fa-lock"></i> Secure payment via Remita
            </div>
        </div>
    </div>
</div>

<div id="toastMsg" class="toast-msg"></div>
{% endblock %}

{% block scripts %}
<script type="module" src="{{ url_for('static', filename='js/payment_summary/payment_summary.js') }}"></script>
{% endblock %}
```

- [ ] **Step 5: Create `static/js/payment_summary/payment_summary.js`**

```js
import { postJson } from '../shared/api.js';
import { showToast } from '../shared/toast.js';

const btn = document.getElementById('payNowBtn');
if (btn) {
    btn.addEventListener('click', async () => {
        btn.disabled = true;
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Redirecting to Remita…';

        const reference = btn.dataset.reference;
        const result = await postJson(`/payment/${reference}/initiate`, {});

        if (result.success) {
            window.location.href = result.redirect;
        } else {
            showToast(result.message || 'Could not start payment.', true);
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    });
}
```

- [ ] **Step 6: Update `static/js/registration/registration.js`**

Replace the `setupRegisterNow` function's confirm message and success handler:
```js
function setupRegisterNow() {
    const btn = document.getElementById('registerNowBtn');
    if (!btn) return;

    btn.addEventListener('click', async () => {
        if (!window.confirm('Confirm semester registration? You will be redirected to complete payment.')) {
            return;
        }

        btn.disabled = true;
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Registering…';

        const result = await postJson('/registration/register', {});

        if (result.success) {
            showToast(result.message || 'Registration created.');
            window.location.href = result.redirect;
        } else {
            showToast(result.message || 'Registration failed.', true);
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    });
}
```

- [ ] **Step 7: Manual verification**

```bash
python -c "
from app import app
from models import db, PaymentCategory

with app.app_context():
    if not PaymentCategory.query.filter_by(code='registration_fee').first():
        db.session.add(PaymentCategory(name='Registration Fee', code='registration_fee', default_amount=None, is_active=True))
        db.session.commit()
        print('registration_fee category seeded for manual test')

    from models import User, RegistrationPeriod
    from services.registration import register_student, get_active_period
    user = User.query.filter(User.reg_no.isnot(None)).first()
    period = get_active_period()
    print('active period:', period)
    if user and period:
        from models import StudentRegistration
        StudentRegistration.query.filter_by(user_id=user.id, registration_period_id=period.id).delete()
        db.session.commit()
        reg = register_student(user, period)
        print('registration created, payment_status:', reg.payment_status, 'payment_reference:', reg.payment_reference)
        from models import Payment
        p = Payment.query.filter_by(reference=reg.payment_reference).first()
        print('payment row:', p.status, p.total_amount)
        StudentRegistration.query.filter_by(id=reg.id).delete()
        Payment.query.filter_by(id=p.id).delete() if p else None
        db.session.commit()
        print('cleanup done')
"
```
Expected: `payment_status: pending`, a real `payment_reference`, and a matching `Payment` row with `status: pending`. This script is throwaway — do not commit it. (The `registration_fee` category it seeds here is a manual-test convenience; Task 10 seeds it properly for the dev DB.)

- [ ] **Step 8: Commit**
```bash
git add services/registration.py app.py templates/payment_summary.html static/js/payment_summary/payment_summary.js static/js/registration/registration.js
git commit -m "feat: registration fee payment now creates a real pending Payment and redirects to Pay Now instead of simulating instant success"
```

---

### Task 6: Payment Callback, Verify, Retry, Resume, Cancel

**Files:**
- Modify: `app.py`
- Create: `templates/payment_callback.html`
- Modify: `static/css/pay_summary.css`

**Interfaces:**
- Consumes: `services.payment.verify_payment`/`retry_verification`/`cancel_payment`, `services.payment_gateway.build_checkout_url`.
- Produces: routes `payment_callback` (GET `/payment/callback`), `payment_resume` (GET `/payment/<reference>/resume`), `payment_cancel` (POST `/payment/<reference>/cancel`), `payment_retry` (POST `/payment/<reference>/retry`).

- [ ] **Step 1: Add the callback/resume/cancel/retry routes to `app.py`**

Add `from services.payment_gateway import get_gateway, GatewayError, build_checkout_url` (extend the import already added in Task 5 to include `build_checkout_url`).

```python
@app.route('/payment/callback')
def payment_callback():
    # No @login_required: Remita's redirect may arrive in a context where
    # the session cookie isn't guaranteed, so this route is scoped instead
    # by the payment's unique unguessable reference token (like a password
    # reset link). It performs no write on behalf of a user identity beyond
    # what verify_payment does to the Payment/Registration it already owns.
    order_id = request.args.get('orderId') or request.args.get('orderid') or request.args.get('reference')
    payment = Payment.query.filter_by(reference=order_id).first() if order_id else None
    if payment is None:
        flash('Could not identify the payment to verify.')
        return redirect(url_for('payments_history'))

    gateway = get_gateway(app)
    verify_payment(gateway, payment)
    return render_template('payment_callback.html', payment=payment)


@app.route('/payment/<reference>/resume')
@login_required
def payment_resume(reference):
    payment = Payment.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    if payment.status not in ('pending', 'timeout'):
        flash('This payment is no longer pending.')
        return redirect(url_for('payments_history'))

    if payment.rrr:
        return redirect(build_checkout_url(payment.rrr))

    gateway = get_gateway(app)
    try:
        checkout_url = initiate_payment(gateway, payment, current_user)
    except GatewayError:
        flash('Could not reach the payment gateway. Please try again shortly.')
        return redirect(url_for('payments_history'))
    return redirect(checkout_url)


@app.route('/payment/<reference>/cancel', methods=['POST'])
@login_required
def payment_cancel(reference):
    payment = Payment.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    try:
        cancel_payment(payment)
    except PaymentError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    return jsonify({'success': True, 'message': 'Payment cancelled.'})


@app.route('/payment/<reference>/retry', methods=['POST'])
@login_required
def payment_retry(reference):
    payment = Payment.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    gateway = get_gateway(app)
    retry_verification(gateway, payment)
    return jsonify({'success': True, 'status': payment.status})
```

- [ ] **Step 2: Create `templates/payment_callback.html`**

```html
{% extends "base.html" %}

{% block head %}
    <title>Payment Result · Student Portal</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/pay_summary.css') }}">
{% endblock %}

{% block content %}
<div class="payment-summary-container">
    <div class="summary-card">
        <div class="summary-body" style="text-align:center; padding: 3rem 2rem;">
            {% if payment.status == 'successful' %}
                <div class="result-icon success"><i class="fas fa-check-circle"></i></div>
                <h2>Payment Successful</h2>
                <p>Your payment of ₦{{ '{:,.2f}'.format(payment.total_amount) }} (reference {{ payment.reference }}) was completed.</p>
                <a class="pay-now-btn" style="display:inline-flex; text-decoration:none; margin-top:1.5rem;" href="{{ url_for('payment_receipt', reference=payment.reference) }}"><i class="fas fa-receipt"></i> View Receipt</a>
            {% elif payment.status == 'failed' %}
                <div class="result-icon failed"><i class="fas fa-times-circle"></i></div>
                <h2>Payment Failed</h2>
                <p>Your payment (reference {{ payment.reference }}) was not successful. You can retry from Payment History.</p>
            {% else %}
                <div class="result-icon pending"><i class="fas fa-hourglass-half"></i></div>
                <h2>Payment Pending</h2>
                <p>We haven't received confirmation yet for reference {{ payment.reference }}. Check Payment History shortly, or retry verification there.</p>
            {% endif %}
            <div style="margin-top:2rem;">
                <a href="{{ url_for('payments_history') }}" style="font-weight:600; color: var(--primary-dark, #103957);">Go to Payment History</a>
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Add result-icon styles to `static/css/pay_summary.css`**

Append to the end of the file:
```css
.result-icon {
    font-size: 3.5rem;
    margin-bottom: 1rem;
}
.result-icon.success { color: #0e7a4b; }
.result-icon.failed { color: #b13e3e; }
.result-icon.pending { color: #b6580b; }
```

- [ ] **Step 4: Manual verification**

```bash
python -c "
from app import app
from models import db, User, Payment, PaymentCategory
from services.payment import create_payment, initiate_payment, verify_payment
from services.payment_gateway import SimulatedGateway

with app.app_context():
    app.config['PAYMENT_GATEWAY_MODE'] = 'simulated'
    user = User.query.first()
    cat = PaymentCategory(name='Callback Test Fee', code='callback_test_fee', default_amount=500, is_active=True)
    db.session.add(cat)
    db.session.commit()

    p = create_payment(user, [(cat, 1, 500)], idempotency_key='idem-callback-1')
    gw = SimulatedGateway()
    checkout_url = initiate_payment(gw, p, user)
    print('checkout_url:', checkout_url)

    p.gateway_status = 'successful'
    verify_payment(gw, p)
    print('status after verify:', p.status)
    assert p.status == 'successful'

    # idempotent re-verify should no-op
    p.gateway_status = 'failed'
    verify_payment(gw, p)
    print('status after second verify (should still be successful):', p.status)
    assert p.status == 'successful'

    from models import PaymentItem
    PaymentItem.query.filter_by(payment_id=p.id).delete()
    from models import PaymentReceipt, GatewayResponse
    PaymentReceipt.query.filter_by(payment_id=p.id).delete()
    GatewayResponse.query.filter_by(payment_id=p.id).delete()
    db.session.delete(p)
    db.session.delete(cat)
    db.session.commit()
    print('cleanup done')
"
```
Expected: `status after verify: successful`, and the idempotency re-verify confirms status stays `successful` despite `gateway_status` being set to `failed` before the second call. This script is throwaway — do not commit it.

- [ ] **Step 5: Commit**
```bash
git add app.py templates/payment_callback.html static/css/pay_summary.css
git commit -m "feat: add payment callback/verify, resume, cancel, and retry routes"
```

---

### Task 7: Create Payment (Independent Payments)

**Files:**
- Create: `templates/payment_create.html`
- Create: `static/css/payment_create.css`
- Create: `static/js/payment_create/payment_create.js`
- Modify: `app.py`

**Interfaces:**
- Consumes: `services.payment.get_active_categories`/`create_payment`/`initiate_payment`.
- Produces: routes `payment_create_page` (GET `/payment/create`), `payment_create_submit` (POST `/payment/create`).

- [ ] **Step 1: Add routes to `app.py`**

```python
@app.route('/payment/create', methods=['GET'])
@login_required
def payment_create_page():
    categories = get_active_categories()
    idempotency_key = str(uuid.uuid4())
    return render_template('payment_create.html', categories=categories, idempotency_key=idempotency_key)


@app.route('/payment/create', methods=['POST'])
@login_required
def payment_create_submit():
    data = request.get_json() or {}
    idempotency_key = data.get('idempotency_key', '')
    selections = data.get('items', [])
    if not idempotency_key:
        return jsonify({'success': False, 'message': 'Invalid request.'}), 400

    item_specs = []
    for sel in selections:
        category = PaymentCategory.query.filter_by(id=sel.get('category_id'), is_active=True).first()
        if category is None or category.default_amount is None:
            continue
        quantity = max(1, int(sel.get('quantity', 1)))
        item_specs.append((category, quantity, category.default_amount))

    try:
        payment = create_payment(current_user, item_specs, idempotency_key)
    except PaymentError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    gateway = get_gateway(app)
    try:
        checkout_url = initiate_payment(gateway, payment, current_user)
    except GatewayError as e:
        return jsonify({'success': False, 'message': str(e)}), 502

    return jsonify({'success': True, 'redirect': checkout_url})
```
(`uuid` is already imported at the top of `app.py`.)

- [ ] **Step 2: Create `templates/payment_create.html`**

```html
{% extends "base.html" %}

{% block head %}
    <title>Create Payment · Student Portal</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/payment_create.css') }}">
{% endblock %}

{% block content %}
<div class="payment-create-page">
    <input type="hidden" id="csrf_token" value="{{ csrf_token() }}">
    <input type="hidden" id="idempotencyKey" value="{{ idempotency_key }}">

    <div class="page-header">
        <a href="{{ url_for('payments_history') }}" class="back-link"><i class="fas fa-arrow-left"></i> Payment History</a>
        <h1 class="page-title"><i class="fas fa-plus-circle"></i> Create Payment</h1>
        <div></div>
    </div>

    {% if not categories %}
    <div class="empty-state-card">
        <i class="fas fa-inbox"></i>
        <p>No payable items are currently available.</p>
    </div>
    {% else %}
    <div class="category-grid" id="categoryGrid">
        {% for category in categories %}
        <label class="category-card">
            <input type="checkbox" class="category-checkbox" data-id="{{ category.id }}" data-amount="{{ category.default_amount }}" data-name="{{ category.name }}">
            <div class="category-info">
                <span class="category-name">{{ category.name }}</span>
                {% if category.description %}<span class="category-desc">{{ category.description }}</span>{% endif %}
            </div>
            <span class="category-amount">₦{{ '{:,.2f}'.format(category.default_amount) }}</span>
        </label>
        {% endfor %}
    </div>

    <div class="summary-panel">
        <h3><i class="fas fa-receipt"></i> Payment Summary</h3>
        <ul id="summaryList" class="summary-list">
            <li class="summary-empty">No items selected yet.</li>
        </ul>
        <div class="summary-total">
            <span>Total</span>
            <span id="summaryTotal">₦0.00</span>
        </div>
        <button class="pay-now-btn" id="proceedBtn" disabled><i class="fas fa-credit-card"></i> Proceed to Payment</button>
    </div>
    {% endif %}
</div>

<div id="toastMsg" class="toast-msg"></div>
{% endblock %}

{% block scripts %}
<script type="module" src="{{ url_for('static', filename='js/payment_create/payment_create.js') }}"></script>
{% endblock %}
```

- [ ] **Step 3: Create `static/css/payment_create.css`**

```css
:root {
    --bg-body: #f5faff;
    --card-bg: rgba(255, 255, 255, 0.9);
    --primary-dark: #103957;
    --primary: #1d4f7c;
    --primary-light: #e3efff;
    --accent: #286b9f;
    --text-main: #102c42;
    --text-muted: #5f7e9c;
    --border-color: #cfe0f2;
    --radius-md: 1.6rem;
    --radius-sm: 1.2rem;
}

.payment-create-page {
    max-width: 1100px;
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
    margin: 20px auto;
}

.page-header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
}

.back-link {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    background: white;
    padding: 0.7rem 1.6rem;
    border-radius: 60px;
    color: var(--primary-dark);
    font-weight: 600;
    text-decoration: none;
    border: 1px solid var(--border-color);
}

.page-title { font-size: 1.5rem; color: var(--primary-dark); }

.category-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 1rem;
}

.category-card {
    display: flex;
    align-items: center;
    gap: 0.8rem;
    background: var(--card-bg);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-sm);
    padding: 1rem 1.2rem;
    cursor: pointer;
}
.category-card:has(.category-checkbox:checked) {
    border-color: var(--accent);
    background: var(--primary-light);
}
.category-checkbox { width: 18px; height: 18px; }
.category-info { display: flex; flex-direction: column; flex: 1; }
.category-name { font-weight: 600; color: var(--text-main); }
.category-desc { font-size: 0.85rem; color: var(--text-muted); }
.category-amount { font-weight: 700; color: var(--primary-dark); }

.summary-panel {
    background: white;
    border-radius: var(--radius-md);
    border: 1px solid var(--border-color);
    padding: 1.5rem;
}
.summary-list { list-style: none; padding: 0; margin: 0.8rem 0; display: flex; flex-direction: column; gap: 0.4rem; }
.summary-list li { display: flex; justify-content: space-between; color: var(--text-main); }
.summary-empty { color: var(--text-muted); font-style: italic; }
.summary-total { display: flex; justify-content: space-between; font-weight: 700; font-size: 1.1rem; padding-top: 0.8rem; border-top: 1px solid var(--border-color); color: var(--primary-dark); }

.pay-now-btn {
    margin-top: 1.2rem;
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.6rem;
    padding: 0.9rem;
    border: none;
    border-radius: 60px;
    background: #0f3150;
    color: white;
    font-weight: 600;
    cursor: pointer;
}
.pay-now-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.empty-state-card {
    background: white;
    border-radius: var(--radius-md);
    border: 1px solid var(--border-color);
    padding: 3rem;
    text-align: center;
    color: var(--text-muted);
}
.empty-state-card i { font-size: 2rem; margin-bottom: 0.8rem; display: block; }
```

- [ ] **Step 4: Create `static/js/payment_create/payment_create.js`**

```js
import { postJson } from '../shared/api.js';
import { showToast } from '../shared/toast.js';

const checkboxes = document.querySelectorAll('.category-checkbox');
const summaryList = document.getElementById('summaryList');
const summaryTotal = document.getElementById('summaryTotal');
const proceedBtn = document.getElementById('proceedBtn');

function formatNaira(amount) {
    return '₦' + amount.toLocaleString('en-NG', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function renderSummary() {
    const selected = Array.from(checkboxes).filter((cb) => cb.checked);

    if (selected.length === 0) {
        summaryList.innerHTML = '<li class="summary-empty">No items selected yet.</li>';
        summaryTotal.textContent = formatNaira(0);
        proceedBtn.disabled = true;
        return;
    }

    let total = 0;
    summaryList.innerHTML = '';
    selected.forEach((cb) => {
        const amount = parseFloat(cb.dataset.amount);
        total += amount;
        const li = document.createElement('li');
        li.textContent = '';
        const nameSpan = document.createElement('span');
        nameSpan.textContent = cb.dataset.name;
        const amountSpan = document.createElement('span');
        amountSpan.textContent = formatNaira(amount);
        li.appendChild(nameSpan);
        li.appendChild(amountSpan);
        summaryList.appendChild(li);
    });
    summaryTotal.textContent = formatNaira(total);
    proceedBtn.disabled = false;
}

checkboxes.forEach((cb) => cb.addEventListener('change', renderSummary));

if (proceedBtn) {
    proceedBtn.addEventListener('click', async () => {
        const selected = Array.from(checkboxes).filter((cb) => cb.checked);
        if (selected.length === 0) return;

        proceedBtn.disabled = true;
        const originalHtml = proceedBtn.innerHTML;
        proceedBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Redirecting to Remita…';

        const idempotencyKey = document.getElementById('idempotencyKey').value;
        const items = selected.map((cb) => ({ category_id: parseInt(cb.dataset.id, 10), quantity: 1 }));

        const result = await postJson('/payment/create', { idempotency_key: idempotencyKey, items });

        if (result.success) {
            window.location.href = result.redirect;
        } else {
            showToast(result.message || 'Could not start payment.', true);
            proceedBtn.disabled = false;
            proceedBtn.innerHTML = originalHtml;
        }
    });
}
```

- [ ] **Step 5: Manual verification**

```bash
python -c "
from app import app
from models import db, PaymentCategory

with app.app_context():
    if not PaymentCategory.query.filter_by(code='manual_test_fee').first():
        db.session.add(PaymentCategory(name='Manual Test Fee', code='manual_test_fee', default_amount=1000, is_active=True))
        db.session.commit()

    client = app.test_client()
    # Fetch a real CSRF token + session from a rendered page first (this app's
    # global CSRFProtect requires a real token — a bare test client POST
    # without one will 400).
    from models import User
    with app.app_context():
        user = User.query.filter(User.reg_no.isnot(None)).first()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
    page = client.get('/payment/create')
    print('GET /payment/create status:', page.status_code)
    assert page.status_code == 200
    assert b'Manual Test Fee' in page.data
    print('category rendered on page: OK')

    PaymentCategory.query.filter_by(code='manual_test_fee').delete()
    db.session.commit()
    print('cleanup done')
"
```
Expected: `GET /payment/create status: 200` and confirmation the seeded category name appears in the rendered HTML. This script is throwaway — do not commit it.

- [ ] **Step 6: Commit**
```bash
git add templates/payment_create.html static/css/payment_create.css static/js/payment_create/payment_create.js app.py
git commit -m "feat: add Create Payment page for independent payments (library fee, hostel fee, etc.)"
```

---

### Task 8: Payment History and Dashboard Wiring

**Files:**
- Modify: `app.py`
- Modify: `templates/payments_history.html`
- Create: `static/js/payments_history/payments_history.js`
- Modify: `templates/dashboard.html`

**Interfaces:**
- Consumes: `services.payment.get_payment_history`/`get_summary_counts`.
- Produces: routes `payments_history` (GET `/payments_history`), `payments_history_data` (GET `/payments_history/data`).

- [ ] **Step 1: Replace the `payments_history` route in `app.py`**

Replace:
```python
@app.route('/payments_history')
def payments_history():
    return render_template('payments_history.html')
```
with:
```python
@app.route('/payments_history')
@login_required
def payments_history():
    items, total = get_payment_history(current_user, page=1, per_page=10)
    summary = get_payment_summary_counts(current_user)
    return render_template('payments_history.html', payments=items, total=total, page=1, per_page=10, summary=summary)


@app.route('/payments_history/data')
@login_required
def payments_history_data():
    status = request.args.get('status') or None
    search = request.args.get('search') or None
    date_from = request.args.get('date_from') or None
    date_to = request.args.get('date_to') or None
    page = max(1, int(request.args.get('page', 1)))
    per_page = 10

    items, total = get_payment_history(
        current_user, status=status, search=search,
        date_from=date_from, date_to=date_to, page=page, per_page=per_page,
    )
    raw_summary = get_payment_summary_counts(current_user)

    return jsonify({
        'success': True,
        'page': page,
        'per_page': per_page,
        'total': total,
        'summary': {
            'total': raw_summary['total'],
            'total_amount_paid': float(raw_summary['total_amount_paid']),
            'pending': raw_summary['pending'],
            'cancelled': raw_summary['cancelled'],
        },
        'payments': [
            {
                'reference': p.reference,
                'rrr': p.rrr or '-',
                'description': ', '.join(i.description for i in p.items) or '-',
                'category': p.items[0].category.name if p.items else '-',
                'amount': float(p.total_amount),
                'status': p.status,
                'date': p.initiated_at.strftime('%d %b %Y'),
                'session': p.registration.registration_period.academic_session.name if p.registration else '-',
                'semester': p.registration.registration_period.semester.name if p.registration else '-',
                'method': 'Remita',
                'can_retry': p.status in ('pending', 'timeout', 'failed'),
                'can_resume': p.status in ('pending', 'timeout'),
                'has_receipt': p.status == 'successful',
            }
            for p in items
        ],
    })
```

- [ ] **Step 2: Rewrite `templates/payments_history.html`**

Replace the summary-grid, filter-bar, and table sections (keep the outer `.payment-page`/`.page-header` structure and CSS link):
```html
{% extends "base.html" %}


{% block head %}
    <title>Full Payment History · EduPortal</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/payments_history.css') }}">
{% endblock %}


{% block content %}
    <div class="payment-page">
        <input type="hidden" id="csrf_token" value="{{ csrf_token() }}">

        <div class="page-header">
            <a href="{{ url_for('dashboard') }}" class="back-link"><i class="fas fa-arrow-left"></i> Back to Dashboard</a>
            <h1 class="page-title"><i class="fas fa-credit-card" style="margin-right: 0.5rem;"></i>Full Payment History</h1>
            <a href="{{ url_for('payment_create_page') }}" class="back-link"><i class="fas fa-plus-circle"></i> Create Payment</a>
        </div>

        <div class="summary-grid">
            <div class="summary-card">
                <div class="summary-icon"><i class="fas fa-receipt"></i></div>
                <div class="summary-content"><h4>Total payments</h4><div class="summary-amount" id="summaryTotal">{{ summary.total }}</div></div>
            </div>
            <div class="summary-card">
                <div class="summary-icon"><i class="fas fa-wallet"></i></div>
                <div class="summary-content"><h4>Total paid</h4><div class="summary-amount" id="summaryAmountPaid">₦{{ '{:,.2f}'.format(summary.total_amount_paid) }}</div></div>
            </div>
            <div class="summary-card">
                <div class="summary-icon"><i class="fas fa-clock"></i></div>
                <div class="summary-content"><h4>Pending</h4><div class="summary-amount" id="summaryPending">{{ summary.pending }}</div></div>
            </div>
            <div class="summary-card">
                <div class="summary-icon"><i class="fas fa-exclamation-triangle"></i></div>
                <div class="summary-content"><h4>Cancelled</h4><div class="summary-amount" id="summaryCancelled">{{ summary.cancelled }}</div></div>
            </div>
        </div>

        <div class="filter-bar">
            <div class="filter-tabs" id="filterTabs">
                <button class="filter-tab active" data-status="">All payments</button>
                <button class="filter-tab" data-status="successful">Paid</button>
                <button class="filter-tab" data-status="pending">Pending</button>
                <button class="filter-tab" data-status="cancelled">Cancelled</button>
            </div>
            <input type="date" id="dateFrom" class="date-filter">
            <input type="date" id="dateTo" class="date-filter">
            <div class="search-box">
                <i class="fas fa-search"></i>
                <input type="text" id="searchInput" placeholder="Search reference or RRR">
                <button id="searchBtn">Search</button>
            </div>
        </div>

        <div class="table-card">
            <div class="table-header">
                <h2><i class="fas fa-history"></i> Transaction history</h2>
                <div class="print-export">
                    <button onclick="window.print()"><i class="fas fa-print"></i> Print</button>
                </div>
            </div>

            <div class="table-wrapper">
                <table id="paymentsTable">
                    <thead>
                        <tr>
                            <th>Description</th>
                            <th>Date</th>
                            <th>Session / Semester</th>
                            <th>Reference</th>
                            <th>Amount (₦)</th>
                            <th>Status</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody id="paymentsTableBody">
                        <tr><td colspan="7" style="text-align:center; padding:2rem; color: var(--text-muted);"><i class="fas fa-spinner fa-spin"></i> Loading…</td></tr>
                    </tbody>
                </table>
            </div>

            <div class="pagination">
                <div id="paginationInfo" style="color: var(--text-muted); font-size:0.9rem;"></div>
                <div class="page-buttons" id="pageButtons"></div>
            </div>
        </div>
    </div>

<div id="toastMsg" class="toast-msg"></div>
{% endblock %}

{% block scripts %}
<script type="module" src="{{ url_for('static', filename='js/payments_history/payments_history.js') }}"></script>
{% endblock %}
```

- [ ] **Step 3: Create `static/js/payments_history/payments_history.js`**

```js
import { postJson } from '../shared/api.js';
import { showToast } from '../shared/toast.js';

const tableBody = document.getElementById('paymentsTableBody');
const filterTabs = document.getElementById('filterTabs');
const searchInput = document.getElementById('searchInput');
const searchBtn = document.getElementById('searchBtn');
const dateFrom = document.getElementById('dateFrom');
const dateTo = document.getElementById('dateTo');
const paginationInfo = document.getElementById('paginationInfo');
const pageButtons = document.getElementById('pageButtons');

const STATUS_LABELS = {
    successful: '<span class="status-badge paid"><i class="fas fa-check-circle"></i> Paid</span>',
    pending: '<span class="status-badge pending"><i class="fas fa-hourglass-half"></i> Pending</span>',
    cancelled: '<span class="status-badge overdue"><i class="fas fa-exclamation-circle"></i> Cancelled</span>',
    failed: '<span class="status-badge overdue"><i class="fas fa-exclamation-circle"></i> Failed</span>',
    timeout: '<span class="status-badge overdue"><i class="fas fa-exclamation-circle"></i> Timed out</span>',
};

let state = { status: '', search: '', page: 1 };

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

async function getJson(url) {
    const csrf = document.getElementById('csrf_token').value;
    const response = await fetch(url, { headers: { 'X-CSRFToken': csrf } });
    return response.json();
}

function renderActions(p) {
    const actions = [];
    if (p.has_receipt) {
        actions.push(`<a href="/payment/${p.reference}/receipt" class="receipt-link"><i class="fas fa-eye"></i> View</a>`);
        actions.push(`<a href="/payment/${p.reference}/receipt.pdf" class="receipt-link"><i class="fas fa-file-pdf"></i> PDF</a>`);
        actions.push(`<button class="receipt-link resend-btn" data-reference="${p.reference}"><i class="fas fa-envelope"></i> Resend</button>`);
    }
    if (p.can_resume) {
        actions.push(`<a href="/payment/${p.reference}/resume" class="receipt-link"><i class="fas fa-play"></i> Resume</a>`);
    }
    if (p.can_retry) {
        actions.push(`<button class="receipt-link retry-btn" data-reference="${p.reference}"><i class="fas fa-redo"></i> Retry</button>`);
    }
    return actions.join(' ');
}

function renderRows(payments) {
    if (payments.length === 0) {
        tableBody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:2rem; color: var(--text-muted);">No payments found.</td></tr>';
        return;
    }
    tableBody.innerHTML = payments.map((p) => `
        <tr>
            <td><strong>${escapeHtml(p.description)}</strong></td>
            <td>${escapeHtml(p.date)}</td>
            <td>${escapeHtml(p.session)} ${escapeHtml(p.semester)}</td>
            <td style="font-family: monospace;">${escapeHtml(p.reference)}</td>
            <td><strong>${p.amount.toLocaleString('en-NG', { minimumFractionDigits: 2 })}</strong></td>
            <td>${STATUS_LABELS[p.status] || escapeHtml(p.status)}</td>
            <td>${renderActions(p)}</td>
        </tr>
    `).join('');

    tableBody.querySelectorAll('.retry-btn').forEach((btn) => {
        btn.addEventListener('click', async () => {
            btn.disabled = true;
            const result = await postJson(`/payment/${btn.dataset.reference}/retry`, {});
            showToast(result.success ? `Status: ${result.status}` : (result.message || 'Retry failed.'), !result.success);
            load();
        });
    });
    tableBody.querySelectorAll('.resend-btn').forEach((btn) => {
        btn.addEventListener('click', async () => {
            btn.disabled = true;
            const result = await postJson(`/payment/${btn.dataset.reference}/resend-receipt`, {});
            showToast(result.message || (result.success ? 'Receipt sent.' : 'Could not resend receipt.'), !result.success);
            btn.disabled = false;
        });
    });
}

function renderPagination(total, page, perPage) {
    const totalPages = Math.max(1, Math.ceil(total / perPage));
    paginationInfo.textContent = total === 0 ? 'No transactions' : `Showing page ${page} of ${totalPages} (${total} total)`;
    pageButtons.innerHTML = '';
    for (let i = 1; i <= totalPages; i++) {
        const btn = document.createElement('button');
        btn.className = 'page-btn' + (i === page ? ' active' : '');
        btn.textContent = i;
        btn.addEventListener('click', () => { state.page = i; load(); });
        pageButtons.appendChild(btn);
    }
}

async function load() {
    tableBody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:2rem; color: var(--text-muted);"><i class="fas fa-spinner fa-spin"></i> Loading…</td></tr>';

    const params = new URLSearchParams({ page: state.page });
    if (state.status) params.set('status', state.status);
    if (state.search) params.set('search', state.search);
    if (dateFrom.value) params.set('date_from', dateFrom.value);
    if (dateTo.value) params.set('date_to', dateTo.value);

    const result = await getJson(`/payments_history/data?${params.toString()}`);
    if (!result.success) {
        tableBody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:2rem; color: #b13e3e;">Could not load payment history.</td></tr>';
        return;
    }

    document.getElementById('summaryTotal').textContent = result.summary.total;
    document.getElementById('summaryAmountPaid').textContent = '₦' + result.summary.total_amount_paid.toLocaleString('en-NG', { minimumFractionDigits: 2 });
    document.getElementById('summaryPending').textContent = result.summary.pending;
    document.getElementById('summaryCancelled').textContent = result.summary.cancelled;

    renderRows(result.payments);
    renderPagination(result.total, result.page, result.per_page);
}

filterTabs.querySelectorAll('.filter-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
        filterTabs.querySelectorAll('.filter-tab').forEach((t) => t.classList.remove('active'));
        tab.classList.add('active');
        state.status = tab.dataset.status;
        state.page = 1;
        load();
    });
});

searchBtn.addEventListener('click', () => { state.search = searchInput.value.trim(); state.page = 1; load(); });
searchInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { state.search = searchInput.value.trim(); state.page = 1; load(); } });
dateFrom.addEventListener('change', () => { state.page = 1; load(); });
dateTo.addEventListener('change', () => { state.page = 1; load(); });

load();
```

- [ ] **Step 4: Wire the dashboard's payment panel**

In `app.py`, replace the `dashboard` route:
```python
def dashboard():
    notify_registration_window_events(current_user)
    return render_template('dashboard.html', profile_display=get_profile_display(current_user))
```
with:
```python
def dashboard():
    notify_registration_window_events(current_user)
    recent_payments, _ = get_payment_history(current_user, page=1, per_page=5)
    payment_summary = get_payment_summary_counts(current_user)
    return render_template(
        'dashboard.html',
        profile_display=get_profile_display(current_user),
        recent_payments=recent_payments,
        payment_summary=payment_summary,
    )
```

In `templates/dashboard.html`, replace the dead payment panel:
```html
        <div class="payment-section">
            <div class="payment-header">
                <h3><i class="fas fa-credit-card" style="background: none; padding:0;"></i> Recent payment history</h3>
                <a href="#" style="color: #1e5a8a; font-weight:600;">View all <i class="fas fa-chevron-right"></i></a>
            </div>
            <div class="table-wrapper">
                <div class="empty-state-row">
                    <i class="fas fa-receipt"></i>
                    <p>No payment history yet.</p>
                </div>
            </div>

        </div>
```
with:
```html
        <div class="payment-section">
            <div class="payment-header">
                <h3><i class="fas fa-credit-card" style="background: none; padding:0;"></i> Recent payment history</h3>
                <a href="{{ url_for('payments_history') }}" style="color: #1e5a8a; font-weight:600;">View all <i class="fas fa-chevron-right"></i></a>
            </div>
            <div class="table-wrapper">
                {% if not recent_payments %}
                <div class="empty-state-row">
                    <i class="fas fa-receipt"></i>
                    <p>No payment history yet.</p>
                </div>
                {% else %}
                <table>
                    <thead><tr><th>Description</th><th>Date</th><th>Amount</th><th>Status</th></tr></thead>
                    <tbody>
                        {% for p in recent_payments %}
                        <tr>
                            <td>{{ p.items[0].description if p.items else '-' }}</td>
                            <td>{{ p.initiated_at.strftime('%d %b %Y') }}</td>
                            <td>₦{{ '{:,.2f}'.format(p.total_amount) }}</td>
                            <td>{{ p.status|capitalize }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
                {% endif %}
            </div>

        </div>
```

- [ ] **Step 5: Manual verification**

```bash
python -c "
from app import app
from models import db, User, Payment, PaymentItem, PaymentCategory

with app.app_context():
    user = User.query.filter(User.reg_no.isnot(None)).first()
    cat = PaymentCategory(name='History Test Fee', code='history_test_fee', default_amount=750, is_active=True)
    db.session.add(cat)
    db.session.commit()
    p = Payment(user_id=user.id, reference='HISTTEST01', idempotency_key='idem-hist-1', status='successful', total_amount=750, gateway_status='00')
    db.session.add(p)
    db.session.commit()
    db.session.add(PaymentItem(payment_id=p.id, category_id=cat.id, description='History Test Fee', amount=750, quantity=1))
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True

    resp = client.get('/payments_history')
    print('GET /payments_history status:', resp.status_code)
    assert resp.status_code == 200

    data_resp = client.get('/payments_history/data')
    payload = data_resp.get_json()
    print('data endpoint payments count:', len(payload['payments']))
    assert any(item['reference'] == 'HISTTEST01' for item in payload['payments'])
    print('real payment appears in data endpoint: OK')

    dash_resp = client.get('/dashboard')
    print('GET /dashboard status:', dash_resp.status_code)
    assert b'History Test Fee' in dash_resp.data
    print('dashboard shows recent payment: OK')

    PaymentItem.query.filter_by(payment_id=p.id).delete()
    db.session.delete(p)
    db.session.delete(cat)
    db.session.commit()
    print('cleanup done')
"
```
Expected: both routes 200, the seeded payment appears in the `/payments_history/data` JSON and on the dashboard. This script is throwaway — do not commit it.

- [ ] **Step 6: Commit**
```bash
git add app.py templates/payments_history.html static/js/payments_history/payments_history.js templates/dashboard.html
git commit -m "feat: wire Payment History (search/filter/pagination/actions) and dashboard recent-payments panel to real data"
```

---

### Task 9: Receipt Views

**Files:**
- Modify: `app.py`
- Create: `templates/payment_receipt.html`

**Interfaces:**
- Consumes: `services.receipt.get_or_create_receipt`/`render_pdf`/`send_receipt_email`.
- Produces: routes `payment_receipt` (GET `/payment/<reference>/receipt`), `payment_receipt_pdf` (GET `/payment/<reference>/receipt.pdf`), `payment_resend_receipt` (POST `/payment/<reference>/resend-receipt`).

- [ ] **Step 1: Add receipt routes to `app.py`**

Add `from flask import Response` to the existing `from flask import (...)` import line, and `from services.receipt import get_or_create_receipt, render_pdf, send_receipt_email` as a new import.

```python
@app.route('/payment/<reference>/receipt')
@login_required
def payment_receipt(reference):
    payment = Payment.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    if payment.status != 'successful':
        flash('Receipt is only available for successful payments.')
        return redirect(url_for('payments_history'))
    receipt = get_or_create_receipt(payment)
    return render_template('payment_receipt.html', payment=payment, receipt=receipt)


@app.route('/payment/<reference>/receipt.pdf')
@login_required
def payment_receipt_pdf(reference):
    payment = Payment.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    if payment.status != 'successful':
        flash('Receipt is only available for successful payments.')
        return redirect(url_for('payments_history'))
    receipt = get_or_create_receipt(payment)
    pdf_bytes = render_pdf(payment, receipt)
    return Response(pdf_bytes, mimetype='application/pdf', headers={
        'Content-Disposition': f'attachment; filename={receipt.receipt_number}.pdf'
    })


@app.route('/payment/<reference>/resend-receipt', methods=['POST'])
@login_required
def payment_resend_receipt(reference):
    payment = Payment.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    if payment.status != 'successful':
        return jsonify({'success': False, 'message': 'No receipt available for this payment.'}), 400
    receipt = get_or_create_receipt(payment)
    send_receipt_email(payment, receipt)
    return jsonify({'success': True, 'message': 'Receipt email sent.'})
```

- [ ] **Step 2: Create `templates/payment_receipt.html`**

```html
{% extends "base.html" %}

{% block head %}
    <title>Payment Receipt · Student Portal</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        .receipt-container { max-width: 700px; margin: 2rem auto; background: white; padding: 2rem; border-radius: 1rem; border: 1px solid #d9e9ff; }
        .receipt-header { display: flex; align-items: center; gap: 1rem; margin-bottom: 1.5rem; }
        .receipt-header img { width: 48px; height: 48px; border-radius: 50%; object-fit: cover; }
        .receipt-table { width: 100%; border-collapse: collapse; margin: 1rem 0; }
        .receipt-table th, .receipt-table td { padding: 0.6rem; border-bottom: 1px solid #eef3fc; text-align: left; }
        .receipt-total { text-align: right; font-weight: 700; font-size: 1.1rem; margin-top: 0.5rem; }
        .receipt-qr { width: 90px; height: 90px; border: 1px dashed #9fb8d1; display: flex; align-items: center; justify-content: center; color: #5f7e9c; margin-top: 1.5rem; }
        .receipt-actions { display: flex; gap: 0.8rem; margin-top: 1.5rem; }
        .receipt-actions button, .receipt-actions a { display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.6rem 1.4rem; border-radius: 60px; background: #0f3150; color: white; border: none; cursor: pointer; text-decoration: none; font-size: 0.9rem; }
        @media print {
            .navbar, .receipt-actions { display: none !important; }
        }
    </style>
{% endblock %}

{% block content %}
<div class="receipt-container">
    <input type="hidden" id="csrf_token" value="{{ csrf_token() }}">
    <div class="receipt-header">
        <img src="{{ url_for('static', filename='img/jspict-logo.png') }}" alt="JSPICT Logo">
        <div>
            <h2>Payment Receipt</h2>
            <p>{{ receipt.receipt_number }}</p>
        </div>
    </div>
    <div>
        <strong>Student:</strong> {{ payment.user.name }} ({{ payment.user.reg_no }})<br>
        <strong>Reference:</strong> {{ payment.reference }}<br>
        <strong>RRR:</strong> {{ payment.rrr or '-' }}<br>
        <strong>Payment Date:</strong> {{ payment.verified_at.strftime('%d %b %Y, %I:%M %p') if payment.verified_at else '-' }}<br>
        <strong>Gateway Status:</strong> {{ payment.gateway_status or '-' }}
    </div>
    <table class="receipt-table">
        <thead><tr><th>Description</th><th>Qty</th><th>Amount (₦)</th></tr></thead>
        <tbody>
            {% for item in payment.items %}
            <tr><td>{{ item.description }}</td><td>{{ item.quantity }}</td><td>{{ '{:,.2f}'.format(item.amount * item.quantity) }}</td></tr>
            {% endfor %}
        </tbody>
    </table>
    <div class="receipt-total">Total: ₦{{ '{:,.2f}'.format(payment.total_amount) }}</div>
    <div class="receipt-qr">QR</div>

    <div class="receipt-actions">
        <button onclick="window.print()"><i class="fas fa-print"></i> Print</button>
        <a href="{{ url_for('payment_receipt_pdf', reference=payment.reference) }}"><i class="fas fa-file-pdf"></i> Download PDF</a>
        <button id="resendBtn" data-reference="{{ payment.reference }}"><i class="fas fa-envelope"></i> Resend Email</button>
    </div>
</div>

<div id="toastMsg" class="toast-msg"></div>
{% endblock %}

{% block scripts %}
<script type="module">
    import { postJson } from '{{ url_for("static", filename="js/shared/api.js") }}';
    import { showToast } from '{{ url_for("static", filename="js/shared/toast.js") }}';

    const btn = document.getElementById('resendBtn');
    btn.addEventListener('click', async () => {
        btn.disabled = true;
        const result = await postJson(`/payment/${btn.dataset.reference}/resend-receipt`, {});
        showToast(result.message || (result.success ? 'Receipt sent.' : 'Could not resend receipt.'), !result.success);
        btn.disabled = false;
    });
</script>
{% endblock %}
```

- [ ] **Step 3: Manual verification**

```bash
python -c "
from app import app
from models import db, User, Payment, PaymentItem, PaymentCategory

with app.app_context():
    user = User.query.filter(User.reg_no.isnot(None)).first()
    cat = PaymentCategory(name='Receipt View Test Fee', code='receipt_view_test_fee', default_amount=1200, is_active=True)
    db.session.add(cat)
    db.session.commit()
    p = Payment(user_id=user.id, reference='RCPTVIEW01', idempotency_key='idem-rcptview-1', status='successful', total_amount=1200, gateway_status='00')
    db.session.add(p)
    db.session.commit()
    db.session.add(PaymentItem(payment_id=p.id, category_id=cat.id, description='Receipt View Test Fee', amount=1200, quantity=1))
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True

    resp = client.get('/payment/RCPTVIEW01/receipt')
    print('GET receipt page status:', resp.status_code)
    assert resp.status_code == 200 and b'Receipt View Test Fee' in resp.data

    pdf_resp = client.get('/payment/RCPTVIEW01/receipt.pdf')
    print('GET receipt PDF status:', pdf_resp.status_code, 'content-type:', pdf_resp.content_type)
    assert pdf_resp.status_code == 200 and pdf_resp.data[:4] == b'%PDF'
    print('receipt PDF verified')

    from models import PaymentReceipt
    PaymentReceipt.query.filter_by(payment_id=p.id).delete()
    PaymentItem.query.filter_by(payment_id=p.id).delete()
    db.session.delete(p)
    db.session.delete(cat)
    db.session.commit()
    print('cleanup done')
"
```
Expected: both routes 200, the PDF response's raw bytes start with `%PDF`. This script is throwaway — do not commit it.

- [ ] **Step 4: Commit**
```bash
git add app.py templates/payment_receipt.html
git commit -m "feat: add printable receipt view, PDF download, and resend-by-email routes"
```

---

### Task 10: Seed Data and Progress Log

**Files:**
- Modify: `seed_dev_data.py`
- Modify: `DEVELOPMENT_PROGRESS.md`

**Interfaces:**
- Consumes: `services.payment.create_payment`/`initiate_payment`, `services.payment_gateway.SimulatedGateway`.
- Produces: `seed_payment_categories()`, `seed_payments()` (called from `seed()`).

- [ ] **Step 1: Read `seed_dev_data.py` first, then add `seed_payment_categories()`**

Following the file's established pattern (idempotent, checks-before-insert, prints one confirmation line per unit, called from the outer `seed()` which already holds `app.app_context()`), add:
```python
def seed_payment_categories():
    categories = [
        ('Registration Fee', 'registration_fee', 'Per-semester registration fee (amount set by the active registration period).', None),
        ('Library Fee', 'library_fee', 'Annual library access and book borrowing fee.', 5000),
        ('Laboratory Fee', 'laboratory_fee', 'Per-semester laboratory materials and equipment fee.', 12000),
        ('Acceptance Fee', 'acceptance_fee', 'One-time fee paid on admission.', 50000),
        ('Hostel Fee', 'hostel_fee', 'Per-session hostel accommodation fee.', 45000),
        ('Transcript Fee', 'transcript_fee', 'Official transcript request and processing fee.', 7500),
        ('ID Card', 'id_card', 'Student ID card issuance or replacement.', 2000),
        ('Late Registration', 'late_registration', 'Penalty fee for registering after the deadline.', 10000),
    ]
    for name, code, description, default_amount in categories:
        if PaymentCategory.query.filter_by(code=code).first():
            print(f'Skipping payment category "{name}" (already exists)')
            continue
        db.session.add(PaymentCategory(
            name=name, code=code, description=description,
            default_amount=default_amount, is_active=True,
        ))
        db.session.commit()
        print(f'Seeded payment category: {name}')
```
Add `PaymentCategory` to the `from models import (...)` block at the top of the file.

- [ ] **Step 2: Add `seed_payments()`**

```python
def seed_payments():
    from services.payment import create_payment, initiate_payment, verify_payment
    from services.payment_gateway import SimulatedGateway

    chiamaka = User.query.filter_by(reg_no='2308-2301-0003').first()
    if not chiamaka:
        print('Skipping seed_payments (Chiamaka demo user not found)')
        return

    if Payment.query.filter_by(user_id=chiamaka.id).count() > 0:
        print('Skipping seed_payments (Chiamaka already has payment history)')
        return

    library = PaymentCategory.query.filter_by(code='library_fee').first()
    id_card = PaymentCategory.query.filter_by(code='id_card').first()
    hostel = PaymentCategory.query.filter_by(code='hostel_fee').first()
    if not (library and id_card and hostel):
        print('Skipping seed_payments (categories not seeded yet)')
        return

    gateway = SimulatedGateway()

    # One successful payment, fully driven through the real service flow.
    p1 = create_payment(chiamaka, [(library, 1, library.default_amount)], idempotency_key='seed-payment-1')
    initiate_payment(gateway, p1, chiamaka)
    p1.gateway_status = 'successful'
    verify_payment(gateway, p1)

    # One pending payment (RRR obtained, never completed — exercises Resume).
    p2 = create_payment(chiamaka, [(id_card, 1, id_card.default_amount)], idempotency_key='seed-payment-2')
    initiate_payment(gateway, p2, chiamaka)

    # One cancelled payment.
    p3 = create_payment(chiamaka, [(hostel, 1, hostel.default_amount)], idempotency_key='seed-payment-3')
    initiate_payment(gateway, p3, chiamaka)
    from services.payment import cancel_payment
    cancel_payment(p3)

    print('Seeded 3 demo payments for Chiamaka (1 successful, 1 pending, 1 cancelled)')
```
Add `Payment` to the `from models import (...)` block.

- [ ] **Step 3: Call both from `seed()`, run the seed script**

In the `seed()` function, add calls to `seed_payment_categories()` and `seed_payments()` after the existing `seed_profile_extras()` call (matching the existing call order).

```bash
python seed_dev_data.py
```
Expected: prints 8 "Seeded payment category" lines (or "Skipping" if re-run) and the "Seeded 3 demo payments" line.

- [ ] **Step 4: Update `DEVELOPMENT_PROGRESS.md`**

Replace the "Known pre-existing issues" bullet about `payments_history`/`pay_summary` missing `@login_required` (now fixed) — remove that bullet.

Replace:
```
## Next milestone

Feature 9: Payments — awaiting approval before starting.
```
with:
```
## Feature 9, 10 & 11: Payment Module (History, Independent Creation, Processing) — Complete

- New models: `PaymentCategory`, `PaymentItem`, `PaymentReceipt`, `GatewayResponse`; `Payment` extended from its unused one-column stub into the real transaction record.
- New services: `services/payment_gateway.py` (`PaymentGateway` abstraction with a real `RemitaGateway` against Remita's published test/demo sandbox, and an offline `SimulatedGateway` used only by manual verification scripts), `services/payment.py` (create/initiate/verify/retry/cancel/history — `verify_payment` is idempotent), `services/payment_validation.py` (duplicate-pending detection), `services/receipt.py` (reportlab PDF generation, resend-by-email).
- `services/registration.py`'s `register_student()` refactored: registration payment is no longer simulated as instantly successful — it creates a real pending `Payment` and the student completes it via `payment_summary.html`'s Pay Now button, through the real gateway.
- `payments_history.html` and `payment_summary.html` keep their existing visual structure, wired to real data (AJAX-driven search/status filter/date-range filter/pagination for history, matching the Notifications page's established pattern). New `/payment/create` page for independent payments (Library Fee, Hostel Fee, ID Card, etc.) against the admin-configurable `PaymentCategory` catalog.
- Printable receipts (`window.print()`, matching the registration slip pattern) plus real PDF download (`reportlab`) and resend-by-email.
- Fixed: `/payments_history` and `/pay_summary` (now `/payment/registration/<id>`) were missing `@login_required`.
- Spec: `docs/superpowers/specs/2026-08-01-payment-module-design.md`
- Out of scope (deferred): Admin UI for managing `PaymentCategory` (Admin Portal not started), gating Add/Drop or course submission on `payment_status`.

## Next milestone

Admin Portal — not yet started.
```

- [ ] **Step 5: Commit**
```bash
git add seed_dev_data.py DEVELOPMENT_PROGRESS.md
git commit -m "feat: seed payment categories and demo payment history; record Payment Module as complete"
```
