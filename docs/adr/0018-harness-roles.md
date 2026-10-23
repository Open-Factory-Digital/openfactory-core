# ADR 0018 — Three harness roles: executor, reviewer, techlead

- **Status:** **Accepted; shipped.** Claude is the default and runs unchanged. Codex is wired and
  has completed a real ticket end-to-end; Kimi is wired but **unproven** (no account yet).
- **Date:** 2026-07-26
- **Relates to:** ADR-0014 (frontier-default, "still agnostic" — this is what makes that sentence
  true), ADR-0013 (the sizing gate and the effort budget, both of which the `techlead` role
  serves), ADR-0015 (the tech-lead's diagnosis and Slack answers), ADR-0001 D-4 (the ephemeral,
  credential-less box every harness runs inside).

## Context

The platform's *protocols* were agnostic from the start. Its *composition* was not: six call sites
constructed `ClaudeCodeAdapter()` or `ClaudeCodeReviewer()` by name. So "agnostic" was true of the
design and false of the product — supporting a second harness meant editing six files, and a client
who does not use Claude at all could not be served.

That client is not hypothetical. OpenFactory is sold as vendor-agnostic, and some deployments will
run with no Claude account whatsoever. For those, "the reviewer and the tech-lead only really work
on Claude" is not a limitation to document — it is a false claim.

The naive fix (one `harness:` setting for everything) is too coarse, and for a specific reason.
Review is only an *independent* second opinion when the reviewer is a different engine from the one
that wrote the code. Collapsing writer and reviewer into a single setting quietly destroys the
property the review exists to provide.

## Decision

**Three named roles, each independently configurable, named after what they do and after the prompt
files that shape them (`org_defaults/roles/*.md`) — so what you configure and what drives its
behaviour share a name.**

| Role | Does | Methods | Runs in |
|---|---|---|---|
| `executor` | writes the code | plan · execute · repair · continue · recover | the ephemeral box |
| `reviewer` | reviews the diff | review | the ephemeral box |
| `techlead` | judges | size · advise · diagnose · chat | the long-lived worker |

`techlead` covers the pre-flight sizer as well. Same nature (read-only judgment), same place, and
nobody wants those two on different engines. Split it if that stops being true.

### 1. One line for the common case, three when they differ

```yaml
harness: codex                  # all three roles

harness:                        # …or per role
  executor: codex
  reviewer: claude_code         # a genuinely independent second opinion
  techlead: claude_code
```

Resolution per role: env override → the project's `harness` → `DEFAULT_KIND`. The env vars
(`SDLC_HARNESS_EXECUTOR`, `…_REVIEWER`, `…_TECHLEAD`) exist **only** as an operational escape hatch
for an experiment, because the registry is baked into the worker image and trying another harness
would otherwise cost a rebuild and a roll. They are not the normal way to configure this.

**An unknown harness raises.** Falling back to a default would let a whole run use an engine nobody
chose and then report clean numbers for the wrong thing.

### 2. One judging implementation over one primitive

Every judging role — sizer, coordinator, tech-lead, reviewer — is the same operation: *run this
prompt read-only against a checkout and give me the text back*. That is the primitive, `ask()`, and
each harness implements it once in whatever way its CLI makes read-only real:

| harness | how read-only is achieved | strength |
|---|---|---|
| `claude_code` | `--tools Read,Grep,Glob` + explicit deny of the mutating set | enforced (twice) |
| `codex` | `-s read-only` | enforced — a sandbox **policy** |
| `kimi` | instruction only | **weakest** — no mode; enforcement through `--agent-file` is reachable and not used yet (#785) |

Kimi's row is stated rather than papered over. It cannot escape the platform's own box (ADR-0001
D-4), but it could edit inside it while judging.

**Amended (2026-10-17, #362, #783):** the row above used to name the plan flag, `--plan` — a mode
plus instruction. `kimi-code` 0.31.1, the pinned version, refuses that flag (and `--auto`, `--yolo`)
beside `-p` before calling a model, and its only other route into plan mode, `defaultPlanMode` in
`config.toml`, is account-wide rather than per run — so the flag is no longer sent, and the
instruction alone is what keeps that harness read-only. `--agent-file` with a `tools:` list is
reachable per run and not used yet (#785): measured in the review of #783, it takes `Write` off the
model's tool list, but its body replaces Kimi's whole system prompt and 0.31.1 refuses it beside
`-S`, so adopting it is a design choice of its own.

**Amended (2026-10-20, #788):** the two sentences under the table, on where a Kimi judging role
could edit, are not what the code does. Where an
`ask()` runs is its caller's choice. A judging role's caller builds its room with
`sandbox/registry.py::judging_worktree`, which always returns a host `WorktreeSandbox`, so a
question runs on the host even for a project whose jobs run in a container (measured on 620bb577
by `tests/test_where_a_kimi_judging_role_runs_is_what_its_documents_say.py`, where a `kimi` that
disobeys its instruction leaves its file in the host room). The rooms are a fresh temporary clone
for the tech-lead's conversation and the diagnosis, a fresh temporary directory for the
coordinator's advice, the cards and the documents extractor, the battery's workdir for the
evaluation judge, the repo cache's master clone for the sizer and the product baseline, the
module's cached view for the product role, and a source clone for onboarding. Each is a room
nothing commits from, so a judging role's edit does not reach a pull request, except
`env context --ask`, which asks in the target checkout it is pointed at (the person's own
repository on a local deployment), where a write is left in that working tree (measured in the
review of e2b57dd1, 2026-10-20: `?? wrote.txt` in that checkout; the same test now holds it),
and the independent review, which runs in the job's box on the job's workspace before the push:
`JobRunner._review` hands `HarnessReviewer.review` the job's own box and workspace, and it asks
there, so on Kimi a write it commits, or one a review-repair pass then sweeps in, can reach the
pull request (measured in the review of dc0efac4, 2026-10-20: `reviewed.txt` in the pushed
branch; the same test file now holds it). Review is on by default, and that pass is not measured.
The onboarding first run's review asks in its own rehearsal workspace, from which nothing is
pushed. Nothing but the harness confines a write to its room, and on Kimi nothing does. The planner is
the other way round: it does run in the box, but on the job's own workspace, which the executor
then works in and `_commit` sweeps with `git add -A`, so a Kimi planner's edit reached the pull
request, and a planner that wrote and then hit a rate limit had its
edit pushed to the job's branch by the pause. With `--sandbox worktree` that workspace is itself on
the host. So the orchestrator now measures that workspace around a Kimi plan pass
(`orchestrator/read_only_pass.py`: the tree `git add -A` would commit, written from a copy of the
index, HEAD, the ref HEAD is on and the commit of the job's branch, the one that is pushed, before
the pass and after it) and holds the job when the pass wrote, naming the
paths, before the pause, the commit or the push; the job stops before pushing anything, and the
workspace is discarded with the sandbox. A workspace git cannot answer holds the job too, with
git's exit code and its words, and before the pass is run when the first reading fails. The hold
detects the write, it does not prevent or undo it, and it sees only what is there at the second
reading: a process the planner leaves running that writes after it is not seen, and that write can
reach the pull request (measured in the review of dc0efac4, 2026-10-20: a background process that
wrote `late.txt` a second after the pass left the job unheld and the file in the pushed branch). A
pass the box walled is now held before the executor runs (#980): the box's wall kills only the
shell it started, so a walled planner may still be running, and an ordinary timeout was enough to
reach that limit. What remains of it is a process left behind by a pass that ended on its own. Which harnesses are measured is
`adapters/agent/base.py::PLANNERS_READ_ONLY_BY_INSTRUCTION`, Kimi alone. A planner runs only where
a project turned `planner_stage` on (ADR-0014).

Everything above that primitive — the sizer, the diagnosis, the coordinator's advice, the Slack
answer, the independent review — is **one shared implementation**. Parity by construction rather
than by four more copies per harness.

### 3. Native-first: a proven implementation is never displaced by the generic one

Where a harness already implements a role itself, that implementation wins; the generic path serves
the harnesses that would otherwise have nothing.

This is not a style preference. Claude's reviewer runs `--output-format json` and reads
`envelope["result"]`; the generic path runs `--output-format stream-json` through a different
parser. Routing Claude through the generic implementation swapped a production-proven invocation for
one with zero miles — on the exact path that had just produced twelve real findings on a live PR.
Uniform code is not worth an unproven production path.

**Amended (2026-10-19, #755):** the paragraph above describes the reviewer's invocation as it was.
It now streams like every other Claude role (`--output-format stream-json --verbose`), so a wrapper
in front of `claude` sees a review's `rate_limit_event`s; it reads the stream's last `type ==
"result"` event, which carries the same keys as the single envelope (measured on the pinned 2.1.219),
and falls back to `json_envelope` when a CLI answers with one envelope. It is still the native
implementation and is still not routed through the generic reviewer, so the decision of this
section (native-first) stands; only the description of its invocation changed.

The consequence is deliberate: **a Claude deployment behaves exactly as it did before this ADR.**

### 4. A wall-clock wall, because turn caps are not portable

Claude bounds effort with `--max-turns` (the ADR-0013 D4 budget). Codex exposes no equivalent. So
rather than leave the harnesses asymmetric, a single wall-clock wall applies to all of them: **four
hours**, after which the run is stopped and parked as an impediment with a diagnosis — a task still
running after four hours is stuck, looping, or far larger than it looked, and it will not succeed on
hour five. A turn-capped run still stops on turns first.

Deliberately *not* a rate-limit pause: a pause auto-resumes on a timer because the limit lifts by
itself, and a four-hour run does not get better by waiting. A human decides: resume, split, or drop.

The wall is the innermost of three nested clocks, and the ordering is load-bearing — only the
innermost one produces an explanation. See `sdlc/adapters/sandbox/timeouts.py`.

### 5. Cost is never invented

A harness that reports tokens but no price (Codex) yields an **unknown** ticket cost, never `$0.00`.
A zero would make that harness look free and let it silently win every cost comparison — the exact
opposite of what the telemetry exists to do, and directly corrosive to an efficiency claim that is
measured with these numbers.

## Consequences

**Good.** A Claude-free deployment is now genuinely possible, with a real reviewer and a real
tech-lead rather than a deployment that quietly loses them. Adding a harness is one registry entry
plus one module. Writer and reviewer can be different engines, which is the only configuration where
"you did NOT write this code" is structurally true.

**Costs and open risks.**
- **Kimi is wired, not proven.** Its stream schema was never observed; parsing degrades to
  `None`/`[]` and never raises, and cost is left unknown rather than guessed. Treat any number from
  it as unverified until a real run.
- **Codex lacks feature parity in the plumbing, not the roles:** credential pooling, durable
  cross-container resume, and transcript writing are Claude-only today; the roles themselves
  are at parity.
- **Same-harness review is a real reduction.** When `executor` and `reviewer` point at the same
  engine, the review is a fresh context on the same model — it still catches plenty, but it is not
  an independent second opinion. Said here rather than in a release note nobody reads.

## Addendum (2026-08-24): the set of roles is open; the meaning of these names is not

The Decision fixed the roles at three (a fourth, `product`, joined with ADR-0019). On 2026-08-24
the doctrine that the public repository is the core and agents around it are installed from
outside made a fixed set a defect: a consultancy's QA role had no way to exist without a pull
request against us. The role is now an axis — `role.<name>` in the `openfactory.adapters`
entry-point group, whose builder returns a `RoleSpec` — and `known_roles()` (shipped ∪ installed)
is the one list every surface reads: both resolvers, `build_asker`, `set-model --role`, the panel
cockpit, and the registry file's unknown-key warning.

What this addendum keeps **closed**, each refused by name and logged once:

- the shipped names and prompts (`techlead`, `sizer`, …) — built-ins win a collision, the rule
  `plugins.py` states for every axis;
- `default`, the per-role fallback key, and any name a shipped **phase** is spelled after
  (`size`, `chat`): a phase is where an add-on's `human_facing` is read, so a role by that name
  would decide the language of a shipped prompt;
- any env name in the platform's namespace (`OPENFACTORY_*`, its old spelling) or one the
  platform reads from the tools it drives — reserved by namespace, and the foreign names derived
  from the package's own reads (`environ.names_read`, 2026-08-26), never by a list written by hand:
  the hand table was measured to be exactly what its own guard could see, and six names read
  through a table or a default argument were open;
- a variable another installed role already reads — one variable binds one role.

And what the core does **not** do for an add-on role: invoke it. There is one reviewer slot and no
stage seam; the package that ships the role calls `build_asker(project, role=…)` and acts on the
answer. A place in the lifecycle is a successor ADR, not a registry row.

**Language, corrected on 2026-08-25.** The same change inverted the language rule from an
allowlist of human phases to a closed set of coding phases, so that a phase nobody listed is
localised rather than emitted in English at a client who set `language:`. That inversion moved
two prompts it must not have: `product_confirm` and `product_accept` are one-word verdicts code
parses (`approve`/`reject`/`neither`, `worked`/`did-not-work`/`neither`), and a directive asking
for pt-BR on a prompt that demands an English token leaves every proposal pending and every
acceptance open. The fact is now modelled rather than left to exclusion: `MACHINE_PHASES` holds
the shipped verdicts, `RoleSpec.human_facing=False` says the same thing for an add-on, and one
rule (`roles.needs_language_directive`) serves all four harnesses — not the coding path, not a
verdict code parses, everything else.
