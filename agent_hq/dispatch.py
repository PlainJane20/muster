"""Dispatches a ticket to an agent -- prints what would happen by default,
`run=True` actually does it. Same safety posture as every other tool in
this portfolio: a human decides whether a real side-effecting run
happens, and medium/high-risk agents get a visible warning either way.

If the agent's cwd is a git repo and use_worktree is set, the dispatch
runs in its own git worktree (see worktree.py) instead of the shared
directory -- created before the run, deliberately left in place after
(not auto-removed) so a human can inspect or merge what the agent did.
`agent-hq worktree remove` cleans it up explicitly.

For standard/full dispatches with a worktree, a successful attempt also
gets its `filesystem_verified` field cross-checked against the worktree's
actual git state -- see worktree.has_real_changes and its docstring for
why this exists (a real, confirmed case of a tool reporting success on a
change that never actually happened).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from agent_hq import attempts as attempts_mod
from agent_hq import worktree as worktree_mod
from agent_hq.models import Agent, DispatchAttempt, Ticket
from agent_hq.runtimes import (
    aider, claude_code, codex, cursor_agent, gemini_cli, lm_studio, ollama, opencode,
)

_RUNTIME_MODULES = {
    "claude_code": claude_code,
    "codex": codex,
    "cursor_agent": cursor_agent,
    "ollama": ollama,
    "gemini_cli": gemini_cli,
    "aider": aider,
    "opencode": opencode,
    "lm_studio": lm_studio,
}


def _build_prompt(ticket: Ticket) -> str:
    return f"Ticket {ticket.id}: {ticket.title}\n\n{ticket.body}"


def dispatch(agent: Agent, ticket: Ticket, run: bool = False) -> Optional[DispatchAttempt]:
    runtime_module = _RUNTIME_MODULES[agent.runtime]
    prompt = _build_prompt(ticket)

    if agent.risk_tier in ("medium", "high") and run:
        print(
            f"WARNING: {agent.id} is a {agent.risk_tier}-risk agent "
            f"(tool_access={agent.tool_access}). Running anyway because run=True."
        )

    if not run:
        print(
            f"Prepared -- would dispatch to {agent.id} ({agent.runtime}, "
            f"tool_access={agent.tool_access}"
            + (f", isolated worktree" if agent.cwd and agent.use_worktree else "")
            + f").\n\nPrompt:\n{prompt}\n"
        )
        return None

    attempt_holder = {}
    worktree_path: Optional[Path] = None
    base_commit: Optional[str] = None

    # Worktree creation can fail for real reasons (a repo with no commits
    # yet -- see ARCHITECTURE.md) and used to crash with a raw traceback
    # here instead of a clean failed attempt. It's now inside the same
    # try/except as the runtime call, one step down, for exactly that
    # reason: any real failure before or during a dispatch should produce
    # a DispatchAttempt a human can look up later, not an unhandled crash.
    try:
        if agent.cwd and agent.use_worktree and worktree_mod.is_git_repo(Path(agent.cwd)):
            worktree_path = worktree_mod.create_worktree(Path(agent.cwd), ticket.id)
            # Recorded before the runtime ever touches the worktree, so
            # the post-run check below has an honest "before" to compare
            # against -- not the worktree's state after the agent already
            # ran, which would always show zero drift.
            base_commit = worktree_mod.current_head(worktree_path)
    except (RuntimeError, ValueError) as e:
        attempt = attempts_mod.record_attempt(
            ticket_id=ticket.id, agent_id=agent.id, prompt=prompt, worktree_path=None, pid=None,
        )
        attempt = attempts_mod.update_attempt(attempt.id, status="failed", result_text=str(e))
        print(f"Attempt {attempt.id}: failed to set up -- {e}")
        return attempt

    effective_cwd = str(worktree_path) if worktree_path else agent.cwd

    def _on_pid(pid):
        attempt_holder["attempt"] = attempts_mod.record_attempt(
            ticket_id=ticket.id, agent_id=agent.id, prompt=prompt,
            worktree_path=str(worktree_path) if worktree_path else None, pid=pid,
        )
        print(f"Dispatched (attempt {attempt_holder['attempt'].id}"
              + (f", pid {pid}" if pid else "") + "). Waiting for it to finish...")

    try:
        result = runtime_module.run(
            prompt=prompt, cwd=effective_cwd, tool_access=agent.tool_access,
            model=agent.model, pid_callback=_on_pid,
        )
    except (RuntimeError, TimeoutError, ValueError, NotImplementedError) as e:
        attempt = attempt_holder.get("attempt") or attempts_mod.record_attempt(
            ticket_id=ticket.id, agent_id=agent.id, prompt=prompt,
            worktree_path=str(worktree_path) if worktree_path else None, pid=None,
        )
        attempt = attempts_mod.update_attempt(attempt.id, status="failed", result_text=str(e))
        print(f"Attempt {attempt.id}: failed -- {e}")
        return attempt

    status = "failed" if result.is_error else "succeeded"

    # The check this whole file exists to make honest: a runtime exiting
    # 0 and reporting "success" doesn't mean the change it claims to have
    # made is actually in the worktree -- a real, confirmed failure mode
    # (see aider.py's docstring, and ARCHITECTURE.md). Only meaningful
    # when tool_access could have produced a change at all; read_only
    # dispatches are supposed to leave the worktree untouched.
    filesystem_verified: Optional[bool] = None
    if status == "succeeded" and worktree_path and agent.tool_access in ("standard", "full"):
        filesystem_verified = worktree_mod.has_real_changes(worktree_path, base_commit)

    attempt = attempts_mod.update_attempt(
        attempt_holder["attempt"].id, status=status, returncode=result.returncode,
        result_text=result.result_text, session_id=result.session_id, cost_usd=result.cost_usd,
        filesystem_verified=filesystem_verified,
    )
    print(f"Attempt {attempt.id}: {status}.\n\n{result.result_text}")
    if filesystem_verified is False:
        print(
            "\nWARNING: the tool reported success, but no new commit or "
            "uncommitted change was found in the worktree. 'succeeded' "
            "means the tool didn't error -- it doesn't prove the "
            "requested change actually happened. Check the worktree "
            "yourself before trusting this attempt."
        )
    if worktree_path:
        print(f"\nWorktree left in place for review: {worktree_path}")
        print(f"Remove it with: agent-hq worktree remove {ticket.id}")
    return attempt
