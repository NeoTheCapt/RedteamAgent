import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parents[1]
DEFAULT_PROJECTS_DIR = Path.home() / ".redteam-orchestrator" / "projects"


@dataclass(frozen=True)
class Settings:
    app_name: str = "Redteam Orchestrator"
    data_dir: Path = Path(os.environ.get("REDTEAM_ORCHESTRATOR_DATA_DIR", str(BACKEND_ROOT / "data")))
    projects_dir: Path = Path(os.environ.get("REDTEAM_ORCHESTRATOR_PROJECTS_DIR", str(DEFAULT_PROJECTS_DIR)))
    frontend_dist_dir: Path = REPO_ROOT / "orchestrator" / "frontend" / "dist"
    session_ttl_hours: int = 24
    agent_source_dir: Path = REPO_ROOT / "agent"
    install_script_path: Path = REPO_ROOT / "install.sh"
    opencode_command: str = "opencode"
    redteam_allinone_image: str = os.environ.get("REDTEAM_ALLINONE_IMAGE", "redteam-allinone:latest")
    orchestrator_public_url: str = os.environ.get("ORCHESTRATOR_PUBLIC_URL", "http://127.0.0.1:18000")
    orchestrator_container_url: str = os.environ.get("ORCHESTRATOR_CONTAINER_URL", "http://host.docker.internal:18000")
    auto_launch_runs: bool = True
    # Keepalive: auto-recreate a run when the listed targets have no active
    # run. Intended for long-lived observation targets (OKX / local Juice
    # Shop) so a stall-detector false positive doesn't leave the operator
    # with a dead run until the next 30-min scheduled cycle.
    #   REDTEAM_ORCHESTRATOR_KEEPALIVE_PROJECT_ID=19
    #   REDTEAM_ORCHESTRATOR_KEEPALIVE_TARGETS=http://127.0.0.1:8000,https://www.okx.com
    #   REDTEAM_ORCHESTRATOR_KEEPALIVE_INTERVAL_SECONDS=60
    #   REDTEAM_ORCHESTRATOR_KEEPALIVE_GRACE_SECONDS=120   (don't replace runs
    #     younger than this, even if already marked failed; avoids flapping
    #     when a cycle intentionally stops its run mid-work)
    keepalive_project_id: int = int(
        os.environ.get("REDTEAM_ORCHESTRATOR_KEEPALIVE_PROJECT_ID", "0")
    )
    keepalive_targets: str = os.environ.get(
        "REDTEAM_ORCHESTRATOR_KEEPALIVE_TARGETS", ""
    )
    keepalive_interval_seconds: int = int(
        os.environ.get("REDTEAM_ORCHESTRATOR_KEEPALIVE_INTERVAL_SECONDS", "60")
    )
    keepalive_grace_seconds: int = int(
        os.environ.get("REDTEAM_ORCHESTRATOR_KEEPALIVE_GRACE_SECONDS", "120")
    )


settings = Settings()
