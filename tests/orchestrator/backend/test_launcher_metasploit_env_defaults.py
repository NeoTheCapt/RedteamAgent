import json
from types import SimpleNamespace


def test_workspace_env_includes_metasploit_defaults_for_snapshot_launchers():
    from app.services.launcher import _render_workspace_env_file

    project = SimpleNamespace(
        env_json="{}",
        provider_id="openai",
        api_key="",
        api_key_encrypted="",
        base_url="",
        model_id="",
        small_model_id="",
        crawler_json='{"KATANA_CRAWL_DEPTH": 16}',
        parallel_json="{}",
        agents_json="{}",
    )

    env_text = _render_workspace_env_file(project)

    assert "KATANA_CRAWL_DEPTH=16" in env_text
    assert "MSF_USER=msf" in env_text
    assert "MSF_PASSWORD=msf" in env_text
    assert "MSF_SERVER=127.0.0.1" in env_text
    assert "MSF_PORT=55553" in env_text
    assert "MSF_SSL=false" in env_text


def test_runtime_env_normalizes_blank_metasploit_overrides(monkeypatch):
    from app.services import launcher

    monkeypatch.setattr(launcher, "create_session_token", lambda: "session-token")
    monkeypatch.setattr(launcher.db, "create_session", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(launcher, "session_expiry_timestamp", lambda: 0)

    project = SimpleNamespace(
        id=7,
        env_json=json.dumps(
            {
                "MSF_USER": "",
                "MSF_PASSWORD": "",
                "MSF_SERVER": "",
                "MSF_PORT": "",
                "MSF_SSL": "",
            }
        ),
        provider_id="openai",
        api_key="",
        api_key_encrypted="",
        base_url="",
        model_id="",
        small_model_id="",
        crawler_json="{}",
        parallel_json="{}",
        agents_json="{}",
    )
    run = SimpleNamespace(id=42, engagement_root="/tmp/redteam-run-42")
    user = SimpleNamespace(id=3)

    env = launcher._runtime_env(project, run, user)

    assert env["MSF_USER"] == "msf"
    assert env["MSF_PASSWORD"] == "msf"
    assert env["MSF_SERVER"] == "127.0.0.1"
    assert env["MSF_PORT"] == "55553"
    assert env["MSF_SSL"] == "false"
