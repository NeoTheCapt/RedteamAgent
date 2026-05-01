from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_operator_names_exact_recall_replays_for_hash_schema_credentials():
    text = (ROOT / "agent" / "operator-core.md").read_text()
    required = [
        "A decoded JWT claim, `/rest/saveLoginIp`, or `/api/Users` roster is not enough",
        "requeue a signed-auth replay of `/rest/user/authentication-details/`",
        "if `databaseSchemaChallenge` remains false",
        "explicit `sqlite_master` payload",
        "If `/api/Users` or JWT metadata proves only emails/roles/deluxe tokens while `userCredentialsChallenge` remains false",
    ]
    for snippet in required:
        assert snippet in text


def test_sensitive_data_skill_keeps_hash_and_user_credentials_separate():
    text = (ROOT / "agent" / "skills" / "sensitive-data-detection" / "SKILL.md").read_text()
    required = [
        "Password Hash Leak and User Credentials are separate Juice Shop recall closures",
        "`passwordHashLeakChallenge` is still false",
        "signed-auth `/rest/user/authentication-details/` replay",
        "`userCredentialsChallenge` remains false",
        "do not retire it as duplicate sensitive-data evidence",
    ]
    for snippet in required:
        assert snippet in text


def test_sqli_skill_requires_schema_and_credential_solved_checks():
    text = (ROOT / "agent" / "skills" / "sqli-testing" / "SKILL.md").read_text()
    required = [
        "### Juice Shop recall closure",
        "generic SQLi proof or admin roster access is not enough",
        "`databaseSchemaChallenge` remains false",
        "`sqlite_master` extraction payload",
        "`userCredentialsChallenge` remains false after `/api/Users` or JWT metadata",
        "challenge=<Database Schema|User Credentials> status=solved|requeued",
    ]
    for snippet in required:
        assert snippet in text
