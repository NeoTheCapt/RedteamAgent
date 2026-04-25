#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

python3 - <<'PY' "$ROOT"
import importlib.util
import json
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
        selector = args[0]
        if 'option not found' in script:
            if selector == '#security':
                if args[1] == 'city':
                    return {
                        'ok': True,
                        'requested_value': 'city',
                        'requested_text': '',
                        'requested_index': '',
                        'effective_index': '2',
                        'effective_value': 'city',
                        'effective_text': 'City you were born in?',
                        'option_count': 3,
                        'mode': 'value',
                    }
                return {
                    'ok': True,
                    'requested_value': '',
                    'requested_text': "Mother's maiden name?",
                    'requested_index': '',
                    'effective_index': '1',
                    'effective_value': 'maiden',
                    'effective_text': "Mother's maiden name?",
                    'option_count': 3,
                    'mode': 'text',
                }
        raise AssertionError(f'unexpected execute call: selector={selector!r}')

with tempfile.TemporaryDirectory() as tmp:
    flow = module.BrowserFlow(DummyClient(), pathlib.Path(tmp))
    waited = []
    recorded = []
    lookups = []

    def fake_wait_for_js_result(script, timeout_ms, reason, args, predicate):
        lookups.append((script, timeout_ms, reason, args))
        payload = {'ok': True, 'selector': '#security'}
        assert predicate(payload)
        return payload

    def fake_wait_for_selector(selector, timeout_ms):
        waited.append((selector, timeout_ms))

    def fake_record(action, **kwargs):
        recorded.append({'action': action, **kwargs})

    flow.wait_for_js_result = fake_wait_for_js_result
    flow.wait_for_selector = fake_wait_for_selector
    flow.record = fake_record
    flow.call_with_alert_recovery = lambda fn, source_action='': fn()
    flow.dismiss_common_overlays = lambda timeout_ms, source_action='': None

    flow.select_by_label('Security Question', 5000, text="Mother's maiden name?")
    flow.select_option('#security', 5000, value='city', action='select')
    flow.execute_step({'action': 'select_by_label', 'label': 'Security Question', 'text': "Mother's maiden name?", 'timeout_ms': 5000})
    flow.execute_step({'action': 'select', 'selector': '#security', 'value': 'city', 'timeout_ms': 5000})

    assert lookups, 'expected label lookup'
    lookup_script = lookups[0][0]
    assert 'fieldSelector' in lookup_script, lookup_script
    assert waited.count(('#security', 5000)) == 4, waited

    first = recorded[0]
    assert first['action'] == 'select_by_label', first
    assert first['label'] == 'Security Question', first
    assert first['matched_selector'] == '#security', first
    assert first['effective_value'] == 'maiden', first
    assert first['effective_text'] == "Mother's maiden name?", first

    second = recorded[1]
    assert second['action'] == 'select', second
    assert second['effective_value'] == 'city', second
    assert second['effective_text'] == 'City you were born in?', second

    assert any(item['action'] == 'select_by_label' for item in recorded[2:]), recorded
    assert any(item['action'] == 'select' for item in recorded[2:]), recorded

print('ok')
PY
