"""VERIFIED runtime: `claude -p`, Anthropic's Claude Code CLI.

Every flag below was checked against `claude --help` on the actual
installed CLI (v2.1.239) before being written here, and the JSON response
shape was taken from one real `claude -p ... --output-format json`
invocation, not assumed. See ARCHITECTURE.md for the exact commands run
to verify this.

Deliberately does not use --bare: it restricts auth to
ANTHROPIC_API_KEY/apiKeyHelper only, and fails outright on a machine
where managed/enterprise settings pin first-party OAuth login -- a real
finding from developing this, not a guess. Deliberately does not use
--dangerously-skip-permissions: --permission-mode plus an explicit
--allowedTools allowlist is the scoped equivalent for an unattended agent.
"""

from __future__ import annotations

import json
import subprocess
from typing import List, Optional

from agent_hq.models import RuntimeResult, ToolAccess

_TOOL_ACCESS_TO_TOOLS = {
    "read_only": ["Read", "Grep", "Glob"],
    "standard": ["Read", "Grep", "Glob", "Edit", "Write"],
    "full": ["Read", "Grep", "Glob", "Edit", "Write", "Bash"],
}
_TOOL_ACCESS_TO_PERMISSION_MODE = {
    "read_only": "dontAsk",
    "standard": "acceptEdits",
    "full": "acceptEdits",
}


def _parse_result_json(stdout: str) -> dict:
    stdout = stdout.strip()
    if not stdout:
        raise ValueError("claude -p produced no stdout at all")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        last_line = stdout.splitlines()[-1]
        try:
            return json.loads(last_line)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"could not parse claude -p output as JSON. Raw stdout:\n{stdout[:500]}"
            ) from e


def run(
    prompt: str,
    cwd: Optional[str] = None,
    tool_access: ToolAccess = "read_only",
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    timeout: int = 600,
    pid_callback=None,
) -> RuntimeResult:
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--permission-mode", _TOOL_ACCESS_TO_PERMISSION_MODE[tool_access],
        "--allowedTools", ",".join(_TOOL_ACCESS_TO_TOOLS[tool_access]),
    ]
    if model:
        cmd += ["--model", model]
    if system_prompt:
        cmd += ["--append-system-prompt", system_prompt]

    process = subprocess.Popen(
        cmd, cwd=cwd, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if pid_callback:
        pid_callback(process.pid)

    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        raise TimeoutError(f"claude -p exceeded {timeout}s. stderr: {stderr[:500]}")

    if process.returncode != 0:
        raise RuntimeError(f"claude -p exited {process.returncode}. stderr: {stderr[:1000] or '(empty)'}")

    data = _parse_result_json(stdout)
    return RuntimeResult(
        is_error=data.get("is_error", False),
        result_text=data.get("result", ""),
        session_id=data.get("session_id"),
        cost_usd=data.get("total_cost_usd"),
        returncode=process.returncode,
        pid=process.pid,
    )
