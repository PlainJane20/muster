"""DOCUMENTED, PARTIALLY VERIFIED: cursor-agent (Cursor's CLI).

Installed for real (`curl https://cursor.com/install -fsS | bash`, version
2026.08.31-4057e58) and its flags checked against the real `--help` output,
not just the docs page this adapter was originally built from -- but never
completed an authenticated dispatch (cursor-agent has no free tier; it
requires `agent login` or a `CURSOR_API_KEY`, neither available in this
environment), so the *success* response shape below is still the original
documented assumption, not a confirmed one.

Two things confirmed real, not guessed:

1. **Every flag this adapter uses is real.** `--print`, `--output-format
   json`, `--trust`, `--workspace`, `--force`, `--model` all appear
   verbatim in the real `--help` output. Unlike gemini_cli, the original
   docs page this was built from turned out to be accurate -- a useful
   negative result: not every "documented, not verified" adapter is
   hiding a gap.
2. **The real, unauthenticated failure mode is a plain non-zero exit with
   a plain-text stderr message** (`Error: Authentication required. Please
   run 'agent login' first, or set CURSOR_API_KEY environment variable.`),
   not a JSON error body the way gemini_cli's is. The generic
   any-non-zero-exit-is-a-RuntimeError handling below already covers this
   correctly without needing a special case -- confirmed by triggering it
   live, not assumed.

Still unconfirmed: the exact shape of a *successful* JSON response
(`result` vs `response` vs something else), since no authenticated run
was possible here. `run()` below tries both known field names and falls
back to raw stdout, same defensive shape as before this was ever run.

This is a deliberate, permanent stopping point, not a pending TODO.
Gemini CLI had the exact same shape of gap and closed it by getting a
free Google AI Studio API key. Cursor's equivalent requires a paid
Cursor subscription -- there's no free tier for `CURSOR_API_KEY` access.
A decision was made not to pay for one just to complete this adapter's
verification, so `cursor_agent` stays "documented, flags/errors confirmed
live" rather than "verified" -- an honest, cost-based stopping point, not
a gap left open because it wasn't tried hard enough. If a `CURSOR_API_KEY`
becomes available later (e.g. a Cursor subscription obtained for other
reasons), promoting this adapter is exactly the same process that
promoted gemini_cli: run a real dispatch, fix whatever it surfaces, flip
`RUNTIME_VERIFICATION["cursor_agent"]` to `"verified"`.

`full` is intentionally NOT mapped to `--yolo` (confirmed live to be a
real, working alias for `--force`) -- using the explicit `--force` name
throughout keeps this file's intent readable without relying on Cursor's
more casually-named alias, the same reasoning as aider.py using
`--yes-always` instead of the shorter `--yes`.
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
