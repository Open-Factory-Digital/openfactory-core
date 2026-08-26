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
| `kimi` | `--plan` | **weaker** — a mode plus instruction, not enforcement |

Kimi's row is stated rather than papered over. It cannot escape the platform's own box (ADR-0001
D-4), but it could in principle edit inside it while judging.

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
