from __future__ import annotations
from pathlib import Path
from fastapi import APIRouter, HTTPException, status

from .. import db
from ..security import CurrentUser
from ..services.runs import _project_or_404
from ..services.artifacts import ARTIFACT_SPECS, _active_engagement_root

router = APIRouter(
    prefix="/projects/{project_id}/runs/{run_id}/documents",
    tags=["documents"],
)

_MAX_PREVIEW_BYTES = 1_048_576  # 1 MB

# Files the artifacts service marks as sensitive — never expose through documents.
_SENSITIVE_NAMES: frozenset[str] = frozenset(
    spec[0] for spec in ARTIFACT_SPECS.values() if spec[2]  # sensitive flag
)


def _resolve_engagement_root(
    project_id: int, run_id: int, current_user: CurrentUser,
) -> Path | None:
    """Return the active engagement dir, or None if no engagement exists yet."""
    project = _project_or_404(project_id, current_user)
    run = db.get_run_by_id(run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    run_root = Path(run.engagement_root).resolve()
    try:
        eng = _active_engagement_root(run_root)
    except Exception:
        return None
    eng_resolved = eng.resolve()
    # _active_engagement_root falls back to run_root itself when no engagement
    # exists yet — treat that as "no engagement dir" so the UI shows empty buckets
    # rather than leaking arbitrary run_root files.
    if eng_resolved == run_root:
        return None
    if not eng_resolved.exists() or not eng_resolved.is_dir():
        return None
    return eng_resolved


def _categorize(relative_path: str) -> str:
    """Map a file path (relative to the engagement dir) to a UI bucket."""
    parts = Path(relative_path).parts
    name = parts[-1] if parts else ""
    top = parts[0] if parts else ""
    if name == "findings.md" or top == "findings":
        return "findings"
    if name == "report.md" or top == "reports":
        return "reports"
    if name == "intel.md" or top == "intel":
        return "intel"
    if name == "surfaces.jsonl" or top == "surface":
        return "surface"
    return "other"


@router.get("")
def list_documents(
    project_id: int, run_id: int, current_user: CurrentUser,
) -> dict[str, list[dict]]:
    eng = _resolve_engagement_root(project_id, run_id, current_user)
    tree: dict[str, list[dict]] = {
        "findings": [],
        "reports": [],
        "intel": [],
        "surface": [],
        "other": [],
    }
    if eng is None:
        return tree
    for p in sorted(eng.rglob("*")):
        if not p.is_file():
            continue
        if p.name in _SENSITIVE_NAMES:
            continue
        rel = p.relative_to(eng)
        rel_str = str(rel)
        stat = p.stat()
        tree[_categorize(rel_str)].append({
            "name": p.name,
            "path": rel_str,
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
        })
    return tree


@router.get("/{path:path}")
def get_document(
    project_id: int, run_id: int, path: str, current_user: CurrentUser,
) -> dict:
    eng = _resolve_engagement_root(project_id, run_id, current_user)
    if eng is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    target = (eng / path).resolve()
    try:
        target.relative_to(eng)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Path escapes engagement root")
    if target.name in _SENSITIVE_NAMES:
        # Deny by pretending it doesn't exist — same surface as the listing.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if target.stat().st_size > _MAX_PREVIEW_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="Document too large for inline preview")
    return {"path": path, "content": target.read_text(errors="replace")}
