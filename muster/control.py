"""Real process control over a running dispatch, from a second CLI
invocation -- no daemon, no server, nothing running in the background
except the actual runtime subprocess (Claude Code, Aider, etc.) that
dispatch() already spawned and recorded the real PID for.

This is the scaled-down, "no server, read every line" answer to a much
bigger control-plane spec someone pasted in: pause, resume, and kill are
just `os.kill()` with the right signal, sent to the same PID
`DispatchAttempt.pid` has always tracked. No process supervisor, no
telemetry bus, no persistent daemon -- Unix signals already do this job,
and they work across separate terminal invocations because the target is
a real OS process, not something living inside this CLI's own memory.

Important limitation, stated plainly rather than glossed over: pausing
doesn't stop the *original* `dispatch --run` invocation's blocking
`communicate()` call from eventually returning once the process resumes
or exits -- that original call is still the only thing that writes the
final "succeeded"/"failed" status. `pause`/`resume`/`kill` here only
control the underlying OS process and update an interim status
("paused"/"terminated") so a second terminal watching `ticket-show` can
see it -- they don't (and can't, without a daemon) reach into another
process's Python call stack to change what it does next.
"""

from __future__ import annotations

import os
import signal

from muster import attempts as attempts_mod
from muster.models import DispatchAttempt

DEFAULT_ATTEMPTS_DIR = attempts_mod.DEFAULT_ATTEMPTS_DIR


def is_alive(pid: int) -> bool:
    """Real OS check, not a status-field guess -- an attempt's stored
    status can go stale (see filesystem_verified's sibling honesty
    theme), so pause/resume/kill always check the real process first."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is owned by someone else -- rare locally,
        # but "exists and I can't touch it" is not the same as "dead."
        return True
    return True


def _load(attempt_id: str, attempts_dir) -> DispatchAttempt:
    attempts = attempts_mod.list_attempts(attempts_dir=attempts_dir)
    for attempt in attempts:
        if attempt.id == attempt_id:
            return attempt
    raise ValueError(f"no attempt found with id '{attempt_id}'")


def pause_attempt(attempt_id: str, attempts_dir=DEFAULT_ATTEMPTS_DIR) -> DispatchAttempt:
    attempt = _load(attempt_id, attempts_dir)
    if attempt.status != "running":
        raise RuntimeError(f"attempt {attempt_id} is '{attempt.status}', not running -- nothing to pause")
    if attempt.pid is None or not is_alive(attempt.pid):
        raise RuntimeError(f"attempt {attempt_id}'s process is no longer running -- its status was stale")
    os.kill(attempt.pid, signal.SIGSTOP)
    return attempts_mod.update_attempt(attempt_id, attempts_dir=attempts_dir, status="paused")


def resume_attempt(attempt_id: str, attempts_dir=DEFAULT_ATTEMPTS_DIR) -> DispatchAttempt:
    attempt = _load(attempt_id, attempts_dir)
    if attempt.status != "paused":
        raise RuntimeError(f"attempt {attempt_id} is '{attempt.status}', not paused -- nothing to resume")
    if attempt.pid is None or not is_alive(attempt.pid):
        raise RuntimeError(f"attempt {attempt_id}'s process is no longer running -- can't resume a dead process")
    os.kill(attempt.pid, signal.SIGCONT)
    return attempts_mod.update_attempt(attempt_id, attempts_dir=attempts_dir, status="running")


def kill_attempt(attempt_id: str, force: bool = False, attempts_dir=DEFAULT_ATTEMPTS_DIR) -> DispatchAttempt:
    """SIGTERM by default (lets the tool try to clean up); SIGKILL with
    force=True. A process paused with SIGSTOP can still be killed --
    SIGTERM/SIGKILL aren't blocked by a stop signal, unlike most others."""
    attempt = _load(attempt_id, attempts_dir)
    if attempt.status not in ("running", "paused"):
        raise RuntimeError(f"attempt {attempt_id} is '{attempt.status}' -- nothing to kill")
    if attempt.pid is None or not is_alive(attempt.pid):
        return attempts_mod.update_attempt(attempt_id, attempts_dir=attempts_dir, status="terminated")
    os.kill(attempt.pid, signal.SIGKILL if force else signal.SIGTERM)
    return attempts_mod.update_attempt(attempt_id, attempts_dir=attempts_dir, status="terminated")
