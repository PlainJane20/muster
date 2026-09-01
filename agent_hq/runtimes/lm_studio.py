"""DOCUMENTED, NOT VERIFIED: LM Studio's local HTTP server.

The one runtime in this registry where a real attempt to verify it hit a
structural wall rather than a missing credential. `brew install --cask
lm-studio` really did install it (v0.4.23, ~1.6GB, confirmed with `brew
info`) -- but LM Studio is a GUI-first Electron app, and this environment
has no interactive GUI/window-server session for it to attach to.
`open -a "LM Studio"` returns exit 0 with no process ever appearing, and
launching the app binary directly falls all the way through Electron into
its embedded Node.js runtime's own `--help`/arg parser instead of starting
the app -- confirmed by literally getting Node's usage text back. Because
the app never completes first-run setup, `~/.lmstudio` (where its `lms`
CLI and local inference server would live) never gets created. This is a
different, more fundamental gap than Cursor or Gemini CLI: those two just
need an account/API key this environment lacks; LM Studio needs a GUI
session this kind of environment structurally doesn't have, headless or
not.

So the adapter itself is unchanged and still built from
https://lmstudio.ai/docs/app/api/endpoints/openai (fetched during
development), which documents the endpoint as OpenAI-compatible --
`response.choices[0].message.content` is the standard OpenAI chat
completion shape this assumes, not independently re-confirmed against a
real LM Studio response. That's a reasonably safe assumption (OpenAI's
chat completion shape is about as stable and widely mirrored as a JSON
API gets), but "documented as compatible with a well-known spec" is still
one step short of "checked against a real response." Verifying this one
for real needs a machine with an actual desktop session to launch the app
on, load a model into it, and start its local server -- not something
achievable from this environment no matter how many more things get
installed.

Same no-tool-access, no-PID shape as ollama.py -- see that module's
docstring for why.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Optional

from agent_hq.models import RuntimeResult, ToolAccess

DEFAULT_BASE_URL = "http://localhost:1234/v1"


def run(
    prompt: str,
    cwd: Optional[str] = None,  # unused -- no filesystem access in this adapter
    tool_access: ToolAccess = "read_only",  # unused -- see module docstring
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    timeout: int = 600,
    pid_callback=None,
    base_url: str = DEFAULT_BASE_URL,
) -> RuntimeResult:
    if pid_callback:
        pid_callback(None)

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps({"model": model or "local-model", "messages": messages}).encode()
    request = urllib.request.Request(
        f"{base_url}/chat/completions", data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f"could not reach LM Studio at {base_url}: {e}") from e

    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"unexpected LM Studio response shape: {data}") from e

    return RuntimeResult(is_error=False, result_text=text, returncode=0, pid=None)
