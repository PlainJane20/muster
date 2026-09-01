---
id: gemini-drafter
name: Gemini Drafter
runtime: gemini_cli
tool_access: read_only
tags:
- drafting
- research
risk_tier: low
---

A Gemini CLI session for drafting and research questions. Documented-only
adapter -- Gemini CLI wasn't installed in the environment this was built
in, so only read_only is implemented (no documented auto-approval flag
exists for unattended tool use). See runtimes/gemini_cli.py.
