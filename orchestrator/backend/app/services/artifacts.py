from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, status

from ..models.run import Run
from ..models.user import User
from .runs import _project_or_404


@dataclass(frozen=True, slots=True)
class ArtifactEntry:
    name: str
    relative_path: str
    media_type: str
    sensitive: bool
    exists: bool


@dataclass(frozen=True, slots=True)
class ArtifactContent:
    entry: ArtifactEntry
    content: str


ARTIFACT_SPECS = {
    "scope.json": ("scope.json", "application/json", False),
    "log.md": ("log.md", "text/markdown", False),
    "findings.md": ("findings.md", "text/markdown", False),
    "report.md": ("report.md", "text/markdown", False),
    "intel.md": ("intel.md", "text/markdown", False),
    "intel-secrets.json": ("intel-secrets.json", "application/json", True),
    "auth.json": ("auth.json", "application/json", True),
    "surfaces.jsonl": ("surfaces.jsonl", "text/plain", False),
}


def _run_or_404(project_id: int, run_id: int, user: User) -> Run:
    project = _project_or_404(project_id, user)
    from .. import db

    run = db.get_run_by_id(run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


def _artifact_entry(run_root: Path, name: str) -> ArtifactEntry:
    relative_path, media_type, sensitive = ARTIFACT_SPECS[name]
    return ArtifactEntry(
        name=name,
        relative_path=relative_path,
        media_type=media_type,
        sensitive=sensitive,
        exists=(run_root / relative_path).exists(),
    )


def list_artifacts_for_run(project_id: int, run_id: int, user: User) -> list[ArtifactEntry]:
    run = _run_or_404(project_id, run_id, user)
    run_root = Path(run.engagement_root)
    return [_artifact_entry(run_root, name) for name in ARTIFACT_SPECS]


def read_artifact_for_run(project_id: int, run_id: int, user: User, name: str) -> ArtifactContent:
    if name not in ARTIFACT_SPECS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")

    run = _run_or_404(project_id, run_id, user)
    run_root = Path(run.engagement_root)
    entry = _artifact_entry(run_root, name)
    artifact_path = run_root / entry.relative_path
    if not artifact_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")

    return ArtifactContent(
        entry=entry,
        content=artifact_path.read_text(encoding="utf-8"),
    )
