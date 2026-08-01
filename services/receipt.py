import io
import secrets
import string

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas

from extensions import mail, Message
from models import db, PaymentReceipt


def _generate_receipt_number():
    suffix = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(10))
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
