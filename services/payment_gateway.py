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
