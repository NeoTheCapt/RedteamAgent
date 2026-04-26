from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FILE_UPLOAD_SKILL = REPO_ROOT / "agent" / "skills" / "file-upload-testing" / "SKILL.md"
SENSITIVE_DATA_SKILL = REPO_ROOT / "agent" / "skills" / "sensitive-data-detection" / "SKILL.md"


def test_file_upload_skill_requires_consumer_path_after_spa_fallback() -> None:
    skill = FILE_UPLOAD_SKILL.read_text(encoding="utf-8")

    assert "If direct retrieval falls back to a generic SPA/root page" in skill
    assert "Pivot once to the workflow consumer" in skill
    assert "rendered, linked, parsed, or rejected" in skill


def test_file_upload_skill_keeps_ctf_upload_recall_branches_alive() -> None:
    skill = FILE_UPLOAD_SKILL.read_text(encoding="utf-8")

    assert "canonical challenge-triggering consumer action" in skill
    assert "converts an upload finding into solved-state evidence" in skill
    assert "DONE STAGE=vuln_confirmed" in skill
    assert "REQUEUE" in skill


def test_sensitive_data_skill_sweeps_privileged_juice_shop_endpoints_after_admin_access() -> None:
    skill = SENSITIVE_DATA_SKILL.read_text(encoding="utf-8")

    assert "Authenticated Privileged Data Sweep" in skill
    assert "/rest/user/authentication-details/" in skill
    assert "/api/Users" in skill
    assert "admin/JWT exploit confirms access" in skill
    assert "requeue a narrowed follow-up" in skill
