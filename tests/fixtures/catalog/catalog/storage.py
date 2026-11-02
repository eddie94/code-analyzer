class Store:
    def fetch(self, key: str) -> list[str]:
        return []


class CachedStore(Store):
    def fetch(self, key: str) -> list[str]:
        return super().fetch(key.lower())
