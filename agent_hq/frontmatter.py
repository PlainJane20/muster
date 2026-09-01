"""Minimal YAML-frontmatter markdown parsing: `---\\nYAML\\n---\\nbody`.
Every durable thing in agent-hq (agents, tickets, memory entries) is one
of these files. Git is the database -- there's no separate store to keep
in sync with what's actually on disk."""

from __future__ import annotations

from typing import Any, Dict, Tuple

import yaml

_DELIM = "---"


def parse(text: str) -> Tuple[Dict[str, Any], str]:
    if not text.startswith(_DELIM):
        raise ValueError("expected file to start with '---' frontmatter delimiter")
    parts = text.split(_DELIM, 2)
    if len(parts) < 3:
        raise ValueError("frontmatter block is not closed with a second '---'")
    _, raw_meta, body = parts
    meta = yaml.safe_load(raw_meta) or {}
    return meta, body.strip("\n")


def render(meta: Dict[str, Any], body: str) -> str:
    raw_meta = yaml.safe_dump(meta, sort_keys=False, default_flow_style=False)
    return f"{_DELIM}\n{raw_meta}{_DELIM}\n\n{body.strip()}\n"
