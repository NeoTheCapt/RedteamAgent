from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = REPO_ROOT / "agent"
RENDER_SCRIPT = AGENT_ROOT / "scripts" / "render-operator-prompts.sh"


def _render_repo(tmp_path: Path) -> None:
    subprocess.run(
        ["bash", str(RENDER_SCRIPT), "repo", str(tmp_path)],
        cwd=str(REPO_ROOT),
        check=True,
    )


def test_rendered_operator_prompts_are_committed(tmp_path: Path) -> None:
    _render_repo(tmp_path)

    expected_pairs = [
        (tmp_path / "AGENTS.md", AGENT_ROOT / "AGENTS.md"),
        (tmp_path / "CLAUDE.md", AGENT_ROOT / "CLAUDE.md"),
        (
            tmp_path / ".opencode" / "prompts" / "agents" / "operator.txt",
            AGENT_ROOT / ".opencode" / "prompts" / "agents" / "operator.txt",
        ),
    ]

    for generated_path, committed_path in expected_pairs:
        assert generated_path.read_text(encoding="utf-8") == committed_path.read_text(encoding="utf-8")


def test_rendered_operator_prompt_keeps_consume_test_serialized(tmp_path: Path) -> None:
    _render_repo(tmp_path)

    rendered = (tmp_path / ".opencode" / "prompts" / "agents" / "operator.txt").read_text(encoding="utf-8")

    assert "if `BATCH_COUNT > 0`, the very next advancing action MUST be the matching `task(...)` call" in rendered
    assert "if you are not ready to launch the matching subagent immediately, do NOT fetch yet" in rendered
    assert "NEVER combine outcome recording" in rendered
    assert "consume-test dispatch is PARALLEL" not in rendered
    assert "parallel dispatch is the default" not in rendered


def test_rendered_operator_prompt_bans_nonterminal_wrapup_turns(tmp_path: Path) -> None:
    _render_repo(tmp_path)

    rendered = (tmp_path / ".opencode" / "prompts" / "agents" / "operator.txt").read_text(encoding="utf-8")
    resume_cmd = (AGENT_ROOT / ".opencode" / "commands" / "resume.md").read_text(encoding="utf-8")

    expected_line = "If queue work still remains after any tool call, do NOT emit a wrap-up/status message; immediately make the next advancing tool call instead."

    assert expected_line in rendered
    assert expected_line in resume_cmd


def test_rendered_operator_prompt_forbids_orphaned_source_carrier_fetches(tmp_path: Path) -> None:
    _render_repo(tmp_path)

    rendered = (tmp_path / ".opencode" / "prompts" / "agents" / "operator.txt").read_text(encoding="utf-8")

    assert "source-carrier types (`data`, `unknown`, `api-spec`, `javascript`, `stylesheet`, `page`)" in rendered
    assert "a non-empty fetch for `BATCH_AGENT=source-analyzer` MUST be followed by the source-analyzer task" in rendered
    assert "A fetched `data` carrier left in `processing` is an orphaned batch and will fail the run." in rendered


def test_rendered_operator_prompt_prevents_respawn_starving_queue(tmp_path: Path) -> None:
    _render_repo(tmp_path)

    rendered = (tmp_path / ".opencode" / "prompts" / "agents" / "operator.txt").read_text(encoding="utf-8")

    assert "respawn work MUST NOT starve the case queue" in rendered
    assert "must perform a real stage fetch+task dispatch before doing another respawn-only pass" in rendered
    assert "Respawn dispatch is queue expansion, not a substitute for queue consumption." in rendered
    assert "OSINT correlation must not become a liveness loop." in rendered
