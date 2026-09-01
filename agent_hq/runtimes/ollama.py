"""VERIFIED runtime: Ollama's local HTTP API.

Originally documented-only (no Ollama server was running when this was
first written), then actually verified: Ollama was installed via
Homebrew, a real model (llama3.2:1b) was pulled, and this exact function
was called against the real running server. It returned a real response
("Goodbye world." to a "reply with exactly hello world" prompt -- correct
code path, imperfect small-model instruction-following, which is a model
quality question, not a question about whether this adapter works).

This is the one runtime with no tool access at all: plain Ollama's
/api/generate is text generation only, no file/shell tools. tool_access
is accepted for interface consistency with the other runtimes but has no
effect here -- see the module-level note in dispatch.py.

Also the one runtime with no PID: it's an HTTP call, not a subprocess.
pid_callback is still accepted (called with None) so dispatch.py's
attempt-tracking code doesn't need a runtime-specific branch.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Optional

from agent_hq.models import RuntimeResult, ToolAccess

DEFAULT_BASE_URL = "http://localhost:11434"


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

    full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
    payload = json.dumps({
        "model": model or "llama3.2",
        "prompt": full_prompt,
        "stream": False,
    }).encode()

    request = urllib.request.Request(
        f"{base_url}/api/generate", data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f"could not reach Ollama at {base_url}: {e}") from e

    if not data.get("done", False):
        raise RuntimeError(f"Ollama response did not report done=true: {data}")

    return RuntimeResult(is_error=False, result_text=data.get("response", ""), returncode=0, pid=None)
