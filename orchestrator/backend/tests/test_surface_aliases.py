from app.services.launcher import _normalize_surface_type


def test_normalize_surface_type_accepts_runtime_aliases():
    assert _normalize_surface_type("auth_surface") == "auth_entry"
    assert _normalize_surface_type("anti_automation") == "auth_entry"
    assert _normalize_surface_type("broken_anti_automation") == "auth_entry"
    assert _normalize_surface_type("update_distribution") == "file_handling"
    assert _normalize_surface_type("cors_surface") == "cors_review"
    assert _normalize_surface_type("opaque_post_contract") == "api_param_followup"
    assert _normalize_surface_type("body_contract") == "api_param_followup"
