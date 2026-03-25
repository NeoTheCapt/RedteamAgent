from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Row


@dataclass(frozen=True, slots=True)
class Project:
    id: int
    user_id: int
    name: str
    slug: str
    root_path: str
    created_at: str

    @classmethod
    def from_row(cls, row: Row) -> "Project":
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            slug=row["slug"],
            root_path=row["root_path"],
            created_at=row["created_at"],
        )
