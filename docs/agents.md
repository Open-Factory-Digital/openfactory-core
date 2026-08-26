# The agents: what each one does, what it does not, and where that is written

This document exists for two questions that always come up: *"what exactly can this agent do?"* —
from a client evaluating the platform — and *"where do I change it?"* — from whoever operates it.
Both answers sit side by side in every section, because when they drift apart the documentation
ages.

Four roles. Three of them judge, one writes code.

| role | decides | runs in | instructions |
|---|---|---|---|
| **executor** | *how* to implement | ephemeral box | `openfactory/org_defaults/roles/executor.md` |
| **reviewer** | whether the diff meets what was agreed | ephemeral box | `openfactory/adapters/reviewer/harness.py` → `build_review_prompt` |
| **tech lead** | what to do when something stops | worker | `openfactory/org_defaults/roles/techlead.md` |
| **product** | *what* to build and why | worker | `openfactory/org_defaults/roles/product.md` |

Three of the four read a file that ships with the package; the reviewer's is **built**, and that
is deliberate rather than an omission. Its prompt has to quote the spec and the diff of the job in
front of it, so there is nothing to put in a file — and keeping it in one harness-agnostic
function is what stops each engine growing its own idea of what a review is.

Which engine (harness) serves each role is configuration, not code: `harness: codex` on one line,
or one per role (ADR-0018). **Four harnesses ship**, and the list is one table —
`openfactory/adapters/agent/registry.py` → `HARNESSES`, where adding a fifth is one entry plus its
module: `claude_code`, `codex`, `kimi` and `opencode`. The last is the provider-agnostic line: one
binary that reaches several model providers, so *which* provider serves a client is `model:`
rather than a different harness.

---

## The product role — PO, BA and delivery manager at once

It talks to the client in their own language, without delivery jargon. It is the only agent a
non-technical person meets.

**Where that conversation happens is the panel** — the surface every deployment has, with no
account to open and nothing to install (ADR-0038). A team that already talks somewhere else can
have the same conversation delivered there instead: a chat channel is an **add-on package**, and a
project that names one (`channel: slack`, or a `channel_id`) on a deployment that has not
installed it is refused by name rather than going quiet. Declare nothing and the channel resolves
to the panel — that is what `openfactory/adapters/channel/registry.py` → `channel_kind` answers
with nothing configured.

### What it does on its own

| it does | and what that means |
|---|---|
| answers questions about the product | citing the **requirement number** behind every claim, and saying when it does not know |
| reads the work board | how many items in each state, what has gone stale, what is stuck |
| proposes what enters the queue | ordered by business value, with what was left out and why |
| asks what is missing | of the **item's owner**, one question at a time, at most three per pass |
| chases once | 48h later, with a way out: *"if this is not a priority, tell me and I will stop"* |
| announces a delivery | unprompted, when all the work behind a request finishes |
| **chases a decision it asked for** | what it asks of a person becomes a tracked commitment, chased once at 48h **repeating the question** — a request made in conversation no longer dies in the chat |
| **asks whether it worked** | and does **not treat it as delivered** until you answer — silence never counts as acceptance (ADR-0025) |
| weekly triage | only what is **new**; the rest becomes a count |

### What it only does with a confirmation

Every write goes through **one** confirmation from somebody authorised — the `admins` list of the
project's `product:` section (`openfactory/contracts/product.py` → `ProductConfig.admins`; the old
`slack_admins:` spelling is still read as an alias, so an existing registry keeps working).
Reading is free; writing costs money or creates a commitment.

| you say | it proposes | and after your "yes" |
|---|---|---|
| *"I need the system to do X"* | a drafted requirement, with any conflicts it found | opens a pull request on the documentation repo |
| *"the reconciliation is duplicating"* | records it as a **defect**, citing the promise it breaks | creates the classified item, and tells you when the fix ships |
| *"note that the firm uses Primavera"* | shows you how it will note it | stores it as a **learned** fact, attributed to whoever said it |
| *"break requirement 7 into tasks"* | the tasks it derived | creates the items in Backlog, each citing the requirement |
| *"survey what already exists"* | warns you it will take minutes | reads the code and opens **one** pull request with what it observed |
| *"what goes in now?"* | the proposed queue | moves items to TO-DO — the only point that **starts spending** |

### What it never does

- **Write code, or opine on implementation.** Not its role, and the prompt says so.
- **Turn code into a promise.** Reading the code produces `observed`, never `accepted` — see
  "reverse engineering" below; it is the most important rule in this document.
- **Start work on its own.** A filed item lands in Backlog; leaving it is a human decision
  (ADR-0019 §5).
- **Assert what it cannot support.** With no written requirements it **refuses** to prioritise, and
  says why, instead of inventing an order.
- **Treat a delivery as accepted without you saying so.** The board closing is the factory agreeing
  with itself. Only your answer closes it; without one, the delivery stays visibly pending.
- **Go quiet when something breaks on its side.** It answers saying that it broke, and an alarm
  fires on the first occurrence.
- **Notify the wrong person.** When it cannot identify somebody with confidence, it writes the name
  in plain text — the reader knows who is meant and nobody is misled into thinking they were
  notified.

### Reverse engineering: why the output is an "observation", never a requirement

The normal case for a new client: a year of code, zero written requirements. The obvious move is to
read the code and write the requirements from it. **That move is wrong**, and the reason is worth
stating before the mechanics:

> A requirement says what **should** be true. The code says what **is** true — including bugs,
> accidents and behaviour nobody chose.

Turning the second into the first freezes defects into promises: once a behaviour is an accepted
requirement, the factory starts **defending** it, and the fix that should have come now looks like a
violation of what was agreed. And the provenance would be a lie — *"requested by: the code"* is not a
person.

So the survey produces **observations**, each with its evidence classified:

| evidence | what it means | how much to trust it |
|---|---|---|
| `asked` | somebody asked — there is an issue, PR or comment with an author and a date | the strongest a first pass finds |
| `tested` | a test guarantees it | somebody made this a promise on purpose |
| `code` | the code does it and nothing guarantees it | the most likely to be an accident |

Everything arrives in **one** pull request — the inventory, the candidates, and the questions the
code did not answer. A person moving an item from `observed` to `accepted` is the only event that
creates a promise.

And the pass **declares its own coverage**: which areas it looked at and which it left out. A
document that suggests completeness it does not have is worse than a short one — it gives confidence
exactly where it is not due.

**Where it lives:** `openfactory/product/brownfield.py` (the rules), `module.baseline()` (the
execution), `authoring.propose_baseline()` (the pull request).

---

## The tech lead — on call, not on demand

It speaks in the technical channel. It classifies every failure by **what resolves it**, resolves
the classes the factory owns, and escalates the rest along with what it already tried.

| class | example | who resolves it |
|---|---|---|
| `transient` | an API limit, an unstable network | **the factory** — waits out the window, tries again |
| `credential` | an exhausted token | **the factory** — rotates; escalates if the whole pool fails |
| `environment` | a missing permission, a broken image | a person, named, with what to change |
| `requirement` | the ticket is ambiguous | the **product role** |
| `code` | the change is wrong | a person, with the diagnosis |
| `unknown` | it cannot say | a person, told that it does not know |

`unknown` **never** degrades into "try again". Repeating a failure nobody understands is how a token
pool burns on something structurally broken, while looking like progress.

**It has memory.** A remedy that failed twice on the same failure, with no success at all, stops
being offered — and the escalation says what it learned: *"I have seen this on 4 tickets and
resuming resolved none of them"* is somewhere to look; *"I could not"* is a shrug. And the outcome is
always **observed**, never self-reported: nothing that calls itself successful counts as success
(ADR-0021).

---

## The three locks that apply to all of them

**0. The confirmation is a click, not a sentence.** Every proposal arrives with **Confirm and
record** / **Do not record**. The click carries who clicked and names exactly what was shown — if the
proposal has changed since, it **refuses** rather than recording something you did not read. Whoever
prefers to type still can: then the sentence is read by a model, and it is the less certain of the
two paths (ADR-0029).

**1. One confirmation, from somebody who may.** Reading is free for anyone in the channel. Writing
requires a "yes" from somebody on the administrators list. An unauthorised "yes" does **not consume**
the proposal — the real administrator still finds it afterwards.

**2. Nothing starts spending on its own.** Filed work is born in Backlog. Only a person moves it into
the execution queue.

**3. What is said to the client is verified.** Every fixed sentence goes through a jargon test; a
wrong mention degrades to a plain name; and a sweep of 2,000+ simulated conversations makes sure no
message breaks the invariants (`tests/test_conversation_worlds.py`).

---

## Where to change things

Three rows point at **the registry** — the deployment's own file, which is not in this repository
because it holds a particular installation's coordinates. It lives wherever
`OPENFACTORY_REGISTRY` says, `~/.openfactory/registry.yaml` by default, and
`deploy/registry.yaml.example` is the annotated shape to copy.

| I want to change | file |
|---|---|
| a role's doctrine | `openfactory/org_defaults/roles/*.md` |
| what a review asks for | `openfactory/adapters/reviewer/harness.py` → `build_review_prompt` |
| how the agent speaks to the client | `openfactory/product/voice.py` — `AUDIENCE_RULES` and the fixed sentences |
| what it recognises in a sentence | `openfactory/product/intents.py` |
| what it can do, and the locks | `openfactory/product/module.py` |
| who may authorise | the registry → `product.admins` |
| delete a client's conversations | `openfactory project forget-conversations <project>` |
| how long a conversation is kept | `openfactory/memory/transcript.py` → `RETENTION_DAYS` (180; only conversations expire, the agents' memory never does) |
| who is who (mentions) | the registry → `people:` (forge login → channel id) |
| which engine serves each role | the registry → `harness:` |

**A boundary worth stating to the client:** their board carries their product. Work that exists only
to test the factory runs against a test-bench project of ours, and a card labelled `factory-test` is
**refused** on a board that has not declared it accepts one (ADR-0027) — refused at the door, with
the reason written on the card itself.

The decisions behind all of this are in the ADRs: **0018** (roles), **0019** (the product role and
the requirements repo), **0020** (the tech lead on call), **0021** (operational memory), **0022**
(provider agnosticism), **0024** (conversational memory), **0025** (acceptance), **0026** (shared
vocabulary), **0027** (the client's board is not a test bench), **0038** (the panel is the
reference surface and a channel is an add-on).
