class RegistrationError(Exception):
    """Raised for a business-rule violation in the registration flow.
    The message is user-facing."""


class PaymentError(Exception):
    """Raised for any payment business-rule violation (validation, duplicate
    detection, cancellation of a non-cancellable payment, etc.)."""
