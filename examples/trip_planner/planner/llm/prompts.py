ITINERARY_PROMPT = """Plan a trip to {city}.
Weather by day: {forecast}
Places worth seeing: {spots}
Write one line per day, places separated by commas."""


def build_prompt(city: str, forecast: list[str], spots: list[str]) -> str:
    return ITINERARY_PROMPT.format(city=city, forecast="; ".join(forecast), spots=", ".join(spots))
