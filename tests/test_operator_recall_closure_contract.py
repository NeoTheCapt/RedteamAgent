from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_RECALL_CONTRACTS = [
    'DOM XSS',
    'canonical Juice Shop hash route payload',
    'Exposed Metrics',
    'fetch `/metrics` as a standalone recall branch',
    'Exposed credentials',
    'solved-check the exact `Exposed credentials` challenge separately',
    "Bjoern's Favorite Pet",
    "Reset Bjoern's Password",
    'Bjoern-specific recovery/reset follow-up',
    'final-report blocker ledger',
    'completed-with-blockers',
    'Auth-respawn dispatch is atomic',
    'AUTH_RESPAWN_REQUIRED flag set true',
    'A standalone progress sentence such as "Launching auth-context recon" after the flag is a queue-stall bug',
]


def test_operator_core_names_regressed_peak_recall_branches():
    text = (ROOT / 'agent' / 'operator-core.md').read_text()
    for contract in REQUIRED_RECALL_CONTRACTS:
        assert contract in text


def test_rendered_operator_prompts_include_regressed_peak_recall_branches():
    rendered_paths = [
        ROOT / 'agent' / 'AGENTS.md',
        ROOT / 'agent' / 'CLAUDE.md',
        ROOT / 'agent' / '.opencode' / 'prompts' / 'agents' / 'operator.txt',
    ]
    for path in rendered_paths:
        text = path.read_text()
        for contract in REQUIRED_RECALL_CONTRACTS:
            assert contract in text, f'{contract!r} missing from {path}'
