import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parents[3]
backend_root = repo_root / "orchestrator" / "backend"
sys.path.insert(0, str(backend_root))

from app.config import settings


@pytest.fixture(autouse=True)
def isolate_data_dir(tmp_path):
    original_data_dir = settings.data_dir
    original_auto_launch_runs = settings.auto_launch_runs
    object.__setattr__(settings, "data_dir", tmp_path)
    object.__setattr__(settings, "auto_launch_runs", False)
    try:
        yield tmp_path
    finally:
        object.__setattr__(settings, "data_dir", original_data_dir)
        object.__setattr__(settings, "auto_launch_runs", original_auto_launch_runs)
