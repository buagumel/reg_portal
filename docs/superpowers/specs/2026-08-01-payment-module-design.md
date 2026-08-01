# Payment Module Design (Features 9, 10 & 11)

**Status:** Approved for planning
**Author:** Controller (Claude), approved by user 2026-08-01

## Goal

Replace the two fully-hardcoded payment pages (`payments_history.html`, `payment_summary.html`) and the simulated always-succeeds registration payment with a real, database-backed Payment Module: payment history with search/filter/pagination, independent payment creation against an admin-configurable catalog, and a full initiate → redirect → gateway callback → verify → receipt → notify workflow integrated with the real Remita payment gateway in test mode.

## Current state (confirmed by codebase audit)

- `Payment` model is a one-column stub (`id` only), unused anywhere.
- `/pay_summary` and `/payments_history` routes `render_template()` with zero DB queries and no `@login_required` (a bug already flagged in `DEVELOPMENT_PROGRESS.md`).
- `services/registration.py`'s `register_student()` marks `StudentRegistration.payment_status='paid'` immediately with a `SIMULATED-` reference — explicit `# TODO` comments mark this as the seam for real Remita integration.
- No payment JS exists anywhere. No PDF library is installed. No gateway integration code exists — "Remita" appears only in comments/UI text.
- Dashboard's "Recent payment history" panel is a hardcoded empty state.
- `payment_summary.html` is orphaned — nothing links to it today.

## Data model

Extend the existing `Payment` stub; add four new tables. All new columns/tables — no destructive changes to existing tables.

```python
class PaymentCategory(db.Model):
    __tablename__ = 'payment_categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)      # "Library Fee"
    code = db.Column(db.String(50), unique=True, nullable=False)       # "library_fee"
    description = db.Column(db.Text, nullable=True)
    default_amount = db.Column(db.Numeric(10, 2), nullable=True)       # None only for the 'registration_fee' category (variable, period-driven)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=now_lagos, nullable=False)

class Payment(db.Model):  # extends existing stub — do not rename table
    __tablename__ = 'payments'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reference = db.Column(db.String(50), unique=True, nullable=False)      # "PAY-XXXXXXXXXX"
    idempotency_key = db.Column(db.String(64), unique=True, nullable=False)
    rrr = db.Column(db.String(50), nullable=True)                          # Remita Retrieval Reference, set after initiate
    registration_id = db.Column(db.Integer, db.ForeignKey('student_registrations.id'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending')   # pending, successful, failed, cancelled, timeout
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    gateway_status = db.Column(db.String(100), nullable=True)              # raw status string from gateway
    initiated_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
    verified_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User')
    registration = db.relationship('StudentRegistration')

class PaymentItem(db.Model):
    __tablename__ = 'payment_items'
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payments.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('payment_categories.id'), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)

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
    raw_payload = db.Column(db.Text, nullable=False)   # JSON string of whatever the gateway returned
    received_at = db.Column(db.DateTime, default=now_lagos, nullable=False)
```

`PaymentCategory` being a real table (not a hardcoded Python list) satisfies "admin-configurable, not hardcoded." Building an admin CRUD screen for it is **out of scope** per "Do not begin the Admin Portal yet" — categories are seeded via `seed_dev_data.py` for this milestone.

## Services

`services/payment_gateway.py`:
- `class PaymentGateway` (ABC): `initiate(payment, payer) -> {rrr, checkout_url}`, `verify(payment) -> {status, gateway_status, raw}`.
- `class RemitaGateway(PaymentGateway)` — the real implementation, using Remita's published test/demo sandbox:
  - Base: `https://remitademo.net/remita/exapp/api/v1/send/api`
  - Initiate: `POST /echannelsvc/merchant/api/paymentinit` — body `serviceTypeId`, `amount`, `orderId` (= `payment.reference`), `payerName`, `payerEmail`, `payerPhone`, `description`, `responseurl` (our callback route); header `Authorization: remitaConsumerKey={merchantId},remitaConsumerToken={hash}`, `hash = SHA512(merchantId+serviceTypeId+orderId+amount+apiKey)`.
  - Checkout redirect: `https://demo.remita.net/remita/onepage/payment/init.reg?rrr={rrr}&channel=CARD,USSD,ENAIRA,TRANSFER`
  - Verify: `GET /echannelsvc/{merchantId}/{rrr}/{hash}/status.reg`, `hash = SHA512(rrr+apiKey+merchantId)`. `"00"` in the response status field = successful.
  - Credentials (Remita's own published sandbox values, stored in `constants_file.py` alongside the existing `SECRET_KEY`/`MAIL_*` constants, following this repo's established config pattern): `REMITA_MERCHANT_ID = "2547916"`, `REMITA_API_KEY = "1946"`, `REMITA_SERVICE_TYPE_ID = "4430731"`, `REMITA_PUBLIC_KEY = "<value supplied by user>"`, `REMITA_BASE_URL`, `REMITA_CHECKOUT_BASE_URL`. `requests` (already a dependency) makes the HTTP calls, `timeout=10` on every call.
  - Every raw request/response is written to `GatewayResponse` regardless of outcome.
- `class SimulatedGateway(PaymentGateway)` — kept as an offline, deterministic implementation used only by the automated test suite (selected via `app.config['PAYMENT_GATEWAY_MODE']`, default `'remita'`; tests set it to `'simulated'`). This is what makes "successful / failed / cancelled / timeout" all reliably testable without depending on Remita's demo server being reachable from the test environment.
- `get_gateway(app)` factory function reading the config flag.

`services/payment.py` → `PaymentService`:
- `get_active_categories()`
- `create_payment(user, item_specs, idempotency_key, registration_id=None)` — `item_specs` is a list of `(category, quantity)`. Runs `PaymentValidationService` checks, builds `Payment` + `PaymentItem` rows, `status='pending'`. If a `Payment` with this `idempotency_key` already exists, returns it instead of creating a duplicate (double-submit guard).
- `initiate_payment(payment)` — calls `gateway.initiate()`, stores `rrr`, logs `GatewayResponse`, returns `checkout_url`. On `requests` timeout/connection error, sets `status='timeout'` and re-raises a `PaymentError` the route turns into a flash message + retry button.
- `verify_payment(payment)` — **idempotent**: no-ops (just returns current state) if `payment.status` is already `successful`/`failed`/`cancelled`. Otherwise calls `gateway.verify()`, logs `GatewayResponse`, and on success: sets `status='successful'`, `verified_at`, updates `registration.payment_status='paid'` if `registration_id` set, calls `ReceiptService.get_or_create_receipt`, `create_notification(..., category='payments')`, sends receipt email (best-effort try/except, matching the existing welcome-email pattern), `log_action(user, 'payment_successful', ...)`. On failure: `status='failed'`, notify, audit log.
- `retry_verification(payment)` — re-runs `verify_payment` (covers "resume interrupted payment" once the student returns from the gateway).
- `cancel_payment(payment)` — `status='cancelled'`, audit log; cancelled is terminal but non-blocking (a fresh payment can be created afterward).
- `get_payment_history(user, status=None, search=None, date_from=None, date_to=None, page=1, per_page=10)`
- `get_summary_counts(user)` → `{total, total_amount_paid, pending, cancelled}` — `cancelled` bucket rolls up `cancelled`+`failed`+`timeout` (the UI's spec only asks for 4 cards; the precise status stays visible in the detail view/table).

`services/payment_validation.py` → `PaymentValidationService`:
- `validate_items_selected(item_specs)`
- `validate_no_duplicate_pending(user, registration_id=None, category_ids=None)` — blocks creating a second pending `Payment` for the same registration or same category set; surfaces the existing pending payment for "resume" instead.

`services/receipt.py` → `ReceiptService`:
- `get_or_create_receipt(payment)` — creates `PaymentReceipt` with `receipt_number = "RCT-" + 10 random alnum chars` on first successful verification (idempotent — returns existing row if already created).
- `render_pdf(payment)` — builds a PDF in-memory with **reportlab** (pure-Python, no system binaries — the safe choice on Windows, unlike weasyprint/pdfkit): school logo (`static/img/jspict-logo.png`), receipt number, student name/reg no, itemized breakdown, total, reference/RRR, payment date, gateway status, and a bordered placeholder box labeled "QR" (no real QR library — matches the spec's literal "QR Code placeholder" ask). Returns bytes.
- `resend_receipt_email(payment)` — reuses the existing `Message`/`mail.send()` pattern (try/except, non-fatal on failure).

## Workflow

1. **Registration fee** (Part 3, "integrate the existing payment flow"): `register_student()` is refactored — it still creates the `StudentRegistration` (now with `payment_status='pending'`, no longer instantly `'paid'`) and immediately calls `PaymentService.create_payment(..., registration_id=reg.id)` for a single `registration_fee` line item, **without** calling `initiate_payment` yet. It redirects to `payment_summary.html` (now real data: this registration's session/semester/fee, replacing every hardcoded field), which becomes the "payment summary before checkout" screen and is no longer orphaned. Its "Pay Now" button calls `initiate_payment` and redirects the browser to Remita's real checkout page.
2. **Independent payments** (Part 2): new `/payment/create` page — no existing template covers this (the orphaned `payment_summary.html` is registration-specific, not a generic fee catalog), so it's built new, matching the existing CSS variables/visual language rather than inventing a new style. Lists active `PaymentCategory` rows as selectable items, JS computes a running total client-side, submits selected `(category, quantity)` pairs, which calls `create_payment` + `initiate_payment` and redirects to checkout.
3. **Gateway → callback**: Remita's checkout redirects back to `/payment/callback?orderId=...` (the `responseurl` supplied at initiate time). The route looks up the `Payment` by reference and calls `verify_payment`, then renders a result page (success/failure/pending) with a link to Payment History / the receipt.
4. **Registration status update**: only touched when `payment.registration_id` is set — `add_drop`/course submission logic is **not** newly gated on `payment_status` (nothing gates on it today; adding that would reach beyond this milestone into already-reviewed modules). "Update registration status if applicable" is satisfied by updating `StudentRegistration.payment_status` itself.
5. **Dashboard**: the dead "Recent payment history" panel gets `get_payment_history(user, per_page=5)`; summary cards use `get_summary_counts`.

## Failure handling

| Requirement | Implementation |
|---|---|
| Retry failed verification | "Retry" button on a `pending`/`timeout` payment calls `retry_verification` |
| Resume interrupted payment | Payment History / Create Payment surfaces existing `pending` payments with a "Resume" action that re-derives the checkout URL from the stored `rrr` (no duplicate `Payment` created) |
| Duplicate payment detection | `validate_no_duplicate_pending` at creation time |
| Idempotency | Unique `idempotency_key` per `Payment`; `create_payment` returns the existing row on a repeat submission instead of creating a new one |
| Gateway timeout | `requests` calls use `timeout=10`; a timeout on *initiate* marks the payment `timeout` with a retry option; a timeout on *verify* leaves the payment `pending` (safe — never guess a status) with a manual "check status" retry |
| Cancelled payment | `cancel_payment` — reachable from a "Cancel" action before redirect, or a cancel indicator on the callback |

## UI

- `payments_history.html` / its CSS stay visually as-is; route gets `@login_required` + real Jinja context. Two label fixes required because the existing tabs don't map to any real status in this domain: "Overdue" → "Cancelled" (this app has no recurring-billing concept, so "overdue" was never meaningful), and the hardcoded "2025" tab is replaced with a real date-range filter (the spec explicitly asks for a "Date Filter" as its own feature, which the current UI doesn't have). Everything else (search, status filter, pagination, print/PDF/resend-email buttons) is wired to real routes/JS.
- `payment_summary.html` — repurposed with real data as described above; `/pay_summary` becomes `/payment/registration/<registration_id>`.
- `/payment/create` — new template, same design language, per Workflow #2.
- Receipt: server-rendered HTML print view (same `window.print()` + `@media print` pattern as `registration_slip.html`) at `/payment/<reference>/receipt`, plus `/payment/<reference>/receipt.pdf` (reportlab) and `/payment/<reference>/resend-receipt` (POST).
- Loading/error/success/empty states added throughout per the spec's explicit ask (matches patterns already used in `add_drop.js`/`announcements.js`: `postJson`/`showToast` from `static/js/shared/`).

## Testing

- Automated tests run against `SimulatedGateway` (config-selected, no real network calls in the test suite) covering: successful payment, failed payment, cancelled payment, retry verification, duplicate payment prevention, idempotency, receipt generation, PDF download, payment history updates, dashboard updates, notification created, email attempted.
- Manual end-to-end verification against the real Remita demo sandbox (test-mode credentials) is the user's own follow-up step post-merge, since it requires actually completing a payment on Remita's hosted page.

## Global constraints

- No changes to Add/Drop, My Courses, Notifications, or Profile business logic beyond the additive `register_student()` refactor described above.
- SQLite dev DB: new tables only (no altered columns on existing tables except none needed — `StudentRegistration.payment_status`/`payment_reference` already exist), so no `ALTER TABLE` needed at merge time for schema, only new `CREATE TABLE`s.
- `reportlab` and (already present) `requests` are the only new dependencies — add to `requirements.txt`.
- Remita credentials live in `constants_file.py` next to existing `SECRET_KEY`/`MAIL_*` constants, matching this repo's established (if imperfect) config pattern — not introducing a new secrets-management scheme in this milestone.
- Admin CRUD for `PaymentCategory` is out of scope (Admin Portal not started yet); categories are seeded via `seed_dev_data.py`.
