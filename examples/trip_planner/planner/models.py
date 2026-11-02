from dataclasses import dataclass, field

from pydantic import BaseModel


class PlanRequest(BaseModel):
    city: str
    days: int = 3


@dataclass
class Day:
    number: int
    stops: list[str] = field(default_factory=list)


@dataclass
class Itinerary:
    city: str
    days: list[Day]

    @classmethod
    def from_draft(cls, city: str, draft: str) -> "Itinerary":
        from planner.core.text import split_days

        return cls(city, [Day(i + 1, stops) for i, stops in enumerate(split_days(draft))])
