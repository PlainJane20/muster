"""VERIFIED runtime: `codex exec`, OpenAI's Codex CLI.

Flags checked against `codex exec --help` on the actual installed CLI
(codex-cli 0.146.0) before being written here. `read_only` tool_access was
proven with a real invocation:

    codex exec -s read-only --skip-git-repo-check \\
        -o /tmp/out.txt "Reply with exactly the two words: hello world"
    # exit 0, /tmp/out.txt contained exactly: hello world

`--output-last-message <file>` is used instead of parsing stdout: a real
run's stdout is full of banner/progress text (model, workdir, token
counts) ahead of the actual answer, but the file argument gets written
with just the final message, cleanly.

One real finding from that same test run, worth knowing before trusting
`standard`/`full` tool_access: this machine's Codex install has
`approval_policy` pinned by enterprise-managed settings (a warning fired
when `-c approval_policy=never` was implicitly attempted), falling back to
`UnlessTrusted`. That means a dispatch that actually needs to edit files
or run shell commands may hit an approval prompt this subprocess can't
answer, and hang until the timeout. `read_only` (sandbox=read-only, no
edits, nothing needing approval) is the only tool_access level actually
exercised end-to-end here -- `standard`/`full` are implemented per the
documented flags but that specific interaction hasn't been proven live.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from agent_hq.models import RuntimeResult, ToolAccess

_TOOL_ACCESS_TO_SANDBOX = {
    "read_only": "read-only",
    "standard": "workspace-write",
    "full": "danger-full-access",
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

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "last_message.txt"
        cmd = [
            "codex", "exec",
            "-s", _TOOL_ACCESS_TO_SANDBOX[tool_access],
            "-o", str(output_path),
        ]
        if cwd:
            cmd += ["-C", cwd]
        else:
            cmd += ["--skip-git-repo-check"]
        if model:
            cmd += ["-m", model]
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
            raise TimeoutError(
                f"codex exec exceeded {timeout}s -- if tool_access was "
                f"'standard' or 'full', this may be an unanswerable "
                f"approval prompt rather than a slow response. "
                f"stderr: {stderr[:500]}"
            )

        if process.returncode != 0:
            raise RuntimeError(f"codex exec exited {process.returncode}. stderr: {stderr[:1000] or '(empty)'}")

        result_text = output_path.read_text().strip() if output_path.exists() else ""

    return RuntimeResult(
        is_error=False,
        result_text=result_text,
        returncode=process.returncode,
        pid=process.pid,
    )
