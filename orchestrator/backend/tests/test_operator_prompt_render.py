from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = REPO_ROOT / "agent"
RENDER_SCRIPT = AGENT_ROOT / "scripts" / "render-operator-prompts.sh"


def test_rendered_operator_prompts_are_committed(tmp_path: Path) -> None:
    subprocess.run(
        ["bash", str(RENDER_SCRIPT), "repo", str(tmp_path)],
        cwd=str(REPO_ROOT),
        check=True,
    )

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
