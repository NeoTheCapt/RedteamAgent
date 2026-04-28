import os
import shutil
import subprocess
from pathlib import Path


def test_start_metasploit_mcp_defaults_blank_env_placeholders(tmp_path: Path) -> None:
    """Blank OpenCode env placeholders must not reach the MCP server as blank creds."""

    repo_root = Path(__file__).resolve().parents[1]
    root = tmp_path / "agent"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(repo_root / "scripts" / "start_metasploit_mcp.sh", root / "scripts" / "start_metasploit_mcp.sh")

    (root / ".opencode" / "vendor" / "MetasploitMCP").mkdir(parents=True)
    (root / ".opencode" / "vendor" / "MetasploitMCP" / "MetasploitMCP.py").write_text("# stub\n")
    python_bin = root / ".opencode" / "vendor" / "metasploitmcp-venv" / "bin" / "python"
    python_bin.parent.mkdir(parents=True)
    python_bin.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"MSF_USER=$MSF_USER\" \"MSF_PASSWORD=$MSF_PASSWORD\" \"MSF_SERVER=$MSF_SERVER\" \"MSF_PORT=$MSF_PORT\" \"MSF_SSL=$MSF_SSL\" > \"$CAPTURE_ENV\"\n"
    )
    python_bin.chmod(0o755)

    runtime_check = root / "scripts" / "check_metasploit_runtime.sh"
    runtime_check.write_text("#!/usr/bin/env bash\nexit 0\n")
    runtime_check.chmod(0o755)

    capture = tmp_path / "captured.env"
    env = os.environ.copy()
    env.update(
        {
            "CAPTURE_ENV": str(capture),
            # OpenCode can expand missing {env:...} placeholders to blank strings.
            "MSF_USER": "",
            "MSF_PASSWORD": "",
            "MSF_SERVER": "",
            "MSF_PORT": "",
            "MSF_SSL": "",
        }
    )

    subprocess.run(["bash", str(root / "scripts" / "start_metasploit_mcp.sh")], env=env, check=True)

    captured = capture.read_text().splitlines()
    assert "MSF_USER=msf" in captured
    assert "MSF_PASSWORD=msf" in captured
    assert "MSF_SERVER=127.0.0.1" in captured
    assert "MSF_PORT=55553" in captured
    assert "MSF_SSL=false" in captured
