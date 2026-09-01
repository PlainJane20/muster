# Architecture notes

The "why," not just the "what." Same house style as this portfolio's other
tools: this document is what I'd defend in a design review, not a second
copy of the README.

## Why `tool_access` is a 3-level dial, not raw CLI flags

Claude Code has `--permission-mode` with six values. Codex has `--sandbox`
with three. Cursor has `--force`/`--yolo`. Every one of them means
something slightly different, and none of them are things a beginner
should have to learn just to register an agent safely. `tool_access:
read_only / standard / full` is one concept that means the same thing
regardless of which runtime an agent uses, and each adapter translates it
into the right flag for that specific tool. The cost is some precision --
Codex's three sandbox levels and Claude Code's six permission modes don't
map perfectly onto three tiers. The benefit is that "how much can this
agent actually do" is one honest question with one honest answer,
independent of which tool answers it.

## Why two runtimes are "verified" and six are "documented," and why that distinction is load-bearing

It would have been easy to build eight adapters from eight sets of
official docs and claim "8 runtimes." Instead:

- **claude_code** and **codex**: every flag was checked against that
  tool's own `--help` output on the actual installed CLI, and each was
  proven with a real invocation before being trusted. `claude_code`'s
  JSON parser was built from one real `claude -p ... --output-format
  json` response, not assumed. `codex`'s `--output-last-message` pattern
  was chosen specifically because a real run showed stdout is full of
  banner text ahead of the actual answer.
- **cursor_agent**, **ollama**, **gemini_cli**, **aider**, **opencode**,
  **lm_studio**: none of these tools were installed or running in the
  environment this was developed in. Each is built from that tool's
  official documentation, and each adapter's docstring says exactly that,
  plus any specific gaps found in that documentation -- and the gaps
  differ in kind, not just degree:
  - Gemini CLI's docs don't cover a working-directory flag or an
    auto-approval flag at all (see below).
  - Aider's scripting docs don't say what happens to a proposed edit when
    nothing can answer its confirmation prompt -- `read_only` here is a
    guess at safe behavior, not a confirmed one.
  - OpenCode's own docs describe `--format json` as "raw JSON events"
    (plural), not a single response object -- the parser tries one JSON
    object, then newline-delimited events, then falls back to raw stdout,
    and that fallback chain is itself a guess at the real shape.
  - LM Studio's docs describe the endpoint as OpenAI-compatible, which is
    a safe assumption (it's about as stable a JSON shape as exists) but
    still one step short of a confirmed real response.

`Agent.verification` surfaces the verified/documented split on every
agent, in `agent-hq agent-list`, and in `agent-hq doctor` -- but within
"documented," the *specific* gap for each adapter lives in that adapter's
own docstring, not flattened into one generic disclaimer. The alternative
-- one flat "supported runtimes" list -- would let a documented-but-never-
run adapter look exactly as trustworthy as one that's actually been
exercised, and would hide that some documented adapters are gappier than
others. That's the same failure mode this whole portfolio has been built
to avoid since the very first comparison to Livery: a "5 adapters" claim
that sounds complete while being partly untested is worse than an honest
"2 verified, 6 not, and here's specifically why" claim that's actually true.

## Why Gemini CLI only implements `read_only`, and Aider's `read_only` is the least trustworthy setting in the registry

Google's headless-mode docs (fetched during development) document exit
codes precisely (0/1/42/53) but say nothing about a working-directory flag
or an auto-approval/"yolo" flag for unattended tool use. Implementing
`standard`/`full` anyway would mean either guessing a flag that might not
exist, or sending no approval flag at all and risking a dispatch that
hangs forever waiting for an interactive prompt nothing in this pipeline
can answer. `gemini_cli.run()` raises `NotImplementedError` for anything
but `read_only`, with the reason stated in the exception message itself --
a documentation gap became a real, enforced constraint in the code,
instead of a footnote nobody reads before the first hung dispatch.

Aider's situation is the opposite kind of gap, and arguably worse:
`read_only` here means "run without `--yes`," but Aider's own scripting
docs never say what actually happens to a proposed edit when there's no
terminal to answer its confirmation prompt in a non-interactive context.
Unlike Gemini CLI, there was no clean way to turn this into a hard
`NotImplementedError` -- the uncertainty is inherent to the tool's
documented behavior, not a missing flag this code can refuse to guess at.
This is named explicitly, here and in the adapter's own docstring, rather
than left for `tool_access: read_only` to imply a safety guarantee the
documentation doesn't actually back up.

## Why worktrees are created before the run and left in place after

Two decisions, for the same underlying reason -- isolation should be
inspectable, not just automatic:

1. **Created before, not lazily**: `dispatch()` creates the worktree and
   only then runs the agent inside it, so the `DispatchAttempt` record's
   `worktree_path` is always accurate for a run that used one, never a
   guess about where the isolation *would* have happened.
2. **Left in place, not auto-removed**: an agent with `tool_access:
   standard` or `full` can produce real work -- new files, edits, a
   branch worth reviewing or merging. Auto-deleting the worktree the
   moment the dispatch finishes would silently discard that. `worktree
   remove` is a separate, explicit command specifically so "did the agent
   actually produce something I want" is a question a human answers, not
   a default the tool assumes.

## A real bug found in exactly the way this section describes

`create_worktree` was tested against this repo itself, freshly
`git init`-ed with zero commits, dispatching a real file-editing ticket to
a real Claude Code agent. It failed:

```
git worktree add failed: Preparing worktree (new branch 'agent-hq/0003-...')
fatal: not a valid object name: 'HEAD'
```

A fresh repo has no HEAD to branch a worktree off of -- obvious in
hindsight, not something written defensively in advance. The fix: catch
that specific git error and explain it in plain language instead of
relaying git's raw stderr, which is exactly the kind of message this
tool's "savvy for beginners" goal exists to prevent. `test_create_
worktree_on_repo_with_no_commits_gives_clear_error` exists so this
doesn't regress silently.

## Why this doesn't do automatic routing

[switchboard](https://github.com/PlainJane20/switchboard) — a separate
project in this portfolio — already does exactly that: deterministic
tag-match routing with a Claude-assisted fallback and a routing-correction
memory loop. Rebuilding that here would either duplicate it or force this
project's ticket model to carry routing metadata it doesn't otherwise
need. `assign` here is deliberately manual, matching Livery's own
`assignee` field -- the two projects in this portfolio compose rather than
overlap: switchboard could, in principle, decide *which* agent-hq agent a
ticket goes to, while agent-hq handles the actual live dispatch and
worktree isolation. That composition isn't built, but the separation of
concerns is deliberate, not an oversight.

## The honest comparison to Livery, restated

Livery has more of everything that isn't runtime verification: 5 adapters
all presumably exercised in real use, scheduling, Talk, Walkie-Talkie,
Telegram, and actual production mileage. agent-hq's answer isn't "we did
all of that too" -- it's two things done and proven (worktree isolation,
two genuinely verified live runtimes) plus an honest accounting of
everything that's documented-only or not attempted at all. A shorter,
truthful feature list is worth more than a longer one with gaps papered
over -- which is the same principle this portfolio's very first comparison
to Livery was built on, applied here to a bigger, riskier build instead of
a narrow one.
