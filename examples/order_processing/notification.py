"""
Notification service for Order Processing
"""
import asyncio
import logging
import random
from typing import Any, Dict

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for sending notifications (email, SMS, push)"""
    
    # Class-level failure rates for testing
    _email_failure_rate: float = 0.0
    _sms_failure_rate: float = 0.0
    _push_failure_rate: float = 0.0
    
    @classmethod
    def set_failure_rates(cls, email: float = None, sms: float = None, push: float = None):
        """Set failure rates for testing"""
        if email is not None:
            cls._email_failure_rate = email
        if sms is not None:
            cls._sms_failure_rate = sms
        if push is not None:
            cls._push_failure_rate = push
    
    @classmethod
    def reset_failure_rates(cls):
        """Reset to default failure rates"""
        cls._email_failure_rate = 0.0
        cls._sms_failure_rate = 0.0
        cls._push_failure_rate = 0.0
    
    @classmethod
    async def send_email(
        cls,
        to: str,
        subject: str,
        body: str,
        template: str = None,
        template_data: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Send email notification"""
        await asyncio.sleep(0.05)  # Simulate API call
        
        # Simulate failure for testing
        if random.random() < cls._email_failure_rate:
            logger.warning(f"Email to {to} failed (simulated)")
            return {
                "status": "failed",
                "to": to,
                "subject": subject,
                "error": "Simulated failure"
            }
        
        logger.info(f"Email sent to {to}: {subject}")
        return {
            "status": "sent",
            "to": to,
            "subject": subject,
            "message_id": f"MSG-{hash(to + subject) % 10000:04d}",
            "template": template,
            "template_data": template_data
        }
    
    @classmethod
    async def send_sms(cls, phone: str, message: str) -> Dict[str, Any]:
        """Send SMS notification"""
        await asyncio.sleep(0.05)  # Simulate API call
        
        # Simulate failure for testing
        if random.random() < cls._sms_failure_rate:
            logger.warning(f"SMS to {phone} failed (simulated)")
            return {
                "status": "failed",
                "phone": phone,
                "error": "Simulated failure"
            }
        
        logger.info(f"SMS sent to {phone}")
        return {
            "status": "sent",
            "phone": phone,
            "message_id": f"SMS-{hash(phone + message) % 10000:04d}"
        }
    
    @classmethod
    async def send_push(
        cls,
        user_id: str,
        title: str,
        body: str,
        data: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Send push notification"""
        await asyncio.sleep(0.05)  # Simulate API call
        
        # Simulate failure for testing
        if random.random() < cls._push_failure_rate:
            logger.warning(f"Push to {user_id} failed (simulated)")
            return {
                "status": "failed",
                "user_id": user_id,
                "error": "Simulated failure"
            }
        
        logger.info(f"Push notification sent to {user_id}: {title}")
        return {
            "status": "sent",
            "user_id": user_id,
            "title": title,
            "notification_id": f"PUSH-{hash(user_id + title) % 10000:04d}",
            "data": data
        }


def _get_ctx_attr(ctx: Any, attr: str, default: Any = None) -> Any:
    """Safely get attribute from context."""
    return getattr(ctx, attr)if hasattr(ctx, attr) else default


async def send_order_confirmation_email(ctx: Any) -> Dict[str, Any]:
    """Send order confirmation email"""
    order_id = _get_ctx_attr(ctx, 'order_id', 'unknown')
    user_id = _get_ctx_attr(ctx, 'user_id', 'unknown')
    user_email = _get_ctx_attr(ctx, 'user_email', f"user-{user_id}@example.com")
    
    logger.info(f"Sending confirmation email for order {order_id}")
    
    template_data = {
        "order_id": _get_ctx_attr(ctx, 'order_id'),
        "user_id": _get_ctx_attr(ctx, 'user_id'),
        "items": _get_ctx_attr(ctx, 'items', []),
        "total_amount": _get_ctx_attr(ctx, 'total_amount', 0),
        "shipment_info": ctx.get("shipment_id") if hasattr(ctx, 'get') else None
    }
    
    result = await NotificationService.send_email(
        to=user_email,
        subject=f"Order Confirmation - {order_id}",
        body=f"Your order {order_id} has been confirmed!",
        template="order_confirmation",
        template_data=template_data
    )
    
    return {
        "email_sent": result["status"] == "sent",
        "email_id": result.get("message_id"),
        **result
    }


async def send_payment_receipt_email(ctx: Any) -> Dict[str, Any]:
    """Send payment receipt email"""
    logger.info(f"Sending payment receipt for {ctx.get('transaction_id', 'unknown')}")
    
    result = await NotificationService.send_email(
        to=ctx.user_email if hasattr(ctx, 'user_email') else f"user@example.com",
        subject="Payment Receipt",
        body=f"Payment received: ${ctx.get('amount', 0)}",
        template="payment_receipt",
        template_data={
            "transaction_id": ctx.get("transaction_id"),
            "amount": ctx.get("amount", 0)
        }
    )
    
    return {
        "email_sent": result["status"] == "sent",
        "email_id": result.get("message_id"),
        **result
    }


async def send_shipping_notification(ctx: Any) -> Dict[str, Any]:
    """Send shipment notification"""
    logger.info(f"Sending shipment notification for order {ctx.order_id if hasattr(ctx, 'order_id') else 'unknown'}")
    
    tracking_number = ctx.get("tracking_number") if hasattr(ctx, 'get') else "N/A"
    
    email_result = await NotificationService.send_email(
        to=ctx.user_email if hasattr(ctx, 'user_email') else f"user-{ctx.user_id if hasattr(ctx, 'user_id') else 'unknown'}@example.com",
        subject=f"Your Order Has Shipped - {ctx.order_id if hasattr(ctx, 'order_id') else 'N/A'}",
        body=f"Tracking number: {tracking_number}",
        template="shipment_notification",
        template_data={
            "order_id": ctx.order_id if hasattr(ctx, 'order_id') else None,
            "tracking_number": tracking_number,
            "shipment_id": ctx.get("shipment_id") if hasattr(ctx, 'get') else None
        }
    )
    
    sms_result = await NotificationService.send_sms(
        phone=ctx.user_phone if hasattr(ctx, 'user_phone') else "+1234567890",
        message=f"Your order {ctx.order_id if hasattr(ctx, 'order_id') else 'N/A'} has shipped! Track: {tracking_number}"
    )
    
    return {
        "email_sent": email_result["status"] == "sent",
        "sms_sent": sms_result["status"] == "sent",
        "email_id": email_result.get("message_id"),
        "sms_id": sms_result.get("message_id")
    }


async def send_order_cancellation_email(ctx: Any) -> Dict[str, Any]:
    """Send order cancellation email"""
    logger.info(f"Sending cancellation email")
    
    result = await NotificationService.send_email(
        to=ctx.user_email if hasattr(ctx, 'user_email') else f"user@example.com",
        subject="Order Cancelled",
        body="Your order has been cancelled",
        template="order_cancellation",
        template_data={}
    )
    
    return {
        "email_sent": result["status"] == "sent",
        "email_id": result.get("message_id"),
        **result
    }


async def send_bulk_notifications(ctx: Any) -> Dict[str, Any]:
    """Send bulk notifications"""
    recipients = ctx.get("recipients", []) if hasattr(ctx, 'get') else []
    logger.info(f"Sending bulk notifications to {len(recipients)} recipients")
    
    successful = []
    failed = []
    
    for recipient in recipients:
        result = await NotificationService.send_email(
            to=recipient.get("email", "unknown@example.com"),
            subject=recipient.get("subject", "Notification"),
            body=recipient.get("body", ""),
            template=recipient.get("template")
        )
        
        if result["status"] == "sent":
            successful.append(recipient)
        else:
            failed.append(recipient)
    
    return {
        "successful_sends": successful,
        "failed_sends": failed,
        "total": len(recipients),
        "success_count": len(successful),
        "failure_count": len(failed)
    }
