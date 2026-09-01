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

from agent_hq import attempts as attempts_mod  # noqa: E402
from agent_hq import dispatch as dispatch_mod  # noqa: E402
from agent_hq import doctor as doctor_mod  # noqa: E402
from agent_hq import memory as memory_mod  # noqa: E402
from agent_hq import registry, tickets  # noqa: E402
from agent_hq import worktree as worktree_mod  # noqa: E402
from agent_hq.models import Agent, RuntimeResult  # noqa: E402
from agent_hq.runtimes import claude_code, codex, ollama  # noqa: E402

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


# --- doctor ---------------------------------------------------------------

def test_doctor_check_all_reports_every_runtime():
    checks = doctor_mod.check_all()
    runtimes = {c.runtime for c in checks}
    assert runtimes == {"claude_code", "codex", "cursor_agent", "gemini_cli", "ollama"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
