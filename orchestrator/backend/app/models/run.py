from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Row


@dataclass(frozen=True, slots=True)
class Run:
    id: int
    project_id: int
    target: str
    status: str
    engagement_root: str
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Row) -> "Run":
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            target=row["target"],
            status=row["status"],
            engagement_root=row["engagement_root"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
