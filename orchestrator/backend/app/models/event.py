from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Row


@dataclass(frozen=True, slots=True)
class Event:
    id: int
    run_id: int
    event_type: str
    phase: str
    task_name: str
    agent_name: str
    summary: str
    created_at: str

    @classmethod
    def from_row(cls, row: Row) -> "Event":
        return cls(
            id=row["id"],
            run_id=row["run_id"],
            event_type=row["event_type"],
            phase=row["phase"],
            task_name=row["task_name"],
            agent_name=row["agent_name"],
            summary=row["summary"],
            created_at=row["created_at"],
        )
