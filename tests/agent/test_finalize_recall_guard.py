import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CHECKLIST = [
    "Admin Registration",
    "Admin Section",
    "NFT Takeover",
    "Web3 Sandbox",
    "Confidential Document",
    "DOM XSS",
    "Database Schema",
    "Deprecated Interface",
    "Error Handling",
    "Five-Star Feedback",
    "Forged Feedback",
    "Forgotten Developer Backup",
    "Login Admin",
    "Password Strength",
    "Score Board",
    "Security Policy",
    "Upload Type",
    "User Credentials",
    "Zero Stars",
    "Exposed Metrics",
    "Poison Null Byte",
    "Exposed credentials",
    "Missing Encoding",
    "Password Hash Leak",
]


class ChallengeHandler(BaseHTTPRequestHandler):
    solved = True

    def log_message(self, *args):
        return

    def do_GET(self):
        if self.path != "/api/Challenges":
            self.send_response(404)
            self.end_headers()
            return
        data = []
        for name in CHECKLIST:
            solved = self.solved and name != "Missing Encoding"
            data.append({"name": name, "solved": solved})
        payload = json.dumps({"data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def run_server():
    server = HTTPServer(("127.0.0.1", 0), ChallengeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def make_engagement(tmp_path, port):
    eng = tmp_path / "engagement"
    eng.mkdir()
    (eng / "scope.json").write_text(
        json.dumps({"target": f"http://127.0.0.1:{port}", "status": "in_progress", "current_phase": "report"})
    )
    (eng / "log.md").write_text("# log\n- **Status**: In Progress\n")
    (eng / "report.md").write_text("**Date**: today — In Progress\n**Status**: In Progress\n")
    return eng


def test_finalize_blocks_local_juice_shop_when_recall_checklist_unsolved(tmp_path):
    server = run_server()
    try:
        eng = make_engagement(tmp_path, server.server_port)
        result = subprocess.run(
            ["bash", str(ROOT / "agent/scripts/finalize_engagement.sh"), str(eng)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "REDTEAM_RECALL_FINALIZE_GUARD_PORTS": str(server.server_port)},
        )
    finally:
        server.shutdown()

    assert result.returncode == 2
    assert "Missing Encoding" in result.stderr
    scope = json.loads((eng / "scope.json").read_text())
    assert scope["status"] == "in_progress"
    assert "CTF recall finalize guard blocked completion" in (eng / "log.md").read_text()


def test_finalize_skip_env_preserves_legacy_completion_path(tmp_path):
    server = run_server()
    try:
        eng = make_engagement(tmp_path, server.server_port)
        result = subprocess.run(
            ["bash", str(ROOT / "agent/scripts/finalize_engagement.sh"), str(eng)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "REDTEAM_SKIP_RECALL_FINALIZE_GUARD": "1"},
        )
    finally:
        server.shutdown()

    assert result.returncode == 0, result.stderr
    scope = json.loads((eng / "scope.json").read_text())
    assert scope["status"] == "complete"
    assert scope["current_phase"] == "complete"
