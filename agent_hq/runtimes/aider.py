"""DOCUMENTED, NOT VERIFIED: Aider (open-source terminal pair programmer).

Not installed in the environment this was developed in. Built from
https://aider.chat/docs/scripting.html (fetched during development).

Known documentation gap: exit codes aren't documented. A bigger gap,
specific to this adapter: the scripting docs describe `--message` +
`--yes` for auto-accepting edits, but don't document a distinct
"read-only, ask a question, don't edit anything" mode. `read_only` here
means "run without --yes" -- Aider's own docs don't confirm what happens
to a proposed edit when nothing can answer its confirmation prompt in a
non-interactive context, so this may not behave the way the name implies.
Treat `read_only` on this specific adapter as the least-verified setting
in the entire registry, not as a safety guarantee.
"""

from __future__ import annotations

import subprocess
from typing import List, Optional

from agent_hq.models import RuntimeResult, ToolAccess


def run(
    prompt: str,
    cwd: Optional[str] = None,
    tool_access: ToolAccess = "read_only",
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    timeout: int = 600,
    pid_callback=None,
    files: Optional[List[str]] = None,
) -> RuntimeResult:
    full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
    cmd = ["aider", "--message", full_prompt, "--no-stream"]
    if tool_access in ("standard", "full"):
        cmd.append("--yes")
    if model:
        cmd += ["--model", model]
    cmd += files or []

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
        raise TimeoutError(f"aider exceeded {timeout}s. stderr: {stderr[:500]}")

    if process.returncode != 0:
        raise RuntimeError(f"aider exited {process.returncode} (undocumented meaning). stderr: {stderr[:1000] or '(empty)'}")

    return RuntimeResult(is_error=False, result_text=stdout.strip(), returncode=process.returncode, pid=process.pid)
