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

## Why five runtimes are "verified" and three are "documented," and why that distinction is load-bearing

It would have been easy to build eight adapters from eight sets of
official docs and claim "8 runtimes." Instead, verification started at
two (claude_code, codex -- both installed in the original development
environment) and grew to five by actually installing three more
(ollama, aider, opencode) and running real dispatches against them,
rather than leaving "documented" as a permanent label for a tool that was
simply never tried. The remaining three (cursor_agent, gemini_cli,
lm_studio) each got a real install/CLI-verification attempt too, and each
hit a different, disclosed, concrete wall short of a full dispatch --
not "never tried," just "tried and blocked by something specific." See
the next two sections for exactly what that testing found.

- **claude_code**, **codex**, **ollama**, **aider**, **opencode**: every
  flag was checked against that tool's own `--help`/official reference,
  and each was proven with a real invocation before being trusted.
  `claude_code`'s JSON parser was built from one real `claude -p ...
  --output-format json` response. `codex`'s `--output-last-message`
  pattern was chosen because a real run showed stdout is full of banner
  text ahead of the actual answer. `ollama`, `aider`, and `opencode` were
  each verified after initially shipping as documented-only -- all three
  required actually installing the tool, not just reading about it.
- **cursor_agent**, **gemini_cli**, **lm_studio**: real install attempts
  were made for all three, and the gaps that remain differ in kind, not
  just degree:
  - Cursor CLI is installed and every flag this adapter uses was
    confirmed against the real `--help` output -- the original docs this
    adapter was built from turned out to be accurate. The only thing not
    confirmed is the *success* response shape, because cursor-agent has
    no free tier and this environment has no `CURSOR_API_KEY`.
  - Gemini CLI's original docstring was itself built from a secondary
    summary that missed real flags (`--approval-mode`,
    `--include-directories`); installing the real CLI found and fixed
    that, plus a silent gotcha (`--approval-mode` reverts to `default`
    unless `--skip-trust` is also passed). The only thing not confirmed
    is the success response shape, because this environment has no
    `GEMINI_API_KEY`/Google auth.
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
"5 verified, 3 not, and here's specifically why" claim that's actually true.

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
`--approval-mode auto_edit` and `full` to `--approval-mode yolo`, always
paired with `--skip-trust` (without which the approval mode silently
reverts to `default` in an untrusted directory -- found by triggering
that exact silent downgrade live, not inferred from docs). The lesson
generalizes past this one adapter: a documented-only claim is only as
good as the documentation actually consulted, and a summary of a doc is
not the doc.

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
response shape, since cursor-agent has no free tier and this environment
has no `CURSOR_API_KEY` to complete an authenticated run with.

**Gemini CLI**: installed via `npm install -g @google/gemini-cli`
(v0.57.0). Covered in detail in the section above -- the short version is
that the *original* adapter's documented-only claims were themselves
built on an incomplete secondary source, and installing the real CLI
caught that. What's still unconfirmed, same shape as Cursor, is the
successful response body, blocked by missing `GEMINI_API_KEY`/Google auth.

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
than Cursor's or Gemini's: those two are one API key away from a full
dispatch; LM Studio needs an actual desktop session, which no amount of
further installing in a CLI-only environment produces. It stays
documented-only, and the adapter's docstring says exactly why, rather
than a generic "not installed" note.

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
five genuinely verified live runtimes, two of which surfaced real bugs
along the way -- Aider's "reported success doesn't mean it happened,"
OpenCode's silently-wrong parser) plus an honest accounting of everything
that's documented-only or not attempted at all, including *why* each
remaining gap exists (missing credentials for two runtimes, no GUI
session for a third -- not "didn't get around to it" for any of them). A
shorter, truthful feature list is worth more than a longer one with gaps
papered over -- which is the same principle this portfolio's very first
comparison to Livery was built on, applied here to a bigger, riskier
build instead of a narrow one, and applied again, twice, mid-build, each
time "documented" was questioned rather than taken as a permanent label.
