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
    current_phase: str = ""
    current_round: int = 0
    parallel_config: str = "{}"
    benchmark_json: str = "{}"

    @classmethod
    def from_row(cls, row: Row) -> "Run":
        keys = set(row.keys())
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            target=row["target"],
            status=row["status"],
            engagement_root=row["engagement_root"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            current_phase=row["current_phase"] if "current_phase" in keys else "",
            current_round=row["current_round"] if "current_round" in keys else 0,
            parallel_config=row["parallel_config"] if "parallel_config" in keys else "{}",
            benchmark_json=row["benchmark_json"] if "benchmark_json" in keys else "{}",
        )
