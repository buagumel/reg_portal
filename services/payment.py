import secrets
import string

from flask import url_for

from models import db, now_lagos, Payment, PaymentItem
from services.errors import PaymentError
from services.payment_validation import validate_items_selected, validate_no_duplicate_pending
from services.payment_gateway import GatewayError
from services.notification import create_notification
from services.audit import log_action


def _generate_reference():
    suffix = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(10))
    return f'PAY-{suffix}'


def create_payment(user, item_specs, idempotency_key, registration_id=None):
    """Returns the Payment. If idempotency_key was already used, returns the
    existing row instead of creating a duplicate (double-submit guard)."""
    existing = Payment.query.filter_by(idempotency_key=idempotency_key, user_id=user.id).first()
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
        'response_url': url_for('payments.payment_callback', _external=True),
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
    elif result['status'] == 'cancelled':
        payment.status = 'cancelled'
        db.session.commit()
        log_action(payment.user, 'payment_cancelled_by_gateway', details=f'reference={payment.reference}')
    else:
        db.session.commit()  # still pending — gateway_status updated, no state change

    return payment


def _on_payment_successful(payment):
    """The gateway has already confirmed success and `payment.status` is
    already committed as 'successful' by the caller — that fact is durable
    and correct regardless of what happens below. Receipt creation,
    notification, audit logging, and email are best-effort follow-ups: since
    verify_payment's idempotency guard short-circuits on a terminal status,
    nothing would ever retry these if one of them raised, so any failure
    here must be swallowed (logged, not re-raised) rather than leave the
    request — and the payment — stuck."""
    if payment.registration_id:
        payment.registration.payment_status = 'paid'
        db.session.commit()

    try:
        from flask import current_app
        from services.receipt import get_or_create_receipt, send_receipt_email

        receipt = get_or_create_receipt(payment)

        create_notification(
            payment.user, 'Payment successful',
            f'Your payment of ₦{payment.total_amount:,.2f} (reference {payment.reference}) was successful. Receipt: {receipt.receipt_number}.',
            category='payments', priority='high', related_url=f'/payment/{payment.reference}/receipt',
        )
        log_action(payment.user, 'payment_successful', details=f'reference={payment.reference} amount={payment.total_amount}')
        send_receipt_email(payment, receipt)
    except Exception:
        current_app.logger.warning(
            'Post-payment follow-up (receipt/notification/email) failed for reference %s',
            payment.reference,
        )


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
