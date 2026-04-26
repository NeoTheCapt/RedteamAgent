#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

python3 - <<'PY' "$ROOT"
import importlib.util
import pathlib
import tempfile
import sys

root = pathlib.Path(sys.argv[1])
module_path = root / 'agent' / 'scripts' / 'browser_flow.py'
spec = importlib.util.spec_from_file_location('browser_flow', module_path)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

class DummyClient:
    def __init__(self):
        self.execute_calls = []

    def execute(self, script, args):
        self.execute_calls.append((script, args))
        return {
            'ok': True,
            'dismissed': [
                {'kind': 'button', 'label': 'Dismiss cookie message'},
                {'kind': 'backdrop', 'label': 'welcome overlay backdrop'},
            ],
        }

with tempfile.TemporaryDirectory() as tmp:
    flow = module.BrowserFlow(DummyClient(), pathlib.Path(tmp))
    recorded = []
    flow.record = lambda action, **kwargs: recorded.append({'action': action, **kwargs})
    flow.call_with_alert_recovery = lambda fn, source_action='': fn()

    flow.dismiss_common_overlays(5000, source_action='post_navigate')

    assert flow.client.execute_calls, 'expected dismiss_common_overlays to execute JS in page context'
    dismiss_script = flow.client.execute_calls[0][0]
    assert 'backdrop' in dismiss_script.lower(), dismiss_script
    assert 'cookie' in dismiss_script.lower() or 'welcome' in dismiss_script.lower(), dismiss_script
    assert recorded[0]['action'] == 'dismiss_common_overlays', recorded
    assert recorded[0]['dismissed_count'] == 2, recorded
    assert 'Dismiss cookie message' in recorded[0]['dismissed_labels'], recorded

with tempfile.TemporaryDirectory() as tmp:
    flow = module.BrowserFlow(DummyClient(), pathlib.Path(tmp))
    calls = []
    flow.dismiss_common_overlays = lambda timeout_ms, source_action='': calls.append(('dismiss', timeout_ms, source_action))
    flow.click = lambda selector, timeout_ms: calls.append(('click', selector, timeout_ms))

    flow.execute_step({'action': 'click', 'selector': '#launch', 'timeout_ms': 1200})

    assert calls == [
        ('dismiss', 1200, 'click'),
        ('click', '#launch', 1200),
    ], calls

print('ok')
PY
