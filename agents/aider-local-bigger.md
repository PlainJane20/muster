---
id: aider-local-bigger
name: Aider Local (bigger model)
runtime: aider
model: ollama_chat/qwen2.5-coder:7b
tool_access: standard
cwd: /tmp/aider_test_repo
use_worktree: true
tags:
- code
risk_tier: medium
---

Aider running against a larger local Ollama model, used once to confirm
the filesystem_verified check reports True on a real dispatch that
actually persists a change (not just mocked in tests).
