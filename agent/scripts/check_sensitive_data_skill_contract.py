#!/usr/bin/env python3
"""Regression guard for the Juice Shop sensitive-data recall contract."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "sensitive-data-detection" / "SKILL.md"
text = SKILL.read_text(encoding="utf-8")

required_phrases = [
    "Treat the named recall targets as a closure checklist",
    "challenge=<name> status=solved|blocked|requeued evidence=<path or response> next=<exact concrete action>",
    "A generic phrase such as \"ftp artifact closure\", \"metrics checked\", or \"Web3 route inspected\" is not sufficient.",
    "emit `REQUEUE` with the exact path or workflow as the next case instead of `DONE STAGE=exhausted`",
]

required_challenges = [
    "Exposed Metrics",
    "Exposed credentials",
    "NFT Takeover",
    "Forged Feedback",
    "Easter Egg",
    "Forgotten Sales Backup",
]

missing = []
for phrase in required_phrases:
    if phrase not in text:
        missing.append("phrase: " + phrase)
for challenge in required_challenges:
    if challenge not in text:
        missing.append("challenge: " + challenge)

if missing:
    print("Sensitive-data recall contract is missing required items:", file=sys.stderr)
    for item in missing:
        print("- " + item, file=sys.stderr)
    sys.exit(1)

print("sensitive-data recall contract OK")
