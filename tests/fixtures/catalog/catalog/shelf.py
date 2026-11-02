from catalog.storage import CachedStore, Store


class Shelf:
    def __init__(self, store: Store = CachedStore()) -> None:
        self.store = store

    async def lookup(self, words: list[str]) -> list[str]:
        found = self.store.fetch(" ".join(words))
        return self._sorted(found)

    def _sorted(self, titles: list[str]) -> list[str]:
        return sorted(titles)
