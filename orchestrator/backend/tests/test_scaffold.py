import sys
from pathlib import Path


def test_orchestrator_root_scaffold_exists():
    repo_root = Path(__file__).resolve().parents[3]
    expected = [
        repo_root / "orchestrator" / "backend" / "pyproject.toml",
        repo_root / "orchestrator" / "backend" / "app" / "__init__.py",
        repo_root / "orchestrator" / "backend" / "app" / "main.py",
        repo_root / "orchestrator" / "backend" / "app" / "config.py",
        repo_root / "orchestrator" / "frontend" / "package.json",
        repo_root / "orchestrator" / "frontend" / "vite.config.ts",
        repo_root / "orchestrator" / "frontend" / "src" / "main.tsx",
        repo_root / "orchestrator" / "frontend" / "src" / "App.tsx",
    ]

    missing = [path for path in expected if not path.exists()]

    assert not missing, f"Missing orchestrator scaffold files: {missing}"


def test_orchestrator_backend_import_and_healthz():
    repo_root = Path(__file__).resolve().parents[3]
    backend_root = repo_root / "orchestrator" / "backend"
    sys.path.insert(0, str(backend_root))
    try:
        from app.main import app, healthz
    finally:
        sys.path.remove(str(backend_root))

    assert app.title == "Redteam Orchestrator"
    assert healthz() == {"status": "ok", "app": "Redteam Orchestrator"}
