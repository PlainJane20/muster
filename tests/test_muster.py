"""Offline tests. Runtime adapter tests mock subprocess/HTTP calls (using
real captured output as fixtures where available -- see comments) rather
than spawning real claude/codex processes on every test run; worktree
tests use real `git` commands against a throwaway tmp_path repo, since
that's fully offline and deterministic."""

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from muster import attempts as attempts_mod  # noqa: E402
from muster import control as control_mod  # noqa: E402
from muster import dispatch as dispatch_mod  # noqa: E402
from muster import doctor as doctor_mod  # noqa: E402
from muster import memory as memory_mod  # noqa: E402
from muster import registry, tickets  # noqa: E402
from muster import worktree as worktree_mod  # noqa: E402
from muster.models import Agent, RuntimeResult  # noqa: E402
from muster.runtimes import (  # noqa: E402
    aider, claude_code, codex, cursor_agent, gemini_cli, lm_studio, ollama, opencode,
)

AGENT_FIXTURE = """---
id: test-agent
name: Test Agent
runtime: claude_code
tool_access: read_only
tags: [alpha, beta]
risk_tier: low
---

A fixture agent for tests.
"""


@pytest.fixture
def workspace(tmp_path):
    agents_dir = tmp_path / "agents"
    tickets_dir = tmp_path / "tickets"
    agents_dir.mkdir()
    tickets_dir.mkdir()
    (agents_dir / "test-agent.md").write_text(AGENT_FIXTURE)
    return agents_dir, tickets_dir


# --- registry / models -------------------------------------------------------

def test_registry_loads_agent(workspace):
    agents_dir, _ = workspace
    agents = registry.load_agents(agents_dir)
    assert len(agents) == 1
    assert agents[0].id == "test-agent"
    assert agents[0].verification == "verified"


def test_registry_skips_readme(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "README.md").write_text("not an agent file")
    (agents_dir / "test-agent.md").write_text(AGENT_FIXTURE)
    assert len(registry.load_agents(agents_dir)) == 1


def test_new_agent_round_trips(tmp_path):
    agents_dir = tmp_path / "agents"
    agent = Agent(id="a1", name="A1", runtime="ollama", purpose="Test purpose.", tags=["x"])
    registry.new_agent(agent, agents_dir=agents_dir)

    loaded = registry.agents_by_id(agents_dir)
    assert loaded["a1"].purpose == "Test purpose."
    assert loaded["a1"].tool_access == "read_only"  # default preserved


def test_agent_verification_property_matches_runtime():
    documented = Agent(id="c", name="C", runtime="cursor_agent", purpose="p")
    verified = Agent(id="v", name="V", runtime="codex", purpose="p")
    assert documented.verification == "documented"
    assert verified.verification == "verified"


def test_ollama_aider_opencode_are_verified_not_documented():
    """Promoted from documented-only to verified after actually installing
    each tool and running real dispatches against a local Ollama server --
    not asserted from the start."""
    for runtime in ("ollama", "aider", "opencode"):
        assert Agent(id=runtime, name=runtime, runtime=runtime, purpose="p").verification == "verified"


def test_gemini_cli_is_verified_not_documented():
    """Promoted from documented-only to verified after a real
    GEMINI_API_KEY was obtained and a real authenticated dispatch through
    this exact adapter returned a correct response -- not asserted from
    the start, and not the same as Cursor, which is still blocked by a
    missing credential."""
    assert Agent(id="gemini_cli", name="g", runtime="gemini_cli", purpose="p").verification == "verified"


# --- tickets ------------------------------------------------------------

def test_ticket_lifecycle(workspace):
    _, tickets_dir = workspace
    ticket = tickets.new_ticket(title="Do the thing", tags=["alpha"], body="Body.", tickets_dir=tickets_dir)
    assert ticket.id == "0001"
    assert ticket.status == "open"

    updated = tickets.update_ticket(ticket.id, tickets_dir, status="assigned", assignee="test-agent")
    assert updated.status == "assigned"
    assert tickets.list_tickets(tickets_dir, status="open") == []


def test_concurrent_ticket_creation_never_collides(workspace):
    _, tickets_dir = workspace

    def _file_one(i):
        return tickets.new_ticket(title=f"Ticket {i}", tickets_dir=tickets_dir)

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(_file_one, range(10)))

    ids = [t.id for t in results]
    assert len(ids) == len(set(ids)), f"collision: {ids}"


# --- memory -----------------------------------------------------------------

def test_memory_add_and_list(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_mod.add("lesson", "Test lesson", "Body text.", tags=["x"], memory_dir=memory_dir)
    memory_mod.add("decision", "Test decision", "Reasoning.", memory_dir=memory_dir)

    lessons = memory_mod.list_entries("lesson", memory_dir=memory_dir)
    assert len(lessons) == 1
    assert lessons[0].title == "Test lesson"

    everything = memory_mod.list_entries(memory_dir=memory_dir)
    assert len(everything) == 2


def test_memory_search_matches_title_body_and_tags(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_mod.add("lesson", "Worktree bug", "HEAD didn't exist yet.", tags=["git"], memory_dir=memory_dir)
    memory_mod.add("decision", "Unrelated", "Nothing to do with it.", memory_dir=memory_dir)

    assert len(memory_mod.search("worktree", memory_dir=memory_dir)) == 1
    assert len(memory_mod.search("head didn't", memory_dir=memory_dir)) == 1
    assert len(memory_mod.search("git", memory_dir=memory_dir)) == 1
    assert len(memory_mod.search("nonexistent", memory_dir=memory_dir)) == 0


# --- attempts -----------------------------------------------------------

def test_attempt_lifecycle(tmp_path):
    attempts_dir = tmp_path / "attempts"
    attempt = attempts_mod.record_attempt("0001", "test-agent", "prompt text", pid=123, attempts_dir=attempts_dir)
    assert attempt.status == "running"

    updated = attempts_mod.update_attempt(attempt.id, attempts_dir=attempts_dir, status="succeeded", result_text="ok")
    assert updated.status == "succeeded"
    assert attempts_mod.list_attempts(ticket_id="0001", attempts_dir=attempts_dir)[0].result_text == "ok"


# --- control (real OS processes and real signals, no mocking) ----------

def _process_state(pid: int) -> str:
    """'T' means stopped (SIGSTOP'd); anything else means running/sleeping.
    Real `ps` output, not a guess -- same macOS/Linux `ps -o state=` both
    understand."""
    result = subprocess.run(["ps", "-o", "state=", "-p", str(pid)], capture_output=True, text=True)
    return result.stdout.strip()


def test_pause_resume_kill_a_real_process(tmp_path):
    """No mocking: a real `sleep` process, paused with a real SIGSTOP,
    confirmed stopped via `ps`, resumed with a real SIGCONT, then killed
    -- proving control.py's signals actually reach a real OS process
    across what would ordinarily be two separate terminal invocations."""
    attempts_dir = tmp_path / "attempts"
    proc = subprocess.Popen(["sleep", "30"])
    try:
        attempt = attempts_mod.record_attempt("0001", "test-agent", "prompt", pid=proc.pid, attempts_dir=attempts_dir)

        paused = control_mod.pause_attempt(attempt.id, attempts_dir=attempts_dir)
        assert paused.status == "paused"
        assert _process_state(proc.pid) == "T"

        resumed = control_mod.resume_attempt(attempt.id, attempts_dir=attempts_dir)
        assert resumed.status == "running"
        assert _process_state(proc.pid) != "T"

        killed = control_mod.kill_attempt(attempt.id, attempts_dir=attempts_dir)
        assert killed.status == "terminated"
        proc.wait(timeout=5)
        assert control_mod.is_alive(proc.pid) is False
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_pause_raises_clearly_on_unknown_attempt(tmp_path):
    with pytest.raises(ValueError, match="no attempt found"):
        control_mod.pause_attempt("does-not-exist", attempts_dir=tmp_path / "attempts")


def test_pause_raises_clearly_when_not_running(tmp_path):
    attempts_dir = tmp_path / "attempts"
    attempt = attempts_mod.record_attempt("0001", "a", "p", pid=123, attempts_dir=attempts_dir)
    attempts_mod.update_attempt(attempt.id, attempts_dir=attempts_dir, status="succeeded")
    with pytest.raises(RuntimeError, match="not running"):
        control_mod.pause_attempt(attempt.id, attempts_dir=attempts_dir)


def test_resume_raises_clearly_when_not_paused(tmp_path):
    attempts_dir = tmp_path / "attempts"
    attempt = attempts_mod.record_attempt("0001", "a", "p", pid=123, attempts_dir=attempts_dir)
    with pytest.raises(RuntimeError, match="not paused"):
        control_mod.resume_attempt(attempt.id, attempts_dir=attempts_dir)


def test_kill_marks_terminated_without_crashing_when_process_already_dead(tmp_path):
    """The exact stale-status scenario this module is honest about: the
    recorded pid points at a process that's already gone (a real dead
    pid: spawn, wait for exit, then act on the stale record). Killing it
    should mark terminated cleanly, not raise a raw ProcessLookupError."""
    attempts_dir = tmp_path / "attempts"
    proc = subprocess.Popen(["true"])
    proc.wait()
    attempt = attempts_mod.record_attempt("0001", "a", "p", pid=proc.pid, attempts_dir=attempts_dir)
    result = control_mod.kill_attempt(attempt.id, attempts_dir=attempts_dir)
    assert result.status == "terminated"


# --- worktree (real git, no mocking) -----------------------------------------

@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
    return repo


def test_is_git_repo(git_repo, tmp_path):
    assert worktree_mod.is_git_repo(git_repo) is True
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    assert worktree_mod.is_git_repo(not_a_repo) is False


def test_create_and_remove_worktree(git_repo, tmp_path):
    worktrees_root = tmp_path / "worktrees"
    wt_path = worktree_mod.create_worktree(git_repo, "0001", worktrees_root=worktrees_root)
    assert wt_path.exists()
    assert (wt_path / "README.md").exists()  # checked out from the real commit

    worktree_mod.remove_worktree(git_repo, wt_path)
    assert not wt_path.exists()


def test_create_worktree_on_repo_with_no_commits_gives_clear_error(tmp_path):
    """The exact bug found during development: `git init` with zero
    commits has no HEAD to branch a worktree off of. The error must say
    that in plain language, not just relay git's raw stderr."""
    empty_repo = tmp_path / "empty"
    empty_repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=empty_repo, check=True)

    with pytest.raises(RuntimeError, match="has no commits yet"):
        worktree_mod.create_worktree(empty_repo, "0001", worktrees_root=tmp_path / "worktrees")


def test_list_worktrees(git_repo, tmp_path):
    worktrees_root = tmp_path / "worktrees"
    wt_path = worktree_mod.create_worktree(git_repo, "0001", worktrees_root=worktrees_root)
    listed = worktree_mod.list_worktrees(git_repo)
    assert wt_path.resolve() in [p.resolve() for p in listed]


def test_has_real_changes_detects_a_new_commit(git_repo, tmp_path):
    wt_path = worktree_mod.create_worktree(git_repo, "0001", worktrees_root=tmp_path / "worktrees")
    base = worktree_mod.current_head(wt_path)

    (wt_path / "new.txt").write_text("real change")
    subprocess.run(["git", "add", "."], cwd=wt_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "agent edit"], cwd=wt_path, check=True)

    assert worktree_mod.has_real_changes(wt_path, base) is True


def test_has_real_changes_detects_uncommitted_edits(git_repo, tmp_path):
    wt_path = worktree_mod.create_worktree(git_repo, "0001", worktrees_root=tmp_path / "worktrees")
    base = worktree_mod.current_head(wt_path)

    (wt_path / "README.md").write_text("edited but never committed")

    assert worktree_mod.has_real_changes(wt_path, base) is True


def test_has_real_changes_is_false_when_nothing_changed(git_repo, tmp_path):
    """The exact scenario this feature exists to catch: a tool reports
    success but the worktree is untouched -- see aider.py's docstring.
    Covered end-to-end at the dispatch level too, in
    test_dispatch_flags_reported_success_with_no_real_change below."""
    wt_path = worktree_mod.create_worktree(git_repo, "0001", worktrees_root=tmp_path / "worktrees")
    base = worktree_mod.current_head(wt_path)
    assert worktree_mod.has_real_changes(wt_path, base) is False


def test_has_real_changes_returns_none_when_base_commit_unknown(git_repo, tmp_path):
    wt_path = worktree_mod.create_worktree(git_repo, "0001", worktrees_root=tmp_path / "worktrees")
    assert worktree_mod.has_real_changes(wt_path, None) is None


def test_has_real_changes_ignores_dotfile_only_bookkeeping(git_repo, tmp_path):
    """The exact real bug found on the first live dispatch this feature
    ran against: Aider writes its own `.gitignore` as housekeeping
    ('Added .aider* to .gitignore'), which is an uncommitted change but
    not the requested one. A dotfile-only diff must not count as a real
    change, or this check would have missed the discrepancy it exists to
    catch."""
    wt_path = worktree_mod.create_worktree(git_repo, "0001", worktrees_root=tmp_path / "worktrees")
    base = worktree_mod.current_head(wt_path)

    (wt_path / ".gitignore").write_text(".aider*\n")

    assert worktree_mod.has_real_changes(wt_path, base) is False


# --- runtime adapters ---------------------------------------------------

REAL_CLAUDE_JSON = (
    '{"is_error":false,"session_id":"0cc73525-7969-45c1-868d-28a64836c35d",'
    '"total_cost_usd":0.03,"result":"hello world"}'
)


def test_claude_code_parses_real_captured_output():
    data = claude_code._parse_result_json(REAL_CLAUDE_JSON)
    assert data["result"] == "hello world"


def test_claude_code_never_uses_dangerous_flags():
    fake_process = MagicMock()
    fake_process.pid = 1
    fake_process.communicate.return_value = (REAL_CLAUDE_JSON, "")
    fake_process.returncode = 0

    with patch("subprocess.Popen", return_value=fake_process) as mock_popen:
        claude_code.run(prompt="hi", tool_access="full")

    args = mock_popen.call_args[0][0]
    assert "--dangerously-skip-permissions" not in args
    assert "--bare" not in args


def test_claude_code_raises_on_nonzero_exit():
    fake_process = MagicMock()
    fake_process.pid = 1
    fake_process.communicate.return_value = ("", "boom")
    fake_process.returncode = 1
    with patch("subprocess.Popen", return_value=fake_process):
        with pytest.raises(RuntimeError, match="exited 1"):
            claude_code.run(prompt="hi")


def test_codex_reads_output_last_message_file(tmp_path):
    fake_process = MagicMock()
    fake_process.pid = 1
    fake_process.communicate.return_value = ("banner text\n", "")
    fake_process.returncode = 0

    def fake_popen(cmd, **kwargs):
        # Codex writes to whatever -o path it's given -- simulate that.
        o_index = cmd.index("-o")
        Path(cmd[o_index + 1]).write_text("hello world")
        return fake_process

    with patch("subprocess.Popen", side_effect=fake_popen):
        result = codex.run(prompt="hi")

    assert result.result_text == "hello world"
    assert result.is_error is False


def test_codex_never_uses_dangerous_bypass_flag():
    fake_process = MagicMock()
    fake_process.pid = 1
    fake_process.communicate.return_value = ("", "")
    fake_process.returncode = 0

    def fake_popen(cmd, **kwargs):
        assert "--dangerously-bypass-approvals-and-sandbox" not in cmd
        return fake_process

    with patch("subprocess.Popen", side_effect=fake_popen):
        codex.run(prompt="hi", tool_access="full")


def test_ollama_parses_documented_response_shape():
    fake_response = MagicMock()
    fake_response.read.return_value = b'{"response": "hello world", "done": true}'
    fake_response.__enter__ = lambda self: fake_response
    fake_response.__exit__ = lambda *a: None

    with patch("urllib.request.urlopen", return_value=fake_response):
        result = ollama.run(prompt="hi")

    assert result.result_text == "hello world"
    assert result.pid is None  # HTTP call, no subprocess


def test_ollama_raises_clearly_when_unreachable():
    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
        with pytest.raises(RuntimeError, match="could not reach Ollama"):
            ollama.run(prompt="hi")


# --- dispatch (mocked runtime layer) -----------------------------------

def test_dispatch_prints_without_running(capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    agent = Agent(id="a", name="A", runtime="claude_code", purpose="p")
    ticket = tickets.new_ticket(title="T")
    result = dispatch_mod.dispatch(agent, ticket, run=False)
    assert result is None
    assert "Prepared" in capsys.readouterr().out


def test_dispatch_records_successful_attempt(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    agent = Agent(id="a", name="A", runtime="claude_code", purpose="p", cwd=None)
    ticket = tickets.new_ticket(title="T")

    fake_result = RuntimeResult(is_error=False, result_text="answer", returncode=0, pid=99)

    def fake_run(*, prompt, cwd, tool_access, model, pid_callback=None, **kw):
        if pid_callback:
            pid_callback(99)
        return fake_result

    with patch.object(dispatch_mod.claude_code, "run", side_effect=fake_run):
        attempt = dispatch_mod.dispatch(agent, ticket, run=True)

    assert attempt.status == "succeeded"
    assert attempt.result_text == "answer"


def test_dispatch_creates_worktree_for_git_backed_agent(git_repo, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    agent = Agent(id="a", name="A", runtime="claude_code", purpose="p", cwd=str(git_repo), use_worktree=True)
    ticket = tickets.new_ticket(title="T")

    fake_result = RuntimeResult(is_error=False, result_text="done", returncode=0, pid=1)
    seen_cwd = {}

    def fake_run(*, prompt, cwd, tool_access, model, pid_callback=None, **kw):
        seen_cwd["cwd"] = cwd
        if pid_callback:
            pid_callback(1)
        return fake_result

    with patch.object(dispatch_mod.claude_code, "run", side_effect=fake_run):
        attempt = dispatch_mod.dispatch(agent, ticket, run=True)

    assert attempt.worktree_path is not None
    assert seen_cwd["cwd"] == attempt.worktree_path
    assert Path(attempt.worktree_path).exists()  # left in place, not auto-removed


def test_dispatch_flags_reported_success_with_no_real_change(capsys, git_repo, monkeypatch, tmp_path):
    """The exact discrepancy a real Aider dispatch surfaced: exit 0 and
    'succeeded' with nothing actually changed in the worktree. dispatch()
    must catch this itself, not rely on a human noticing."""
    monkeypatch.chdir(tmp_path)
    agent = Agent(id="a", name="A", runtime="claude_code", purpose="p",
                  cwd=str(git_repo), use_worktree=True, tool_access="standard")
    ticket = tickets.new_ticket(title="T")

    fake_result = RuntimeResult(is_error=False, result_text="Applied edit", returncode=0, pid=1)

    def fake_run(*, prompt, cwd, tool_access, model, pid_callback=None, **kw):
        if pid_callback:
            pid_callback(1)
        return fake_result  # note: never actually touches the worktree

    with patch.object(dispatch_mod.claude_code, "run", side_effect=fake_run):
        attempt = dispatch_mod.dispatch(agent, ticket, run=True)

    assert attempt.status == "succeeded"
    assert attempt.filesystem_verified is False
    assert "WARNING" in capsys.readouterr().out


def test_dispatch_confirms_a_real_change(capsys, git_repo, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    agent = Agent(id="a", name="A", runtime="claude_code", purpose="p",
                  cwd=str(git_repo), use_worktree=True, tool_access="standard")
    ticket = tickets.new_ticket(title="T")

    fake_result = RuntimeResult(is_error=False, result_text="Applied edit", returncode=0, pid=1)

    def fake_run(*, prompt, cwd, tool_access, model, pid_callback=None, **kw):
        (Path(cwd) / "real-edit.txt").write_text("the agent actually did this")
        if pid_callback:
            pid_callback(1)
        return fake_result

    with patch.object(dispatch_mod.claude_code, "run", side_effect=fake_run):
        attempt = dispatch_mod.dispatch(agent, ticket, run=True)

    assert attempt.filesystem_verified is True
    assert "WARNING" not in capsys.readouterr().out


def test_dispatch_skips_filesystem_check_for_read_only(git_repo, monkeypatch, tmp_path):
    """read_only dispatches are supposed to leave the worktree untouched --
    flagging that as a discrepancy would be a false positive, not a real
    finding. filesystem_verified should stay None (not checked)."""
    monkeypatch.chdir(tmp_path)
    agent = Agent(id="a", name="A", runtime="claude_code", purpose="p",
                  cwd=str(git_repo), use_worktree=True, tool_access="read_only")
    ticket = tickets.new_ticket(title="T")

    fake_result = RuntimeResult(is_error=False, result_text="answer", returncode=0, pid=1)

    def fake_run(*, prompt, cwd, tool_access, model, pid_callback=None, **kw):
        if pid_callback:
            pid_callback(1)
        return fake_result

    with patch.object(dispatch_mod.claude_code, "run", side_effect=fake_run):
        attempt = dispatch_mod.dispatch(agent, ticket, run=True)

    assert attempt.filesystem_verified is None


# --- doctor ---------------------------------------------------------------

def test_doctor_check_all_reports_every_runtime():
    checks = doctor_mod.check_all()
    runtimes = {c.runtime for c in checks}
    assert runtimes == {
        "claude_code", "codex", "cursor_agent", "gemini_cli", "ollama",
        "aider", "opencode", "lm_studio",
    }


# --- aider / opencode / lm_studio (documented-tier) --------------------------

def test_aider_uses_yes_always_flag_only_for_standard_and_full():
    """--yes-always is the canonical name confirmed by --help; a live
    test also proved the abbreviated --yes works via argparse prefix
    matching, but this adapter uses the full name on purpose -- see the
    module docstring for why that distinction matters."""
    fake_process = MagicMock()
    fake_process.pid = 1
    fake_process.communicate.return_value = ("edited file.py", "")
    fake_process.returncode = 0

    with patch("subprocess.Popen", return_value=fake_process) as mock_popen:
        aider.run(prompt="fix the bug", tool_access="read_only")
    assert "--yes-always" not in mock_popen.call_args[0][0]

    with patch("subprocess.Popen", return_value=fake_process) as mock_popen:
        aider.run(prompt="fix the bug", tool_access="standard")
    assert "--yes-always" in mock_popen.call_args[0][0]


def test_aider_always_disables_repo_map():
    """The real, confirmed finding: repo-map construction caused an 8+
    minute hang against a small local model. --map-tokens 0 must always
    be present, not conditional on anything."""
    fake_process = MagicMock()
    fake_process.pid = 1
    fake_process.communicate.return_value = ("ok", "")
    fake_process.returncode = 0

    with patch("subprocess.Popen", return_value=fake_process) as mock_popen:
        aider.run(prompt="hi")
    args = mock_popen.call_args[0][0]
    assert "--map-tokens" in args
    assert args[args.index("--map-tokens") + 1] == "0"


# Real captured output from `opencode run "..." --format json --model
# ollama/llama3.2:1b` against a live local Ollama server (see
# ARCHITECTURE.md) -- not a hand-authored guess at the shape.
REAL_OPENCODE_NDJSON = (
    '{"type":"step_start","timestamp":1788240800110,"sessionID":"ses_1",'
    '"part":{"id":"prt_1","type":"step-start"}}\n'
    '{"type":"text","timestamp":1788240800121,"sessionID":"ses_1",'
    '"part":{"id":"prt_2","type":"text","text":"hello world"}}\n'
    '{"type":"step_finish","timestamp":1788240800121,"sessionID":"ses_1",'
    '"part":{"id":"prt_3","type":"step-finish","tokens":{"total":21}}}'
)


def test_opencode_parses_real_captured_ndjson_events():
    """The real shape: text lives at event['part']['text'] for
    type == 'text' events, not a top-level 'text' key -- confirmed live,
    not guessed. An earlier version of this parser assumed the top-level
    key and silently fell through to the raw-stdout fallback on this
    exact input."""
    fake_process = MagicMock()
    fake_process.pid = 1
    fake_process.communicate.return_value = (REAL_OPENCODE_NDJSON, "")
    fake_process.returncode = 0
    with patch("subprocess.Popen", return_value=fake_process):
        result = opencode.run(prompt="hi")
    assert result.result_text == "hello world"


def test_opencode_concatenates_multiple_text_events():
    fake_process = MagicMock()
    fake_process.pid = 1
    events = (
        '{"type":"text","part":{"type":"text","text":"hello "}}\n'
        '{"type":"text","part":{"type":"text","text":"world"}}'
    )
    fake_process.communicate.return_value = (events, "")
    fake_process.returncode = 0
    with patch("subprocess.Popen", return_value=fake_process):
        result = opencode.run(prompt="hi")
    assert result.result_text == "hello world"


def test_opencode_falls_back_to_raw_stdout_on_unparseable_output():
    fake_process = MagicMock()
    fake_process.pid = 1
    fake_process.communicate.return_value = ("not json at all", "")
    fake_process.returncode = 0
    with patch("subprocess.Popen", return_value=fake_process):
        result = opencode.run(prompt="hi")
    assert result.result_text == "not json at all"


def test_lm_studio_parses_openai_compatible_response():
    fake_response = MagicMock()
    fake_response.read.return_value = b'{"choices": [{"message": {"content": "hello world"}}]}'
    fake_response.__enter__ = lambda self: fake_response
    fake_response.__exit__ = lambda *a: None

    with patch("urllib.request.urlopen", return_value=fake_response):
        result = lm_studio.run(prompt="hi")
    assert result.result_text == "hello world"
    assert result.pid is None


def test_lm_studio_raises_clearly_on_unexpected_shape():
    fake_response = MagicMock()
    fake_response.read.return_value = b'{"unexpected": "shape"}'
    fake_response.__enter__ = lambda self: fake_response
    fake_response.__exit__ = lambda *a: None

    with patch("urllib.request.urlopen", return_value=fake_response):
        with pytest.raises(RuntimeError, match="unexpected LM Studio response shape"):
            lm_studio.run(prompt="hi")


# --- gemini_cli (real error shape confirmed, success shape still assumed) ---

# Real captured output from an actual unauthenticated `gemini -p ...
# --output-format json --skip-trust` run -- confirms the error JSON shape
# and that the exit code equals error.code (41 here), not a fixed enum.
REAL_GEMINI_ERROR_JSON = (
    '{"session_id": "909e6cda-97c3-4e62-863b-5a3c3148b1bc", '
    '"error": {"type": "Error", "message": "Please set an Auth method", "code": 41}}'
)


def test_gemini_cli_raises_with_real_error_shape():
    fake_process = MagicMock()
    fake_process.pid = 1
    fake_process.communicate.return_value = (REAL_GEMINI_ERROR_JSON, "")
    fake_process.returncode = 41
    with patch("subprocess.Popen", return_value=fake_process):
        with pytest.raises(RuntimeError, match="code 41"):
            gemini_cli.run(prompt="hi")


def test_gemini_cli_always_passes_skip_trust():
    """A real read_only dispatch (no --approval-mode sent at all) still
    failed outright with exit 55 in an untrusted directory unless
    --skip-trust was present -- confirmed live, not a guess. Gemini CLI
    doesn't just downgrade a requested approval mode in that case, it
    refuses to run headlessly at all. --skip-trust must be sent on every
    invocation, independent of tool_access."""
    fake_process = MagicMock()
    fake_process.pid = 1
    fake_process.communicate.return_value = ('{"response": "ok"}', "")
    fake_process.returncode = 0

    with patch("subprocess.Popen", return_value=fake_process) as mock_popen:
        gemini_cli.run(prompt="hi", tool_access="read_only")
    args = mock_popen.call_args[0][0]
    assert "--approval-mode" not in args
    assert "--skip-trust" in args

    with patch("subprocess.Popen", return_value=fake_process) as mock_popen:
        gemini_cli.run(prompt="hi", tool_access="standard")
    args = mock_popen.call_args[0][0]
    assert "--approval-mode" in args and "auto_edit" in args
    assert "--skip-trust" in args


def test_gemini_cli_full_uses_yolo_not_a_full_bypass_flag():
    fake_process = MagicMock()
    fake_process.pid = 1
    fake_process.communicate.return_value = ('{"response": "ok"}', "")
    fake_process.returncode = 0
    with patch("subprocess.Popen", return_value=fake_process) as mock_popen:
        gemini_cli.run(prompt="hi", tool_access="full")
    args = mock_popen.call_args[0][0]
    assert "yolo" in args
    assert "--dangerously-skip-permissions" not in args


# --- cursor_agent (flags now confirmed real; response shape still unauthenticated) ---

def test_cursor_agent_never_uses_full_yolo_alias():
    """--yolo is a real, documented alias for --force (confirmed against
    the real --help). This adapter uses --force explicitly rather than
    the alias, for the same 'use the name a --help reader expects'
    reasoning as aider's --yes-always."""
    fake_process = MagicMock()
    fake_process.pid = 1
    fake_process.communicate.return_value = ('{"result": "ok"}', "")
    fake_process.returncode = 0
    with patch("subprocess.Popen", return_value=fake_process) as mock_popen:
        cursor_agent.run(prompt="hi", tool_access="full")
    args = mock_popen.call_args[0][0]
    assert "--force" in args
    assert "--yolo" not in args


def test_cursor_agent_raises_on_real_auth_error_shape():
    """Real captured behavior: an unauthenticated cursor-agent exits
    non-zero with a plain-text stderr message (confirmed live), not a
    JSON error body -- unlike gemini_cli. This adapter's generic
    non-zero-exit handling covers it correctly without special-casing."""
    fake_process = MagicMock()
    fake_process.pid = 1
    fake_process.communicate.return_value = (
        "", "Error: Authentication required. Please run 'agent login' first, "
        "or set CURSOR_API_KEY environment variable.",
    )
    fake_process.returncode = 1
    with patch("subprocess.Popen", return_value=fake_process):
        with pytest.raises(RuntimeError, match="Authentication required"):
            cursor_agent.run(prompt="hi")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
