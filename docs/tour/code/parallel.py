"""Steps that do not depend on each other run at the same time."""

import asyncio

from sagaz import Saga, action

events = []


class TripSaga(Saga):
    saga_name = "trip"

    @action("book_flight")
    async def book_flight(self, ctx):
        events.append("flight starts")
        await asyncio.sleep(0.05)
        events.append("flight booked")
        return {"flight": "LH-400"}

    @action("book_hotel")
    async def book_hotel(self, ctx):
        events.append("hotel starts")
        await asyncio.sleep(0.05)
        events.append("hotel booked")
        return {"hotel": "Ritz"}

    # Runs once both bookings are done, and reads what they returned.
    @action("send_itinerary", depends_on=["book_flight", "book_hotel"])
    async def send_itinerary(self, ctx):
        print("itinerary:", ctx["flight"], "+", ctx["hotel"])


asyncio.run(TripSaga().run({}))
print("both started before either was booked:", sorted(events[:2]))
