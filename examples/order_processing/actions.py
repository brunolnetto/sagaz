"""
Actions for Order Processing Saga
"""
import asyncio
import logging
import random
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ===== Inventory Actions =====

async def reserve_inventory(ctx: Any) -> Dict[str, Any]:
    """Reserve inventory items"""
    logger.info(f"Reserving inventory for order {ctx.order_id}")
    await asyncio.sleep(0.1)  # Simulate API call
    
    reserved_items = []
    for item in ctx.items:
        reserved_items.append({
            "sku": item["sku"],
            "quantity": item["quantity"],
            "reservation_id": f"RES-{item['sku']}-{ctx.order_id}"
        })
    
    return {"reserved_items": reserved_items}


async def reserve(ctx: Any) -> Dict[str, Any]:
    """Reserve inventory (alias)"""
    return await reserve_inventory(ctx)


async def check_availability(ctx: Any) -> Dict[str, Any]:
    """Check inventory availability"""
    logger.info(f"Checking availability for {ctx.get('sku', 'items')}")
    await asyncio.sleep(0.05)
    
    return {
        "available": True,
        "stock_count": 100,
        "sku": ctx.get("sku", "DEFAULT-SKU")
    }


# ===== Payment Actions =====

class PaymentProvider:
    """Mock payment provider"""
    
    _failure_rate: float = 0.05  # 5% default failure rate for realism
    
    @classmethod
    def set_failure_rate(cls, rate: float):
        """Set failure rate for testing"""
        cls._failure_rate = rate
    
    @classmethod
    async def charge_card(
        cls,
        card_token: str,
        amount: float,
        currency: str = "USD",
        metadata: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Charge a credit card"""
        await asyncio.sleep(0.1)
        
        # Simulate occasional failures
        if random.random() < cls._failure_rate:
            raise Exception("Payment gateway temporarily unavailable")
        
        return {
            "transaction_id": f"txn_{hash(card_token + str(amount)) % 1000000:06d}",
            "amount": amount,
            "currency": currency,
            "status": "success",
            "card_last4": card_token[-4:] if len(card_token) >= 4 else "****"
        }
    
    @classmethod
    async def refund(cls, transaction_id: str, amount: float) -> Dict[str, Any]:
        """Refund a transaction"""
        await asyncio.sleep(0.1)
        
        return {
            "refund_id": f"ref_{transaction_id}",
            "amount": amount,
            "status": "refunded"
        }


async def process_payment(ctx: Any) -> Dict[str, Any]:
    """Process payment for order"""
    logger.info(f"Processing payment for order {ctx.order_id}")
    await asyncio.sleep(0.1)  # Simulate payment processing
    
    return {
        "transaction_id": f"TXN-{ctx.order_id}",
        "amount": ctx.total_amount,
        "status": "completed"
    }


async def authorize_payment(ctx: Any) -> Dict[str, Any]:
    """Authorize payment"""
    logger.info(f"Authorizing payment for {ctx.get('amount', 0)}")
    await asyncio.sleep(0.1)
    
    return {
        "authorization_id": f"AUTH-{hash(str(ctx)) % 100000:05d}",
        "amount": ctx.get("amount", 0),
        "status": "authorized"
    }


async def capture_payment(ctx: Any) -> Dict[str, Any]:
    """Capture authorized payment"""
    auth_id = ctx.get("authorization_id", "AUTH-00000")
    logger.info(f"Capturing payment {auth_id}")
    await asyncio.sleep(0.1)
    
    return {
        "transaction_id": f"TXN-{auth_id}",
        "status": "captured"
    }


async def process_wallet_payment(ctx: Any) -> Dict[str, Any]:
    """Process wallet payment"""
    logger.info(f"Processing wallet payment for {ctx.get('wallet_id', 'unknown')}")
    await asyncio.sleep(0.1)
    
    return {
        "transaction_id": f"WAL-TXN-{hash(str(ctx)) % 100000:05d}",
        "wallet_id": ctx.get("wallet_id"),
        "amount": ctx.get("amount", 0),
        "status": "completed"
    }


async def validate_payment_method(ctx: Any) -> Dict[str, Any]:
    """Validate payment method"""
    method = ctx.get("payment_method", "credit_card")
    logger.info(f"Validating payment method: {method}")
    await asyncio.sleep(0.05)
    
    valid_methods = ["credit_card", "wallet", "bank_transfer"]
    if method not in valid_methods:
        return {
            "valid": False,
            "error": f"Unsupported payment method: {method}"
        }
    
    return {
        "valid": True,
        "method": method
    }


# ===== Shipment Actions =====

async def create_shipment(ctx: Any) -> Dict[str, Any]:
    """Create shipment for order"""
    logger.info(f"Creating shipment for order {ctx.order_id}")
    await asyncio.sleep(0.1)  # Simulate shipment creation
    
    return {
        "shipment_id": f"SHIP-{ctx.order_id}",
        "tracking_number": f"TRK-{ctx.order_id}",
        "estimated_delivery": "2024-01-15"
    }


# ===== Email Actions =====

async def send_confirmation_email(ctx: Any) -> Dict[str, Any]:
    """Send order confirmation email"""
    logger.info(f"Sending confirmation email for order {ctx.order_id}")
    await asyncio.sleep(0.05)  # Simulate email sending
    
    return {
        "email_sent": True,
        "email_id": f"EMAIL-{ctx.order_id}"
    }
