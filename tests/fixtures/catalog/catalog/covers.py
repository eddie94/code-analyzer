import httpx


class CoverClient:
    def download(self, title: str) -> bytes:
        return httpx.get(f"https://covers.example.invalid/{title}").content


def connect() -> CoverClient:
    return CoverClient()


async def covers_for(titles: list[str]) -> list[bytes]:
    client = connect()
    return [client.download(title) for title in titles]
