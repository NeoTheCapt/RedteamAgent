import types
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_context.sh"


def _load_guard_function():
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("def has_solved_challenge_evidence")
    end = text.index("\ndef build_summary", start)
    namespace = {"Path": Path}
    exec(text[start:end], namespace)
    return namespace["has_solved_challenge_evidence"]


def test_zero_solved_score_guard_detects_completed_run_solved_evidence(tmp_path):
    guard = _load_guard_function()
    engagement = tmp_path / "engagement"
    engagement.mkdir()
    (engagement / "log.md").write_text(
        "**Result**: /#/score-board visit flipped Score Board solved=true; "
        "Five-Star Feedback challenge solved.\n",
        encoding="utf-8",
    )

    assert guard(engagement) is True


def test_zero_solved_score_guard_ignores_logs_without_solved_evidence(tmp_path):
    guard = _load_guard_function()
    engagement = tmp_path / "engagement"
    engagement.mkdir()
    (engagement / "log.md").write_text(
        "**Result**: recon completed, no challenge state observed.\n",
        encoding="utf-8",
    )

    assert guard(engagement) is False


def test_build_context_withholds_false_zero_score_instead_of_reporting_scored():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "live /api/Challenges reported 0 solved" in text
    assert "score withheld as likely post-run target reset" in text
    assert "if items and not solved and has_solved_challenge_evidence" in text
