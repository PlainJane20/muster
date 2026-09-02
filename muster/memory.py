"""Durable, git-tracked institutional memory -- decisions, lessons, and
preferences, one markdown file each under memory/<type>s/. This is the
generalized version of what switchboard built narrowly for one purpose
(routing corrections): a place for anything worth remembering across
sessions that isn't tied to a single ticket.

Search is deliberately simple -- substring match across title, body, and
tags, not embeddings. For a personal, single-operator memory store that's
going to hold dozens to low hundreds of entries, a full-text index is
solving a problem this doesn't have yet. `git log -p memory/` already
gives you the real history; search just needs to find things fast today.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import List, Optional

from muster import frontmatter
from muster.models import MemoryEntry, MemoryType

DEFAULT_MEMORY_DIR = Path("memory")

_SLUG_RE = __import__("re").compile(r"[^a-z0-9]+")


def _type_dir(memory_type: MemoryType, memory_dir: Path) -> Path:
    return memory_dir / f"{memory_type}s"


def _next_id(type_dir: Path) -> str:
    existing = sorted(type_dir.glob("[0-9][0-9][0-9][0-9]-*.md")) if type_dir.exists() else []
    if not existing:
        return "0001"
    return f"{int(existing[-1].name[:4]) + 1:04d}"


def add(
    memory_type: MemoryType, title: str, body: str = "",
    tags: Optional[List[str]] = None, memory_dir: Path = DEFAULT_MEMORY_DIR,
) -> MemoryEntry:
    type_dir = _type_dir(memory_type, memory_dir)
    type_dir.mkdir(parents=True, exist_ok=True)
    entry = MemoryEntry(
        id=_next_id(type_dir), type=memory_type, title=title,
        body=body, tags=tags or [], created=date.today(),
    )
    slug = _SLUG_RE.sub("-", title.lower()).strip("-")[:40]
    path = type_dir / f"{entry.id}-{slug}.md"
    meta = entry.model_dump(exclude={"body"}, mode="json")
    path.write_text(frontmatter.render(meta, entry.body))
    return entry


def _load_all(memory_dir: Path = DEFAULT_MEMORY_DIR) -> List[MemoryEntry]:
    entries = []
    for memory_type in ("decision", "lesson", "preference"):
        type_dir = _type_dir(memory_type, memory_dir)
        if not type_dir.exists():
            continue
        for path in sorted(type_dir.glob("*.md")):
            meta, body = frontmatter.parse(path.read_text())
            entries.append(MemoryEntry(body=body, **meta))
    return entries


def list_entries(
    memory_type: Optional[MemoryType] = None, memory_dir: Path = DEFAULT_MEMORY_DIR
) -> List[MemoryEntry]:
    entries = _load_all(memory_dir)
    if memory_type:
        entries = [e for e in entries if e.type == memory_type]
    return entries


def search(query: str, memory_dir: Path = DEFAULT_MEMORY_DIR) -> List[MemoryEntry]:
    query = query.lower()
    return [
        e for e in _load_all(memory_dir)
        if query in e.title.lower() or query in e.body.lower() or any(query in t.lower() for t in e.tags)
    ]
