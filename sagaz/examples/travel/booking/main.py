"""
Travel Booking Saga Example

Demonstrates multi-service travel reservation with the declarative pattern.
Data is passed through the run() method's initial context, not the constructor.
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
    """
    Travel booking across multiple services (flight + hotel + car rental).

    This saga is stateless - all booking data is passed through the context
    via the run() method. The same saga instance can process multiple bookings.

    Expected context:
        - booking_id: str - Unique booking identifier
        - user_id: str - Customer identifier
        - flight_details: dict - Flight info with 'flight_number', 'from', 'to'
        - hotel_details: dict - Hotel info with 'hotel_name', 'nights'
        - car_details: dict | None - Optional car rental info with 'car_type', 'days'
    """

    saga_name = "travel-booking"

    @action("book_flight")
    async def book_flight(self, ctx: SagaContext) -> dict[str, Any]:
        """Book flight."""
        booking_id = ctx.get("booking_id")
        user_id = ctx.get("user_id")
        flight_details = ctx.get("flight_details", {})

        logger.info(f"Booking flight for {user_id}")
        await asyncio.sleep(0.3)

        return {
            "flight_booking_reference": f"FL-{booking_id}",
            "flight_number": flight_details.get("flight_number"),
            "flight_confirmation": f"CONF-FL-{booking_id}",
        }

    @compensate("book_flight")
    async def cancel_flight(self, ctx: SagaContext) -> None:
        """Cancel flight booking using booking data from context."""
        booking_id = ctx.get("booking_id")
        logger.warning(f"Canceling flight for booking {booking_id}")

        # Access flight booking result from context
        booking_reference = ctx.get("flight_booking_reference")
        confirmation = ctx.get("flight_confirmation")
        if booking_reference:
            logger.info(f"Canceling flight booking {booking_reference} (confirmation: {confirmation})")

        await asyncio.sleep(0.2)

    @action("book_hotel", depends_on=["book_flight"])
    async def book_hotel(self, ctx: SagaContext) -> dict[str, Any]:
        """Book hotel."""
        booking_id = ctx.get("booking_id")
        user_id = ctx.get("user_id")
        hotel_details = ctx.get("hotel_details", {})

        logger.info(f"Booking hotel for {user_id}")
        await asyncio.sleep(0.3)

        return {
            "hotel_booking_reference": f"HT-{booking_id}",
            "hotel_name": hotel_details.get("hotel_name"),
            "hotel_confirmation": f"CONF-HT-{booking_id}",
        }

    @compensate("book_hotel")
    async def cancel_hotel(self, ctx: SagaContext) -> None:
        """Cancel hotel booking using booking data from context."""
        booking_id = ctx.get("booking_id")
        logger.warning(f"Canceling hotel for booking {booking_id}")

        # Access hotel booking result from context
        booking_reference = ctx.get("hotel_booking_reference")
        hotel_name = ctx.get("hotel_name")
        if booking_reference:
            logger.info(f"Canceling hotel {hotel_name} booking {booking_reference}")

        await asyncio.sleep(0.2)

    @action("book_car", depends_on=["book_hotel"])
    async def book_car(self, ctx: SagaContext) -> dict[str, Any]:
        """Book rental car (if requested)."""
        booking_id = ctx.get("booking_id")
        user_id = ctx.get("user_id")
        car_details = ctx.get("car_details")

        if not car_details:
            return {"car_skipped": True}

        logger.info(f"Booking car for {user_id}")
        await asyncio.sleep(0.2)

        return {
            "car_booking_reference": f"CAR-{booking_id}",
            "car_type": car_details.get("car_type"),
            "car_confirmation": f"CONF-CAR-{booking_id}",
        }

    @compensate("book_car")
    async def cancel_car(self, ctx: SagaContext) -> None:
        """Cancel car booking using booking data from context."""
        booking_id = ctx.get("booking_id")
        logger.warning(f"Canceling car for booking {booking_id}")

        # Access car booking result from context (may not exist if skipped)
        booking_reference = ctx.get("car_booking_reference")
        car_type = ctx.get("car_type")
        if booking_reference and not ctx.get("car_skipped"):
            logger.info(f"Canceling {car_type} rental booking {booking_reference}")

        await asyncio.sleep(0.1)

    @action("send_itinerary", depends_on=["book_car"])
    async def send_itinerary(self, ctx: SagaContext) -> dict[str, Any]:
        """Send complete itinerary to user."""
        booking_id = ctx.get("booking_id")
        user_id = ctx.get("user_id")

        logger.info(f"Sending itinerary to {user_id}")
        await asyncio.sleep(0.1)

        return {
            "itinerary_sent": True,
            "booking_id": booking_id,
        }


async def main():
    """Run the travel booking saga demo."""

    # Create a reusable saga instance
    saga = TravelBookingSaga()

    # Book first trip - with car rental
    await saga.run({
        "booking_id": "BOOK-456",
        "user_id": "USER-123",
        "flight_details": {"flight_number": "AA123", "from": "NYC", "to": "LAX"},
        "hotel_details": {"hotel_name": "Grand Hotel", "nights": 3},
        "car_details": {"car_type": "Sedan", "days": 3},
    })


    # Demonstrate reusability - same saga, different booking (no car)

    await saga.run({
        "booking_id": "BOOK-789",
        "user_id": "USER-456",
        "flight_details": {"flight_number": "UA456", "from": "SFO", "to": "JFK"},
        "hotel_details": {"hotel_name": "City Inn", "nights": 2},
        "car_details": None,  # No car rental
    })



if __name__ == "__main__":
    asyncio.run(main())
