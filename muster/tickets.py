"""Create, list, update, and close tickets -- each one a markdown file
under tickets/. Same lock-guarded id allocation as switchboard (this
portfolio's other git-native ticket tool) -- proven pattern, freshly
written for a separate, independent project."""

from __future__ import annotations

import os
import re
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import List, Optional

from muster import frontmatter
from muster.models import Ticket

DEFAULT_TICKETS_DIR = Path("tickets")
DEFAULT_LEDGER_PATH = Path("ledger.md")

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_LOCK_TIMEOUT_SECONDS = 5.0
_LOCK_RETRY_INTERVAL = 0.05


@contextmanager
def _id_allocation_lock(tickets_dir: Path):
    lock_path = tickets_dir / ".id.lock"
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    fd = None
    while fd is None:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"could not acquire ticket-id lock at {lock_path} within "
                    f"{_LOCK_TIMEOUT_SECONDS}s -- delete it if a previous run crashed."
                )
            time.sleep(_LOCK_RETRY_INTERVAL)
    try:
        yield
    finally:
        os.close(fd)
        lock_path.unlink(missing_ok=True)


def _slugify(title: str) -> str:
    return _SLUG_RE.sub("-", title.lower()).strip("-")[:40]


def _next_id(tickets_dir: Path) -> str:
    existing = sorted(tickets_dir.glob("[0-9][0-9][0-9][0-9]-*.md"))
    if not existing:
        return "0001"
    return f"{int(existing[-1].name[:4]) + 1:04d}"


def path_for(tickets_dir: Path, ticket_id: str) -> Path:
    matches = list(tickets_dir.glob(f"{ticket_id}-*.md"))
    if not matches:
        raise FileNotFoundError(f"no ticket found with id {ticket_id!r}")
    return matches[0]


def new_ticket(
    title: str, tags: Optional[List[str]] = None, body: str = "",
    tickets_dir: Path = DEFAULT_TICKETS_DIR,
) -> Ticket:
    tickets_dir.mkdir(parents=True, exist_ok=True)
    with _id_allocation_lock(tickets_dir):
        ticket = Ticket(
            id=_next_id(tickets_dir), title=title, status="open",
            created=date.today(), tags=tags or [], assignee=None, body=body,
        )
        _write(ticket, tickets_dir)
    return ticket


def _write(ticket: Ticket, tickets_dir: Path) -> None:
    meta = ticket.model_dump(exclude={"body"}, mode="json")
    path = tickets_dir / f"{ticket.id}-{_slugify(ticket.title)}.md"
    path.write_text(frontmatter.render(meta, ticket.body))


def load_ticket(ticket_id: str, tickets_dir: Path = DEFAULT_TICKETS_DIR) -> Ticket:
    meta, body = frontmatter.parse(path_for(tickets_dir, ticket_id).read_text())
    return Ticket(body=body, **meta)


def list_tickets(tickets_dir: Path = DEFAULT_TICKETS_DIR, status: Optional[str] = None) -> List[Ticket]:
    tickets = []
    for path in sorted(tickets_dir.glob("*.md")):
        meta, body = frontmatter.parse(path.read_text())
        ticket = Ticket(body=body, **meta)
        if status is None or ticket.status == status:
            tickets.append(ticket)
    return tickets


def update_ticket(ticket_id: str, tickets_dir: Path = DEFAULT_TICKETS_DIR, **changes) -> Ticket:
    ticket = load_ticket(ticket_id, tickets_dir)
    updated = ticket.model_copy(update=changes)
    meta = updated.model_dump(exclude={"body"}, mode="json")
    path_for(tickets_dir, ticket_id).write_text(frontmatter.render(meta, updated.body))
    return updated


def append_ledger(ticket: Ticket, summary: str, ledger_path: Path = DEFAULT_LEDGER_PATH) -> None:
    line = f"- **{ticket.id}** *{ticket.title}* -- assigned to `{ticket.assignee or 'unassigned'}` -- {summary}\n"
    if not ledger_path.exists():
        ledger_path.write_text("# Ledger\n\nAppend-only record of closed tickets.\n\n")
    with ledger_path.open("a") as f:
        f.write(line)
