import hashlib
import json

import requests
from flask import current_app

from models import db, GatewayResponse


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
    checkout_base_url = current_app.config['REMITA_CHECKOUT_BASE_URL']
    return f'{checkout_base_url}?rrr={rrr}&channel=CARD,USSD,ENAIRA,TRANSFER'


class RemitaGateway(PaymentGateway):
    """Real integration against Remita's published test/demo sandbox
    (remitademo.net / demo.remita.net). The exact response shape isn't
    fully documented publicly, so both request functions read the RRR /
    status defensively and always log the raw response to GatewayResponse
    so a mismatch is debuggable rather than silently swallowed."""

    def initiate(self, payment, payer):
        merchant_id = current_app.config['REMITA_MERCHANT_ID']
        api_key = current_app.config['REMITA_API_KEY']
        service_type_id = current_app.config['REMITA_SERVICE_TYPE_ID']
        base_url = current_app.config['REMITA_BASE_URL']

        order_id = payment.reference
        amount = str(payment.total_amount)
        hash_input = f'{merchant_id}{service_type_id}{order_id}{amount}{api_key}'
        api_hash = hashlib.sha512(hash_input.encode('utf-8')).hexdigest()

        payload = {
            'serviceTypeId': service_type_id,
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
            'Authorization': f'remitaConsumerKey={merchant_id},remitaConsumerToken={api_hash}',
        }

        try:
            response = requests.post(
                f'{base_url}/echannelsvc/merchant/api/paymentinit',
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
        merchant_id = current_app.config['REMITA_MERCHANT_ID']
        api_key = current_app.config['REMITA_API_KEY']
        base_url = current_app.config['REMITA_BASE_URL']

        hash_input = f'{payment.rrr}{api_key}{merchant_id}'
        api_hash = hashlib.sha512(hash_input.encode('utf-8')).hexdigest()
        url = f'{base_url}/echannelsvc/{merchant_id}/{payment.rrr}/{api_hash}/status.reg'

        try:
            response = requests.get(url, timeout=10)
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            _log_response(payment, {'error': str(exc)})
            raise GatewayError(f'Could not reach the payment gateway: {exc}') from exc

        _log_response(payment, data)

        # Fail OPEN, not closed: only explicitly-known codes resolve to a
        # terminal state. Success and pending are recognized allow-lists;
        # anything unrecognized (a response shape we didn't anticipate, a
        # transient error body, a missing field) falls through to 'pending'
        # so the payment stays retryable instead of being permanently marked
        # failed with no in-app recovery path. No failure codes are known to
        # be documented with confidence, so there is deliberately no
        # explicit failure allow-list here — default-to-pending is the safe
        # minimum.
        status_code = str(data.get('status', ''))
        if status_code == '00':
            resolved = 'successful'
        else:
            resolved = 'pending'  # includes '021'/'025' and anything unrecognized

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
