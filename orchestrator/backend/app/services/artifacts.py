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
    "process.log": ("runtime/process.log", "text/plain", False),
    "findings.md": ("findings.md", "text/markdown", False),
    "report.md": ("report.md", "text/markdown", False),
    "intel.md": ("intel.md", "text/markdown", False),
    "intel-secrets.json": ("intel-secrets.json", "application/json", True),
    "auth.json": ("auth.json", "application/json", True),
    "surfaces.jsonl": ("surfaces.jsonl", "text/plain", False),
}


def _engagement_dir_rank(path: Path) -> tuple[int, float, str]:
    return (1 if (path / "scope.json").exists() else 0, path.stat().st_mtime, path.name)



def _active_engagement_root(run_root: Path) -> Path:
    workspace = run_root / "workspace"
    engagements_root = workspace / "engagements"
    active_file = engagements_root / ".active"
    if not active_file.exists():
        candidates = (
            sorted(
                [path for path in engagements_root.iterdir() if path.is_dir()],
                key=_engagement_dir_rank,
                reverse=True,
            )
            if engagements_root.exists()
            else []
        )
        if candidates:
            active_file.write_text(f"engagements/{candidates[0].name}", encoding="utf-8")
            return candidates[0]
        return run_root

    active_name = active_file.read_text(encoding="utf-8").strip()
    if not active_name:
        return run_root

    active_path = Path(active_name)
    if active_path.is_absolute():
        if active_path.exists() and (active_path / "scope.json").exists():
            return active_path
    else:
        active_relative = active_name.removeprefix("./").removeprefix("/")
        engagement_root = workspace / active_relative if active_relative.startswith("engagements/") else engagements_root / active_relative
        if engagement_root.exists() and (engagement_root / "scope.json").exists():
            return engagement_root

    candidates = (
        sorted(
            [path for path in engagements_root.iterdir() if path.is_dir()],
            key=_engagement_dir_rank,
            reverse=True,
        )
        if engagements_root.exists()
        else []
    )
    if candidates:
        active_file.write_text(f"engagements/{candidates[0].name}", encoding="utf-8")
        return candidates[0]
    if active_path.is_absolute() and active_path.exists():
        return active_path
    if 'engagement_root' in locals() and engagement_root.exists():
        return engagement_root
    return run_root


def _run_or_404(project_id: int, run_id: int, user: User) -> Run:
    project = _project_or_404(project_id, user)
    from .. import db

    run = db.get_run_by_id(run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


def _artifact_entry(run_root: Path, name: str) -> ArtifactEntry:
    relative_path, media_type, sensitive = ARTIFACT_SPECS[name]
    base_root = run_root if relative_path.startswith("runtime/") else _active_engagement_root(run_root)
    return ArtifactEntry(
        name=name,
        relative_path=relative_path,
        media_type=media_type,
        sensitive=sensitive,
        exists=(base_root / relative_path).exists(),
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
    artifact_root = run_root if entry.relative_path.startswith("runtime/") else _active_engagement_root(run_root)
    artifact_path = artifact_root / entry.relative_path
    if not artifact_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")

    return ArtifactContent(
        entry=entry,
        content=artifact_path.read_text(encoding="utf-8"),
    )
