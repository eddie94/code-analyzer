from fastapi import FastAPI

from planner.core.planner import Planner
from planner.models import Itinerary, PlanRequest
from planner.routes import router
from planner.settings import Settings

app = FastAPI(title="Trip planner")
app.include_router(router)
planner = None


@app.on_event("startup")
def start() -> None:
    global planner
    planner = Planner(Settings())


@app.post("/plans")
async def create_plan(request: PlanRequest) -> Itinerary:
    return await planner.plan(request)
