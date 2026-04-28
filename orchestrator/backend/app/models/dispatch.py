from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Row


@dataclass(frozen=True, slots=True)
class Dispatch:
    id: str
    run_id: int
    phase: str
    round: int
    agent: str
    slot: str
    task: str | None
    state: str
    started_at: int | None
    finished_at: int | None
    error: str | None

    @classmethod
    def from_row(cls, row: Row) -> "Dispatch":
        return cls(
            id=row["id"], run_id=row["run_id"], phase=row["phase"],
            round=row["round"], agent=row["agent"], slot=row["slot"],
            task=row["task"], state=row["state"],
            started_at=row["started_at"], finished_at=row["finished_at"],
            error=row["error"],
        )
