"""
Travel Booking Saga Example

Demonstrates multi-service travel reservation with the declarative pattern.
"""

import asyncio
import logging
from typing import Any

from sagaz import Saga, SagaContext, action, compensate

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class TravelBookingSaga(Saga):
    """Travel booking across multiple services (flight + hotel + car rental)."""
    
    saga_name = "travel-booking"

    def __init__(
        self,
        booking_id: str,
        user_id: str,
        flight_details: dict,
        hotel_details: dict,
        car_details: dict | None = None,
    ):
        super().__init__()
        self.booking_id = booking_id
        self.user_id = user_id
        self.flight_details = flight_details
        self.hotel_details = hotel_details
        self.car_details = car_details

    @action("book_flight")
    async def book_flight(self, ctx: SagaContext) -> dict[str, Any]:
        """Book flight."""
        logger.info(f"Booking flight for {self.user_id}")
        await asyncio.sleep(0.3)

        return {
            "booking_reference": f"FL-{self.booking_id}",
            "flight_number": self.flight_details["flight_number"],
            "confirmation": f"CONF-FL-{self.booking_id}",
        }

    @compensate("book_flight")
    async def cancel_flight(self, ctx: SagaContext) -> None:
        """Cancel flight booking."""
        logger.warning(f"Canceling flight for booking {self.booking_id}")
        await asyncio.sleep(0.2)

    @action("book_hotel", depends_on=["book_flight"])
    async def book_hotel(self, ctx: SagaContext) -> dict[str, Any]:
        """Book hotel."""
        logger.info(f"Booking hotel for {self.user_id}")
        await asyncio.sleep(0.3)

        return {
            "booking_reference": f"HT-{self.booking_id}",
            "hotel_name": self.hotel_details["hotel_name"],
            "confirmation": f"CONF-HT-{self.booking_id}",
        }

    @compensate("book_hotel")
    async def cancel_hotel(self, ctx: SagaContext) -> None:
        """Cancel hotel booking."""
        logger.warning(f"Canceling hotel for booking {self.booking_id}")
        await asyncio.sleep(0.2)

    @action("book_car", depends_on=["book_hotel"])
    async def book_car(self, ctx: SagaContext) -> dict[str, Any]:
        """Book rental car (if requested)."""
        if not self.car_details:
            return {"skipped": True}
            
        logger.info(f"Booking car for {self.user_id}")
        await asyncio.sleep(0.2)

        return {
            "booking_reference": f"CAR-{self.booking_id}",
            "car_type": self.car_details["car_type"],
            "confirmation": f"CONF-CAR-{self.booking_id}",
        }

    @compensate("book_car")
    async def cancel_car(self, ctx: SagaContext) -> None:
        """Cancel car booking."""
        logger.warning(f"Canceling car for booking {self.booking_id}")
        await asyncio.sleep(0.1)

    @action("send_itinerary", depends_on=["book_car"])
    async def send_itinerary(self, ctx: SagaContext) -> dict[str, Any]:
        """Send complete itinerary to user."""
        logger.info(f"Sending itinerary to {self.user_id}")
        await asyncio.sleep(0.1)

        return {
            "sent": True,
            "booking_id": self.booking_id,
        }


async def main():
    """Run the travel booking saga demo."""
    print("=" * 60)
    print("Travel Booking Saga Demo")
    print("=" * 60)

    saga = TravelBookingSaga(
        booking_id="BOOK-456",
        user_id="USER-123",
        flight_details={"flight_number": "AA123", "from": "NYC", "to": "LAX"},
        hotel_details={"hotel_name": "Grand Hotel", "nights": 3},
        car_details={"car_type": "Sedan", "days": 3},
    )

    result = await saga.run({"booking_id": saga.booking_id})

    print(f"\n{'✅' if result.get('saga_id') else '❌'} Travel Booking Result:")
    print(f"   Saga ID: {result.get('saga_id')}")
    print(f"   Booking ID: {result.get('booking_id')}")


if __name__ == "__main__":
    asyncio.run(main())
