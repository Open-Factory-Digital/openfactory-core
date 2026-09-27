# 06 — The product role: switching it on for a real product owner

The engineering loop ships tickets. The product role decides WHAT becomes a ticket: requirements
written as reviewed documents in a **context repository**, a panel surface at **`/product/<name>`**
for the person who owns the product, and a human release gate before production. This page is the
whole enablement chain, in order — every command verified against the CLI.

## 1 · Three declarations that must agree

The role refuses to run half-configured, so three places name each other:

| where | what it declares |
|---|---|
| the registry entry | `product: {docs_repo: <org>/<name>-context}` — where requirements live |
| the context repo | `.openfactory/product.yaml` — `product: <name>` + `sources:` (EVERY repo implementing it) |
| each source repo | `docs_repo: <org>/<name>-context` in its `.openfactory/project.yaml` |

A mismatch is reported as a sentence naming both sides, not a stack trace. Two of the three are
written for you:

```bash
openfactory product init <name>                   # shows what it would write, and where
openfactory product init <name> --create-context  # no context repo yet? create one in the client's org
openfactory product init <name> --write           # open the PR on the context repository
```

**Both shapes, on either vendor.** A client's projects rarely all look the same — some already
keep a documentation repository, some have none at all — and the command answers to that
rather than to a flag:

| the project | what to run | what happens |
|---|---|---|
| **already has** a context repository | set `product.docs_repo` in its registry entry, then `product init <name> --write` | it is USED: cloned, read, and the declaration proposed as a pull request on it |
| **has none** | `product init <name> --create-context --write` | one is created in the client's own organisation, recorded in the registry, and the declaration proposed |

`--create-context` is the one operation that makes a repository in somebody's organisation, so
it is behind its own flag and says whether it CREATED or FOUND it. It is implemented for
**GitHub and Azure Repos**; a forge without the capability refuses by name and tells you to
create it by hand and set `product.docs_repo`. On Azure DevOps the repository is created in the
project the forge already drives, and a context repository that lives in a **different project
of the same organisation** is addressed by qualifying it — `product.docs_repo: SharedDocs/
product-context` — which the clone, the branch lookup and the pull request all follow.

`--write` opens the PR carrying `.openfactory/product.yaml`; the THIRD declaration — the
`docs_repo:` line in each source repo's own manifest — is **printed as a todo, not written**:
it lives in a repository you review, so committing it is deliberately yours.

## 2 · Who the product owner IS to the platform

**What the role can open while it answers:** the documentation repository, the source code,
the knowledge bundle when one has been published, and — since #33 — its own **facts pack**: the
board *whole* (every card and title, where the prompt's own board section is budgeted), what it
is waiting on a person for, and the register of every decision it asked somebody to take. The
pack's `README.md` names what could **not** be read, so a failed read is never reported as
"nothing there".

**The source code is every repository the product declares (#268).** Each entry of `sources:`
is mounted read-only under `src/<name>/`, not only the registry project's own repository — and
nothing outside `sources:` is. Each is a **partial clone checked out sparsely**
(`product/sources.py`, `runtime/repo_cache.py::SparseRepoCache`): no history blob is fetched,
directories that hold only pictures, fonts, archives or binaries are left out (and named), and a
source is cloned the first time a conversation needs it, then only brought up to date. A source
that cannot be mounted is **named in the prompt with why** — not authorised, not found,
unreachable, not declared — and the factory's "cannot open the code" impediment opens for it.
The prompt also names each source's **module map**, only after checking it against the code
mounted for that source, and the documents the onboarding wrote (`docs/architecture/`, the
invariants, the open questions, the survey). The confidence bound on an answer reads every
source's knowledge bundle. What it costs: `tools/measure_the_mount.py`.

**It sees what the panel shows (#267).** When the role answers somebody, its pack also carries
the product's **read model** (`openfactory/product/model.py`) — one projection of what the
panel's project screens show, built from the same reads, for every registry project of the
product (the union, when one context repository serves several):

- `now.md` — the floor's verdict, the jobs on the floor and **why** (the engine's own reason and
  the tech-lead's diagnosis as it wrote it, never diagnosed again), their pull requests, checks
  and reviews, and what waits on whom;
- `history.md` — the version in production (the newest release tag), what was delivered, the
  finished jobs, who asked for what;
- `board.md` — the **whole** board, with no window, with labels, assignees and who asked;
- `requirements.md` — every requirement with who asked;
- `documents.md` — the context repository's documents as their ingestion found them: how many
  were read, and every one that **could not be**, with its type, its audience and why (#269);
- `cards/` and `pulls/` — a file per card (body, thread, linked pull requests, timeline) and per
  pull request (description, reviews, changes).

**It remembers the product, by search (#269).** The product's documents, its requirements with
the decisions recorded in them, its closed cards and its conversations are one index per product.
Before the role answers, the engine searches it from the message and writes what it found as
`found/before-the-turn.md` in the pack: every hit with where it is (a PDF's page, a document's
section), its date and where the date came from, and how it was read. A decision that was reversed
is never handed over as what holds today — it is listed only under what replaced it, with the
timeline. Every document is found for whoever asks, and what a group said to somebody else is
never searched for the role unless it asks. When it needs more, the role writes
`[[BUSCA: <what to look for>]]`; the engine searches, writes `found/search-1.md`, and asks again —
two rounds at most. Every search is recorded. Without a local embedding model the search runs on
exact words, metadata and dates, and says so.

Nobody is named across conversations: a requester is "its requester", or "you" to themselves, and
a person's id is withheld wherever it rides. Some of what the panel shows is **withheld on
purpose**, and the list says what and why (`EXCLUDED` in that module): **spend** first (#266,
decision 7), then a run's raw log, the cockpit's machinery and credentials, the factory's thread
with its operators, who may approve a release, and an operator's controls. A guard
(`tests/test_the_read_model.py`) finds the panel's project routes itself and fails when a field
they show is neither in the role's files nor on that list.

**And it answers from a briefing (#267).** Every answer's prompt carries a short **briefing**
(`openfactory/product/briefing.py`) — what the product's owner carries in their head in the
morning, read from that model: which cards are moving, which are parked and on whom they wait,
what waits on a person (a merge, a delivery's verdict, a decision, a question asked on a card),
the version in production, and what was delivered lately. Every line ends with its source and
its age — `(ledger — asked 2 days ago)` — so the role says "as of" rather than asserting a present
it did not see, and a fact that could not be read is a line saying so. It is bounded (twelve lines,
2,000 characters) and says how many lines it left out; the files hold the rest. It names nobody
but the person being answered, carries no spend and no credential, and quotes the tech-lead's
diagnosis only to an engineer in a private conversation: everybody else is told what a stopped
card waits on, and the role says what the diagnosis means for the product. The briefing takes
the place of the budgeted board section in an answer; `board.md` holds every card.
`OPENFACTORY_PRODUCT_BRIEFING=off` turns it off and brings the board section back — the "without"
arm of a measurement with the evaluation battery ([configuration](../configuration.md)).

**It checks the map against the code, and says where the map is thin (#268).** On every turn
each concept of each source's bundle is re-checked against the code mounted for that source
(`check_concepts`, the tech-lead's own check); one whose code moved is **named stale** in the
prompt, a reading that cites it is no higher than `média`, and the answer says the description is
out of date. The prompt also says, bounded, what the role cannot stand on: a source with no bundle
or no code mounted, the code no concept describes, what a bundle or the system map says it could
not establish (`openfactory/product/sight.py`). When an answer rests on code **no concept covers**,
a `no-concept` request goes to the knowledge pipeline's inbox — the repository and the path,
never the question — and the next knowledge refresh records it in that source's bundle; the role
itself never writes a bundle (`openfactory/knowledge/requests.py`). A **flow that crosses
services** is a concept of its own, observed by the pipeline from a requirement that names several
repositories (`.okf/flows/`, `openfactory/knowledge/flows.py`); it becomes a **business
capability** of the product only when an admin of the product confirms it
(`product_confirm_capability`), which writes `capabilities/<slug>.md` in the context repository —
until then the role says it is observed. A confirmed capability whose link no longer holds is
said beside it. And the pack's `chain.md` walks every requirement to production — card, job, pull
request, deploy, release tag, each named as the link the verdict rests on — and every flow to the
code that serves it (`openfactory/product/chain.py`).

**Every document in the context repository is read, once per version (#269).** People put
anything there: PDFs, diagrams, charts, e-mails, minutes. Each file becomes normalised text plus
a record — its date, authors, type, area, the product's terms it uses, the requirements and cards
it cites, and, written by a model once per version and marked as a model's, a summary and the
decisions it mentions (`openfactory/product/documents/`). What reads each kind of file is a row
on the extraction axis (`openfactory/adapters/extract/`): text, markdown, mermaid, HTML, draw.io
and SVG, `.eml`, a PDF's text layer (the `ingest` extra), OCR for a scanned PDF (`tesseract` and
`pdftoppm`, when installed), and a model describing an image — whose record says its content came
from an image. A file is read on the knowledge pipeline's schedule when it changed, or at once
through `openfactory act product_ingest --param project=<name> --param path=<file>`; a version
already recorded is never read again. The records are derived: they live under the product's
state directory and are rebuilt from the repository when deleted. A file that **cannot** be
read — a protected PDF, a format nothing reads, a file over the size limit, a link out of the
repository — is recorded with why, listed under *Documents* on the product page, and named in
the role's `documents.md`: it exists, and could not be read. **Whoever talks to the product role
reads everything the product exposes** — a co-owner, an engineer, a client, in a room or in
private (the product owner's decision of 2026-09-25, replacing #266 decision 8 for what the role
reads). A document still carries the label its folder (`internal/`, `client/`, …) or its front
matter (`audience:`) gives it, as what it says of itself; nothing a turn reads, and nothing the
panel lists, is withheld by it. A document read into the product's memory is announced where it
was brought — the conversation of whoever asked for it to be read, else the room — once, never
for a product's first reading, and at most five per pass.

**Was this asked before?** Before every answer the role is handed the tickets, the requirements
and the open decisions whose titles overlap the message — with their references, and never who
asked (ADR-0051 D9) — so a request somebody else already made is answered with a pointer to it,
not with a second draft of the same requirement. Read from the board, the corpus and the loops,
never from one conversation's transcript: a repeat has to be caught across people. And from the
product's whole memory (#269): a card closed years ago, a requirement dropped or superseded, a
document, a distilled conversation — each with its date and what became of it, searched before
anything is locked, and only among what this conversation may be shown. A draft is checked
against the same list before it is shown for its yes.

**What a quiet conversation came to is kept (#269).** A requirement, a decision, a card or a fact
is written the moment it is confirmed. What nobody confirmed — an option refused, a preference, a
question left open — is distilled when the conversation has been quiet for six hours: a model
reads its lines (who said each one only by their role, never by name) and what it agreed, asked,
decided, refused and left open is committed to the context repository under `conversations/`,
once per stretch of conversation. It names nobody — a distillate is permanent, and a name in it
would outlive the conversation's own deletion. It is evidence the role cites with its date, never
a requirement or a decision. A room's is readable by every conversation; a private conversation's
comes back only to that conversation.

**What stays private is a person's conversation.** The role reads its workspace with its own
tools; the workspace a turn is given holds every document of the product and never the summary
of somebody else's private conversation. Who is asking — a client, a product admin, an engineer —
shapes how the role speaks, and whose yes records anything is still `admins`' alone; neither
changes what the role may read.

**What becomes work is checked and written as one step.** Conversations run side by side, and a
requirement, a card, a decision, a fact or an acceptance passes one lock per product — per
context repository, shared by every registry project that points at it. Inside it the role looks
only at what was saved after its own check: the same request saved moments ago in another
conversation is linked instead of written twice, and the person hears that it exists and where —
never who asked. A draft still waiting for its yes in another conversation is mentioned only as
"someone asked for something close to this a few minutes ago". A lock that cannot be had in time
writes nothing, and says so.

**Each person has their own conversation with the role on the panel.** What Ana said
yesterday is the thread Ana continues today, from any browser — never Bruno's. A browser nobody
has identified gets a conversation of its own too, keyed by a cookie the page sets, so two
people on a shared token stop writing into one thread. Reading is not gated; agreeing to
anything still needs a known person.

**A request is confirmed in the conversation, on every surface.** When the role hears a request
(or a defect, a card, an order for the backlog) it stages it and asks for one yes. Type "sim" in
the same box — or press the button beside the proposal — and it is written, once; "não" throws it
away and is answered as the correction it usually is. The panel, the CLI (`openfactory product
ask … --propose --yes`) and a chat add-on all reach the same turn, so the same message gets the
same answer wherever it is typed.

**Many conversations at once; one turn at a time inside each.** Every message goes through one
door onto its conversation. People in different conversations are answered side by side; in a
room, the role answers one person at a time, and whoever writes while it is busy is told at once
that the message is kept and they are next — never whom it is answering. Lines a person sends in
a burst are answered together. "Status", the triage and the introduction are answered straight
away, even while the role is busy. A turn that takes longer than about a minute and a half says
so, and its answer arrives in the same conversation when it is ready. Two registry projects that
share a documentation repository are one product: the same conversation, and one memory
(`docs/configuration.md` → *Conversations*).

**The panel is a chat, on every page.** At `/product/<name>` the conversation is the page; on the
floor, the board and a card it is a dock in the corner, for the project the page is about. What
anybody says in the conversation, what the role answers and whether it is thinking or answering
arrive as they happen, over the panel's product socket (`/api/product/stream`) — nothing on the
page re-reads the conversation on a clock, and a page whose connection drops reconnects and is
handed what it missed from the conversation's record. A private conversation reaches its own
person and nobody else; the project's room reaches whoever may read the product area. Every
message carries the page it was written on, so "why did this stop?" typed beside card #42 is a
question about card #42 — the role is handed that card as the project's tracker has it. Only a
card of that project, and only for somebody who may read the board: a credential scoped to the
product area can ask about a card in words, not by pointing at it. The role's answer arrives
whole when it is ready; it is not typed out word by word.

The panel identifies people by token. Two shapes, and the difference is the whole point:

```bash
# .env.compose (or the deployment's secret store)
OPENFACTORY_PRODUCT_TOKENS="tok-ana:ana:Ana Souza,tok-rui:rui:Rui Lima"   # per person: token:id:display
OPENFACTORY_PRODUCT_TOKEN="one-shared-token"                              # shared: READ-ONLY in practice
```

The shared token resolves to a subject with no id, and **every write path checks
`product.admins`** — so a shared-token holder can look and never act. For a PO who accepts,
drops, queues and releases:

1. issue a per-person entry in `OPENFACTORY_PRODUCT_TOKENS`, and
2. list that person's `id` in the registry entry's `product.admins`:

```yaml
# the registry entry (openfactory project add wrote the rest)
product:
  docs_repo: <org>/<name>-context
  admins: [ana, rui]          # the ids from OPENFACTORY_PRODUCT_TOKENS — these may accept/release
```

Then hand them the link — `http://<panel>/product/<name>` — which is the entire onboarding for
somebody holding a product credential. A legacy corpus of existing requirements is adopted with
`openfactory product baseline <name>` (it proposes, a human confirms; nothing is rewritten
silently).

## 3 · The release gate

Production is human-approved, always (D-12), and the chain has two halves — WHO may approve, and
HOW they prove it is them:

```yaml
# .openfactory/project.yaml — beside environments/promote
prod_approvers: [ana, rui]        # or the deployment-wide OPENFACTORY_PROD_APPROVERS env
```

```bash
openfactory approver add ana      # sets the password, stored hashed in ~/.openfactory/approvers.json
# deployments that cannot mount a home dir: OPENFACTORY_APPROVERS='{"ana": "<scrypt-hash>"}'
# or OPENFACTORY_APPROVERS_FILE=/path/to/approvers.json
```

The panel's release form asks login + password; the approval is recorded on the ticket with the
approver's name and the version tag. With a declared promotion chain (`promote: [dev, qa, prod]`
— see [04](configuration.md)), the gate sits before the LAST stage, whatever you named it.

## 4 · The fifteen-minute checklist

```bash
openfactory product init <name> --create-context --write   # context repo + three-way declaration
# put OPENFACTORY_PRODUCT_TOKENS in .env.compose; add the ids to product.admins in the registry
# restart the stack with --env-file so the tokens reach the panel
openfactory approver add <login>                           # the release password
open http://localhost:8787/product/<name>                  # hand this link to the PO
```

If any of it is missing the surface says so by name — a PO who sees "every write refuses" was
given the shared token; go back to §2.

## 5 · Measuring it

How well the role answers is measured, not believed: `make eval-product` asks it a battery of
product-owner questions about a fixture product and records whether each answer is correct,
cited, and says "I do not know" when it should. It asks a live model, so it spends tokens and never
runs inside `make test`. [product-role-evaluation.md](product-role-evaluation.md) is how to write
the questions and read a score.
