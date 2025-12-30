"""
Notification service stub for testing.
"""


class NotificationService:
    """Service for sending notifications (stub for test compatibility)."""

    _email_failure_rate: float = 0.0
    _sms_failure_rate: float = 0.0

    @classmethod
    def set_failure_rates(cls, email: float = None, sms: float = None, push: float = None):
        """Set failure rates for testing."""
        if email is not None:
            cls._email_failure_rate = email
        if sms is not None:
            cls._sms_failure_rate = sms

    @classmethod
    def reset_failure_rates(cls):
        """Reset to default failure rates."""
        cls._email_failure_rate = 0.0
        cls._sms_failure_rate = 0.0
