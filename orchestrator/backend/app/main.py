from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.projects import router as projects_router
from .config import settings
from .api.auth import router as auth_router
from .db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(auth_router)
app.include_router(projects_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
