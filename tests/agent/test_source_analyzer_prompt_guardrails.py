from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ANALYZER_PROMPT = (
    REPO_ROOT / "agent" / ".opencode" / "prompts" / "agents" / "source-analyzer.txt"
)


def test_source_analyzer_avoids_approval_gated_external_directory_globs() -> None:
    prompt = SOURCE_ANALYZER_PROMPT.read_text(encoding="utf-8")

    assert "Do not inspect, grep, glob, or enumerate broad filesystem roots" in prompt
    assert "approval-gated external directories" in prompt
    assert "avoid recursive catch-all patterns like `$DIR/scans/**/*`" in prompt
    assert "record `REQUEUE` or a bounded follow-up instead of asking" in prompt
