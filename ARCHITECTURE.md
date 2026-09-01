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

## Why six runtimes are "verified" and two are "documented," and why that distinction is load-bearing

It would have been easy to build eight adapters from eight sets of
official docs and claim "8 runtimes." Instead, verification started at
two (claude_code, codex -- both installed in the original development
environment) and grew to six by actually installing four more (ollama,
aider, opencode, gemini_cli) and running real dispatches against them,
rather than leaving "documented" as a permanent label for a tool that was
simply never tried. The one remaining fully-blocked runtime beyond that
(cursor_agent) got a real install/CLI-verification attempt too, and hit a
disclosed, concrete wall short of a full dispatch -- not "never tried,"
just "tried and blocked by something specific." lm_studio's wall is
different in kind, not credentials-shaped at all -- see below. See the
next two sections for exactly what that testing found.

- **claude_code**, **codex**, **ollama**, **aider**, **opencode**,
  **gemini_cli**: every flag was checked against that tool's own
  `--help`/official reference, and each was proven with a real invocation
  before being trusted. `claude_code`'s JSON parser was built from one
  real `claude -p ... --output-format json` response. `codex`'s
  `--output-last-message` pattern was chosen because a real run showed
  stdout is full of banner text ahead of the actual answer. `ollama`,
  `aider`, `opencode`, and `gemini_cli` were each verified after initially
  shipping as documented-only -- all four required actually installing
  the tool, and `gemini_cli` additionally required getting a real
  `GEMINI_API_KEY` and completing a real authenticated dispatch through
  the full ticket -> assign -> dispatch pipeline before it could be
  trusted, not just the tool being installed.
- **cursor_agent**, **lm_studio**: real install attempts were made for
  both, and the gaps that remain differ in kind from each other:
  - Cursor CLI is installed and every flag this adapter uses was
    confirmed against the real `--help` output -- the original docs this
    adapter was built from turned out to be accurate. The only thing not
    confirmed is the *success* response shape, because cursor-agent has
    no free tier and a `CURSOR_API_KEY` requires a paid subscription.
    Gemini CLI had the exact same shape of gap and got promoted to
    verified once a real (free) key was obtained; Cursor's was left
    open by deliberate choice -- getting a paid Cursor subscription just
    to finish this one adapter's verification wasn't judged worth it,
    and that's stated here rather than left implicit.
  - LM Studio's cask genuinely installed (`brew install --cask
    lm-studio`, confirmed with `brew info`), but it's a GUI-first
    Electron app with no headless mode, and this environment has no
    window-server session for it to run in -- a structural gap, not a
    credentials gap. See below.

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
"6 verified, 2 not, and here's specifically why" claim that's actually true.

## Why Gemini CLI's tool_access mapping changed after real testing

The original version of this adapter raised `NotImplementedError` for
anything but `read_only`, on the reasoning that Google's headless-mode
docs (as summarized by a secondary source consulted during development)
didn't document a working-directory flag or an auto-approval flag, and
guessing one risked a dispatch hanging forever on an interactive prompt.
Installing the real CLI and reading its actual `--help` output showed
that reasoning was built on incomplete information: `--approval-mode
{default,auto_edit,yolo,plan}` and `--include-directories` are both real,
documented-in-`--help` flags. The adapter now maps `standard` to
`--approval-mode auto_edit` and `full` to `--approval-mode yolo`.

That still undersold the actual behavior, and a second round of testing
-- this time with a real `GEMINI_API_KEY`, not just a live but
unauthenticated CLI -- corrected it further: `--skip-trust` isn't only
needed *alongside* a non-default approval mode to stop it silently
reverting to `default`. It's needed unconditionally. A real dispatch at
`read_only` (which sends no `--approval-mode` flag at all) still failed
outright with exit 55 and a plain-text refusal ("Gemini CLI is not
running in a trusted directory") -- Gemini CLI won't run headlessly in an
untrusted directory at all, regardless of which approval mode was
requested or whether one was requested. The adapter now sends
`--skip-trust` on every invocation. The lesson generalizes past this one
adapter, twice over: a documented-only claim is only as good as the
documentation actually consulted (a summary of a doc is not the doc), and
even a "confirmed live" claim can still be incomplete if it was only
confirmed up to the point testing was able to reach -- getting the actual
credential to go one step further surfaced a real gap the earlier,
unauthenticated testing pass couldn't have found.

## What actually happened when a real GEMINI_API_KEY was obtained

Every other Gemini CLI finding up to this point came from installing and
invoking the CLI without a working credential -- enough to confirm flags,
error shapes, and the trust-related failure modes, but not enough to
prove a real dispatch could complete successfully. Getting an actual
`GEMINI_API_KEY` from Google AI Studio (a real personal account, a real
project, a real generated key) and re-running the same `read_only`
dispatch immediately hit the `--skip-trust`-is-unconditional bug above --
which only became visible *because* authentication succeeded far enough
to reach that check. Fixing it and rerunning produced a correct response
("hello world" for a prompt asking for exactly that), both through the
raw adapter function directly and through the full CLI pipeline (a real
ticket, assigned to a real agent, dispatched with `--run`, closed with an
honest summary). `gemini_cli` moved from "documented, corrected live" to
fully verified on the strength of that -- the same bar `ollama`, `aider`,
and `opencode` were held to, not a lower one because it took two rounds
of testing to get there.

## What actually happened when Ollama and Aider were installed for real

Ollama was the easy case: `brew install ollama`, `ollama pull
llama3.2:1b`, then calling `ollama.run()` unchanged against the real
server. It worked on the first try -- a real response came back, correctly
parsed. Nothing in the adapter needed to change. "Documented" became
"verified" in about five minutes, which is itself worth noting: staying
at "documented" for a tool this simple to actually install would have
been laziness dressed up as caution.

Aider was not the easy case, and testing it live surfaced three distinct
things -- one non-bug, one real bug, and one finding sharper than either:

1. **A flag that looked wrong wasn't.** `--yes` doesn't appear in
   `--help`'s output (only `--yes-always` does), which looked like a
   leftover from an earlier, incorrect draft of this adapter. A live test
   with `--yes` proved it actually works -- argparse's default
   unambiguous-prefix matching resolves it to `--yes-always`, confirmed
   with a real file edit that applied and committed cleanly. The adapter
   uses the full `--yes-always` name anyway (it's what a reader checking
   this against `--help` would expect), but the record here is honest
   that the abbreviated form was never actually broken -- a "looks like a
   bug" that a live test closed out rather than confirmed.
2. **A real bug: repo-map construction hung for 8+ minutes with zero
   output.** Dispatching a simple text prompt to Aider inside a real git
   repo, against the small local model, produced nothing -- no error, no
   progress, no timeout -- for over eight minutes. The process was alive
   the whole time (about 5 seconds of actual CPU use across those 8
   minutes -- waiting, not working), and a parallel direct call to the
   same Ollama model stalled too, consistent with Ollama serializing
   requests to one model while repo-map ranking held a request open.
   `--map-tokens 0` disables just the repo-map step, not git integration
   generally, and the identical command then completed correctly in
   seconds. The adapter now passes `--map-tokens 0` unconditionally.
3. **The sharpest finding: exit 0 and "Applied edit" don't mean the edit
   happened.** A live dispatch through the *full* agent-hq pipeline
   (ticket → worktree → aider → local model, `tool_access: standard`)
   printed "Applied edit to README.md" and returned successfully. `git
   log` in that worktree afterward showed no new commit at all -- the
   small model's response mixed real content with echoed formatting
   instructions, aider's parser apparently couldn't reconcile that into
   an actual change, and reported success regardless. This means a
   `DispatchAttempt` with `status: succeeded` is proof the tool ran
   without erroring, not proof the requested change exists on disk.
   Nothing in `dispatch()` currently cross-checks this against real
   filesystem state -- named explicitly in [What's next](README.md#whats-next)
   rather than quietly left for a future user to discover the hard way.

## What actually happened when OpenCode was installed for real

`npm install -g opencode-ai` (v1.18.25), pointed at the same local Ollama
server used for `aider`. Two real things turned up, neither of which
`--help` would have surfaced, because they're config and output-format
details rather than flags:

1. **A model name that resolves in principle doesn't mean it's reachable.**
   `--model ollama/llama3.2:1b` failed with `ProviderModelNotFoundError:
   Did you mean: ollama-cloud?` -- OpenCode's built-in "ollama" provider
   points at a cloud offering, not a local server. Reaching the real local
   instance required a custom provider block in
   `~/.config/opencode/opencode.jsonc` pointing `baseURL` at
   `http://localhost:11434/v1` via the `@ai-sdk/openai-compatible`
   provider -- host configuration outside anything `run()` can set up on
   a user's behalf, so it's documented rather than silently assumed away.
2. **The untested parser guessed the wrong field, and the fallback chain
   caught it without erroring.** OpenCode's docs describe `--format json`
   as "raw JSON events" with no worked example. An initial guess assumed
   generated text lived at a top-level `text` key on each event; a real
   captured run showed it actually lives at `event["part"]["text"]` for
   `type == "text"` events. The wrong guess never crashed -- it silently
   fell through to the raw-stdout fallback, which is exactly the failure
   mode that fallback chain exists to catch, and exactly why it needed
   checking against real captured output before being trusted, not just
   because it didn't error.

## What actually happened when Cursor CLI, Gemini CLI, and LM Studio were investigated

Prompted directly by being asked whether "documented" runtimes could
actually be tested rather than left as disclosed guesses -- twice, once
for the first six documented-only runtimes and again, after three of
those were promoted, for the remaining ones.

**Cursor CLI**: installed via the official install script (`curl
https://cursor.com/install -fsS | bash`, version
2026.08.31-4057e58). Every flag this adapter uses (`--print`,
`--output-format json`, `--trust`, `--workspace`, `--force`, `--model`)
was confirmed verbatim in the real `--help` output -- a useful negative
result, since it means the original docs-only version of this adapter was
already correct, unlike Gemini CLI's. The real, unauthenticated failure
mode was also confirmed live: a plain non-zero exit with a plain-text
stderr message (`Error: Authentication required...`), not a JSON error
body -- so the adapter's existing generic non-zero-exit handling already
covers it correctly. What's still unconfirmed is the *successful* JSON
response shape, since cursor-agent has no free tier -- a `CURSOR_API_KEY`
requires a paid subscription. Unlike Gemini CLI's gap, which closed once
a free key was obtained, this one is a deliberate stop: not worth paying
for a Cursor subscription solely to finish this adapter's verification.
`cursor_agent` stays "documented, flags/errors confirmed live" on that
basis -- disclosed as a cost decision, not a leftover TODO.

**Gemini CLI**: installed via `npm install -g @google/gemini-cli`
(v0.57.0). The *original* adapter's documented-only claims were
themselves built on an incomplete secondary source, and installing the
real CLI caught that. This one didn't stay in the "flags confirmed,
success shape unconfirmed" state Cursor is still in -- a real
`GEMINI_API_KEY` was obtained afterward and used to complete an actual
authenticated dispatch, which surfaced one more real bug
(`--skip-trust`'s unconditional requirement) before finally succeeding.
See the two sections above for the full detail; `gemini_cli` is now fully
verified, not just "confirmed live short of a credential."

**LM Studio**: `brew install --cask lm-studio` genuinely installed it
(v0.4.23, confirmed via `brew info lm-studio`) -- but LM Studio is a
GUI-first Electron desktop app, and this development environment has no
interactive window-server session for it to attach to. `open -a "LM
Studio"` returns exit 0 with no process ever appearing in `ps aux`, and
launching the app's binary directly falls all the way through Electron
into its embedded Node.js runtime's own bare `--help`/arg-parsing output
instead of ever starting the app -- confirmed by literally getting Node's
usage text back as the result. Because the app never completes first-run
setup, `~/.lmstudio` (where its `lms` CLI and local inference server
would live) is never created. This is a categorically different blocker
than Cursor's: Cursor is one API key away from a full dispatch (Gemini
CLI had the identical gap and closed it once a key was obtained); LM
Studio needs an actual desktop session, which no amount of further
installing in a CLI-only environment produces. It stays documented-only,
and the adapter's docstring says exactly why, rather than a generic "not
installed" note.

## Why filesystem_verified exists, and the two real bugs found building it

Aider's live-testing round (above) surfaced the sharpest finding in this
whole project: a `DispatchAttempt` with `status: succeeded` proves the
tool didn't error, not that the change it claims to have made actually
exists. That was left as a documented, unverified gap for a while --
naming the problem precisely, but not fixing it. This closes it.

The design: `dispatch()` now records the worktree's HEAD commit right
after creating it, before the runtime touches anything (`base_commit` in
`dispatch.py`). After a `standard`/`full` dispatch reports success,
`worktree.has_real_changes(worktree_path, base_commit)` checks whether
the worktree's HEAD moved past `base_commit`, or failing that, whether
`git status --porcelain` shows any uncommitted change. The result lands
on `DispatchAttempt.filesystem_verified` (`True`/`False`/`None`), and a
`False` result prints an explicit warning at dispatch time instead of
waiting for a human to notice via `git log` later, the way the original
Aider discrepancy was found.

`read_only` dispatches are exempt on purpose -- they're not supposed to
change anything, so applying this check there would flag every single
one as a false "problem." `filesystem_verified` stays `None` (not
checked) for read_only, no worktree, or a failed attempt -- it's only
meaningful where a change was actually possible.

Building this against real dispatches (not just mocks) immediately
surfaced two more real bugs, both fixed before this feature shipped:

1. **Tool-generated housekeeping files initially counted as "a real
   change."** The very first live dispatch this ran against was Aider,
   reporting "Applied edit to README.md" and exiting 0 -- exactly the
   original discrepancy. But the check *passed* it as `True` anyway: the
   only uncommitted change in the worktree was Aider's own `.gitignore`,
   written as housekeeping ("Added .aider* to .gitignore"), unrelated to
   the requested edit. `has_real_changes` now filters uncommitted changes
   to non-dotfiles before counting them -- confirmed by rerunning the
   identical dispatch and watching the warning correctly appear once that
   filter was in place.
2. **A real, correctly-detected change can still be the wrong one.** A
   follow-up live dispatch, asking Aider to append a line to README.md,
   instead committed a new file literally named `Verified by agent-hq.`
   with no content. `filesystem_verified` read `True` -- a real commit
   did happen, so the check did its job -- but it wasn't the requested
   change. This is now a stated scope boundary in both `worktree.py`'s
   and `models.py`'s docstrings, not a false claim of correctness:
   `filesystem_verified` answers "did the tool do something real," which
   is strictly more than exit-code-and-stdout proves, but it is not and
   was never meant to be a correctness check on *what* the tool did.

## Why control.py is signals against a real PID, not a control-plane daemon

A much larger spec was proposed for this project at one point: a
persistent Node.js/Go control-plane daemon, a WebSocket/gRPC telemetry
ingestion bus, a dashboard UI with embedded terminal emulation
(xterm.js), resource-capped process supervision, an MCP interceptor
middleware layer, and a file-lock registry with sub-100ms collision
alerts. All real, legitimate things a bigger multi-agent orchestration
product might have. None of it got built, and that was a deliberate
scoping call, not a shortcut:

- It's the opposite of this repo's actual selling point. Every other
  design decision in this document leads back to "no server, no
  database, read every line" -- Livery doesn't have one either, and this
  project's entire positioning against it depends on staying that way.
  A persistent daemon plus a dashboard UI is a different *kind* of
  project, not a bigger version of this one.
- It's a multi-week rebuild across a real backend service and a real
  frontend app, not a session's worth of incremental work -- accepting
  it silently would have meant quietly abandoning the project's own
  stated scope ("lean but real," chosen explicitly early on) without
  saying so.

What was kept: the one piece of that spec with a real, honest answer
that fits the existing architecture as-is. `dispatch()` already spawns
the actual runtime subprocess (Claude Code, Aider, whatever the agent
uses) and records its real PID in `DispatchAttempt.pid` -- that's been
true since the very first version of this tool. Unix signals don't need
a daemon to reach a PID; they work against a real OS process from any
other process on the same machine, including a second, completely
separate `agent-hq` invocation in another terminal. So `control.py` is
exactly that: `agent-hq pause <attempt_id>` looks up the attempt's real
PID and sends it a real `SIGSTOP`; `resume` sends `SIGCONT`; `kill` sends
`SIGTERM` (or `SIGKILL` with `--force`). No process supervisor, no
telemetry bus, no persistent service of any kind -- confirmed with a
real `sleep` process in tests (checking `ps`'s own state field, not a
guess) and again manually against a real ticket (0010) before shipping.

One limitation stated plainly rather than glossed over: pausing the
underlying process doesn't reach into the *original* `dispatch --run`
invocation's Python call stack -- that call is still blocked inside
`subprocess.communicate()`, waiting for the (now-paused) child to
produce output or exit. Pausing just freezes the real work; the original
foreground command keeps waiting the same way it always did, and only it
still writes the final `succeeded`/`failed` status once the process
resumes and actually finishes. `paused`/`terminated` are interim states
set by a second, independent invocation acting on the durable attempt
record -- a real capability, honestly scoped to what's possible without
building the daemon that was asked for.

What was explicitly *not* attempted, and why each is a real gap rather
than an oversight:

- **Resource limits (CPU/memory caps)**: implementable via
  `resource.setrlimit` in a `preexec_fn`, but `RLIMIT_AS` (address space)
  isn't reliably enforced on macOS the way it is on Linux -- the same
  kind of platform inconsistency that already forced a workaround
  elsewhere in this project (macOS lacking GNU `timeout`). Left out
  rather than shipping a check that silently doesn't work on half the
  machines this tool runs on.
- **Streaming telemetry / log virtualization / a dashboard UI**: all
  require a persistent process and a client to stream to -- the daemon
  this project explicitly isn't building. `ticket-show` prints the real,
  current state on demand instead; less real-time, but truthful about
  what's actually running underneath it.
- **File-lock collision detection across arbitrary paths**: worktrees
  already solve the common case (each dispatch gets an isolated copy of
  the repo). A real remaining gap is two *different* agents sharing the
  same `cwd` with `use_worktree: false` running concurrently -- not
  addressed here, and worth its own real implementation later rather
  than a shallow version bolted onto this pass.

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
six genuinely verified live runtimes, three of which surfaced real bugs
along the way -- Aider's "reported success doesn't mean it happened,"
OpenCode's silently-wrong parser, Gemini CLI's unconditional
`--skip-trust` requirement, the last of those only found *after* getting
a real API key and pushing testing one step past where it had stopped)
plus an honest accounting of everything that's documented-only or not
attempted at all, including *why* each remaining gap exists (a missing
credential for Cursor, no GUI session for LM Studio -- not "didn't get
around to it" for either). A shorter, truthful feature list is worth more
than a longer one with gaps papered over -- which is the same principle
this portfolio's very first comparison to Livery was built on, applied
here to a bigger, riskier build instead of a narrow one, and applied
again, three times over, mid-build, each time "documented" (or even
"verified short of a credential") was questioned rather than taken as a
permanent label.
