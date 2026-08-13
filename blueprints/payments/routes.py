import uuid

from flask import request, jsonify, render_template, redirect, url_for, flash, current_app, Response
from flask_login import current_user, login_required

from blueprints.payments import payments_bp
from models import StudentRegistration, Payment, PaymentCategory, AdminUser
from services.payment import (
    create_payment, initiate_payment, verify_payment,
    retry_verification, cancel_payment, get_payment_history,
    get_summary_counts as get_payment_summary_counts,
)
from services.payment_gateway import get_gateway, GatewayError, build_checkout_url
from services.errors import PaymentError
from services.receipt import get_or_create_receipt, render_pdf, send_receipt_email
from services.fee_structure import get_payable_categories, resolve_amount, NON_GENERAL_FLOW_CATEGORY_CODES


@payments_bp.route('/payment/registration/<int:registration_id>')
@login_required
def payment_registration_summary(registration_id):
    registration = StudentRegistration.query.filter_by(id=registration_id, user_id=current_user.id).first_or_404()
    if registration.payment_status == 'paid':
        flash('This registration has already been paid for.')
        return redirect(url_for('registration.registration'))
    payment = (
        Payment.query
        .filter(
            Payment.registration_id == registration.id,
            Payment.status.in_(('pending', 'timeout')),
        )
        .order_by(Payment.id.desc())
        .first()
    )
    return render_template('payment_summary.html', registration=registration, payment=payment)


@payments_bp.route('/payment/<reference>/initiate', methods=['POST'])
@login_required
def payment_initiate(reference):
    payment = Payment.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    if payment.status != 'pending':
        return jsonify({'success': False, 'message': 'This payment is no longer pending.'}), 400

    if payment.rrr:
        return jsonify({'success': True, 'redirect': build_checkout_url(payment.rrr)})

    gateway = get_gateway(current_app)
    try:
        checkout_url = initiate_payment(gateway, payment, current_user)
    except GatewayError as e:
        return jsonify({'success': False, 'message': str(e)}), 502
    return jsonify({'success': True, 'redirect': checkout_url})


@payments_bp.route('/payment/callback')
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
        return redirect(url_for('payments.payments_history'))

    gateway = get_gateway(current_app)
    verify_payment(gateway, payment)
    return render_template('payment_callback.html', payment=payment)


@payments_bp.route('/payment/<reference>/resume')
@login_required
def payment_resume(reference):
    payment = Payment.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    if payment.status not in ('pending', 'timeout'):
        flash('This payment is no longer pending.')
        return redirect(url_for('payments.payments_history'))

    if payment.rrr:
        return redirect(build_checkout_url(payment.rrr))

    gateway = get_gateway(current_app)
    try:
        checkout_url = initiate_payment(gateway, payment, current_user)
    except GatewayError:
        flash('Could not reach the payment gateway. Please try again shortly.')
        return redirect(url_for('payments.payments_history'))
    return redirect(checkout_url)


@payments_bp.route('/payment/<reference>/cancel', methods=['POST'])
@login_required
def payment_cancel(reference):
    payment = Payment.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    try:
        cancel_payment(payment)
    except PaymentError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    return jsonify({'success': True, 'message': 'Payment cancelled.'})


@payments_bp.route('/payment/<reference>/retry', methods=['POST'])
@login_required
def payment_retry(reference):
    payment = Payment.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    gateway = get_gateway(current_app)
    retry_verification(gateway, payment)
    return jsonify({'success': True, 'status': payment.status})


@payments_bp.route('/payment/<reference>/receipt')
@login_required
def payment_receipt(reference):
    payment = Payment.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    if payment.status != 'successful':
        flash('Receipt is only available for successful payments.')
        return redirect(url_for('payments.payments_history'))
    receipt = get_or_create_receipt(payment)
    return render_template('payment_receipt.html', payment=payment, receipt=receipt)


@payments_bp.route('/payment/<reference>/receipt.pdf')
@login_required
def payment_receipt_pdf(reference):
    payment = Payment.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    if payment.status != 'successful':
        flash('Receipt is only available for successful payments.')
        return redirect(url_for('payments.payments_history'))
    receipt = get_or_create_receipt(payment)
    pdf_bytes = render_pdf(payment, receipt)
    return Response(pdf_bytes, mimetype='application/pdf', headers={
        'Content-Disposition': f'attachment; filename={receipt.receipt_number}.pdf'
    })


@payments_bp.route('/payment/<reference>/resend-receipt', methods=['POST'])
@login_required
def payment_resend_receipt(reference):
    payment = Payment.query.filter_by(reference=reference, user_id=current_user.id).first_or_404()
    if payment.status != 'successful':
        return jsonify({'success': False, 'message': 'No receipt available for this payment.'}), 400
    receipt = get_or_create_receipt(payment)
    send_receipt_email(payment, receipt)
    return jsonify({'success': True, 'message': 'Receipt email sent.'})


@payments_bp.route('/payment/create', methods=['GET'])
@login_required
def payment_create_page():
    # Student-only: fee resolution reads user.programme_id/department_id,
    # which AdminUser doesn't have. Nothing currently links here for an
    # admin session, but enforce_onboarding_gate's before_request hook
    # explicitly exempts AdminUser from its gate, so this route is
    # reachable by one in principle (the shared LoginManager resolves both
    # User and AdminUser sessions) — guard explicitly rather than rely on
    # that never happening. Same isinstance(current_user, AdminUser)
    # pattern used elsewhere in this file (e.g. enforce_onboarding_gate).
    if isinstance(current_user, AdminUser):
        return redirect(url_for('admin.core.admin_dashboard'))
    payable = get_payable_categories(current_user)
    idempotency_key = str(uuid.uuid4())
    return render_template('payment_create.html', payable=payable, idempotency_key=idempotency_key)


@payments_bp.route('/payment/create', methods=['POST'])
@login_required
def payment_create_submit():
    if isinstance(current_user, AdminUser):
        return jsonify({'success': False, 'message': 'Not available for admin sessions.'}), 403
    data = request.get_json() or {}
    idempotency_key = data.get('idempotency_key', '')
    selections = data.get('items', [])
    if not idempotency_key:
        return jsonify({'success': False, 'message': 'Invalid request.'}), 400
    # Namespace the client-supplied key by user, defensively — belt-and-braces
    # on top of create_payment's own user_id-scoped lookup, so a client can
    # never collide with (and get handed back) another user's payment even if
    # the query scoping above were ever weakened.
    idempotency_key = f'{current_user.id}:{idempotency_key}'

    item_specs = []
    for sel in selections:
        if not isinstance(sel, dict):
            continue
        category = PaymentCategory.query.filter(
            PaymentCategory.id == sel.get('category_id'),
            PaymentCategory.is_active == True,
            PaymentCategory.code.notin_(NON_GENERAL_FLOW_CATEGORY_CODES),
        ).first()
        if category is None:
            continue
        amount = resolve_amount(current_user, category)
        if amount is None:
            continue
        try:
            quantity = int(sel.get('quantity', 1))
        except (TypeError, ValueError):
            quantity = 1
        quantity = max(1, min(quantity, 10))
        item_specs.append((category, quantity, amount))

    try:
        payment = create_payment(current_user, item_specs, idempotency_key)
    except PaymentError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

    if payment.status != 'pending':
        return jsonify({'success': False, 'message': 'This payment has already been processed.'}), 400

    gateway = get_gateway(current_app)
    try:
        checkout_url = initiate_payment(gateway, payment, current_user)
    except GatewayError as e:
        return jsonify({'success': False, 'message': str(e)}), 502

    return jsonify({'success': True, 'redirect': checkout_url})


@payments_bp.route('/payments_history')
@login_required
def payments_history():
    summary = get_payment_summary_counts(current_user)
    return render_template('payments_history.html', summary=summary)


@payments_bp.route('/payments_history/data')
@login_required
def payments_history_data():
    status = request.args.get('status') or None
    search = request.args.get('search') or None
    date_from = request.args.get('date_from') or None
    date_to = request.args.get('date_to') or None
    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        page = 1
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
