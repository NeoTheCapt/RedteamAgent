from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from ..models.event import Event
from ..security import CurrentUser
from ..services.events import create_event_for_run, list_events_for_run, summarize_events_for_run
from ..ws import broadcaster

router = APIRouter(prefix="/projects/{project_id}/runs/{run_id}/events", tags=["events"])


class CreateEventRequest(BaseModel):
    event_type: str = Field(min_length=1, max_length=64)
    phase: str = Field(min_length=1, max_length=64)
    task_name: str = Field(min_length=1, max_length=128)
    agent_name: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=512)


class EventResponse(BaseModel):
    id: int
    event_type: str
    phase: str
    task_name: str
    agent_name: str
    summary: str
    created_at: str


def _event_response(event: Event) -> EventResponse:
    return EventResponse(
        id=event.id,
        event_type=event.event_type,
        phase=event.phase,
        task_name=event.task_name,
        agent_name=event.agent_name,
        summary=event.summary,
        created_at=event.created_at,
    )


@router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    project_id: int,
    run_id: int,
    request: CreateEventRequest,
    current_user: CurrentUser,
) -> EventResponse:
    event = create_event_for_run(
        project_id,
        run_id,
        current_user,
        event_type=request.event_type,
        phase=request.phase,
        task_name=request.task_name,
        agent_name=request.agent_name,
        summary=request.summary,
    )
    response = _event_response(event)
    await broadcaster.publish(
        project_id,
        run_id,
        {
            "type": "event.created",
            "project_id": project_id,
            "run_id": run_id,
            "event": response.model_dump(),
        },
    )
    return response


@router.get("", response_model=list[EventResponse])
def list_events(project_id: int, run_id: int, current_user: CurrentUser) -> list[EventResponse]:
    return [_event_response(event) for event in list_events_for_run(project_id, run_id, current_user)]


@router.get("/summary")
def summarize_events(project_id: int, run_id: int, current_user: CurrentUser) -> dict[str, dict[str, str] | None]:
    return summarize_events_for_run(project_id, run_id, current_user)
