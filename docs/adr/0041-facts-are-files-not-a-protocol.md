# ADR 0041 — The roles read facts as files, not through a tool protocol

- **Status:** **Accepted**
- **Date:** 2026-08-20
- **Relates to:** ADR-0038 (the platform is complete on its own; channels are add-ons — the same
  shape, one layer up), ADR-0040 (the core runs on the client's own machines),
  ADR-0022 / ADR-0034 (provider seams and the extension model),
  ADR-0014 (frontier-default: question weak-model scaffolding).

## Context

The tech-lead and product roles answer questions about a live factory. Everything they know
arrives as one assembled prompt: the floor, the board, the conversation so far, each parked
ticket's comment thread, each review verdict, and — since #171 — the diff of every pull request
sitting at a human gate.

That shape has a hard ceiling. A prompt is written before the question is understood, so it
carries what somebody guessed would be needed. #169 measured the cost: a 25,000-character digest,
mostly unread, capped precisely where the answer needed depth. The obvious fix is to stop
assembling and let the role **fetch** — and the obvious way to let a model fetch is
[MCP](https://modelcontextprotocol.io), which is what the plan for the tech-lead's tool calling
originally proposed.

The product owner stopped it with one question:

> *"about MCP — I did not understand exactly why we need it, and my concern is that Claude may
> support it, but we are agnostic; we cannot have any vendor locking."*

## Decision

**Facts reach a role as files in the checkout it already has. The platform declares no tool
protocol.**

`techlead/pack.py` writes `floor.md`, `board.md`, `thread.md`, and one file per ticket under
`comments/`, `verdicts/` and `diffs/`, with a `README.md` manifest naming every file **and every
gap**. The prompt shrinks to that manifest — and only when the pack was actually written, because
a prompt that drops the facts and points at files that are not there is worse than the digest it
replaced.

## Why files, measured rather than assumed

Every harness this platform can drive was checked, not reasoned about. All four run a read-only
agentic loop with filesystem reads already available:

| harness | how it reads |
|---|---|
| Claude Code | `--allowedTools Read,Grep,Glob` |
| Codex | `-s read-only` |
| opencode | read-only profile |
| Kimi | `--plan` |

**A filesystem is the one tool all four already have.** It needs no server, no handshake, no
capability negotiation and no per-vendor adapter — and a client who swaps harness swaps nothing
else. That is the property ADR-0040 exists to protect, one layer up: the platform must not need
anything from the model vendor beyond "run this prompt in this directory".

MCP would buy exactly one thing files do not: **fetching a fact nobody gathered**. That is real —
a role that wants the fifth-most-recent comment on a ticket outside the parked set cannot get it —
and it is not worth what it costs. Today one server exists that every registered harness speaks;
adopting it makes the product two-tier, with a good experience on the harness that supports the
protocol and a degraded one everywhere else. A two-tier product is a vendor lock wearing an open
standard's name.

## What this does not say

**Not "MCP is bad".** It is a well-designed protocol and this decision is about *where the
platform's floor sits*, not about its quality.

**Not "never".** The day every harness in `adapters/agent/registry.py` speaks it, the trade
reverses: the cost — a two-tier product — disappears, and the benefit remains. The measurement
above is the one to redo, and this ADR is the thing to supersede. Until then, a capability that
only some clients get is not a capability this platform has.

**Not a ceiling on what a role can reach.** The gap is closed by gathering better, not by a
protocol: #171 added the diff because the tech-lead was being asked to approve a change it had
never seen. That is the pattern — when a role needs a fact it does not have, the fact joins the
pack, on the neutral adapter contract, for every vendor at once.

## Consequences

- The pack must name what it could **not** read, distinctly from what is genuinely absent. A
  failed read rendered as an empty one is a confident claim built on nothing, and the manifest
  says so in those words.
- A new fact costs a port method on the neutral contract, implemented for every registered vendor
  — which is the same bar every other read in this platform is held to, and the reason a fifth
  forge added without `pr_diff` fails the suite.
- The prompt shrinks only when the pack was written. `write_pack` returns `None` on failure and
  the caller honours it.
