# Ledger

Append-only record of closed tickets.

- **0003** *Create a scratch file* -- assigned to `claude-editor` -- Worktree isolation proven: file created only in .agent-hq/worktrees/0003-*, main tree stayed clean.
- **0001** *Explain the point of worktree isolation* -- assigned to `claude-researcher` -- Answered correctly by the real Claude Code runtime.
- **0002** *Summarize what this file does* -- assigned to `codex-researcher` -- Answered correctly by the real Codex runtime.
- **0004** *Ask the local model a simple question* -- assigned to `local-llama` -- Ollama verified live: correct response from the real local model.
- **0005** *Add a note to README* -- assigned to `aider-local` -- Aider verified live via the full pipeline (ticket -> worktree -> dispatch), but revealed a real limitation: reported 'Applied edit' + exit 0 did NOT correspond to an actual git commit -- see runtimes/aider.py docstring.
