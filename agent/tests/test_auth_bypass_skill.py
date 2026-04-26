from pathlib import Path


def test_auth_bypass_skill_preserves_juice_shop_recovery_regression_guidance():
    skill = Path(__file__).resolve().parents[1] / "skills" / "auth-bypass" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")

    required_fragments = [
        "/rest/user/security-question",
        "/rest/user/reset-password",
        "admin@juice-sh.op",
        "bjoern@owasp.org",
        "REQUEUE_CANDIDATE",
        "exact endpoints/artifacts already checked",
    ]
    for fragment in required_fragments:
        assert fragment in text
