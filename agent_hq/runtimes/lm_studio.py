"""DOCUMENTED, NOT VERIFIED: LM Studio's local HTTP server.

No LM Studio server was running in the environment this was developed in.
Built from https://lmstudio.ai/docs/app/api/endpoints/openai (fetched
during development), which documents the endpoint as OpenAI-compatible --
`response.choices[0].message.content` is the standard OpenAI chat
completion shape this assumes, not independently re-confirmed against a
real LM Studio response. That's a reasonably safe assumption (OpenAI's
chat completion shape is about as stable and widely mirrored as a JSON
API gets), but "documented as compatible with a well-known spec" is still
one step short of "checked against a real response," same distinction
every other documented-only adapter in this registry draws.

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
