"""Git worktree isolation for parallel dispatch.

If an agent's `cwd` is a git repo and `use_worktree` is true, each
dispatch gets its own `git worktree` instead of running directly in the
shared directory -- so two dispatches to the same agent at the same time
don't read/write the same files, and a live agent that edits things
doesn't leave the "real" checkout dirty. This is the concrete answer to
"what does Livery's worktree isolation actually buy you," reproduced here
with plain `git worktree` commands -- no wrapping library, since git
already does exactly this one job.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Optional

WORKTREES_ROOT = Path(".agent-hq") / "worktrees"


def _run_git(args, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True
    )


def is_git_repo(path: Path) -> bool:
    result = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=path)
    return result.returncode == 0 and result.stdout.strip() == "true"


def create_worktree(repo_path: Path, ticket_id: str, worktrees_root: Path = WORKTREES_ROOT) -> Path:
    """Creates a new worktree at <worktrees_root>/<ticket_id>-<timestamp>
    on a fresh branch off the repo's current HEAD. Returns the worktree
    path. Raises RuntimeError with git's own stderr on failure -- a
    repo with uncommitted changes that conflict, or a branch name
    collision, should fail loudly, not silently fall back to the shared
    directory."""
    if not is_git_repo(repo_path):
        raise ValueError(f"{repo_path} is not a git repository -- can't create a worktree in it")

    worktrees_root.mkdir(parents=True, exist_ok=True)
    slug = f"{ticket_id}-{int(time.time())}"
    worktree_path = (worktrees_root / slug).resolve()
    branch_name = f"agent-hq/{slug}"

    result = _run_git(
        ["worktree", "add", "-b", branch_name, str(worktree_path)], cwd=repo_path
    )
    if result.returncode != 0:
        if "not a valid object name: 'HEAD'" in result.stderr:
            # Real failure mode, hit during development: a `git init`
            # with zero commits has no HEAD to branch a worktree off of.
            # The raw git error doesn't say that in plain language.
            raise RuntimeError(
                f"{repo_path} has no commits yet -- a worktree needs "
                f"something to branch off of. Make an initial commit in "
                f"that repo first, then try again."
            )
        raise RuntimeError(f"git worktree add failed: {result.stderr.strip()}")
    return worktree_path


def remove_worktree(repo_path: Path, worktree_path: Path, force: bool = False) -> None:
    """Removes a worktree and prunes it from git's records. `force` is
    needed if the agent left uncommitted changes in it -- deliberately
    not the default, so a dispatch that produced real work doesn't get
    silently discarded."""
    args = ["worktree", "remove", str(worktree_path)]
    if force:
        args.append("--force")
    result = _run_git(args, cwd=repo_path)
    if result.returncode != 0:
        raise RuntimeError(f"git worktree remove failed: {result.stderr.strip()}")


def list_worktrees(repo_path: Path) -> list:
    result = _run_git(["worktree", "list", "--porcelain"], cwd=repo_path)
    if result.returncode != 0:
        raise RuntimeError(f"git worktree list failed: {result.stderr.strip()}")
    paths = []
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            paths.append(Path(line[len("worktree "):]))
    return paths
