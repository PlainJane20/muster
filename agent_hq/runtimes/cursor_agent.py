"""DOCUMENTED, NOT VERIFIED: cursor-agent (Cursor's CLI).

cursor-agent isn't installed in the environment this was developed in, so
nothing in this file has been run for real -- everything here comes from
https://cursor.com/docs/cli/reference/parameters (fetched during
development). If you have cursor-agent installed, the flags below should
be correct, but treat the first real run as the actual verification this
adapter hasn't had yet.

Known documentation gap: exit code and failure-output shape aren't
specified on the reference page. `run()` below treats any non-zero exit
as a RuntimeError with whatever stderr it gets -- reasonable, but
untested against a real failure.
"""

from __future__ import annotations

import json
import subprocess
from typing import Optional

from agent_hq.models import RuntimeResult, ToolAccess

# --trust: "Trust the workspace without prompting (headless mode only)" --
# the documented mechanism for running unattended at all. -f/--force
# ("force allow commands unless explicitly denied") is Cursor's rough
# equivalent of a broader-access mode; full is intentionally NOT mapped
# to --yolo (documented as the same as -f, just named more aggressively) --
# same principle as never using claude's --dangerously-skip-permissions.
_TOOL_ACCESS_TO_FLAGS = {
    "read_only": [],
    "standard": ["--force"],
    "full": ["--force"],
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
    full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
    cmd = ["cursor-agent", "--print", "--output-format", "json", "--trust"]
    cmd += _TOOL_ACCESS_TO_FLAGS[tool_access]
    if cwd:
        cmd += ["--workspace", cwd]
    if model:
        cmd += ["--model", model]
    cmd.append(full_prompt)

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
        raise TimeoutError(f"cursor-agent exceeded {timeout}s. stderr: {stderr[:500]}")

    if process.returncode != 0:
        raise RuntimeError(f"cursor-agent exited {process.returncode}. stderr: {stderr[:1000] or '(empty)'}")

    try:
        data = json.loads(stdout.strip())
        result_text = data.get("result") or data.get("response") or stdout.strip()
    except json.JSONDecodeError:
        # Undocumented failure mode -- fall back to raw stdout rather than crash.
        result_text = stdout.strip()

    return RuntimeResult(is_error=False, result_text=result_text, returncode=process.returncode, pid=process.pid)
