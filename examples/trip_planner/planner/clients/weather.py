import httpx


class WeatherClient:
    def __init__(self, base_url: str) -> None:
        self.http = httpx.AsyncClient(base_url=base_url, timeout=5)

    async def forecast(self, city: str, days: int) -> list[str]:
        response = await self.http.get("/forecast", params={"city": city, "days": days})
        response.raise_for_status()
        return [day["summary"] for day in response.json()["days"]]
