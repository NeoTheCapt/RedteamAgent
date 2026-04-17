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
    kind: str = "legacy"
    level: str = "info"
    payload_json: str = "{}"

    @classmethod
    def from_row(cls, row: Row) -> "Event":
        keys = set(row.keys())
        return cls(
            id=row["id"],
            run_id=row["run_id"],
            event_type=row["event_type"],
            phase=row["phase"],
            task_name=row["task_name"],
            agent_name=row["agent_name"],
            summary=row["summary"],
            created_at=row["created_at"],
            kind=row["kind"] if "kind" in keys else "legacy",
            level=row["level"] if "level" in keys else "info",
            payload_json=row["payload_json"] if "payload_json" in keys else "{}",
        )
