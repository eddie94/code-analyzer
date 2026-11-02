from planner.models import Itinerary


def normalize_city(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split())


def split_days(draft: str) -> list[list[str]]:
    return [line.split(", ") for line in draft.splitlines() if line]


def fallback_plan(city: str, spots: list[str]) -> str:
    return "\n".join(", ".join(spots[i : i + 3]) for i in range(0, len(spots), 3))


def describe(itinerary: Itinerary) -> str:
    return f"{itinerary.city}: {len(itinerary.days)} days"
