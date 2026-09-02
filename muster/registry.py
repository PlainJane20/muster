"""Loads the agent registry from agents/*.md. Adding an agent means
adding one file -- no code change, no restart."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from muster import frontmatter
from muster.models import Agent

DEFAULT_AGENTS_DIR = Path("agents")


def load_agents(agents_dir: Path = DEFAULT_AGENTS_DIR) -> List[Agent]:
    if not agents_dir.exists():
        return []
    agents = []
    for path in sorted(agents_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        meta, body = frontmatter.parse(path.read_text())
        agents.append(Agent(purpose=body, **meta))
    return agents


def agents_by_id(agents_dir: Path = DEFAULT_AGENTS_DIR) -> Dict[str, Agent]:
    return {a.id: a for a in load_agents(agents_dir)}


def new_agent(agent: Agent, agents_dir: Path = DEFAULT_AGENTS_DIR) -> Path:
    agents_dir.mkdir(parents=True, exist_ok=True)
    path = agents_dir / f"{agent.id}.md"
    meta = agent.model_dump(exclude={"purpose"}, mode="json")
    path.write_text(frontmatter.render(meta, agent.purpose))
    return path
