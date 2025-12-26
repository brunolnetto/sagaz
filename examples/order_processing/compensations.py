"""
Compensations for Order Processing Saga
"""
import asyncio
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


# ===== Inventory Compensations =====

async def release_inventory(ctx: Any) -> Dict[str, Any]:
    """Release reserved inventory"""
    logger.info(f"Releasing inventory for order {ctx.order_id if hasattr(ctx, 'order_id') else 'unknown'}")
    await asyncio.sleep(0.1)  # Simulate API call
    
    released_items = []
    if hasattr(ctx, "reserved_items"):
        for item in ctx.reserved_items:
            released_items.append({
                "sku": item["sku"],
                "quantity": item["quantity"],
                "released": True
            })
    
    return {"released_items": released_items, "released": True}


async def release(ctx: Any) -> Dict[str, Any]:
    """Release inventory (alias)"""
    return await release_inventory(ctx)


# ===== Payment Compensations =====

async def refund_payment(ctx: Any) -> Dict[str, Any]:
    """Refund payment"""
    # Skip if no transaction was created
    if not hasattr(ctx, 'get') or not ctx.get("transaction_id"):
        if not hasattr(ctx, "transaction_id"):
            logger.info("No transaction to refund, skipping")
            return {"skipped": True, "reason": "no_transaction"}
    
    transaction_id = ctx.get("transaction_id") if hasattr(ctx, 'get') else getattr(ctx, "transaction_id", None)
    logger.info(f"Refunding payment {transaction_id}")
    await asyncio.sleep(0.1)
    
    return {
        "refunded": True,
        "refund_id": f"REF-{transaction_id}",
        "transaction_id": transaction_id
    }


async def void_authorization(ctx: Any) -> Dict[str, Any]:
    """Void payment authorization"""
    if not hasattr(ctx, 'get') or not ctx.get("authorization_id"):
        logger.info("No authorization to void, skipping")
        return {"skipped": True, "reason": "no_authorization"}
    
    auth_id = ctx.get("authorization_id")
    logger.info(f"Voiding authorization {auth_id}")
    await asyncio.sleep(0.1)
    
    return {
        "voided": True,
        "authorization_id": auth_id
    }


async def reverse_wallet_payment(ctx: Any) -> Dict[str, Any]:
    """Reverse wallet payment"""
    if not hasattr(ctx, 'get') or not ctx.get("transaction_id"):
        logger.info("No wallet transaction to reverse, skipping")
        return {"skipped": True, "reason": "no_transaction"}
    
    transaction_id = ctx.get("transaction_id")
    logger.info(f"Reversing wallet payment {transaction_id}")
    await asyncio.sleep(0.1)
    
    return {
        "reversed": True,
        "transaction_id": transaction_id
    }


async def release_payment_hold(ctx: Any) -> Dict[str, Any]:
    """Release payment hold"""
    if not hasattr(ctx, 'get') or not ctx.get("hold_id"):
        logger.info("No hold to release, skipping")
        return {"skipped": True, "reason": "no_hold"}
    
    hold_id = ctx.get("hold_id")
    logger.info(f"Releasing payment hold {hold_id}")
    await asyncio.sleep(0.1)
    
    return {
        "released": True,
        "hold_id": hold_id
    }


async def cancel_recurring_payment(ctx: Any) -> Dict[str, Any]:
    """Cancel recurring payment subscription"""
    if not hasattr(ctx, 'get') or not ctx.get("subscription_id"):
        logger.info("No subscription to cancel, skipping")
        return {"skipped": True, "reason": "no_subscription"}
    
    subscription_id = ctx.get("subscription_id")
    logger.info(f"Cancelling recurring payment {subscription_id}")
    await asyncio.sleep(0.1)
    
    return {
        "cancelled": True,
        "subscription_id": subscription_id
    }


async def reverse_payment_fee(ctx: Any) -> Dict[str, Any]:
    """Reverse payment processing fee"""
    if not hasattr(ctx, 'get') or not ctx.get("fee_id"):
        logger.info("No fee to reverse, skipping")
        return {"skipped": True, "reason": "no_fee"}
    
    fee_id = ctx.get("fee_id")
    logger.info(f"Reversing payment fee {fee_id}")
    await asyncio.sleep(0.1)
    
    return {
        "reversed": True,
        "fee_id": fee_id
    }


async def restore_payment_credits(ctx: Any) -> Dict[str, Any]:
    """Restore payment credits"""
    if not hasattr(ctx, 'get') or not ctx.get("credits_used"):
        logger.info("No credits to restore, skipping")
        return {"skipped": True, "reason": "no_credits"}
    
    credits = ctx.get("credits_used")
    logger.info(f"Restoring {credits} payment credits")
    await asyncio.sleep(0.1)
    
    return {
        "restored": True,
        "credits": credits
    }


# ===== Notification Compensations =====

async def send_order_cancellation_notification(ctx: Any) -> Dict[str, Any]:
    """Send order cancellation notification"""
    # Skip if original notification wasn't sent
    if not hasattr(ctx, 'get') or not ctx.get("email_sent"):
        logger.info("Original notification not sent, skipping cancellation")
        return {"skipped": True, "reason": "not_sent"}
    
    logger.info(f"Sending cancellation notification for order {ctx.order_id if hasattr(ctx, 'order_id') else 'unknown'}")
    await asyncio.sleep(0.05)
    
    return {
        "notification_sent": True,
        "type": "cancellation"
    }


async def send_payment_failure_notification(ctx: Any) -> Dict[str, Any]:
    """Send payment failure notification"""
    if not hasattr(ctx, 'get') or not ctx.get("email_sent"):
        logger.info("Original notification not sent, skipping failure notification")
        return {"skipped": True, "reason": "not_sent"}
    
    logger.info("Sending payment failure notification")
    await asyncio.sleep(0.05)
    
    return {
        "notification_sent": True,
        "type": "payment_failure"
    }


async def send_shipping_cancellation_notification(ctx: Any) -> Dict[str, Any]:
    """Send shipping cancellation notification"""
    # Send if either email or SMS was originally sent
    email_sent = hasattr(ctx, 'get') and ctx.get("email_sent")
    sms_sent = hasattr(ctx, 'get') and ctx.get("sms_sent")
    
    if not email_sent and not sms_sent:
        logger.info("Neither email nor SMS sent, skipping cancellation")
        return {"skipped": True, "reason": "neither_sent"}
    
    logger.info("Sending shipping cancellation notification")
    await asyncio.sleep(0.05)
    
    result = {"notification_sent": True, "type": "shipping_cancellation"}
    if email_sent:
        result["email_sent"] = True
    if sms_sent:
        result["sms_sent"] = True
    
    return result


async def retract_bulk_notifications(ctx: Any) -> Dict[str, Any]:
    """Retract bulk notifications"""
    if not hasattr(ctx, 'get') or not ctx.get("successful_sends"):
        logger.info("No successful sends to retract, skipping")
        return {"skipped": True, "reason": "no_successful_sends"}
    
    successful = ctx.get("successful_sends", [])
    logger.info(f"Retracting {len(successful)} notifications")
    await asyncio.sleep(0.05)
    
    return {
        "retracted": True,
        "count": len(successful)
    }


async def cancel_scheduled_notifications(ctx: Any) -> Dict[str, Any]:
    """Cancel scheduled notifications"""
    if not hasattr(ctx, 'get') or not ctx.get("schedule_id"):
        logger.info("No schedule to cancel, skipping")
        return {"skipped": True, "reason": "no_schedule_id"}
    
    schedule_id = ctx.get("schedule_id")
    logger.info(f"Cancelling scheduled notification {schedule_id}")
    await asyncio.sleep(0.05)
    
    return {
        "cancelled": True,
        "schedule_id": schedule_id
    }


async def suppress_notification_preferences(ctx: Any) -> Dict[str, Any]:
    """Suppress notification preferences"""
    if not hasattr(ctx, 'get') or not ctx.get("user_id"):
        logger.info("No user_id provided, skipping preference suppression")
        return {"skipped": True, "reason": "no_user_id"}
    
    user_id = ctx.get("user_id")
    logger.info(f"Suppressing notification preferences for user {user_id}")
    await asyncio.sleep(0.05)
    
    return {
        "suppressed": True,
        "user_id": user_id
    }


# ===== Shipment Compensations =====

async def cancel_shipment(ctx: Any) -> Dict[str, Any]:
    """Cancel shipment"""
    logger.info(f"Canceling shipment for order {ctx.order_id if hasattr(ctx, 'order_id') else 'unknown'}")
    await asyncio.sleep(0.1)  # Simulate shipment cancellation
    
    cancel_data = {
        "cancelled": True,
        "status": "cancelled"
    }
    if hasattr(ctx, "shipment_id"):
        cancel_data["shipment_id"] = ctx.shipment_id
    
    return cancel_data


async def send_cancellation_email(ctx: Any) -> Dict[str, Any]:
    """Send order cancellation email"""
    logger.info(f"Sending cancellation email for order {ctx.order_id if hasattr(ctx, 'order_id') else 'unknown'}")
    await asyncio.sleep(0.05)  # Simulate email sending
    
    return {
        "cancellation_email_sent": True,
        "email_id": f"CANCEL-EMAIL-{ctx.order_id if hasattr(ctx, 'order_id') else 'unknown'}"
    }
