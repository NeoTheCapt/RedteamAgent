from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Row


@dataclass(frozen=True, slots=True)
class User:
    id: int
    username: str
    password_hash: str
    salt: str
    created_at: str

    @classmethod
    def from_row(cls, row: Row) -> "User":
        return cls(
            id=row["id"],
            username=row["username"],
            password_hash=row["password_hash"],
            salt=row["salt"],
            created_at=row["created_at"],
        )

    def public_dict(self) -> dict[str, int | str]:
        return {"id": self.id, "username": self.username}
