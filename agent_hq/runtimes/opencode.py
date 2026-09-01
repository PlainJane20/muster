"""VERIFIED runtime: OpenCode (open-source, model-agnostic CLI harness).

Verified live: installed via `npm install -g opencode-ai` (v1.18.25), then
dispatched against the same local Ollama server used to verify ollama.py
and aider.py -- zero API key needed, same as those two.

Two real things found that no amount of re-reading `--help` would have
surfaced, because they're config and output-format details, not flags:

1. **A registered model isn't enough -- OpenCode needs an explicit
   provider entry to reach a local model at all.** `--model ollama/
   llama3.2:1b` alone fails with `ProviderModelNotFoundError: Model not
   found: ollama/llama3.2:1b. Did you mean: ollama-cloud?` -- OpenCode's
   built-in "ollama" reference is a cloud offering, not a pointer to a
   local server. Reaching a real local Ollama instance requires a custom
   provider block in `~/.config/opencode/opencode.jsonc`:
   ```json
   {"provider": {"ollama": {"npm": "@ai-sdk/openai-compatible",
     "options": {"baseURL": "http://localhost:11434/v1"},
     "models": {"llama3.2:1b": {}}}}}
   ```
   This is host/environment configuration, not something this adapter's
   `run()` can do on an end user's behalf -- it's documented here and in
   ARCHITECTURE.md instead.
2. **The real `--format json` shape is confirmed, and it's not what an
   initial best-effort guess assumed.** OpenCode's own docs describe
   "raw JSON events" without an example; a real captured run showed each
   line is a distinct event (`step_start`, `text`, `step_finish`, ...),
   and critically, the generated text lives at `event["part"]["text"]`
   for `type == "text"` events -- not a top-level `text` key on the event
   itself, which is what an untested guess had assumed. Verified against
   the real captured output before writing this parser, and the earlier
   guess's failure mode (falling through to the raw-stdout fallback,
   silently) is exactly why the fallback chain exists.
"""

from __future__ import annotations

import json
import subprocess
from typing import Optional

from agent_hq.models import RuntimeResult, ToolAccess


def _best_effort_parse(stdout: str) -> str:
    stdout = stdout.strip()
    if not stdout:
        return ""
    try:
        data = json.loads(stdout)
        return data.get("text") or data.get("result") or data.get("content") or stdout
    except json.JSONDecodeError:
        pass

    texts = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "text":
            text = (event.get("part") or {}).get("text")
            if text:
                texts.append(text)
    return "".join(texts) if texts else stdout


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
    cmd = ["opencode", "run", full_prompt, "--format", "json"]
    if cwd:
        cmd += ["--dir", cwd]
    if model:
        cmd += ["--model", model]
    if tool_access in ("standard", "full"):
        cmd.append("--auto")

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
        raise TimeoutError(f"opencode exceeded {timeout}s. stderr: {stderr[:500]}")

    if process.returncode != 0:
        raise RuntimeError(f"opencode exited {process.returncode} (undocumented meaning). stderr: {stderr[:1000] or '(empty)'}")

    return RuntimeResult(is_error=False, result_text=_best_effort_parse(stdout), returncode=process.returncode, pid=process.pid)
