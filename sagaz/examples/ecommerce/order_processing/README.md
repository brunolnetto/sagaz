# Order Processing Saga

E-commerce order processing workflow with inventory, payment, shipping, and notifications.

## Overview

This example demonstrates a complete order processing flow with proper compensation handling.

## Workflow

```
Order Placed
    ↓
[1] Reserve Inventory → (Compensation: Release Inventory)
    ↓
[2] Process Payment → (Compensation: Refund Payment)
    ↓
[3] Create Shipment → (Compensation: Cancel Shipment)
    ↓
[4] Send Confirmation Email → (Compensation: Send Cancellation Email)
    ↓
Order Complete
```

## Files

- **main.py** - Saga orchestration logic
- **actions.py** - Forward step implementations
- **compensations.py** - Rollback step implementations

## Usage

```python
from examples.order_processing import OrderProcessingSaga

# Create saga
saga = OrderProcessingSaga(
    order_id="ORD-123",
    user_id="USER-456",
    items=[
        {"sku": "ITEM-001", "quantity": 2},
        {"sku": "ITEM-002", "quantity": 1}
    ],
    total_amount=99.99
)

# Execute
result = await saga.execute()
```

## Actions

### reserve_inventory(ctx)
Reserves items in inventory system.

**Returns:**
```python
{
    "reserved_items": [
        {"sku": "ITEM-001", "quantity": 2, "reservation_id": "RES-..."}
    ]
}
```

### process_payment(ctx)
Charges customer's payment method.

**Returns:**
```python
{
    "transaction_id": "TXN-...",
    "amount": 99.99,
    "status": "completed"
}
```

### create_shipment(ctx)
Creates shipment and generates tracking number.

**Returns:**
```python
{
    "shipment_id": "SHIP-...",
    "tracking_number": "TRK-...",
    "estimated_delivery": "2024-01-15"
}
```

### send_confirmation_email(ctx)
Sends order confirmation to customer.

**Returns:**
```python
{
    "email_sent": True,
    "email_id": "EMAIL-..."
}
```

## Compensations

### release_inventory(ctx)
Releases reserved inventory back to pool.

### refund_payment(ctx)
Issues refund to customer's payment method.

### cancel_shipment(ctx)
Cancels shipment and stops delivery.

### send_cancellation_email(ctx)
Notifies customer of order cancellation.

## Error Scenarios

### Insufficient Inventory
If inventory reservation fails, no compensation is needed (no steps executed).

### Payment Failure
If payment fails, inventory is automatically released.

### Shipment Failure
If shipment creation fails, payment is refunded and inventory is released.

## Testing

```bash
pytest tests/test_sagas.py::TestOrderProcessingSaga -v
```

## Integration

This example can be integrated with:
- **Inventory Management Systems** (SAP, Oracle, custom)
- **Payment Gateways** (Stripe, PayPal, Adyen)
- **Shipping Providers** (FedEx, UPS, DHL)
- **Email Services** (SendGrid, Amazon SES)

Simply replace the mock implementations in `actions.py` and `compensations.py` with real API calls.
