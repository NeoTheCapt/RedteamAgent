from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from .api.artifacts import router as artifacts_router
from .api.cases import router as cases_router
from .api.dispatches import router as dispatches_router
from .api.documents import router as documents_router
from .api.events import router as events_router
from .api.projects import router as projects_router
from .api.runs import router as runs_router
from .config import settings
from .api.auth import router as auth_router
from .db import get_project_by_id, get_run_by_id, get_user_by_id, init_db
from .services.runs import recover_active_run_supervisors_on_startup
from .ws import broadcaster, ws_tickets


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    recover_active_run_supervisors_on_startup()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(runs_router)
app.include_router(events_router)
app.include_router(dispatches_router)
app.include_router(cases_router)
app.include_router(documents_router)
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


@app.get("/{full_path:path}")
def frontend_app(full_path: str):
    if not settings.frontend_dist_dir.exists():
        return {"detail": "frontend build not found"}

    requested_path = settings.frontend_dist_dir / full_path
    if full_path and requested_path.is_file() and requested_path.is_relative_to(settings.frontend_dist_dir):
        return FileResponse(requested_path)

    index_path = settings.frontend_dist_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)

    return {"detail": "frontend build not found"}
