"""The `agent-hq` command surface. If you're new to AI agents: run
`agent-hq onboard` first -- it walks you through everything below without
needing to already know what any of these words mean."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from agent_hq import attempts as attempts_mod
from agent_hq import dispatch as dispatch_mod
from agent_hq import doctor as doctor_mod
from agent_hq import memory as memory_mod
from agent_hq import registry, tickets
from agent_hq import worktree as worktree_mod
from agent_hq.models import Agent

STATUS_EMOJI = {"open": "⚪", "assigned": "🔵", "in_progress": "🟡", "done": "🟢", "cancelled": "⚫"}

AGENTS_README = """\
Add one markdown file per agent you want to hire. Minimal shape:

---
id: my-agent
name: My Agent
runtime: claude_code   # or codex, cursor_agent, ollama, gemini_cli
tool_access: read_only  # read_only / standard / full -- see README
tags: [some, keywords]
risk_tier: low
---

Plain English: what does this agent do, and when should a ticket go to it?

Easier way: run `agent-hq onboard` or `agent-hq agent-hire` and answer a
few questions -- no YAML editing required.
"""


# --- onboarding & setup ------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    for d in ("agents", "tickets", "memory/decisions", "memory/lessons", "memory/preferences"):
        Path(d).mkdir(parents=True, exist_ok=True)
    readme = Path("agents/README.md")
    if not readme.exists():
        readme.write_text(AGENTS_README)
    print("Set up: agents/, tickets/, memory/")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    print("Checking what's installed on this machine...\n")
    print(doctor_mod.format_report(doctor_mod.check_all()))
    print(
        "\n✅ = found and this tool can try to use it right now.\n"
        "⚪ = not found -- you can still register an agent for it, you'll "
        "just need to install/run it first before dispatching for real.\n"
        "[verified] means the adapter code was checked against a real run "
        "of that tool during development. [documented only] means it was "
        "built from that tool's official docs but never actually run here."
    )
    return 0


def cmd_onboard(args: argparse.Namespace) -> int:
    print("=" * 70)
    print("Welcome to agent-hq.")
    print("=" * 70)
    print(
        "\nHere's the whole idea in plain English:\n"
        "  - An 'agent' is an AI tool (like Claude Code) registered with a\n"
        "    job description, so you don't have to remember its command-line\n"
        "    flags every time.\n"
        "  - A 'ticket' is a task you want done -- a title and a description.\n"
        "  - 'Dispatch' means: hand a ticket to an agent and let it work.\n"
    )
    cmd_init(args)
    print()
    cmd_doctor(args)

    print("\n" + "-" * 70)
    hire_now = input("\nRegister your first agent now? [Y/n] ").strip().lower()
    if hire_now in ("", "y", "yes"):
        _interactive_hire()

    print("\nYou're set up. Try:")
    print("  agent-hq agent-list")
    print("  agent-hq ticket-new --title \"...\" --tags a,b")
    print("  agent-hq dispatch <ticket-id> --agent <agent-id>")
    return 0


def _interactive_hire() -> None:
    print("\nA few quick questions -- press enter to accept the [default].")
    agent_id = input("Short id for this agent (e.g. 'my-claude-agent'): ").strip()
    name = input(f"Display name [{agent_id}]: ").strip() or agent_id
    print("\nWhich tool should this agent use?")
    print("  1) claude_code  -- Claude Code (verified)")
    print("  2) codex        -- OpenAI Codex (verified)")
    print("  3) ollama       -- a local Ollama model (verified)")
    print("  4) aider        -- Aider, terminal pair programmer (verified)")
    print("  5) opencode     -- OpenCode, model-agnostic CLI (verified)")
    print("  6) cursor_agent -- Cursor CLI (documented, flags confirmed live)")
    print("  7) gemini_cli   -- Gemini CLI (documented, flags confirmed live)")
    print("  8) lm_studio    -- LM Studio local server (documented, needs a GUI session to verify)")
    choice = input("Pick 1-8 [1]: ").strip() or "1"
    runtime = {
        "1": "claude_code", "2": "codex", "3": "ollama", "4": "aider",
        "5": "opencode", "6": "cursor_agent", "7": "gemini_cli", "8": "lm_studio",
    }.get(choice, "claude_code")
    purpose = input("In plain English, what should this agent be used for? ").strip()
    tags_raw = input("A few keywords to describe it, comma-separated: ").strip()
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    agent = Agent(id=agent_id, name=name, purpose=purpose or "General-purpose agent.", runtime=runtime, tags=tags)
    path = registry.new_agent(agent)
    print(f"\nRegistered {agent_id} -> {path}")


def cmd_agent_hire(args: argparse.Namespace) -> int:
    _interactive_hire()
    return 0


def cmd_agent_list(args: argparse.Namespace) -> int:
    agents = registry.load_agents()
    if not agents:
        print("No agents registered yet. Run `agent-hq onboard` or `agent-hq agent-hire`.")
        return 0
    for a in agents:
        tier = "verified" if a.verification == "verified" else "documented only"
        print(f"{a.id:<20} {a.name:<24} runtime={a.runtime:<13} tool_access={a.tool_access:<9} [{tier}]")
    return 0


# --- tickets ------------------------------------------------------------

def cmd_ticket_new(args: argparse.Namespace) -> int:
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else []
    ticket = tickets.new_ticket(title=args.title, tags=tags, body=args.body or "")
    print(f"Created ticket {ticket.id}: {ticket.title}")
    return 0


def cmd_ticket_list(args: argparse.Namespace) -> int:
    for t in tickets.list_tickets(status=args.status):
        emoji = STATUS_EMOJI.get(t.status, "?")
        print(f"{emoji} {t.id}  [{t.status:<11}] {t.title}  (assignee: {t.assignee or '-'})")
    return 0


def cmd_ticket_show(args: argparse.Namespace) -> int:
    ticket = tickets.load_ticket(args.ticket_id)
    print(f"{ticket.id}: {ticket.title}\n  status: {ticket.status}\n  assignee: {ticket.assignee or '(none)'}")
    if ticket.body:
        print(f"\n{ticket.body}")
    ticket_attempts = attempts_mod.list_attempts(ticket_id=ticket.id)
    if ticket_attempts:
        print("\n  dispatch attempts:")
        for a in ticket_attempts:
            print(f"    {a.id}  {a.status:<10} pid={a.pid}")
    return 0


def cmd_assign(args: argparse.Namespace) -> int:
    agents_map = registry.agents_by_id()
    if args.agent_id not in agents_map:
        print(f"{args.agent_id!r} isn't registered. See `agent-hq agent-list`.")
        return 1
    tickets.update_ticket(args.ticket_id, status="assigned", assignee=args.agent_id)
    print(f"Ticket {args.ticket_id} assigned to {args.agent_id}.")
    return 0


def cmd_dispatch(args: argparse.Namespace) -> int:
    ticket = tickets.load_ticket(args.ticket_id)
    agent_id = args.agent or ticket.assignee
    if not agent_id:
        print(f"Ticket {args.ticket_id} has no assignee. Pass --agent or run `assign` first.")
        return 1
    agents_map = registry.agents_by_id()
    agent = agents_map.get(agent_id)
    if agent is None:
        print(f"{agent_id!r} isn't registered. See `agent-hq agent-list`.")
        return 1

    if ticket.assignee != agent_id:
        tickets.update_ticket(args.ticket_id, status="assigned", assignee=agent_id)
        ticket = tickets.load_ticket(args.ticket_id)

    dispatch_mod.dispatch(agent, ticket, run=args.run)
    if args.run:
        tickets.update_ticket(args.ticket_id, status="in_progress")
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    ticket = tickets.update_ticket(args.ticket_id, status="done")
    tickets.append_ledger(ticket, args.summary)
    print(f"Closed {args.ticket_id}.")
    return 0


def cmd_board(args: argparse.Namespace) -> int:
    by_status = {}
    for t in tickets.list_tickets():
        by_status.setdefault(t.status, []).append(t)
    for status in ("open", "assigned", "in_progress", "done", "cancelled"):
        group = by_status.get(status, [])
        if not group:
            continue
        print(f"\n{STATUS_EMOJI[status]} {status.upper()} ({len(group)})")
        for t in group:
            print(f"  {t.id}  {t.title}" + (f" -> {t.assignee}" if t.assignee else ""))
    print()
    return 0


# --- worktree -------------------------------------------------------------

def cmd_worktree_list(args: argparse.Namespace) -> int:
    root = Path(".agent-hq/worktrees")
    if not root.exists():
        print("No worktrees created yet.")
        return 0
    for p in sorted(root.iterdir()):
        print(p)
    return 0


def cmd_worktree_remove(args: argparse.Namespace) -> int:
    if not args.repo:
        print("Pass --repo <path to the git repo the worktree was created from>.")
        return 1
    matches = [p for p in Path(".agent-hq/worktrees").glob(f"{args.ticket_id}-*")] if Path(".agent-hq/worktrees").exists() else []
    if not matches:
        print(f"No worktree found for ticket {args.ticket_id}.")
        return 1
    worktree_mod.remove_worktree(Path(args.repo), matches[0], force=args.force)
    print(f"Removed {matches[0]}")
    return 0


# --- memory -----------------------------------------------------------------

def cmd_memory_add(args: argparse.Namespace) -> int:
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else []
    entry = memory_mod.add(args.type, args.title, args.body or "", tags)
    print(f"Recorded {args.type} {entry.id}: {entry.title}")
    return 0


def cmd_memory_list(args: argparse.Namespace) -> int:
    for e in memory_mod.list_entries(args.type):
        print(f"[{e.type}] {e.id} {e.title}")
    return 0


def cmd_memory_search(args: argparse.Namespace) -> int:
    for e in memory_mod.search(args.query):
        print(f"[{e.type}] {e.id} {e.title}\n  {e.body[:120]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-hq")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("onboard", help="Guided setup for first-time users -- start here").set_defaults(func=cmd_onboard)
    sub.add_parser("init", help="Scaffold agents/, tickets/, memory/").set_defaults(func=cmd_init)
    sub.add_parser("doctor", help="Check which agent tools are installed on this machine").set_defaults(func=cmd_doctor)
    sub.add_parser("agent-hire", help="Interactively register a new agent, no YAML needed").set_defaults(func=cmd_agent_hire)
    sub.add_parser("agent-list", help="List registered agents").set_defaults(func=cmd_agent_list)
    sub.add_parser("board", help="Show the full ticket board").set_defaults(func=cmd_board)

    p_new = sub.add_parser("ticket-new", help="File a new ticket")
    p_new.add_argument("--title", required=True)
    p_new.add_argument("--tags", default="")
    p_new.add_argument("--body", default="")
    p_new.set_defaults(func=cmd_ticket_new)

    p_list = sub.add_parser("ticket-list", help="List tickets")
    p_list.add_argument("--status", default=None)
    p_list.set_defaults(func=cmd_ticket_list)

    p_show = sub.add_parser("ticket-show", help="Show a ticket's full detail")
    p_show.add_argument("ticket_id")
    p_show.set_defaults(func=cmd_ticket_show)

    p_assign = sub.add_parser("assign", help="Assign a ticket to an agent (no automatic routing -- pick one yourself)")
    p_assign.add_argument("ticket_id")
    p_assign.add_argument("agent_id")
    p_assign.set_defaults(func=cmd_assign)

    p_dispatch = sub.add_parser("dispatch", help="Dispatch a ticket. Prints by default; --run does it for real.")
    p_dispatch.add_argument("ticket_id")
    p_dispatch.add_argument("--agent", default=None, help="Override/set the assignee for this dispatch")
    p_dispatch.add_argument("--run", action="store_true")
    p_dispatch.set_defaults(func=cmd_dispatch)

    p_close = sub.add_parser("close", help="Close a ticket")
    p_close.add_argument("ticket_id")
    p_close.add_argument("--summary", required=True)
    p_close.set_defaults(func=cmd_close)

    sub.add_parser("worktree-list", help="List active worktrees").set_defaults(func=cmd_worktree_list)
    p_wt_rm = sub.add_parser("worktree-remove", help="Remove a ticket's worktree")
    p_wt_rm.add_argument("ticket_id")
    p_wt_rm.add_argument("--repo", required=True, help="Path to the git repo the worktree was created from")
    p_wt_rm.add_argument("--force", action="store_true", help="Remove even if it has uncommitted changes")
    p_wt_rm.set_defaults(func=cmd_worktree_remove)

    p_mem_add = sub.add_parser("memory-add", help="Record a decision, lesson, or preference")
    p_mem_add.add_argument("--type", choices=["decision", "lesson", "preference"], required=True)
    p_mem_add.add_argument("--title", required=True)
    p_mem_add.add_argument("--body", default="")
    p_mem_add.add_argument("--tags", default="")
    p_mem_add.set_defaults(func=cmd_memory_add)

    p_mem_list = sub.add_parser("memory-list", help="List memory entries")
    p_mem_list.add_argument("--type", choices=["decision", "lesson", "preference"], default=None)
    p_mem_list.set_defaults(func=cmd_memory_list)

    p_mem_search = sub.add_parser("memory-search", help="Search memory entries")
    p_mem_search.add_argument("query")
    p_mem_search.set_defaults(func=cmd_memory_search)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
