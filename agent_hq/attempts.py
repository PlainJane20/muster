"""Durable dispatch attempt records -- ephemeral runtime state (see
.gitignore), same convention as switchboard: a PID and an exit code from
three runs ago has no lasting value, but "is this dispatch still running,
and did it work" needs a real answer while it matters."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from agent_hq.models import AttemptStatus, DispatchAttempt

DEFAULT_ATTEMPTS_DIR = Path(".agent-hq") / "attempts"


def _attempt_id(ticket_id: str, started_at: datetime) -> str:
    return f"{ticket_id}-{started_at.strftime('%Y%m%dT%H%M%S')}"


def record_attempt(
    ticket_id: str, agent_id: str, prompt: str,
    worktree_path: Optional[str] = None, pid: Optional[int] = None,
    attempts_dir: Path = DEFAULT_ATTEMPTS_DIR,
) -> DispatchAttempt:
    attempts_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now()
    attempt = DispatchAttempt(
        id=_attempt_id(ticket_id, started_at), ticket_id=ticket_id, agent_id=agent_id,
        prompt=prompt, worktree_path=worktree_path, started_at=started_at, pid=pid,
        status="running",
    )
    _write(attempt, attempts_dir)
    return attempt


def update_attempt(attempt_id: str, attempts_dir: Path = DEFAULT_ATTEMPTS_DIR, **changes) -> DispatchAttempt:
    path = attempts_dir / f"{attempt_id}.json"
    attempt = DispatchAttempt(**json.loads(path.read_text()))
    updated = attempt.model_copy(update=changes)
    _write(updated, attempts_dir)
    return updated


def _write(attempt: DispatchAttempt, attempts_dir: Path) -> None:
    (attempts_dir / f"{attempt.id}.json").write_text(attempt.model_dump_json(indent=2))


def list_attempts(ticket_id: Optional[str] = None, attempts_dir: Path = DEFAULT_ATTEMPTS_DIR) -> List[DispatchAttempt]:
    if not attempts_dir.exists():
        return []
    attempts = [DispatchAttempt(**json.loads(p.read_text())) for p in sorted(attempts_dir.glob("*.json"))]
    if ticket_id:
        attempts = [a for a in attempts if a.ticket_id == ticket_id]
    return attempts
