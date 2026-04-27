from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FILE_UPLOAD_SKILL = REPO_ROOT / "agent" / "skills" / "file-upload-testing" / "SKILL.md"
SENSITIVE_DATA_SKILL = REPO_ROOT / "agent" / "skills" / "sensitive-data-detection" / "SKILL.md"
SOURCE_ANALYSIS_SKILL = REPO_ROOT / "agent" / "skills" / "source-analysis" / "SKILL.md"
XSS_SKILL = REPO_ROOT / "agent" / "skills" / "xss-testing" / "SKILL.md"
BUSINESS_LOGIC_SKILL = REPO_ROOT / "agent" / "skills" / "business-logic-testing" / "SKILL.md"
XXE_SKILL = REPO_ROOT / "agent" / "skills" / "xxe-testing" / "SKILL.md"
OPERATOR_CORE = REPO_ROOT / "agent" / "operator-core.md"


def test_file_upload_skill_requires_consumer_path_after_spa_fallback() -> None:
    skill = FILE_UPLOAD_SKILL.read_text(encoding="utf-8")

    assert "If direct retrieval falls back to a generic SPA/root page" in skill
    assert "Pivot once to the workflow consumer" in skill
    assert "rendered, linked, parsed, or rejected" in skill


def test_file_upload_skill_keeps_ctf_upload_recall_branches_alive() -> None:
    skill = FILE_UPLOAD_SKILL.read_text(encoding="utf-8")

    assert "canonical challenge-triggering consumer action" in skill
    assert "converts an upload finding into solved-state evidence" in skill
    assert "Upload Type" in skill
    assert "non-PDF/non-ZIP payload" in skill
    assert "uploaded filename" in skill
    assert "DONE STAGE=vuln_confirmed" in skill
    assert "REQUEUE" in skill


def test_source_analysis_preserves_ctf_scoreboard_routes_for_browser_flow() -> None:
    skill = SOURCE_ANALYSIS_SKILL.read_text(encoding="utf-8")

    assert "challenge-tracker routes" in skill
    assert "`/#/score-board`" in skill
    assert "dynamic_render" in skill
    assert "bounded browser-flow visit" in skill


def test_sensitive_data_skill_sweeps_privileged_juice_shop_endpoints_after_admin_access() -> None:
    skill = SENSITIVE_DATA_SKILL.read_text(encoding="utf-8")

    assert "Authenticated Privileged Data Sweep" in skill
    assert "/rest/user/authentication-details/" in skill
    assert "/api/Users" in skill
    assert "admin/JWT exploit confirms access" in skill
    assert "User Credentials" in skill
    assert "credential-bearing material" in skill
    assert "password hashes" in skill
    assert "requeue a narrowed follow-up" in skill


def test_sensitive_data_skill_runs_ctf_ftp_artifact_recall_sweep() -> None:
    skill = SENSITIVE_DATA_SKILL.read_text(encoding="utf-8")

    assert "CTF / Juice Shop Recall Sweep" in skill
    assert "`acquisitions.md`" in skill
    assert "`package.json.bak`" in skill
    assert "Password Hash Leak" in skill
    assert "check challenge solved-state evidence" in skill
    assert "requeue the exact blocked path" in skill


def test_xss_skill_requires_juice_shop_browser_flow_recall_contract() -> None:
    skill = XSS_SKILL.read_text(encoding="utf-8")

    assert "CTF / Juice Shop recall contract" in skill
    assert "do not close XSS-capable surfaces with API-only probes" in skill
    assert "/#/search?q=<iframe" in skill
    assert "/rest/products/search" in skill
    assert "Zero Stars feedback" in skill
    assert "return `REQUEUE` with a concrete `dynamic_render` or `form` follow-up" in skill


def test_business_logic_skill_preserves_regressed_juice_shop_logic_recall() -> None:
    skill = BUSINESS_LOGIC_SKILL.read_text(encoding="utf-8")

    assert "CTF / Juice Shop Recall Contract" in skill
    assert "Five-Star Feedback" in skill
    assert "Forged Feedback" in skill
    assert "Password Strength" in skill
    assert "Database Schema" in skill
    assert "POST /api/Feedbacks/" in skill
    assert "sqlite_master" in skill
    assert "emit `REQUEUE` with a concrete" in skill
    assert "A functionally successful request is not enough for CTF recall closure" in skill
    assert "technical evidence remains" in skill
    assert "admin123" in skill
    assert "challenge-specific" in skill
    assert "schema-extraction payload" in skill


def test_operator_core_blocks_final_report_until_ctf_recall_closure() -> None:
    core = OPERATOR_CORE.read_text(encoding="utf-8")

    assert "CTF recall closure gate" in core
    assert "do NOT proceed to `report-writer`" in core
    assert "exploit-developer` closure batch" in core
    for challenge in [
        "Score Board",
        "Security Policy",
        "Confidential Document",
        "Five-Star Feedback",
        "Password Strength",
        "Database Schema",
        "Upload Type",
        "User Credentials",
    ]:
        assert challenge in core
    assert "low-friction recall branch" in core
    assert "canonical public document paths" in core
    assert "CTF recall closure is satisfied" in core
    assert "recent peak/baseline" in core
    assert "must return either solved-state evidence or `REQUEUE`" in core
    assert "not a concrete blocker" in core
    assert "or concrete blockers are logged" not in core


def test_xxe_skill_preserves_juice_shop_xxe_data_access_recall() -> None:
    skill = XXE_SKILL.read_text(encoding="utf-8")

    assert "CTF / Juice Shop Recall Contract" in skill
    assert "Content-Type: application/xml" in skill
    assert "SVG/XML payload" in skill
    assert "XXE Data Access" in skill
    assert "return `REQUEUE` with the exact XML-capable endpoint" in skill
