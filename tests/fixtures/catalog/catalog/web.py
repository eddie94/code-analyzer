from fastapi import FastAPI

from catalog.admin import admin
from catalog.search import Searcher
from catalog.settings import Settings

api = FastAPI()
api.include_router(admin)
searcher = None


@api.on_event("startup")
def open_catalog() -> None:
    global searcher
    searcher = Searcher(Settings())


@api.get("/books")
async def find_books(q: str) -> list[str]:
    return await searcher.search(q)


def warm_up() -> None:
    print(Searcher(Settings()).split("Warm Up"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(api)
