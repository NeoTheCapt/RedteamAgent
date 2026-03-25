from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .api.artifacts import router as artifacts_router
from .api.events import router as events_router
from .api.projects import router as projects_router
from .api.runs import router as runs_router
from .config import settings
from .api.auth import router as auth_router
from .db import get_project_by_id, get_run_by_id, get_user_by_id, init_db
from .ws import broadcaster, ws_tickets


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
    ticket = websocket.query_params.get("ticket")
    if not ticket:
        await websocket.close(code=1008, reason="Missing websocket ticket")
        return

    user_id = ws_tickets.consume(ticket)
    if user_id is None:
        await websocket.close(code=1008, reason="Invalid or expired websocket ticket")
        return

    user = get_user_by_id(user_id)
    if user is None:
        await websocket.close(code=1008, reason="Unknown user")
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
