from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str = "Redteam Orchestrator"
    data_dir: Path = Path("data")


settings = Settings()

