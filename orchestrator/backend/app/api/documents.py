from __future__ import annotations
from pathlib import Path
from fastapi import APIRouter, HTTPException, status

from .. import db
from ..security import CurrentUser
from ..services.runs import _project_or_404

router = APIRouter(
    prefix="/projects/{project_id}/runs/{run_id}/documents",
    tags=["documents"],
)

_SUBDIRS = ("findings", "intel", "surface", "artifacts", "reports")
_MAX_PREVIEW_BYTES = 1_048_576  # 1 MB


def _resolve_run_root(project_id: int, run_id: int, current_user: CurrentUser) -> Path:
    project = _project_or_404(project_id, current_user)
    run = db.get_run_by_id(run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return Path(run.engagement_root).resolve()


@router.get("")
def list_documents(
    project_id: int, run_id: int, current_user: CurrentUser,
) -> dict[str, list[dict]]:
    root = _resolve_run_root(project_id, run_id, current_user)
    tree: dict[str, list[dict]] = {}
    for sub in _SUBDIRS:
        d = root / sub
        entries: list[dict] = []
        if d.exists() and d.is_dir():
            for p in sorted(d.rglob("*")):
                if not p.is_file():
                    continue
                rel = p.relative_to(root)
                stat = p.stat()
                entries.append({
                    "name": p.name,
                    "path": str(rel),
                    "size": stat.st_size,
                    "mtime": int(stat.st_mtime),
                })
        tree[sub] = entries
    return tree


@router.get("/{path:path}")
def get_document(
    project_id: int, run_id: int, path: str, current_user: CurrentUser,
) -> dict:
    root = _resolve_run_root(project_id, run_id, current_user)
    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Path escapes run root")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if target.stat().st_size > _MAX_PREVIEW_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="Document too large for inline preview")
    return {"path": path, "content": target.read_text(errors="replace")}
