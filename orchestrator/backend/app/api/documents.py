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

# Relative paths (from run_root) that live under run_root directly rather than
# inside the engagement dir.  These mirror ARTIFACT_SPECS entries whose path
# starts with "runtime/".
_RUN_ROOT_PREFIXES: tuple[str, ...] = tuple(
    spec[0]
    for spec in ARTIFACT_SPECS.values()
    if spec[0].startswith("runtime/") and not spec[2]  # not sensitive
)


def _resolve_roots(
    project_id: int, run_id: int, current_user: CurrentUser,
) -> tuple[Path, Path | None]:
    """Return (run_root, engagement_dir_or_None).

    run_root is always returned so callers can walk runtime/ artifacts.
    engagement_dir is None when no active engagement exists yet.
    """
    project = _project_or_404(project_id, current_user)
    run = db.get_run_by_id(run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    run_root = Path(run.engagement_root).resolve()
    try:
        eng = _active_engagement_root(run_root)
    except Exception:
        return run_root, None
    eng_resolved = eng.resolve()
    # _active_engagement_root falls back to run_root itself when no engagement
    # exists yet — treat that as "no engagement dir" so the UI shows empty buckets
    # rather than leaking arbitrary run_root files.
    if eng_resolved == run_root:
        return run_root, None
    if not eng_resolved.exists() or not eng_resolved.is_dir():
        return run_root, None
    return run_root, eng_resolved


def _categorize(relative_path: str) -> str:
    """Map a file path (relative to the engagement dir or run_root) to a UI bucket."""
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
    run_root, eng = _resolve_roots(project_id, run_id, current_user)
    tree: dict[str, list[dict]] = {
        "findings": [],
        "reports": [],
        "intel": [],
        "surface": [],
        "other": [],
    }

    def _add_file(p: Path, rel_str: str) -> None:
        if p.name in _SENSITIVE_NAMES:
            return
        stat = p.stat()
        tree[_categorize(rel_str)].append({
            "name": p.name,
            "path": rel_str,
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
        })

    # Walk engagement dir files (the primary artifact tree).
    if eng is not None:
        for p in sorted(eng.rglob("*")):
            if not p.is_file():
                continue
            _add_file(p, str(p.relative_to(eng)))

    # Walk run_root-relative paths from ARTIFACT_SPECS (e.g. runtime/process.log).
    for rel_path in _RUN_ROOT_PREFIXES:
        p = run_root / rel_path
        if p.is_file():
            _add_file(p, rel_path)

    return tree


@router.get("/{path:path}")
def get_document(
    project_id: int, run_id: int, path: str, current_user: CurrentUser,
) -> dict:
    run_root, eng = _resolve_roots(project_id, run_id, current_user)

    # Determine which root to resolve from.
    # Paths that match a run_root-relative ARTIFACT_SPECS entry are served from
    # run_root; everything else is served from the engagement dir.
    # Use exact-path matching against the allowlist — prefix-dir matching would
    # allow arbitrary files under e.g. "runtime/" that are NOT in ARTIFACT_SPECS.
    norm_path = path.lstrip("/")
    is_run_root_path = norm_path in _RUN_ROOT_PREFIXES

    if is_run_root_path:
        base = run_root
    else:
        if eng is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        base = eng

    target = (base / norm_path).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Path escapes document root")
    if target.name in _SENSITIVE_NAMES:
        # Deny by pretending it doesn't exist — same surface as the listing.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if target.stat().st_size > _MAX_PREVIEW_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="Document too large for inline preview")
    return {"path": path, "content": target.read_text(errors="replace")}
