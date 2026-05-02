from app.services import launcher


def test_recall_blocker_ledger_is_completed_with_blockers(monkeypatch):
    reason = (
        "Active queue remains drained and coverage checks pass, but fresh recall blocker ledger still "
        "leaves unresolved peak challenges: Password Hash Leak, Bjoern's Favorite Pet, Database Schema, "
        "User Credentials, and Missing Encoding."
    )
    monkeypatch.setattr(launcher, "normalize_active_scope", lambda run: None)
    monkeypatch.setattr(launcher, "engagement_completion_state", lambda run: (False, reason))
    monkeypatch.setattr(launcher, "_init_only_exit", lambda run: False)

    succeeded, reason_code, reason_text, summary = launcher._terminal_reason_from_artifacts(object())

    assert succeeded is True
    assert reason_code == "completed_with_blockers"
    assert reason_text == reason
    assert summary == "Runtime finished with an explicit bounded blocker ledger."
