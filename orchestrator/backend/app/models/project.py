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
    provider_id: str
    model_id: str
    small_model_id: str
    api_key: str
    base_url: str
    auth_json: str
    env_json: str
    created_at: str
    crawler_json: str = "{}"
    parallel_json: str = "{}"
    agents_json: str = "{}"

    @classmethod
    def from_row(cls, row: Row) -> "Project":
        keys = row.keys() if hasattr(row, "keys") else []
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            slug=row["slug"],
            root_path=row["root_path"],
            provider_id=row["provider_id"],
            model_id=row["model_id"],
            small_model_id=row["small_model_id"],
            api_key=row["api_key"],
            base_url=row["base_url"],
            auth_json=row["auth_json"],
            env_json=row["env_json"],
            created_at=row["created_at"],
            crawler_json=row["crawler_json"] if "crawler_json" in keys else "{}",
            parallel_json=row["parallel_json"] if "parallel_json" in keys else "{}",
            agents_json=row["agents_json"] if "agents_json" in keys else "{}",
        )
