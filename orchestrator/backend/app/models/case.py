from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Row


@dataclass(frozen=True, slots=True)
class Case:
    case_id: int
    run_id: int
    method: str
    path: str
    category: str | None
    dispatch_id: str | None
    state: str
    result: str | None
    finding_id: str | None
    started_at: int | None
    finished_at: int | None

    @classmethod
    def from_row(cls, row: Row) -> "Case":
        return cls(
            case_id=row["case_id"], run_id=row["run_id"],
            method=row["method"], path=row["path"],
            category=row["category"], dispatch_id=row["dispatch_id"],
            state=row["state"], result=row["result"],
            finding_id=row["finding_id"],
            started_at=row["started_at"], finished_at=row["finished_at"],
        )
