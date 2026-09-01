"""Typed contracts for agent-hq.

One deliberate choice runs through every model here: nothing forces you to
already know what a "permission mode" or "sandbox policy" is. `tool_access`
is a plain three-level dial (read_only / standard / full) that this
codebase translates into the right flag for whichever runtime an agent
uses -- see runtimes/*.py. If you're new to AI agents, you shouldn't need
to read four different CLIs' manuals just to register one agent safely.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

RuntimeKind = Literal[
    "claude_code", "codex", "cursor_agent", "ollama", "gemini_cli",
    "aider", "opencode", "lm_studio",
]
VerificationTier = Literal["verified", "documented"]
ToolAccess = Literal["read_only", "standard", "full"]
RiskTier = Literal["low", "medium", "high"]
TicketStatus = Literal["open", "assigned", "in_progress", "done", "cancelled"]
AttemptStatus = Literal["running", "succeeded", "failed"]
MemoryType = Literal["decision", "lesson", "preference"]

# Which runtimes were actually exercised against a live install during
# development, vs. built from official documentation only. Both are real
# code paths; only "verified" ones have been proven to work with a real
# invocation. See ARCHITECTURE.md for exactly what was checked for each.
RUNTIME_VERIFICATION: dict = {
    "claude_code": "verified",
    "codex": "verified",
    "cursor_agent": "documented",
    "ollama": "documented",
    "gemini_cli": "documented",
    "aider": "documented",
    "opencode": "documented",
    "lm_studio": "documented",
}


class Agent(BaseModel):
    """One hired agent. 'Hired' just means: a markdown file describing
    what it's for and how to run it -- see agents/README.md for the
    plain-English version of this if YAML frontmatter is new to you."""

    id: str
    name: str
    purpose: str = Field(
        description="Plain English: what does this agent do, and when "
        "should a ticket go to it? This is the only thing the router "
        "(or a human) has to go on."
    )
    runtime: RuntimeKind
    model: Optional[str] = Field(
        default=None,
        description="Which model this agent uses, if the runtime lets you "
        "choose one (e.g. 'llama3.2' for ollama). Leave unset to use that "
        "runtime's own default.",
    )
    tool_access: ToolAccess = Field(
        default="read_only",
        description="read_only: can look things up, can't change anything. "
        "standard: can edit files. full: can also run shell commands. "
        "Never maps to a runtime's full-bypass/no-sandbox flag, regardless "
        "of this setting -- see ARCHITECTURE.md.",
    )
    cwd: Optional[str] = Field(
        default=None,
        description="Working directory this agent operates in -- typically "
        "a git repo. Required for use_worktree to do anything.",
    )
    use_worktree: bool = Field(
        default=True,
        description="If cwd is a git repo, run each dispatch in its own "
        "git worktree instead of the shared directory, so two dispatches "
        "to the same agent at the same time can't collide.",
    )
    tags: List[str] = Field(default_factory=list)
    risk_tier: RiskTier = "low"

    @property
    def verification(self) -> VerificationTier:
        return RUNTIME_VERIFICATION[self.runtime]


class RuntimeResult(BaseModel):
    """What every runtime adapter returns, regardless of whether it's a
    subprocess (Claude Code, Codex, Cursor) or an HTTP call (Ollama)."""

    is_error: bool
    result_text: str
    session_id: Optional[str] = None
    cost_usd: Optional[float] = None
    returncode: Optional[int] = None
    pid: Optional[int] = None


class DispatchAttempt(BaseModel):
    """One real dispatch of a ticket to an agent. Ephemeral -- see
    .gitignore; this answers 'did it work,' it isn't meant to be
    permanent history the way tickets and memory are."""

    id: str
    ticket_id: str
    agent_id: str
    prompt: str
    worktree_path: Optional[str] = None
    started_at: datetime
    pid: Optional[int] = None
    status: AttemptStatus = "running"
    returncode: Optional[int] = None
    result_text: Optional[str] = None
    session_id: Optional[str] = None
    cost_usd: Optional[float] = None


class Ticket(BaseModel):
    id: str
    title: str
    status: TicketStatus = "open"
    created: date
    tags: List[str] = Field(default_factory=list)
    assignee: Optional[str] = None
    body: str = ""


class MemoryEntry(BaseModel):
    """A durable, git-tracked piece of institutional memory -- something
    worth remembering across sessions that isn't tied to one ticket.
    A decision ('we chose X because Y'), a lesson ('Z didn't work,
    here's why'), or a preference ('always do W this way')."""

    id: str
    type: MemoryType
    title: str
    body: str = ""
    tags: List[str] = Field(default_factory=list)
    created: date
