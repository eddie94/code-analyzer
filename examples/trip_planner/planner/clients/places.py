import httpx


class PlaceFinder:
    def __init__(self, base_url: str) -> None:
        self.http = httpx.AsyncClient(base_url=base_url, timeout=5)

    async def top(self, city: str, limit: int = 10) -> list[str]:
        response = await self.http.get("/places", params={"city": city, "limit": limit})
        return [place["name"] for place in response.json()]
