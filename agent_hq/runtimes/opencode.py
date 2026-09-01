"""DOCUMENTED, NOT VERIFIED: OpenCode (open-source, model-agnostic CLI harness).

Not installed in the environment this was developed in. Built from
https://opencode.ai/docs/cli/ (fetched during development).

Known documentation gap: exit codes aren't documented, same as several
other adapters here. `--format json` is documented as "raw JSON events"
(plural) rather than one clean response object like Claude Code's --
this reads as streaming/event-based output, not a single JSON blob. This
adapter parses defensively: try one JSON object first, then newline-
delimited JSON events (accumulating any text-bearing fields found), then
fall back to raw stdout. That fallback chain is a guess at the actual
shape, not a confirmed one -- the least-confident parser in this
registry, and it says so here rather than presenting mocked-test coverage
as equivalent to a real one.
"""

from __future__ import annotations

import json
import subprocess
from typing import Optional

from agent_hq.models import RuntimeResult, ToolAccess


def _best_effort_parse(stdout: str) -> str:
    stdout = stdout.strip()
    if not stdout:
        return ""
    try:
        data = json.loads(stdout)
        return data.get("text") or data.get("result") or data.get("content") or stdout
    except json.JSONDecodeError:
        pass
    texts = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
            text = event.get("text") or event.get("content")
            if text:
                texts.append(text)
        except json.JSONDecodeError:
            continue
    return "".join(texts) if texts else stdout


def run(
    prompt: str,
    cwd: Optional[str] = None,
    tool_access: ToolAccess = "read_only",
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    timeout: int = 600,
    pid_callback=None,
) -> RuntimeResult:
    full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
    cmd = ["opencode", "run", full_prompt, "--format", "json"]
    if cwd:
        cmd += ["--dir", cwd]
    if model:
        cmd += ["--model", model]
    if tool_access in ("standard", "full"):
        cmd.append("--auto")

    process = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if pid_callback:
        pid_callback(process.pid)

    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        raise TimeoutError(f"opencode exceeded {timeout}s. stderr: {stderr[:500]}")

    if process.returncode != 0:
        raise RuntimeError(f"opencode exited {process.returncode} (undocumented meaning). stderr: {stderr[:1000] or '(empty)'}")

    return RuntimeResult(is_error=False, result_text=_best_effort_parse(stdout), returncode=process.returncode, pid=process.pid)
