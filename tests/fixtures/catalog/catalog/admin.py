from fastapi import APIRouter

admin = APIRouter()


@admin.get("/stats")
def stats() -> dict:
    return {"books": 0}
