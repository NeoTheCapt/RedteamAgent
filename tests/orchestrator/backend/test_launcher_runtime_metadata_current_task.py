from types import SimpleNamespace


def test_run_metadata_has_current_task_accepts_legacy_runtime_keys(monkeypatch):
    from app.services import launcher

    run = SimpleNamespace(id=1135)
    monkeypatch.setattr(
        launcher,
        "_read_run_metadata",
        lambda _run: {
            "current_agent": "exploit-developer",
            "current_task": "exploit-developer",
            "current_action": {
                "agent_name": "exploit-developer",
                "task_name": "exploit-developer",
            },
        },
    )

    assert launcher._run_metadata_has_current_task(run) is True


def test_run_metadata_has_current_task_accepts_new_runtime_keys(monkeypatch):
    from app.services import launcher

    run = SimpleNamespace(id=1136)
    monkeypatch.setattr(
        launcher,
        "_read_run_metadata",
        lambda _run: {
            "current_agent_name": "source-analyzer",
            "current_task_name": "case-77",
        },
    )

    assert launcher._run_metadata_has_current_task(run) is True


def test_run_metadata_has_current_task_rejects_empty_runtime_keys(monkeypatch):
    from app.services import launcher

    run = SimpleNamespace(id=1137)
    monkeypatch.setattr(
        launcher,
        "_read_run_metadata",
        lambda _run: {
            "current_agent": "",
            "current_task": "",
            "current_action": {"agent_name": "", "task_name": ""},
        },
    )

    assert launcher._run_metadata_has_current_task(run) is False
