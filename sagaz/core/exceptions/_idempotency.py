"""Idempotency-related exceptions."""


class IdempotencyKeyMissingInPayloadError(Exception):
    """
    Raised when trigger declares idempotency_key but payload lacks the field.

    This prevents silent fallback to random UUIDs when the developer
    explicitly configured idempotency protection.
    """

    def __init__(self, saga_name: str, source: str, key_name: str, payload_keys: list[str]):
        self.saga_name = saga_name
        self.source = source
        self.key_name = key_name
        self.payload_keys = payload_keys

        keys_str = ", ".join(payload_keys) if payload_keys else "(empty payload)"
        message = (
            f"\n╔══════════════════════════════════════════════════════════════╗\n"
            f"║  IDEMPOTENCY KEY MISSING IN PAYLOAD                          ║\n"
            f"╠══════════════════════════════════════════════════════════════╣\n"
            f"║  Saga: {saga_name:<53} ║\n"
            f"║  Trigger Source: {source:<45} ║\n"
            f"║                                                              ║\n"
            f"║  Expected field: '{key_name}'                                  ║\n"
            f"║  Payload keys: {keys_str:<47} ║\n"
            f"║                                                              ║\n"
            f"║  The trigger is configured with idempotency protection,     ║\n"
            f"║  but the payload is missing the required field.             ║\n"
            f"║                                                              ║\n"
            f"║  Solutions:                                                  ║\n"
            f"║  1. Include '{key_name}' in the webhook payload                ║\n"
            f"║  2. Update the idempotency_key to match available fields    ║\n"
            f"║  3. Remove idempotency_key if not needed (triggers warning) ║\n"
            f"║                                                              ║\n"
            f"╚══════════════════════════════════════════════════════════════╝"
        )

        super().__init__(message)


class IdempotencyKeyRequiredError(Exception):
    """
    Raised when a high-value operation lacks an idempotency key.

    This exception enforces safe-by-default behavior for financial
    and high-value operations, preventing duplicate execution.
    """

    def __init__(self, saga_name: str, source: str, detected_fields: list[str]):
        self.saga_name = saga_name
        self.source = source
        self.detected_fields = detected_fields

        fields_str = ", ".join(detected_fields)
        message = (
            f"\n╔══════════════════════════════════════════════════════════════╗\n"
            f"║  IDEMPOTENCY KEY REQUIRED                                    ║\n"
            f"╠══════════════════════════════════════════════════════════════╣\n"
            f"║  Saga: {saga_name:<53} ║\n"
            f"║  Trigger Source: {source:<45} ║\n"
            f"║                                                              ║\n"
            f"║  High-value operation detected with fields:                 ║\n"
            f"║  {fields_str:<59} ║\n"
            f"║                                                              ║\n"
            f"║  To prevent duplicate execution, add an idempotency key:    ║\n"
            f"║                                                              ║\n"
            f"║  @trigger(                                                   ║\n"
            f"║      source='{source}',                                        ║\n"
            f"║      idempotency_key='<unique_field>'  # e.g., 'order_id'   ║\n"
            f"║  )                                                           ║\n"
            f"║                                                              ║\n"
            f"║  Or use a callable for composite keys:                      ║\n"
            '║  idempotency_key=lambda p: f\'{p["user_id"]}-{p["order_id"]}\'  ║\n'
            f"║                                                              ║\n"
            f"╚══════════════════════════════════════════════════════════════╝"
        )

        super().__init__(message)
