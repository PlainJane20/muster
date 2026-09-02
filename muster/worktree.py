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

WORKTREES_ROOT = Path(".muster") / "worktrees"


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

    # Real failure mode, hit during development: a `git init` with zero
    # commits has no HEAD to branch a worktree off of. Checked directly
    # here instead of string-matching git's stderr for "not a valid
    # object name: 'HEAD'" after the fact -- that exact wording turned
    # out to vary by git version (confirmed failing on a newer git in CI
    # than the one this was written against locally), which is exactly
    # the kind of "verified, not asserted" bug this project's README
    # says it cares about catching.
    head_check = _run_git(["rev-parse", "--verify", "HEAD"], cwd=repo_path)
    if head_check.returncode != 0:
        raise RuntimeError(
            f"{repo_path} has no commits yet -- a worktree needs "
            f"something to branch off of. Make an initial commit in "
            f"that repo first, then try again."
        )

    worktrees_root.mkdir(parents=True, exist_ok=True)
    slug = f"{ticket_id}-{int(time.time())}"
    worktree_path = (worktrees_root / slug).resolve()
    branch_name = f"muster/{slug}"

    result = _run_git(
        ["worktree", "add", "-b", branch_name, str(worktree_path)], cwd=repo_path
    )
    if result.returncode != 0:
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


def current_head(repo_path: Path) -> Optional[str]:
    """The commit a worktree is currently sitting on. Returns None if
    that can't be determined (shouldn't happen for a worktree this module
    just created, but a bare git failure here shouldn't crash a dispatch
    over it -- see how dispatch.py treats a None here as "can't verify")."""
    result = _run_git(["rev-parse", "HEAD"], cwd=repo_path)
    return result.stdout.strip() if result.returncode == 0 else None


def has_real_changes(worktree_path: Path, base_commit: Optional[str]) -> Optional[bool]:
    """Did anything actually change in this worktree, independent of
    whatever the runtime *said* it did? Checks two things a runtime
    reporting success should have produced at least one of, if
    tool_access allowed edits at all: a new commit past base_commit, or
    uncommitted working-tree changes. Returns None (can't tell) if
    base_commit is unknown rather than guessing.

    This exists because of a real, confirmed finding: a live Aider
    dispatch printed "Applied edit to README.md" and exited 0, but `git
    log` in that worktree showed no new commit at all -- see aider.py's
    docstring and ARCHITECTURE.md. A DispatchAttempt's `status:
    succeeded` means the tool didn't error; this is what actually checks
    whether the change it claimed happened is really there.

    Uncommitted changes are filtered to non-dotfiles before counting --
    see the inline comment below. An earlier version without that filter
    got it wrong on the very first real dispatch it ran against: Aider's
    own `.gitignore` housekeeping made this check say "yes, something
    changed" while the actual requested README edit had never happened.

    Important scope boundary, also found on a real dispatch: `True` means
    *something* real changed, not that the *right* thing changed. A
    follow-up dispatch asking Aider to append a line to README.md instead
    committed a new, literally-named file called `Verified by muster.`
    with no content -- a real commit, correctly detected as True, but not
    the requested edit. This function answers "did the tool actually do
    something," which is strictly more than exit-code-and-stdout proves,
    but it is not a correctness check on *what* it did."""
    if base_commit is None:
        return None
    new_head = current_head(worktree_path)
    if new_head is not None and new_head != base_commit:
        return True
    status = _run_git(["status", "--porcelain"], cwd=worktree_path)
    for line in status.stdout.splitlines():
        # Porcelain format is "XY path" (or "XY old -> new" for a
        # rename) -- take whichever side is the real path.
        path = line[3:].split(" -> ")[-1]
        # Dotfiles are excluded on purpose: a real dispatch (Aider,
        # standard tool_access) printed "Applied edit to README.md" and
        # exited 0, but the *only* uncommitted change in the worktree
        # afterward was a `.gitignore` Aider writes as its own
        # housekeeping ("Added .aider* to .gitignore") -- README.md
        # itself was untouched. Counting that as "a real change happened"
        # would have hidden the exact discrepancy this check exists to
        # catch. Tool-generated config/bookkeeping files are almost
        # always dotfiles; the actual deliverable almost never is.
        if not Path(path).name.startswith("."):
            return True
    return False


def list_worktrees(repo_path: Path) -> list:
    result = _run_git(["worktree", "list", "--porcelain"], cwd=repo_path)
    if result.returncode != 0:
        raise RuntimeError(f"git worktree list failed: {result.stderr.strip()}")
    paths = []
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            paths.append(Path(line[len("worktree "):]))
    return paths
