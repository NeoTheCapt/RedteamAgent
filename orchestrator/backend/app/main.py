from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .api.artifacts import router as artifacts_router
from .api.events import router as events_router
from .api.projects import router as projects_router
from .api.runs import router as runs_router
from .config import settings
from .api.auth import router as auth_router
from .db import get_project_by_id, get_run_by_id, get_user_by_token, init_db
from .security import format_utc_timestamp, utc_now
from .ws import broadcaster


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(runs_router)
app.include_router(events_router)
app.include_router(artifacts_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@app.websocket("/ws/projects/{project_id}/runs/{run_id}")
async def run_stream(websocket: WebSocket, project_id: int, run_id: int) -> None:
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008, reason="Missing bearer token")
        return

    user = get_user_by_token(token, format_utc_timestamp(utc_now()))
    if user is None:
        await websocket.close(code=1008, reason="Invalid or expired session")
        return

    project = get_project_by_id(project_id)
    run = get_run_by_id(run_id)
    if project is None or run is None or project.user_id != user.id or run.project_id != project.id:
        await websocket.close(code=1008, reason="Run not found")
        return

    await broadcaster.connect(project_id, run_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        broadcaster.disconnect(project_id, run_id, websocket)
