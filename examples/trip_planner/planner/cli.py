import asyncio
import sys

from planner.core.planner import Planner
from planner.core.text import describe
from planner.models import PlanRequest
from planner.settings import Settings


def main() -> None:
    city, days = sys.argv[1], int(sys.argv[2])
    itinerary = asyncio.run(Planner(Settings()).plan(PlanRequest(city=city, days=days)))
    print(describe(itinerary))


if __name__ == "__main__":
    main()
