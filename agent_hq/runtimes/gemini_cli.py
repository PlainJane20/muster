"""DOCUMENTED, PARTIALLY VERIFIED: Gemini CLI (Google).

Installed for real (`npm install -g @google/gemini-cli`, v0.57.0) and its
real CLI behavior checked against `--help` and actual invocations -- but
never completed an authenticated dispatch (no Google account/API key
available in this environment), so the *success* response shape below is
still the original documented assumption, not a confirmed one. Everything
else in this docstring is checked, not guessed.

Three real corrections to the original documented-only version of this
adapter, found only by actually installing and running it:

1. **A working-directory flag and an auto-approval flag both exist.** The
   original version of this adapter, built from a web-fetched summary of
   Gemini CLI's docs, claimed neither was documented and refused
   `standard`/`full` tool_access as a result. The real `--help` shows
   `--approval-mode {default,auto_edit,yolo,plan}` (an auto-approval
   mechanism) and `--include-directories` (adds directories to the
   workspace, the same "doesn't change primary cwd" shape as Claude
   Code's `--add-dir`). The secondary source that produced the original
   docstring was itself incomplete -- a reminder that "documented" is
   only as good as the documentation actually consulted.
2. **`--approval-mode` silently downgrades to `default` in an untrusted
   directory.** Running `--approval-mode auto_edit` in a fresh directory
   printed "Approval mode overridden to 'default' because the current
   folder is not trusted" and proceeded as if no approval mode had been
   set at all -- exactly the kind of silent-fallback failure mode this
   whole registry has been built to catch. `--skip-trust` must be passed
   alongside any non-default approval mode, or the flag does nothing.
3. **The exit code IS the JSON error's `code` field, not a fixed small
   enum.** A real unauthenticated run returned exit code 41 with a JSON
   body `{"error": {"code": 41, ...}}` -- confirming the two travel
   together, but also disproving the original documented exit-code table
   (0/1/42/53) as exhaustive. This adapter parses the JSON body for the
   real error message on any non-zero exit rather than trusting a fixed
   code-to-meaning lookup.

`full` maps to `--approval-mode yolo` (Google's own name for
"auto-approve everything") rather than a safer default, on the same basis
`full` means broad capability elsewhere in this registry (Codex's
`danger-full-access` sandbox, Claude Code's full tool allowlist) -- a
scoped capability grant, not a request to disable every safety check
categorically the way `--dangerously-skip-permissions` would.
"""

from __future__ import annotations

import json
import subprocess
from typing import Optional

from agent_hq.models import RuntimeResult, ToolAccess

_TOOL_ACCESS_TO_APPROVAL_MODE = {
    "read_only": None,
    "standard": "auto_edit",
    "full": "yolo",
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
    cmd = ["gemini", "-p", full_prompt, "--output-format", "json"]
    approval_mode = _TOOL_ACCESS_TO_APPROVAL_MODE[tool_access]
    if approval_mode:
        cmd += ["--approval-mode", approval_mode, "--skip-trust"]
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

    try:
        data = json.loads(stdout.strip())
    except json.JSONDecodeError:
        if process.returncode != 0:
            raise RuntimeError(f"gemini exited {process.returncode}. stderr: {stderr[:1000] or '(empty)'}")
        raise ValueError(f"could not parse gemini output as JSON. Raw stdout:\n{stdout[:500]}")

    if "error" in data:
        error = data["error"]
        raise RuntimeError(f"gemini reported an error (code {error.get('code')}): {error.get('message')}")

    return RuntimeResult(
        is_error=False,
        result_text=data.get("response", ""),
        returncode=process.returncode,
        pid=process.pid,
    )
