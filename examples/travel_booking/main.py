from typing import Any
import asyncio
import logging

from sagaz import (
    ClassicSaga,
    SagaContext,
)

logger = logging.getLogger(__name__)

# ============================================
# EXAMPLE: MULTI-SERVICE BOOKING
# ============================================


class TravelBookingSaga(ClassicSaga):
    """
    Travel booking across multiple services (flight + hotel + car rental)
    """

    def __init__(
        self,
        booking_id: str,
        user_id: str,
        flight_details: dict,
        hotel_details: dict,
        car_details: dict | None = None,
    ):
        super().__init__(name=f"TravelBooking-{booking_id}", version="1.0")
        self.booking_id = booking_id
        self.user_id = user_id
        self.flight_details = flight_details
        self.hotel_details = hotel_details
        self.car_details = car_details

    async def build(self):
        """Build travel booking saga"""

        # Step 1: Book flight
        await self.add_step(
            name="book_flight",
            action=self._book_flight,
            compensation=self._cancel_flight,
            timeout=30.0,
            max_retries=2,
        )

        # Step 2: Book hotel
        await self.add_step(
            name="book_hotel",
            action=self._book_hotel,
            compensation=self._cancel_hotel,
            timeout=30.0,
            max_retries=2,
        )

        # Step 3: Book car (optional)
        if self.car_details:
            await self.add_step(
                name="book_car",
                action=self._book_car,
                compensation=self._cancel_car,
                timeout=20.0,
                max_retries=2,
            )

        # Step 4: Send itinerary
        await self.add_step(name="send_itinerary", action=self._send_itinerary, timeout=10.0)

    async def _book_flight(self, ctx: SagaContext) -> dict[str, Any]:
        """Book flight"""
        logger.info(f"Booking flight for {self.user_id}")
        await asyncio.sleep(0.3)

        return {
            "booking_reference": f"FL-{self.booking_id}",
            "flight_number": self.flight_details["flight_number"],
            "confirmation": f"CONF-FL-{self.booking_id}",
        }

    async def _cancel_flight(self, result: dict, ctx: SagaContext) -> None:
        """Cancel flight booking"""
        logger.warning(f"Canceling flight {result['booking_reference']}")
        await asyncio.sleep(0.2)

    async def _book_hotel(self, ctx: SagaContext) -> dict[str, Any]:
        """Book hotel"""
        logger.info(f"Booking hotel for {self.user_id}")
        await asyncio.sleep(0.3)

        return {
            "booking_reference": f"HT-{self.booking_id}",
            "hotel_name": self.hotel_details["hotel_name"],
            "confirmation": f"CONF-HT-{self.booking_id}",
        }

    async def _cancel_hotel(self, result: dict, ctx: SagaContext) -> None:
        """Cancel hotel booking"""
        logger.warning(f"Canceling hotel {result['booking_reference']}")
        await asyncio.sleep(0.2)

    async def _book_car(self, ctx: SagaContext) -> dict[str, Any]:
        """Book rental car"""
        logger.info(f"Booking car for {self.user_id}")
        await asyncio.sleep(0.2)

        return {
            "booking_reference": f"CAR-{self.booking_id}",
            "car_type": self.car_details["car_type"],
            "confirmation": f"CONF-CAR-{self.booking_id}",
        }

    async def _cancel_car(self, result: dict, ctx: SagaContext) -> None:
        """Cancel car booking"""
        logger.warning(f"Canceling car {result['booking_reference']}")
        await asyncio.sleep(0.1)

    async def _send_itinerary(self, ctx: SagaContext) -> dict[str, Any]:
        """Send complete itinerary to user"""
        logger.info(f"Sending itinerary to {self.user_id}")
        await asyncio.sleep(0.1)

        flight = ctx.get("book_flight")
        hotel = ctx.get("book_hotel")
        car = ctx.get("book_car")

        return {
            "sent": True,
            "flight_confirmation": flight["confirmation"],
            "hotel_confirmation": hotel["confirmation"],
            "car_confirmation": car["confirmation"] if car else None,
        }


async def demo_travel_booking():
    """Demo: Travel booking"""
    print("\n" + "=" * 60)
    print("DEMO 2: Travel Booking")
    print("=" * 60)

    orchestrator = MonitoredSagaOrchestrator()

    # Create travel booking saga
    booking = TravelBookingSaga(
        booking_id="BOOK-456",
        user_id="USER-123",
        flight_details={"flight_number": "AA123", "from": "NYC", "to": "LAX"},
        hotel_details={"hotel_name": "Grand Hotel", "nights": 3},
        car_details={"car_type": "Sedan", "days": 3},
    )

    await booking.build()

    # Execute saga
    result = await orchestrator.execute_saga(booking)

    # Print result
    print(f"\n✅ Travel Booking Result:")
    print(f"   Success: {result.success}")
    print(f"   Status: {result.status.value}")
    print(f"   Completed Steps: {result.completed_steps}/{result.total_steps}")

    if result.is_completed:
        print("\n📧 Itinerary Details:")
        itinerary = booking.context.get("send_itinerary")
        print(f"   Flight: {itinerary['flight_confirmation']}")
        print(f"   Hotel: {itinerary['hotel_confirmation']}")
        if itinerary["car_confirmation"]:
            print(f"   Car: {itinerary['car_confirmation']}")
