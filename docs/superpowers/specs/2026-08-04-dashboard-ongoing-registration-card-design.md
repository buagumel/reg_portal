# Dashboard Ongoing Registration Card Design

**Status:** Approved for planning
**Author:** Controller (Claude), approved by user 2026-08-04

## Goal

Show an "ongoing registration" card on the student dashboard, directly above the existing "Registered Courses (Current)" card, whenever the student has a registration for the active period that hasn't yet reached course-submission. Add the missing "Complete Registration" next-step action that today doesn't exist anywhere once payment succeeds.

## Current state (confirmed by codebase audit)

- `app.py`'s `dashboard()` route (line ~413) renders `dashboard.html` with only `profile_display` and `recent_payments` — it does not call `get_registration_status_context`, so the dashboard has no registration-state data to render with today.
- `services/registration.py`'s `get_registration_status_context(user)` (already built, used by `/registration`) returns `{'period', 'window_status', 'min_credits', 'max_credits', 'registration_fee', 'existing_registration'}`. `existing_registration` is the raw `StudentRegistration` ORM object (or `None`), so `.payment_status` and `.courses_submitted` are directly available in a template — no new service code needed.
- `templates/dashboard.html`'s "Registered Courses (Current)" card (line ~77-90, inside `.courses-grid` > `.payment-section`) is itself a static hardcoded empty state (a pre-existing gap from Feature 3, unrelated to this work — not touched here).
- `templates/registration.html`'s `registered-card` branch (rendered when `status.existing_registration` is truthy, lines 31-56) already distinguishes "Registered" vs. "Registered — Payment Pending" by `payment_status`, and already has a "Complete Payment" button when `payment_status != 'paid'` (lines 48-54). When `payment_status == 'paid'`, it currently shows only static text — no button, no path forward to Add/Drop — regardless of `courses_submitted`.
- `StudentRegistration.courses_submitted` (Boolean, default `False`) is set `True` only by `services/registration.py`'s `submit_registration`, called from `/add_drop/submit`. This is the single source of truth for "registration is fully complete."
- No existing route or template anywhere links from a paid-but-not-submitted registration state to `/add_drop`. This is a genuine functional gap, not a UI-only oversight.

## Design

### Show/hide rule (single source of truth)

A registration counts as "ongoing" exactly when:
```
status.existing_registration is not None and not status.existing_registration.courses_submitted
```
This is evaluated server-side on every dashboard page load — no client-side state, no polling. The card simply stops rendering the moment `courses_submitted` flips to `True` (via `/add_drop/submit`), and reappears automatically only when the student registers again for a new active period (a fresh `StudentRegistration` row with `courses_submitted=False`).

### Dashboard route

`app.py`'s `dashboard()`:
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
`get_registration_status_context` is already imported in `app.py` (used by `registration()`) — no new import.

### Dashboard card (new)

Inserted in `templates/dashboard.html`, directly above the existing "Registered Courses (Current)" `.payment-section` block (both live inside the same `.courses-grid` container). Renders only when the show/hide rule above is true. Two states, condensed to the dashboard's existing card density (one line of context, one badge, one button — no countdown, no credit-limit/fee breakdown, unlike the fuller `/registration` card):

- **Payment pending** (`existing_registration.payment_status != 'paid'`): badge "Payment Pending", `{{ period.academic_session.name }} {{ period.semester.name }}`, button "Complete Payment" → `url_for('payment_registration_summary', registration_id=existing_registration.id)`.
- **Paid, not submitted** (`existing_registration.payment_status == 'paid'`): badge "Paid — Complete Registration", same session/semester line, button "Complete Registration" → `url_for('add_drop')`.

Styling reuses the existing `.payment-section` card shell (same border/spacing convention already used by every other dashboard card) with a small badge element in the header row — no new CSS file, a few rules added to `static/css/dashboard.css` for the badge only.

### `/registration` page CTA (fix the existing gap)

In `templates/registration.html`'s `registered-card` branch, replace the static "Course selection will open separately once available" paragraph (shown unconditionally in that branch today) with a conditional:
- `payment_status != 'paid'`: unchanged — existing "Complete Payment" button stays exactly as-is.
- `payment_status == 'paid' and not courses_submitted`: new "Complete Registration" button → `url_for('add_drop')`, same visual treatment (`.btn-primary`) as the existing "Complete Payment" button it replaces in that branch.
- `payment_status == 'paid' and courses_submitted`: static confirmation text (e.g., "Course selection submitted.") — this state is reachable (the student can revisit `/registration` after finishing Add/Drop, within the same active period, before it closes), so it needs its own explicit rendering rather than falling through.

## Testing

No automated test suite (established convention) — manual verification via a throwaway `test_client` script: create a `StudentRegistration` with `payment_status='pending'` → dashboard shows the pending-payment card, `/registration` shows "Complete Payment"; flip to `payment_status='paid'` → dashboard shows "Complete Registration", `/registration`'s button changes to "Complete Registration"; set `courses_submitted=True` → card disappears from dashboard, `/registration` shows the submitted-confirmation text instead of a button.

## Deliverables

1. Pass `status` into `dashboard()`'s render call.
2. Add the new ongoing-registration card to `templates/dashboard.html` (both states) with matching CSS.
3. Add the "Complete Registration" CTA and the submitted-confirmation state to `templates/registration.html`'s `registered-card` branch.
4. Manual verification across all three `existing_registration` states (pending payment / paid-not-submitted / submitted) on both pages.
