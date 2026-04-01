import sys
from pathlib import Path

from fastapi.testclient import TestClient


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


def test_backend_serves_frontend_build_when_present(isolate_data_dir):
    repo_root = Path(__file__).resolve().parents[3]
    backend_root = repo_root / "orchestrator" / "backend"
    sys.path.insert(0, str(backend_root))
    try:
        from app.config import settings
        from app.main import app
    finally:
        sys.path.remove(str(backend_root))

    settings.frontend_dist_dir.mkdir(parents=True, exist_ok=True)
    (settings.frontend_dist_dir / "assets").mkdir(parents=True, exist_ok=True)
    (settings.frontend_dist_dir / "index.html").write_text("<html><body>orchestrator</body></html>", encoding="utf-8")
    (settings.frontend_dist_dir / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")

    client = TestClient(app)
    root_response = client.get("/")
    asset_response = client.get("/assets/app.js")

    assert root_response.status_code == 200
    assert "orchestrator" in root_response.text
    assert asset_response.status_code == 200
    assert "console.log('ok')" in asset_response.text


def test_frontend_uses_absolute_asset_base():
    repo_root = Path(__file__).resolve().parents[3]
    vite_config = repo_root / "orchestrator" / "frontend" / "vite.config.ts"
    content = vite_config.read_text(encoding="utf-8")

    assert 'base: "/"' in content
    assert 'base: "./"' not in content
