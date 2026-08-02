from pathlib import Path
from types import SimpleNamespace

from app.services import launcher


def test_workspace_root_is_setgid_for_container_host_shared_group(tmp_path, monkeypatch):
    source = tmp_path / "agent-source"
    source.mkdir()
    (source / "AGENTS.md").write_text("test\n", encoding="utf-8")

    monkeypatch.setattr(launcher, "settings", SimpleNamespace(agent_source_dir=source))
    run = SimpleNamespace(engagement_root=str(tmp_path / "run"))

    launcher._sync_agent_source_into_workspace(run)

    workspace = Path(run.engagement_root) / "workspace"
    assert workspace.stat().st_mode & 0o7777 == 0o2775
    assert (workspace / "AGENTS.md").read_text(encoding="utf-8") == "test\n"
