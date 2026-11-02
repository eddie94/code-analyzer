import asyncio

from catalog.shelf import Shelf
from catalog.storage import Store


class Searcher:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.shelf = Shelf()
        self.backup: Store = Store()

    async def search(self, query: str) -> list[str]:
        words = self.split(query)
        if len(words) > 8:
            raise ValueError("query too long")
        asyncio.create_task(self.remember(query))
        titles, art = await asyncio.gather(self.shelf.lookup(words), self.artwork(words))
        if not titles:
            return self.backup.fetch(query)
        return self.merge(titles, art)

    async def remember(self, query: str) -> None:
        self.split(query)

    def split(self, query: str) -> list[str]:
        return query.lower().split()

    async def artwork(self, words: list[str]) -> list[bytes]:
        from catalog.covers import covers_for

        return await covers_for(words)

    def merge(self, titles: list[str], art: list[bytes]) -> list[str]:
        return titles[: len(art) or None]
