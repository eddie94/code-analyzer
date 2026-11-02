import os


class Settings:
    model: str = os.environ.get("PLANNER_MODEL", "gpt-4o-mini")
    weather_url: str = os.environ.get("WEATHER_URL", "https://weather.example.invalid")
    places_url: str = os.environ.get("PLACES_URL", "https://places.example.invalid")
    redis_url: str | None = os.environ.get("REDIS_URL")
