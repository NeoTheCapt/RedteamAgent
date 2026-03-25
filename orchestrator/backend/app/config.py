from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parents[1]


@dataclass(frozen=True)
class Settings:
    app_name: str = "Redteam Orchestrator"
    data_dir: Path = BACKEND_ROOT / "data"
    session_ttl_hours: int = 24
    agent_source_dir: Path = REPO_ROOT / "agent"


settings = Settings()
