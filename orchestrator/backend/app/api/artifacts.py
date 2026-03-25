from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..security import CurrentUser
from ..services.artifacts import list_artifacts_for_run, read_artifact_for_run

router = APIRouter(prefix="/projects/{project_id}/runs/{run_id}/artifacts", tags=["artifacts"])


class ArtifactResponse(BaseModel):
    name: str
    relative_path: str
    media_type: str
    sensitive: bool
    exists: bool


class ArtifactContentResponse(ArtifactResponse):
    content: str


def _artifact_response_payload(artifact) -> dict:
    return {
        "name": artifact.name,
        "relative_path": artifact.relative_path,
        "media_type": artifact.media_type,
        "sensitive": artifact.sensitive,
        "exists": artifact.exists,
    }


@router.get("", response_model=list[ArtifactResponse])
def list_artifacts(project_id: int, run_id: int, current_user: CurrentUser) -> list[ArtifactResponse]:
    artifacts = list_artifacts_for_run(project_id, run_id, current_user)
    return [ArtifactResponse(**_artifact_response_payload(artifact)) for artifact in artifacts]


@router.get("/{artifact_name}", response_model=ArtifactContentResponse)
def read_artifact(project_id: int, run_id: int, artifact_name: str, current_user: CurrentUser) -> ArtifactContentResponse:
    artifact = read_artifact_for_run(project_id, run_id, current_user, artifact_name)
    return ArtifactContentResponse(content=artifact.content, **_artifact_response_payload(artifact.entry))
