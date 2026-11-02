import json

import redis.asyncio as redis

from planner.models import Itinerary


class TripStore:
    def load(self, city: str, days: int) -> Itinerary | None:
        return None

    async def save(self, city: str, days: int, itinerary: Itinerary) -> None:
        pass


class MemoryStore(TripStore):
    def __init__(self) -> None:
        self.trips: dict[tuple[str, int], Itinerary] = {}

    def load(self, city: str, days: int) -> Itinerary | None:
        return self.trips.get((city, days))

    async def save(self, city: str, days: int, itinerary: Itinerary) -> None:
        self.trips[city, days] = itinerary


class RedisStore(TripStore):
    def __init__(self, url: str) -> None:
        self.redis = redis.from_url(url)

    async def save(self, city: str, days: int, itinerary: Itinerary) -> None:
        await self.redis.set(f"trip:{city}:{days}", json.dumps(itinerary.__dict__, default=str))


def open_store(url: str | None) -> TripStore | None:
    return RedisStore(url) if url else None
