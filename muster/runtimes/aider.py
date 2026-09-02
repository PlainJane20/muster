"""VERIFIED runtime: Aider (open-source terminal pair programmer).

Verified live against a real Aider install (pip install aider-chat,
v0.82.3) pointed at a real local Ollama model (llama3.2:1b) -- not just
checked against --help, and not stopping at the first thing that looked
like a bug without re-testing it.

One real finding from that live testing, confirmed and fixed:
**Aider's repo-map feature caused an 8+ minute hang with zero output**
against this small local model, inside a real git repo, with no error and
no timeout. Confirmed by watching the process the whole time (alive,
~5 seconds of actual CPU time over 8 minutes -- waiting, not crunching)
while a parallel direct call to the same Ollama model also stalled,
consistent with Ollama serializing requests to one model. `--map-tokens 0`
disables just the repo-map step, not git integration generally, and the
same command then completed correctly in seconds: "Git repo: .git with 1
files / Repo-map: disabled / hello world / Tokens: 633 sent, 3 received."
This adapter passes `--map-tokens 0` unconditionally -- a feature that can
silently multiply a dispatch's latency by 10x+ against a small local
model, with no visible progress and no error, is a worse default for an
unattended tool than losing what that feature would have added.

One thing that looked like a bug during development and turned out not to
be, worth recording so it isn't "found" again: `--yes` isn't in `--help`'s
output (only `--yes-always` is), which looked like a wrong flag name. A
live test proved otherwise -- argparse's default unambiguous-prefix
matching resolves `--yes` to `--yes-always` correctly (confirmed with a
real file edit that applied and committed without hanging on
confirmation). This adapter uses the full `--yes-always` name anyway,
since that's what a reader checking this against `--help` would expect,
but the abbreviated form was never actually broken.

Separately, and more important than it sounds: **a reported success does
not guarantee a persisted change.** A live edit dispatch through the full
muster pipeline (real ticket, real worktree, tool_access=standard)
printed "Applied edit to README.md" and returned exit code 0 -- but
checking `git log` in that worktree afterward showed no new commit at
all. The small local model's response mixed real content with echoed
formatting instructions, aider's parser apparently couldn't cleanly
reconcile that into an actual file change, and *silently reported success
anyway*. This means: for a `standard`/`full` dispatch, exit 0 and
"succeeded" in a DispatchAttempt record mean "aider ran and didn't error"
-- not "a file was actually changed." Verifying that a dispatch produced
the change it claims to have made means checking the worktree yourself
(`git log`, `git diff`) before trusting the attempt record's status,
not a limitation this adapter can paper over from the outside.
"""

from __future__ import annotations

import subprocess
from typing import List, Optional

from muster.models import RuntimeResult, ToolAccess


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
    cmd = ["aider", "--message", full_prompt, "--no-stream", "--map-tokens", "0", "--no-check-update"]
    if tool_access in ("standard", "full"):
        cmd.append("--yes-always")
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
