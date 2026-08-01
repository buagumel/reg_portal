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
