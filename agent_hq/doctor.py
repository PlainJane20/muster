"""`agent-hq doctor` -- checks which runtimes are actually usable on this
machine, and is honest about the separate question of whether the code
for them has been verified at all (see models.RUNTIME_VERIFICATION).
Availability and verification are different facts; this reports both so
neither gets confused for the other."""

from __future__ import annotations

import shutil
import urllib.request
from typing import NamedTuple

from agent_hq.models import RUNTIME_VERIFICATION


class RuntimeStatus(NamedTuple):
    runtime: str
    available: bool
    detail: str
    verification: str


def _check_cli(binary: str) -> tuple:
    path = shutil.which(binary)
    return (True, f"found at {path}") if path else (False, f"{binary!r} not found on PATH")


def _check_http_server(base_url: str, ping_path: str) -> tuple:
    try:
        urllib.request.urlopen(f"{base_url}{ping_path}", timeout=2)
        return True, f"server responding at {base_url}"
    except Exception as e:
        return False, f"no server responding at {base_url} ({e.__class__.__name__})"


def check_all() -> list:
    checks = []

    for runtime, binary in (
        ("claude_code", "claude"), ("codex", "codex"),
        ("cursor_agent", "cursor-agent"), ("gemini_cli", "gemini"),
        ("aider", "aider"), ("opencode", "opencode"),
    ):
        available, detail = _check_cli(binary)
        checks.append(RuntimeStatus(runtime, available, detail, RUNTIME_VERIFICATION[runtime]))

    available, detail = _check_http_server("http://localhost:11434", "/api/tags")
    checks.append(RuntimeStatus("ollama", available, detail, RUNTIME_VERIFICATION["ollama"]))

    # LM Studio's OpenAI-compatible server exposes /v1/models for listing
    # loaded models -- the standard OpenAI-compatible ping endpoint.
    available, detail = _check_http_server("http://localhost:1234", "/v1/models")
    checks.append(RuntimeStatus("lm_studio", available, detail, RUNTIME_VERIFICATION["lm_studio"]))

    return checks


def format_report(checks: list) -> str:
    lines = []
    for c in checks:
        status_icon = "✅" if c.available else "⚪"
        verify_note = "verified" if c.verification == "verified" else "documented only, unverified here"
        lines.append(f"{status_icon} {c.runtime:<14} {c.detail:<45} [{verify_note}]")
    return "\n".join(lines)
