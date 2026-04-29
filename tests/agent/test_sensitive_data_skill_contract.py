from pathlib import Path


SKILL = Path(__file__).resolve().parents[2] / "agent" / "skills" / "sensitive-data-detection" / "SKILL.md"


def test_peak_retention_sweep_names_lost_recall_triggers():
    text = SKILL.read_text(encoding="utf-8")

    required = [
        "peak-retention sweep",
        "Admin Section",
        "Deprecated Interface",
        "Exposed Metrics",
        "Exposed credentials",
        "User Credentials",
        "Web3 Sandbox",
        "/#/administration",
        "/ftp/package.json.bak%2500.md",
        "/metrics",
        "emit exact `REQUEUE` items",
    ]
    missing = [item for item in required if item not in text]

    assert not missing
