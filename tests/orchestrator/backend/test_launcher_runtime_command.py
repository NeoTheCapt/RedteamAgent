from types import SimpleNamespace


class DummyRun(SimpleNamespace):
    pass


def test_runtime_command_uses_engage_auto_directly_for_initial_launch():
    from app.services.launcher import _runtime_command_text

    run = DummyRun(target="https://init-only.example")

    command = _runtime_command_text(run)

    assert command == "/engage --auto https://init-only.example"
    assert not command.startswith("/autoengage")


def test_runtime_process_detector_accepts_engage_auto_command():
    from app.services.launcher import _looks_like_runtime_process

    assert _looks_like_runtime_process(
        "opencode run --format json /engage --auto https://init-only.example",
        container_name=None,
    )
    assert not _looks_like_runtime_process(
        "opencode run --format json /autoengage https://init-only.example",
        container_name=None,
    )
