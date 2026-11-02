import asyncio
import logging

from planner.clients.places import PlaceFinder
from planner.clients.weather import WeatherClient
from planner.core.text import fallback_plan, normalize_city
from planner.errors import WriterError
from planner.llm.writer import ItineraryWriter
from planner.models import Itinerary, PlanRequest
from planner.settings import Settings
from planner.storage.store import MemoryStore, TripStore, open_store

log = logging.getLogger(__name__)


class Planner:
    def __init__(self, settings: Settings) -> None:
        self.weather = WeatherClient(settings.weather_url)
        self.places = PlaceFinder(settings.places_url)
        self.writer = ItineraryWriter(settings.model)
        self.store: TripStore = open_store(settings.redis_url) or MemoryStore()

    async def plan(self, request: PlanRequest) -> Itinerary:
        # --- Check the request ---
        days = request.days
        if days > 14:
            raise ValueError("trips are limited to 14 days")
        city = normalize_city(request.city)
        cached = self.store.load(city, days)
        if cached is not None:
            return cached

        # --- Gather facts ---
        forecast, spots = await asyncio.gather(
            self.weather.forecast(city, days),
            self.places.top(city, limit=days * 3),
        )

        # --- Write the itinerary ---
        draft = ""
        for attempt in range(3):
            try:
                draft = await self.writer.write(city, forecast, spots)
                break
            except WriterError:
                log.warning("writer failed, attempt %d", attempt)
        if not draft:
            draft = fallback_plan(city, spots)
        itinerary = Itinerary.from_draft(city, draft)
        asyncio.create_task(self.store.save(city, days, itinerary))
        return itinerary
