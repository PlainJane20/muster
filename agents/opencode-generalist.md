---
id: opencode-generalist
name: OpenCode Generalist
runtime: opencode
tool_access: read_only
tags:
- general
- code
risk_tier: medium
---

OpenCode, the open-source model-agnostic CLI harness, for general coding
and research questions. Documented-only adapter -- not installed in the
environment this was built in. Its JSON output format is documented as
"raw events" rather than one clean response object, so this adapter's
parser is a best-effort guess at the real shape; see runtimes/opencode.py.
