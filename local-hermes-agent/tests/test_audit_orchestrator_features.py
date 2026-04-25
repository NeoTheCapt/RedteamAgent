from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_orchestrator_features.py"
SPEC = importlib.util.spec_from_file_location("audit_orchestrator_features", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_extract_token_from_scheduler_env_supports_plain_and_quoted_tokens() -> None:
    text = """
# comment
ORCH_TOKEN='plain-token'
PROJECT_ID=19
"""
    assert MODULE.extract_token_from_scheduler_env(text) == "plain-token"


def test_extract_token_from_scheduler_env_ignores_redacted_placeholders() -> None:
    text = "ORCH_TOKEN=***\nPROJECT_ID=19\n"
    assert MODULE.extract_token_from_scheduler_env(text) == ""


def test_build_temp_project_name_uses_prefix_and_cycle_id() -> None:
    name = MODULE.build_temp_project_name("20260422T032640Z", suffix="20260422040000")
    assert name == "__audit-features-test__-20260422t032640z-20260422040000"
    assert MODULE.is_audit_temp_project(name)
    assert MODULE.is_audit_temp_project("__audit-features-test__")
    assert not MODULE.is_audit_temp_project("customer-project")
