"""DOCUMENTED, NOT VERIFIED: Gemini CLI (Google).

Not installed in the environment this was developed in. Built from
https://www.geminicli.com/docs/cli/headless (fetched during development),
which itself has real gaps -- worth knowing before trusting this adapter
more than the code below actually earns:

- No documented flag for setting a working directory. This adapter falls
  back to the subprocess `cwd`, matching Claude Code's documented
  behavior, but Gemini CLI's own docs don't confirm that's correct for it.
- No documented auto-approval/"yolo" flag for unattended tool use. Because
  of that gap, this adapter only implements `read_only` (plain generation,
  no tool calls to approve) -- `standard`/`full` raise NotImplementedError
  rather than silently sending a flag that might not exist and might hang
  waiting for an approval prompt nothing here can answer.

Exit codes ARE documented (0 success, 1 general error, 42 input error,
53 turn limit exceeded) and are used as-is below.
"""

from __future__ import annotations

import json
import subprocess
from typing import Optional

from agent_hq.models import RuntimeResult, ToolAccess

_EXIT_CODE_MEANINGS = {
    1: "general error or API failure",
    42: "invalid prompt or arguments",
    53: "turn limit exceeded",
}


def run(
    prompt: str,
    cwd: Optional[str] = None,
    tool_access: ToolAccess = "read_only",
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    timeout: int = 600,
    pid_callback=None,
) -> RuntimeResult:
    if tool_access != "read_only":
        raise NotImplementedError(
            "gemini_cli only implements tool_access='read_only' -- no "
            "documented auto-approval flag exists for unattended "
            "standard/full runs. See this module's docstring."
        )

    full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
    cmd = ["gemini", "-p", full_prompt, "--output-format", "json"]
    if model:
        cmd += ["--model", model]

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
        raise TimeoutError(f"gemini exceeded {timeout}s. stderr: {stderr[:500]}")

    if process.returncode != 0:
        meaning = _EXIT_CODE_MEANINGS.get(process.returncode, "undocumented exit code")
        raise RuntimeError(f"gemini exited {process.returncode} ({meaning}). stderr: {stderr[:1000] or '(empty)'}")

    data = json.loads(stdout.strip())
    return RuntimeResult(
        is_error="error" in data,
        result_text=data.get("response", ""),
        returncode=process.returncode,
        pid=process.pid,
    )
