"""The read model of the product: what the panel shows about it, as one projection the product
role reads too (#267 slice 1, ADR-0052 "The owner's view").

THE ROLE COULD NOT SEE WHAT THE PANEL SHOWS. Its facts pack was the board (a window of the 300
most recently updated cards, number, column, title and state), the loops it opened and the
decisions it asked for. The floor was the tech-lead's alone: which jobs run, which parked and why,
the pull requests and what their checks and reviews said, the version in production. So a person
asking the product owner "why did #42 stop?" or "is 1.4 out?" got "I cannot see that", while the
answer sat one tab away on the panel.

THE INVARIANT: anything a person can see about the product on the panel, the role can know,
except what `EXCLUDED` names — and every entry there says what it withholds and why. It starts with
spend (#266, decision 7: cost does not help build the product). `tests/test_the_read_model.py` is
the guard: it finds the panel's project routes in `app.routes`, calls each one on a bed, and holds
every field they answer to this model's files or to this list.

ONE PROJECTION, TWO CONSUMERS, AND THE SAME READS. The panel's screens answer from the ports and
the engine's views — `TrackerAdapter.list_tickets` / `get_ticket` / `comments`,
`BoardAdapter.column_names` / `columns`, the forge's pull-request reads, `view.list_jobs`,
`view.job_detail`, the floor's ladder, the loop ledger — and this model is built from exactly
those, called the way the routes call them. What the model adds on top is organisation (three
layers, keyed by product) and discipline (the exclusions, the names, the credentials).

THREE LAYERS, the issue's table:

    now       what is moving, stopped, waiting on whom — the floor's verdict, the live jobs and WHY
              (the engine's own reason and the tech-lead's diagnosis, as data, never diagnosed
              again here), their pull requests, checks and reviews, and every open loop
    history   what was done, when, for whom — the whole board (no window), the finished jobs and
              their deliveries, the version in production, who asked for what
    meaning   what each card promises — bodies and threads, labels, assignees, linked pull
              requests, and the requirements with `Asked by`

KEYED BY PRODUCT (#266, decision 1). A product is the context repository (`product/key.py`); its
model is the union of every registry project that points at it, and nothing else: the jobs are
filtered to those names, the floor is asked per name, the boards and ledgers are read per name.
Another product's card, job or loop never enters this one's model.

NAMES (#266: nobody is named across conversations). Who asked for what is KEPT as a person id —
the model is the record — and never RENDERED: a requester is "its requester", or "you" when it is
the person this turn answers. Every rendered line also passes through `Names.redact`, so an id that
rides inside a ticket body ("Awaiting the acceptance of …"), a private conversation's key or a
loop's context is withheld wherever it appears. Tracker identities — an assignee, a comment's
author — are the tracker's public record and are rendered as the tracker spells them, as the card
context the panel already hands the role does (`page.py`); a person the platform knows as a
requester is withheld in any spelling, the tracker's included.

NEVER RAISES. It is built inside a turn; every read is caught where it is made and becomes a GAP
with its reason — the manifest's rule that UNREADABLE is not absence, kept verbatim.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

from openfactory.util.bounded import BoundedDict

log = logging.getLogger("openfactory.product")


# ── what the role does not see, and why ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Exclusion:
    """One thing the panel shows about a product that the role is not given.

    A FIELD PATH is `<route>:<key>.<key>[].<key>` — the route as `app.routes` spells it, then the
    keys down to the value, `[]` for a list's items. `paths` are globs over a whole field path;
    `keys` are globs over any ONE key in it, which withholds that key and everything under it
    wherever it appears (spend is a key the engine, the journal and the dashboard all spell)."""

    what: str
    why: str
    paths: tuple[str, ...] = ()
    keys: tuple[str, ...] = ()

    def covers(self, path: str) -> bool:
        if any(_glob(glob).fullmatch(path) for glob in self.paths):
            return True
        if not self.keys:
            return False
        _route, _, rest = path.partition(":")
        names = [part.removesuffix("[]") for part in rest.split(".") if part]
        return any(fnmatch.fnmatchcase(name.lower(), glob) for name in names for glob in self.keys)


def _glob(glob: str) -> re.Pattern:
    """A path glob where `*` is the only wildcard. `fnmatch` would read the `[]` every list path
    carries as a character class, and a class that swallows the dot after it matches paths the
    entry never named."""
    return re.compile(".*".join(re.escape(part) for part in glob.split("*")))


#: The keys that are money or its proxies, wherever they appear. Globs over ONE key, lowercased.
SPEND_KEYS = ("*cost*", "*usd*", "*spend*", "*spent*", "*price*", "*billing*", "tokens",
              "*_tokens", "tokens_*", "num_turns")

#: EVERY ENTRY NAMES WHAT IT WITHHOLDS AND WHY. The guard reads this list: a field it covers is
#: never demanded of the role, and nothing it covers may reach the role's files.
EXCLUDED: tuple[Exclusion, ...] = (
    Exclusion(
        what="spend — what a run, a pass or a task cost, in money or in tokens and turns",
        why="#266, decision 7: cost does not help build the product, so the product role does not "
            "see it. The cost dashboard, a finished job's `cost_usd` and the journal's per-call "
            "spend are the operator's.",
        paths=("/api/metrics:*",),
        keys=SPEND_KEYS),
    Exclusion(
        what="a run's raw log — every tool the agent called, every validation's output, which "
             "credential of the pool it ran on",
        why="the tech-lead's evidence, not the product's facts: the tech-lead diagnoses the "
            "factory from it and the product role consumes that diagnosis (the job's `why`, its "
            "note, the tech-lead's comment on the card) — reading the log itself would be "
            "diagnosing again, a second truth (#267, the tech-lead boundary). It also names a "
            "credential's id and each call's spend.",
        paths=("/api/jobs/{project}/{issue}/events:*", "/api/jobs/{project}/{issue}/stream:*")),
    Exclusion(
        what="the cockpit — which harness, models, auth route, credential pool, region and "
             "consoles the factory runs a project on",
        why="the factory's machinery, not the product: the tech-lead's to read. The credential "
            "pool's ids are a credential's metadata, which never reaches a facts file, and which "
            "credential pays (`auth_credential`) is spend. Whether cards are picked up at all "
            "reaches the role through the floor's verdict, in a sentence.",
        paths=("/api/factory/{project}:*",)),
    Exclusion(
        what="the factory's thread with its operators — the tech-lead's messages, the questions "
             "it asked, the answers and who gave them, a staged suggestion",
        why="another conversation, with another role: #266 decision 3 keeps what is not "
            "addressed to the product role out of its turns, and who answered is a name the role "
            "never carries across conversations. What the factory DID reaches the role from the "
            "jobs, the board and the loops, not from what was said about it.",
        paths=("/api/messages/{project}:*",)),
    Exclusion(
        what="who may approve a release to production, and the approval form's own inputs (the "
             "suggested versions, the tag prefix)",
        why="releasing is not the role's (ADR-0016 holds, #266 'not in this issue'), and the "
            "approvers are people named by the operator's store. The version in production — the "
            "newest release tag — IS in the model.",
        paths=("/api/promote/{project}/{issue}:approvers*",
               "/api/promote/{project}/{issue}:suggestions*",
               "/api/promote/{project}/{issue}:tag_prefix")),
    Exclusion(
        what="an operator's controls — a command to type on the host, the buttons a screen "
             "draws, whether a page may merge by itself, how often a page may re-read the board",
        why="a screen's wiring, not a fact about the product: the role never hands a client an "
            "operator's command, and the fact behind each control (the cause, the gate, the "
            "state) is carried in its own field.",
        paths=("/api/floor*:cmd", "/api/floor*:also[].cmd", "/api/floor*:actions*",
               "/api/board/{project}:poll_seconds", "/api/board/{project}:pr.can_merge_here")),
    Exclusion(
        what="a sealed person or conversation — the digests a decision loop keeps of whom it was "
             "asked and where",
        why="kept only to be COMPARED, never read (#266 slice 4): the model uses them to say "
            "\"asked of you\" to the person it was asked of, and the digest itself says nothing.",
        paths=("/api/loops/{project}:waiting[].context.asked_of",
               "/api/loops/{project}:waiting[].context.asked_in")),
    Exclusion(
        what="an internal document — read or not: its path, its title, its type and, when it "
             "could not be read, why — as the documents screen lists it to a credential that may "
             "read the floor",
        why="#269 and #266 decision 8: a document labelled internal is for the product's own "
            "people, and its name is content, so it is named only to a turn that answers an "
            "engineer or a product admin in a conversation of their own "
            "(`documents/record.py::turn_audience`). Every other turn, a room's included, is told "
            "how many there are and nothing else, as a product credential is on the same screen.",
        paths=("/api/product/{project}/documents:unreadable_internal*",
               "/api/product/{project}/documents:documents_internal*")),
    Exclusion(
        what="a card's preview — whether one is running, why one can or cannot start, and a link "
             "to each service it exposes",
        why="#265: every link carries a key minted for the person who opened the card, a "
            "credential that opens the running change, so this answer is never read into a facts "
            "file whole. Whether a card can be looked at before it merges is the card's, on the "
            "panel; the role says nothing about a preview it cannot see.",
        paths=("/api/preview/{project}/{unit}:*",)),
)


#: The panel routes whose answers the model keeps as they are, less what `EXCLUDED` withholds.
FLOOR_ROUTE = "/api/floor/{project}"
DETAIL_ROUTE = "/api/jobs/{project}/{issue}/detail"


def excluded(path: str) -> Exclusion | None:
    """The entry that withholds `path`, or None when the role may see it."""
    return next((entry for entry in EXCLUDED if entry.covers(path)), None)


def _spend_key(key: str) -> bool:
    return any(fnmatch.fnmatchcase(str(key).lower(), glob) for glob in SPEND_KEYS)


def scrub(value):
    """`value` with every spend key removed, at any depth — what is allowed INTO the model.

    Withheld on the way in rather than skipped on the way out, so no renderer, present or to come,
    can print what the model does not hold."""
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if not _spend_key(k)}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def withhold(value, route: str, prefix: str = ""):
    """`value` — a panel route's answer, or the part of one the model keeps — with every field
    `EXCLUDED` names under `route` removed: what a screen shows and the role is not given never
    enters the model it is rendered from."""
    if isinstance(value, dict):
        out = {}
        for key, inner in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if excluded(f"{route}:{path}") is None:
                out[key] = withhold(inner, route, path)
        return out
    if isinstance(value, list):
        return [withhold(inner, route, f"{prefix}[]") for inner in value]
    return value


def fields(value, prefix: str = "") -> Iterator[tuple[str, object]]:
    """Every leaf of a JSON answer as `(path, value)` — `a.b[].c`, `[]` for a list's items.

    An empty dict or list is a leaf of its own (`{}` / `[]`), because "read, and nothing there" is
    an answer a screen shows."""
    if isinstance(value, dict):
        if not value:
            yield prefix, value
        for key, inner in value.items():
            yield from fields(inner, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, list):
        if not value:
            yield prefix, value
        for inner in value:
            yield from fields(inner, f"{prefix}[]")
    else:
        yield prefix, value


# ── spend and credentials in words ──────────────────────────────────────────────────────────────

#: The sentences the factory itself writes about spend, withheld from any text the model renders.
#: Each is the exact shape its writer produces — `orchestrator/machine.py`'s pull-request line and
#: cost-ceiling park, `techlead/watch.py`'s harness reading — and a test builds each from its own
#: code, so a reworded writer turns the guard red instead of leaking.
_SPEND_WORDS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"^[ \t]*Cost:[ \t]*\$[\d.,]+[ \t]*$\n?", re.M), ""),
    (re.compile(r"cost ceiling reached \([^)\n]*\)[^\n]*"),
     "held for review: the run reached a limit the operator set — split the ticket, or ask the "
     "operator"),
    (re.compile(r"[,;]?\s*the pass had billed \$[\d.,]+ by then"), ""),
)


def scrub_spend(text: str) -> str:
    for pattern, said in _SPEND_WORDS:
        text = pattern.sub(said, text)
    return text


#: A credential by its shape — the forges', the chat vendors', the clouds' and the model vendors'
#: own prefixes — and a URL carrying userinfo, which is how a clone URL holds a token.
_CREDENTIAL_SHAPES = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_-]{16,}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{16,})")
_USERINFO = re.compile(r"(\b[a-zA-Z][a-zA-Z0-9+.-]*://)[^\s/@]+@")
#: An environment variable whose value is a secret, by its name.
_SECRET_NAME = re.compile(r"TOKEN|SECRET|PASSW|API_?KEY|PRIVATE|CREDENTIAL|KEY_CONTENT", re.I)
WITHHELD_CREDENTIAL = "[credential withheld]"


def scrub_credentials(text: str) -> str:
    """`text` with every credential this process holds, and every credential-shaped string,
    withheld. A facts file is read by a model and written to a workspace; a token in one is a token
    handed to whatever reads that directory."""
    text = _USERINFO.sub(r"\1", text)
    text = _CREDENTIAL_SHAPES.sub(WITHHELD_CREDENTIAL, text)
    for secret in _secrets_of_this_process():
        if secret in text:
            text = text.replace(secret, WITHHELD_CREDENTIAL)
    return text


def _secrets_of_this_process() -> list[str]:
    """The values of this process's secret-named variables, longest first. Eight characters at
    least: a shorter value is a flag (`1`, `true`), and withholding it would eat ordinary words."""
    found = {value for name, value in os.environ.items()
             if _SECRET_NAME.search(name) and len(value or "") >= 8}
    return sorted(found, key=len, reverse=True)


# ── names ───────────────────────────────────────────────────────────────────────────────────────

#: A loop context's keys whose values are PEOPLE of the platform (or their spelling on the
#: tracker), as the writers of `memory/ledger.py`'s loops record them. Never rendered; each value
#: joins the ids withheld wherever they ride. (`poster` is not here: it is the platform's own
#: login, which a person reading a card needs to tell a handoff from a remark.)
PEOPLE_KEYS = frozenset({"person", "asked_by", "said_by", "reported_by", "requester",
                         "requester_forge", "by", "actor"})

#: A PRIVATE conversation's key (`conversation.py`: `person:<id>`, `visitor:<id>`) carries a
#: person's id, and rides in a loop's `about` and `channel`.
_PRIVATE_KEY = re.compile(r"\b(?:person|visitor):[^\s,;)\]}>\"'`]+")
SOMEONE, YOU = "[a person]", "[you]"
THEIR_REQUESTER, YOUR_OWN = "its requester", "you (the person speaking)"


class Names:
    """Who this turn may name — nobody but the person it answers — and the withholding of the rest.

    `people` is every person id the model knows (requesters, the product's admins and engineers,
    the people in loop contexts) in every spelling it knows. `speaker` is the person this turn
    answers, or "" when the files may be read by another conversation's turn."""

    def __init__(self, people=(), *, speaker: str = "") -> None:
        self.speaker = str(speaker or "").strip()
        known = {str(p).strip() for p in people if len(str(p or "").strip()) >= 2}
        if self.speaker:
            known.add(self.speaker)
        self._known = sorted(known, key=len, reverse=True)
        self._pattern = (re.compile(
            r"(?<![\w.-])(?:" + "|".join(re.escape(p) for p in self._known) + r")(?![\w-])")
            if self._known else None)

    def requester(self, who: str) -> str:
        """How a requester is SAID: "you" to themselves, "its requester" to everyone else."""
        who = str(who or "").strip()
        if not who:
            return "unrecorded"
        return YOUR_OWN if self.speaker and _bare(who) == _bare(self.speaker) else THEIR_REQUESTER

    def redact(self, text: str) -> str:
        """`text` with every private conversation's key and every known person withheld."""
        text = _PRIVATE_KEY.sub(self._conversation, str(text or ""))
        if self._pattern is not None:
            text = self._pattern.sub(self._person, text)
        return text

    def _conversation(self, match: re.Match) -> str:
        key = match.group(0)
        from openfactory.product.conversation import person_of

        # the OWNER's id, whichever of their sessions the key names (#335)
        mine = self.speaker and person_of(key) == self.speaker
        return "[your private conversation]" if mine else "[a private conversation]"

    def _person(self, match: re.Match) -> str:
        return YOU if self.speaker and match.group(0) == self.speaker else SOMEONE


def _bare(who: str) -> str:
    return str(who or "").strip().strip("<@>").strip()


# ── the model ───────────────────────────────────────────────────────────────────────────────────

@dataclass
class ProductModel:
    """The product as the panel shows it, in three layers, for every registry project it has.

    Each layer maps a member's registry name to what was read for it; `None` for a section is a
    FAILED read (said in `gaps`), never an empty one. `people` is every person id the model holds —
    requesters above all — so a renderer can withhold each wherever it rides. `read_at` is when the
    reading began: the age of every fact that carries no time of its own (#267 slice 2, the
    briefing says it on every line)."""

    key: str
    members: list[str]
    now: dict[str, dict] = field(default_factory=dict)
    history: dict[str, dict] = field(default_factory=dict)
    meaning: dict[str, dict] = field(default_factory=dict)
    requirements: list[dict] | None = None
    #: the context repository's documents as the panel shows them (#269): how many were read and
    #: every one that could not be, with why — `None` when the record could not be read
    documents: dict | None = None
    people: set[str] = field(default_factory=set)
    gaps: list[str] = field(default_factory=list)
    read_at: str = ""


#: How many FINISHED jobs are read in detail (their checks, gates and review), newest first. Every
#: live job is; the rest of the finished ones keep the engine's row — state, deploy, times, pull
#: request — and the manifest says the detail was not read.
FINISHED_DETAILS = 5
#: How many card threads are fetched from the tracker per turn. A thread fetched once is kept until
#: its card changes (`_THREADS`), so this bounds the first turns on a large board, not every turn.
THREAD_READS = 40

#: `(project, ref, updated_at) → thread`. A thread changes only when its card does — a comment
#: moves the card's `updated_at` on every tracker the ports serve — so a card whose stamp has not
#: moved is not asked again. In process, like the board's own snapshot, and BOUNDED: a card that
#: changes leaves its old key behind, and the oldest keys go first.
_THREADS: BoundedDict[tuple[str, str, str], list[dict]] = BoundedDict(5000)


def members(project) -> list:
    """Every registry project of `project`'s product, `project` first — the union's members.

    A registry that cannot be read leaves the product as `project` alone, which is never another
    product's data."""
    from openfactory.product.key import product_key

    key = product_key(project)
    try:
        from openfactory.registry import ProjectRegistry

        others = [p for p in ProjectRegistry().list()
                  if p.name != project.name and product_key(p) == key]
    except Exception as exc:  # noqa: BLE001 — one member is still the product's own
        log.warning("[%s] the read model could not list the product's other registry projects "
                    "(%s) — it is built from this one alone", getattr(project, "name", "?"), exc)
        others = []
    return [project, *sorted(others, key=lambda p: p.name)]


def build(project, *, corpus=None, engine=None, loops_seen=None) -> ProductModel:
    """The product's read model, as read for this turn. Never raises.

    `corpus` is the requirement corpus the module already loaded (the product's own); `engine`
    replaces the engine reads for a caller that has them (a test), and is left out in production,
    where they run on the standing loop.

    `loops_seen(member)` is a member's ledger AS THE CONVERSATION THIS TURN ANSWERS IN MAY READ IT
    (#267 slice 3, `agenda.visible`): the room's items and its own — the rule `/api/loops` applies
    to the panel's viewer. Without one, every loop: right only for a reader no conversation owns."""
    from openfactory.product.key import product_key

    group = members(project)
    names = [p.name for p in group]
    model = ProductModel(key=product_key(project), members=names,
                         read_at=datetime.now(UTC).isoformat())
    reads = (engine or _engine_reads)(names)
    if reads.get("jobs") is None:
        why = reads.get("error") or "no reason given"
        model.gaps.append(f"the engine's jobs could not be read ({why}) — the jobs and their pull "
                          f"requests are unknown, not idle")
    for member in group:
        try:
            _one_member(model, member, reads, loops_seen)
        except Exception as exc:  # noqa: BLE001 — one member's trouble costs that member only
            log.warning("[%s] the read model could not read %s (%s)", project.name, member.name,
                        exc, exc_info=True)
            model.gaps.append(f"{member.name} could not be read ({str(exc)[:160]}) — its part of "
                              f"the product is unknown, not empty")
    model.requirements = _requirements(corpus, model)
    model.documents = _documents(model)
    return model


def _one_member(model: ProductModel, member, reads: dict, loops_seen=None) -> None:
    name = member.name
    board = _board_of(member, model)
    unread = reads.get("jobs") is None
    # ANOTHER PRODUCT'S JOB NEVER ENTERS: the engine lists the deployment's, and only the ones
    # whose registry project is this member are kept.
    rows = [dict(r) for r in (reads.get("jobs") or []) if r.get("project") == name]
    live = [r for r in rows if r.get("status") == "running"]
    finished = [r for r in rows if r.get("status") != "running"]
    details = reads.get("details") or {}
    cards = {c["ref"]: c for c in (board.get("cards") or [])}
    threads = _threads(member, board.get("cards"), live, model)
    for row in rows:
        detail = details.get((name, str(row.get("issue") or "")))
        row["detail"] = withhold(detail, DETAIL_ROUTE) if isinstance(detail, dict) else None
    if len(finished) > FINISHED_DETAILS:
        model.gaps.append(f"{name}: the detail of {len(finished) - FINISHED_DETAILS} older "
                          f"finished job(s) was not read — their state, pull request and deploy "
                          f"are in history.md")
    pulls = _pulls(member, live, model)
    for row in live:
        row["diagnosis"] = _diagnosis(threads.get(str(row.get("issue") or "")))
    floor = (reads.get("floors") or {}).get(name)
    if floor is None:
        model.gaps.append(f"{name}: the floor's verdict could not be read — whether the factory "
                          f"is working on it is unknown")
    model.now[name] = {
        "floor": floor,
        # WHETHER THE ENGINE ANSWERED — the job card's own first word; `jobs` being `None` says
        # the same thing, and this says it where a reader looks.
        "connected": not unread,
        "jobs": None if unread else [scrub(r) for r in live],
        "pulls": pulls,
        "loops": _loops_of(member, model, loops_seen),
    }
    model.history[name] = {
        "board": board,
        "finished": None if unread else [scrub(r) for r in finished],
        "release": _release_of(member, model),
    }
    for ref, thread in threads.items():
        if ref in cards:
            cards[ref]["comments"] = thread
    model.meaning[name] = {"cards": cards}
    people = model.people
    for card in cards.values():
        people.update(x for x in (card.get("requester"), card.get("requester_forge")) if x)
    cfg = getattr(member, "product", None)
    people.update(str(x) for x in (getattr(cfg, "admins", None) or ()))
    people.update(str(x) for x in (getattr(cfg, "engineers", None) or ()))
    people.update(str(v) for v in (getattr(member, "people", None) or {}).values() if v)


# ── the reads, each the one the panel makes ────────────────────────────────────────────────────

def _board_of(member, model: ProductModel) -> dict:
    """The WHOLE board (`read_board(limit=0)`: no window) with the columns the board declares —
    the panel's `/api/board/{project}` reads the same two ports — and each card's requester."""
    from openfactory.product.board import read_board

    tickets, error = read_board(member, limit=0)
    out: dict = {"board": True, "columns": None, "cards": None}
    if error:
        # THE COLUMNS ARE NOT ASKED EITHER: a board whose cards could not be read is unreadable,
        # and asking the same provider again for its column names is a second failure to wait on.
        model.gaps.append(f"{member.name}: the board could not be read ({error}) — do not report "
                          f"any card as absent, say the board was not readable")
        return out
    out["cards"] = [_card(member, t) for t in tickets]
    try:
        from openfactory.adapters.board import build_board
        from openfactory.credentials import deployment_tracker_token, tracker_token_for

        made = build_board(member, token=tracker_token_for(member)
                           or deployment_tracker_token(member))
        if made is None:
            out["board"] = False
        else:
            out["columns"] = made.column_names()
    except Exception as exc:  # noqa: BLE001 — the column names are one line of the board
        log.info("[%s] the read model could not read the board's columns (%s)", member.name, exc)
    if out["board"] and out["columns"] is None:
        model.gaps.append(f"{member.name}: the board's column names could not be read — the "
                          f"cards still say where each one sits")
    return out


def _card(member, ticket) -> dict:
    from openfactory.product.authoring import filed_by_the_product_role

    body = str(getattr(ticket, "body", "") or "")
    requester, forge = _requester_of(member, ticket, body)
    return {"ref": str(ticket.number), "title": ticket.title or "", "state": ticket.state or "",
            "state_reason": ticket.state_reason or "", "column": ticket.column or "",
            "labels": list(ticket.labels or []), "assignees": list(ticket.assignees or []),
            "updated_at": ticket.updated_at or "", "body": body,
            "opened_by_product": filed_by_the_product_role(body),
            "requester": requester, "requester_forge": forge}


def _requester_of(member, ticket, body: str) -> tuple[str, str]:
    """Who asked for this card — the person id the factory wrote on it, and the tracker's spelling
    of the same person — read the way the pipeline reads it (`parse_ticket_body`)."""
    if not body:
        return "", ""
    try:
        from openfactory.adapters.forge.registry import repo_of
        from openfactory.adapters.tracker.parse import parse_ticket_body

        parsed = parse_ticket_body(id=str(ticket.number), title=ticket.title or "", body=body,
                                   repo=repo_of(member) or "")
    except Exception:  # noqa: BLE001 — a card whose body will not parse names nobody
        log.debug("[%s] card %s did not parse for its requester", member.name, ticket.number,
                  exc_info=True)
        return "", ""
    return (parsed.requester or "").strip(), (parsed.requester_forge or "").strip()


def _threads(member, cards, live: list[dict], model: ProductModel) -> dict[str, list | None]:
    """Every card's thread, through the tracker's port — the panel's card drawer reads the same
    `comments` — kept until the card changes.

    THE ORDER IS WHAT A BOUND COSTS LEAST: the cards a live job is on, then the open ones, then
    the closed ones newest-updated first. `None` for a thread that could not be read; a card past
    `THREAD_READS` has no entry this turn, is read on a later one, and the manifest says how many
    are waiting."""
    if not cards:
        return {}
    on_the_floor = {str(r.get("issue") or "") for r in live}
    # TWO STABLE SORTS: newest-updated first, then by what matters more, which keeps the dates in
    # order inside each group.
    wanted = sorted(cards, key=lambda c: c.get("updated_at") or "", reverse=True)
    wanted.sort(key=lambda c: (c["ref"] not in on_the_floor, c["state"] != "open"))
    tracker = None
    out: dict[str, list | None] = {}
    fetched = skipped = 0
    for card in wanted:
        # A CARD WITH NO STAMP IS NEVER KEPT: nothing would ever say it changed.
        key = (member.name, card["ref"], card["updated_at"]) if card["updated_at"] else None
        kept = _THREADS.get(key) if key else None
        if kept is not None:
            out[card["ref"]] = list(kept)
            continue
        if fetched >= THREAD_READS:
            skipped += 1
            continue
        if tracker is None:
            tracker = _tracker_of(member)
            if tracker is None:
                model.gaps.append(f"{member.name}: no tracker could be built — no card's thread "
                                  f"was read")
                return out
        fetched += 1
        try:
            thread = tracker.comments(card["ref"])
        except Exception:  # noqa: BLE001 — the port says the read side degrades; belt, not policy
            log.warning("[%s] the tracker raised reading the thread of %s", member.name,
                        card["ref"], exc_info=True)
            thread = None
        if thread is None:
            out[card["ref"]] = None
            continue
        rows = [{"author": c.author, "body": c.body, "created_at": c.created_at} for c in thread]
        out[card["ref"]] = rows
        if key:
            _THREADS[key] = rows
    unread = [ref for ref, thread in out.items() if thread is None]
    if unread:
        model.gaps.append(f"{member.name}: the threads of {', '.join('#' + r for r in unread)} "
                          f"could not be read — say the platform could not look, never that "
                          f"nobody commented")
    if skipped:
        model.gaps.append(f"{member.name}: {skipped} card(s) had their thread left for a later "
                          f"turn (at most {THREAD_READS} are fetched per turn, and one fetched is "
                          f"kept until its card changes) — their bodies are in their files; say "
                          f"the thread was not read, never that nobody commented")
    return out


def _tracker_of(member):
    try:
        from openfactory.adapters.tracker.registry import build_tracker
        from openfactory.credentials import deployment_tracker_token, tracker_token_for

        return build_tracker(member, token=tracker_token_for(member)
                             or deployment_tracker_token(member))
    except Exception as exc:  # noqa: BLE001 — no tracker is a gap the caller states
        log.warning("[%s] the read model could not build the tracker (%s)", member.name, exc)
        return None


def _diagnosis(thread) -> str:
    """The tech-lead's own diagnosis of a parked card, AS IT WROTE IT — the newest comment on the
    card's thread carrying one of the markers its handoffs open with (`board._DIAGNOSIS_MARKERS`,
    the same ones the Needs Action review reads), or "". Never a fallback to somebody's last
    remark: that is what the thread itself is for, and presenting it as the diagnosis would invent
    a provenance."""
    from openfactory.product.board import _DIAGNOSIS_MARKERS

    for comment in reversed(thread or []):
        if any(m in (comment.get("body") or "").lower() for m in _DIAGNOSIS_MARKERS):
            return str(comment.get("body") or "")
    return ""


def _pulls(member, live: list[dict], model: ProductModel) -> dict[str, dict]:
    """Every live job's pull request, as the panel's pull-request page reads it (the forge port's
    `pr_status` / `pr_body` / `pr_diff`, and the review events and refusal a row may keep)."""
    urls = []
    for row in live:
        for source in (row.get("action") or {}, row.get("detail") or {}):
            url = str(source.get("pr_url") or "").strip()
            if url and url not in urls:
                urls.append(url)
    if not urls:
        return {}
    try:
        from openfactory.adapters.forge.registry import build_forge
        from openfactory.credentials import deployment_forge_token, forge_token_for

        forge = build_forge(member, token=forge_token_for(member)
                            or deployment_forge_token(member))
    except Exception as exc:  # noqa: BLE001 — a forge that cannot be built is a gap
        model.gaps.append(f"{member.name}: the forge could not be built ({str(exc)[:120]}) — "
                          f"the pull requests' state is unknown")
        return {}
    return {url: pull_request(forge, url) for url in urls}


def pull_request(forge, ref: str) -> dict:
    """One pull request as the panel's page shows it — the three answers kept: `readable` false and
    `None` for what could not be read, `""` for what is empty."""

    def _ask(what, *, default=None):
        try:
            return what()
        except Exception:  # noqa: BLE001 — one read failing costs that read
            log.info("the read model could not read %r of a pull request", ref, exc_info=True)
            return default

    state = _ask(lambda: forge.pr_status(pr=ref), default="")
    return {"ref": ref, "state": state or "", "readable": bool(state),
            "body": _ask(lambda: forge.pr_body(pr=ref)),
            "diff": _ask(lambda: forge.pr_diff(pr=ref)),
            "events": _ask(lambda: getattr(forge, "pr_events", lambda **_: [])(pr=ref),
                           default=[]),
            "refused": _ask(lambda: getattr(forge, "pr_refusal", lambda **_: "")(pr=ref),
                            default="")}


def _loops_of(member, model: ProductModel, loops_seen=None) -> list[dict] | None:
    """Everything still waiting (ADR-0021) that this turn may see — the panel's
    `/api/loops/{project}`, filtered for its viewer the same way (`build`'s `loops_seen`)."""
    try:
        from openfactory.memory import store as loop_store
        from openfactory.memory.ledger import waiting

        rows = waiting(loops_seen(member) if loops_seen is not None
                       else loop_store.read(member.name))
    except Exception as exc:  # noqa: BLE001 — an unreadable ledger is a gap, not a quiet one
        model.gaps.append(f"{member.name}: the open-loop ledger could not be read ({exc}) — what "
                          f"is waiting on whom is unknown, not empty")
        return None
    out = []
    for x in rows:
        context = {str(k): str(v) for k, v in (x.context or {}).items()}
        model.people.update(v for k, v in context.items() if k in PEOPLE_KEYS and v)
        out.append({"kind": x.kind, "subject": x.subject, "about": x.about, "owner": x.owner,
                    "state": x.state, "opened": x.ts, "chased": x.chased_ts,
                    "context": context})
    return out


def _release_of(member, model: ProductModel) -> dict | None:
    """The version in production: the newest release tag, as the production-approval dialog reads
    it (`forge.latest_tag()`). `None` when it could not be read."""
    try:
        from openfactory.adapters.forge.registry import build_forge, repo_of
        from openfactory.credentials import deployment_forge_token, forge_token_for

        if not repo_of(member):
            model.gaps.append(f"{member.name} names no repository — the version in production "
                              f"cannot be read, which is not the same as none")
            return None
        forge = build_forge(member, token=forge_token_for(member)
                            or deployment_forge_token(member))
        return {"latest_tag": forge.latest_tag()}
    except Exception as exc:  # noqa: BLE001 — an unread release is a gap, never "no release"
        model.gaps.append(f"{member.name}: the newest release could not be read "
                          f"({str(exc)[:120]}) — the version in production is unknown, not none")
        return None


def _requirements(corpus, model: ProductModel) -> list[dict] | None:
    """The product's requirements, every one, with who asked (kept as the person id it records)."""
    if corpus is None:
        return None
    from openfactory.product.corpus import requester_identity

    out = []
    for r in sorted(getattr(corpus, "requirements", None) or (), key=lambda x: x.number):
        asked = requester_identity(getattr(r, "asked_by", "") or "")
        if asked:
            model.people.add(asked)
        out.append({"number": r.number, "title": r.title or r.slug, "status": r.status,
                    "superseded_by": r.superseded_by, "affects": list(r.affects or []),
                    "path": str(r.path), "asked_by": asked})
    return out


def _documents(model: ProductModel) -> dict | None:
    """The product's documents as `/api/product/{project}/documents` answers them — the same read,
    `documents.overview` (#269 slice 1): so a document the panel shows as unreadable is one the
    role knows exists and could not be read.

    WHOLE, THE INTERNAL ONES INCLUDED: the model is built once per turn and its files are rendered
    for that turn's reader, so the filter is the rendering's (`documents_shown`), per turn."""
    try:
        from openfactory.product.documents.ingest import overview

        return overview(model.key, internal=True)
    except Exception as exc:  # noqa: BLE001 — unread records are a gap, never "no documents"
        model.gaps.append(f"the records of the context repository's documents could not be read "
                          f"({str(exc)[:160]}) — which documents could not be read is unknown, "
                          f"not none")
        return None


def _engine_reads(names: list[str]) -> dict:
    """The floor's verdict per member, the jobs, and the detail of the ones the model reads — the
    same reads `/api/floor/{project}`, `/api/temporal/jobs` and `/api/jobs/.../detail` make, on
    the standing loop (`standing.from_a_thread`: this runs on a turn's thread, with no loop)."""

    async def _run() -> dict:
        from openfactory import floor
        from openfactory.runtime.temporal import view as tv

        try:
            client = await tv.connect()
        except Exception as exc:  # noqa: BLE001 — the floor says the engine did not answer
            log.info("the read model could not reach the engine (%s)", exc)
            client = None
        inputs = await floor.gather(client, want=floor.EVERYTHING)
        # THE FLOOR IS ASKED EITHER WAY: "the engine did not answer" is the floor's own verdict,
        # the one the panel shows, and not a gap in it.
        floors = {n: withhold(floor.state(inputs, n).as_dict(), FLOOR_ROUTE) for n in names}
        if not inputs.connected or inputs.jobs is None:
            return {"error": inputs.engine_error or "the job list could not be read",
                    "floors": floors, "jobs": None, "details": {}}
        rows = [dict(r) for r in inputs.jobs if r.get("project") in names]
        _, namespace = tv.temporal_config()
        details: dict = {}
        finished = 0
        for row in rows:
            if row.get("status") != "running":
                finished += 1
                if finished > FINISHED_DETAILS:
                    continue
            key = (row["project"], str(row.get("issue") or ""))
            try:
                details[key] = await tv.job_detail(client, key[0], key[1], namespace)
            except Exception as exc:  # noqa: BLE001 — one job's detail costs that job's
                log.info("the read model could not read the detail of %s#%s (%s)", *key, exc)
                details[key] = None
        return {"error": "", "floors": floors, "jobs": rows, "details": details}

    try:
        from openfactory.runtime.temporal.standing import from_a_thread

        return from_a_thread(_run)
    except Exception as exc:  # noqa: BLE001 — no engine, no library: a gap, never a crash
        log.info("the read model could not read the engine (%s)", exc)
        return {"error": str(exc)[:200] or type(exc).__name__, "floors": {}, "jobs": None,
                "details": {}}


# ── the files the role opens (ADR-0041: facts stay files) ───────────────────────────────────────

#: What a card's or a pull request's file is called, relative to the pack — a directory per kind,
#: one file per object, the member's name first so a multi-repository product never collides.
CARDS_DIR, PULLS_DIR = "cards", "pulls"


def render(model: ProductModel, *, speaker: str = "", audience: str = "client") -> dict[str, str]:
    """The model as the files of the facts pack — `now.md`, `history.md`, `board.md`,
    `requirements.md`, `documents.md` (#269), and a file per card and per pull request.

    EVERY FILE PASSES THE SAME THREE WITHHOLDINGS on its way out: the names (`Names.redact`), the
    factory's own sentences about spend, and every credential. `speaker` is the person this turn
    answers — named as "you" and nobody else — or "" when the files may be read by another
    conversation's turn. `audience` is the documents the turn may be shown by name
    (`documents/record.py::turn_audience`) — a client's, unless a caller says otherwise."""
    names = Names(model.people, speaker=speaker)
    files: dict[str, str] = {
        "now.md": _render_now(model, names),
        "history.md": _render_history(model, names),
        "board.md": _render_board(model, names),
    }
    if model.requirements is not None:
        files["requirements.md"] = _render_requirements(model, names)
    if model.documents is not None:
        files["documents.md"] = _render_documents(model.documents, audience=audience)
    for member in model.members:
        files.update(_card_files(model, member, names))
        for url, pull in ((model.now.get(member) or {}).get("pulls") or {}).items():
            files[f"{PULLS_DIR}/{member}-{_file_ref(url)}.md"] = _render_pull(member, url, pull)
    return {name: finish(text, names) for name, text in files.items()}


def finish(text: str, names: Names) -> str:
    """The three withholdings, in the order that leaves nothing behind: names first (an id may sit
    inside a URL a credential scrub would otherwise shorten), then spend, then credentials."""
    return scrub_credentials(scrub_spend(names.redact(text)))


def _file_ref(ref: str) -> str:
    """A pull request's ref as a file name: the number its URL ends in, else the ref made safe."""
    from openfactory.techlead.pack import _safe

    tail = re.search(r"(\d+)\D*$", str(ref or ""))
    return tail.group(1) if tail else _safe(str(ref))[-60:]


def _card_file(ref) -> str:
    from openfactory.techlead.pack import _safe

    return _safe(str(ref or ""))


def _key(name: str) -> str:
    """A field's key as the files say it — `opened_by_product` → `opened by product`. The guard
    looks for a yes/no under exactly this spelling, so it is one function, used everywhere."""
    return str(name).replace("_", " ")


def _value(value) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return "none"
    return str(value)


def _data(value, *, depth: int = 0) -> list[str]:
    """`value` as bullet lines, every key and every leaf — the engine's and the floor's answers
    AS DATA, so a field the panel shows is a line the role can read before anybody writes a
    sentence for it."""
    pad = "  " * depth
    lines: list[str] = []
    if isinstance(value, dict):
        for key, inner in value.items():
            if isinstance(inner, dict | list) and inner and not _scalars(inner):
                lines.append(f"{pad}- {_key(key)}:")
                lines += _data(inner, depth=depth + 1)
            else:
                lines.append(f"{pad}- {_key(key)}: {_inline(inner)}")
    elif isinstance(value, list):
        for inner in value:
            if isinstance(inner, dict):
                lines.append(f"{pad}-")
                lines += _data(inner, depth=depth + 1)
            else:
                lines.append(f"{pad}- {_inline(inner)}")
    else:
        lines.append(f"{pad}- {_inline(value)}")
    return lines


def _scalars(value) -> bool:
    return isinstance(value, list) and all(not isinstance(v, dict | list) for v in value)


def _inline(value) -> str:
    if isinstance(value, list):
        return ", ".join(_value(v) for v in value) if value else "(none)"
    if isinstance(value, dict):
        return "(none)"
    return _value(value)


# ── now ──

#: What a live job is waiting on, by its domain state — who has to move for it to move. The
#: briefing (#267 slice 2) says a stopped card in these words to everyone but an engineer in
#: private, so they are the translation, not a paraphrase of the diagnosis.
WAITS_ON = {
    "awaiting_your_merge": "a person to merge its pull request (or ask for an adjustment)",
    "awaiting_prod_approval": "the approval to release it to production",
    "on_hold": "a person — it is on hold until somebody answers what it asks",
    "needs_refinement": "a person to refine the card — the spec was unclear or the plan too big",
    "paused": "a clock — it resumes by itself",
    "merging": "its checks — it merges by itself when they pass",
    "repairing": "the agent — a pass is repairing it right now",
    "running": "the agent — it is being built",
}


def _render_now(model: ProductModel, names: Names) -> str:
    lines = ["# Now — what is moving, stopped, and waiting on whom", "",
             f"As read for this message, for the product `{model.key}` — "
             f"{_members_said(model)}. Every line is the platform's own reading: the floor's "
             "verdict, the engine's state and its reason, the tech-lead's diagnosis as it wrote "
             "it. Translate it for the person you are talking to; never diagnose it again — the "
             "tech-lead's word is the one account of why a job stopped.", ""]
    for member in model.members:
        now = model.now.get(member) or {}
        lines += [f"## {member}", "", "### The floor"]
        floor = now.get("floor")
        if floor is None:
            lines.append("- the floor could not be read — say so; do not call the factory idle")
        else:
            lines += _data(floor)
        lines += ["", "### Jobs on the floor",
                  f"- connected: {_value(bool(now.get('connected')))} — whether the engine "
                  "answered for this message"]
        jobs = now.get("jobs")
        if jobs is None:
            lines.append("- the jobs could not be read — say so; never that nothing is running")
        elif not jobs:
            lines.append("- no job is on the floor for this project")
        for job in jobs or []:
            lines += _render_job(member, job, live=True)
        lines += ["", "### What waits on whom"]
        lines += _waits(member, now, names)
        lines.append("")
    return "\n".join(lines) + "\n"


def _render_job(member: str, job: dict, *, live: bool) -> list[str]:
    detail = job.get("detail") or {}
    state = str(detail.get("state") or job.get("state") or "")
    title = str(job.get("title") or detail.get("title") or "").strip()
    lines = ["", f"#### {member}#{job.get('issue')}" + (f" — {title}" if title else "")
             + (f" ({state})" if state else "")]
    if live and state in WAITS_ON:
        lines.append(f"- waits on: {WAITS_ON[state]}")
    why = str(detail.get("why") or "").strip()
    if why:
        lines.append(f"- why (the engine's own reason): {why}")
    if job.get("diagnosis"):
        lines += ["- the tech-lead's diagnosis, as it wrote it on the card:", "",
                  str(job["diagnosis"]), ""]
    pr = str(detail.get("pr_url") or (job.get("action") or {}).get("pr_url") or "")
    if pr and live:
        lines.append(f"- pull request: {pr} — `{PULLS_DIR}/{member}-{_file_ref(pr)}.md`")
    lines.append(f"- card: `{CARDS_DIR}/{member}-{_card_file(job.get('issue'))}.md`")
    lines.append("- the engine's reading of the job:")
    lines += _data({k: v for k, v in job.items() if k not in ("detail", "diagnosis")}, depth=1)
    if detail:
        lines.append("- its detail (review, checks, gates):")
        lines += _data(detail, depth=1)
    elif job.get("detail") is None:
        lines.append("- its detail was not read for this message (see the manifest)")
    return lines


def _waits(member: str, now: dict, names: Names) -> list[str]:
    """Who has to move for each thing to move — the gates the jobs stand at and every open loop.
    People are said by their relation to the thing, never by name: "its requester", "the person it
    was asked of", or "you"."""
    lines: list[str] = []
    for job in now.get("jobs") or []:
        state = str((job.get("detail") or {}).get("state") or job.get("state") or "")
        if state in WAITS_ON and state not in ("running", "repairing"):
            lines.append(f"- {member}#{job.get('issue')} waits on {WAITS_ON[state]}")
    loops = now.get("loops")
    if loops is None:
        lines.append("- the open-loop ledger could not be read — what waits on whom is unknown")
        return lines
    for loop in loops:
        context = loop.get("context") or {}
        lines.append(f"- {loop.get('kind')} `{loop.get('subject')}` waits on {whom(loop, names)} "
                     f"— opened {loop.get('opened') or '?'}")
        lines += _data({k: v for k, v in loop.items() if k != "context"}, depth=1)
        shown = {k: v for k, v in context.items()
                 if k not in PEOPLE_KEYS and k not in ("asked_of", "asked_in")}
        if shown:
            lines.append("  - context:")
            lines += _data(shown, depth=2)
    if not lines:
        lines.append("- nothing waits on anybody")
    return lines


#: The loops that wait on the FACTORY — a remedy the tech-lead tried, a finding on a review — and
#: close by what a later pass observes. Every other kind waits on a person.
FACTORY_LOOPS = frozenset({"remedy", "finding"})


def whom(loop: dict, names: Names) -> str:
    """Who has to move for `loop` to close — said by relation, never by name: "you", "the person it
    was asked of", "its requester", or the tech-lead's own. `now.md` and the briefing say it in
    the same words, so the two never disagree about one loop.

    A CARD QUESTION IS ITS REQUESTER'S (ADR-0048). The tech-lead owns the loop, but the factory
    asked the card's requester, on the card, and only their answer closes it — the briefing's
    "#42 has waited two days on a decision from its requester" is this loop. Its `requester` is
    the tracker's spelling, which is never the platform id a speaker has, so it is said as "its
    requester" even to them: the safe direction for a name."""
    from openfactory.product.speaker import sealed

    context = loop.get("context") or {}
    kind = loop.get("kind")
    if kind == "decision":
        me = sealed(names.speaker) if names.speaker else ""
        return "you" if me and context.get("asked_of") == me else "the person it was asked of"
    if kind == "card_question":
        said = names.requester(context.get("requester") or "")
        return THEIR_REQUESTER if said == "unrecorded" else said
    if loop.get("owner") == "product":
        said = names.requester(context.get("asked_by") or context.get("person")
                               or context.get("requester") or "")
        return THEIR_REQUESTER if said == "unrecorded" else said
    return "an operator — it is the tech-lead's"


# ── history ──

def _render_history(model: ProductModel, names: Names) -> str:
    lines = ["# History — what was done, when, and for whom", "",
             f"The product `{model.key}` — {_members_said(model)}. The version in production, what "
             "was delivered, every finished job the engine still lists, and who asked for what — "
             "said as \"its requester\", never by name: the person may not be in this "
             "conversation.", ""]
    for member in model.members:
        history = model.history.get(member) or {}
        lines += [f"## {member}", "", "### The version in production"]
        release = history.get("release")
        if release is None:
            lines.append("- it could not be read — say so, never that nothing was released")
        elif release.get("latest_tag"):
            lines.append(f"- latest tag: {release['latest_tag']} — the newest release tag on the "
                         f"repository, what the production approval calls the current version")
        else:
            lines.append("- latest tag: none — the repository has no release tag yet")
        cards = (model.meaning.get(member) or {}).get("cards") or {}
        finished = history.get("finished")
        lines += ["", "### Delivered"]
        lines += _delivered(member, cards, finished, names)
        lines += ["", "### Finished jobs"]
        if finished is None:
            lines.append("- the jobs could not be read — say so")
        elif not finished:
            lines.append("- no finished job is listed by the engine")
        for job in finished or []:
            lines += _render_job(member, job, live=False)
        lines += ["", "### Who asked for what (cards)"]
        asked = sorted((c for c in cards.values() if c.get("requester")),
                       key=lambda c: _ref_key(c["ref"]))
        for card in asked:
            lines.append(f"- #{card['ref']} «{card.get('title')}» — asked by "
                         f"{names.requester(card['requester'])}")
        if not asked:
            lines.append("- no card on this board records who asked for it")
        lines.append("")
    return "\n".join(lines) + "\n"


def _delivered(member: str, cards: dict, finished, names: Names) -> list[str]:
    """What reached the people who asked: every merged job (with its deploy) and every card the
    tracker closed as COMPLETED — closed is not delivered (`triage.Ticket.delivered`)."""
    from openfactory.product.triage import Ticket

    lines = []
    for job in finished or []:
        detail = job.get("detail") or {}
        if (detail.get("state") or job.get("state")) != "merged":
            continue
        deploy = job.get("deploy") or detail.get("deploy") or "no deploy watch"
        lines.append(f"- {member}#{job.get('issue')} merged ({deploy}) — ended "
                     f"{job.get('close_time') or '?'}")
    done = [c for c in cards.values() if c.get("state") == "closed" and Ticket(
        number=c["ref"], state="closed", state_reason=c.get("state_reason") or "").delivered]
    for card in sorted(done, key=lambda c: c.get("updated_at") or "", reverse=True):
        lines.append(f"- card #{card['ref']} closed as {card.get('state_reason') or 'done'} — "
                     f"{card.get('title')} (asked by {names.requester(card.get('requester'))})")
    return lines or ["- nothing delivered is on record here yet"]


# ── the board, whole ──

def _render_board(model: ProductModel, names: Names) -> str:
    lines = ["# The board, whole", "",
             f"Every card of the product `{model.key}` — {_members_said(model)} — as read for this "
             "message: no window, every column, every state, with labels, assignees and who asked "
             "(as \"its requester\"). A card absent from THIS file is absent from the reading, "
             "which is not the same as absent from the product.", ""]
    for member in model.members:
        board = (model.history.get(member) or {}).get("board") or {}
        lines += [f"## {member}", ""]
        cards = board.get("cards")
        if cards is None:
            # NOTHING IS CLAIMED ABOUT A BOARD THAT WAS NOT READ — not even that it has one.
            lines += ["The board could not be read for this message — do not report any card as "
                      "absent; say the board was not readable.", ""]
            continue
        if not board.get("board", True):
            lines += ["- board: no — this project runs on tickets alone, with no columns", ""]
        else:
            columns = board.get("columns")
            lines += ["- board: yes",
                      "- columns: " + (" · ".join(columns) if columns
                                       else "(could not be read)" if columns is None
                                       else "(none)"), ""]
        by_column: dict[str, list] = {}
        for card in sorted(cards, key=lambda c: _ref_key(c["ref"])):
            by_column.setdefault(card.get("column") or "(no column)", []).append(card)
        for column, in_column in sorted(by_column.items(), key=lambda kv: -len(kv[1])):
            lines += [f"### {column} ({len(in_column)})", ""]
            lines += [_board_line(card, names) for card in in_column]
            lines.append("")
    return "\n".join(lines) + "\n"


def _board_line(card: dict, names: Names) -> str:
    state = card.get("state") or ""
    reason = card.get("state_reason") or ""
    tag = f" [{state}{':' + reason if reason else ''}]" if state else ""
    parts = [f"- #{card['ref']}{tag}" + (f" — {card['title']}" if card.get("title") else "")]
    if card.get("labels"):
        parts.append("labels: " + ", ".join(card["labels"]))
    if card.get("assignees"):
        parts.append("assignees: " + ", ".join(card["assignees"]))
    if card.get("requester"):
        parts.append(f"asked by {names.requester(card['requester'])}")
    if card.get("updated_at"):
        parts.append(f"updated {card['updated_at']}")
    return " · ".join(parts)


def _ref_key(ref: str):
    from openfactory.contracts.refs import ref_sort_key

    return ref_sort_key(ref)


# ── meaning ──

def _card_files(model: ProductModel, member: str, names: Names) -> dict[str, str]:
    """A file per card of the whole board — its body, its thread, the pull requests linked to it
    and its timeline. Every card, closed ones too: what a closed card promised is a question the
    panel's drawer answers, so the role's files answer it."""
    cards = (model.meaning.get(member) or {}).get("cards") or {}
    jobs = [*((model.now.get(member) or {}).get("jobs") or []),
            *((model.history.get(member) or {}).get("finished") or [])]
    loops = (model.now.get(member) or {}).get("loops") or []
    return {f"{CARDS_DIR}/{member}-{_card_file(c['ref'])}.md":
            _render_card(member, c, [j for j in jobs if str(j.get("issue")) == c["ref"]],
                         [lp for lp in loops if str(lp.get("subject")) == c["ref"]], names)
            for c in cards.values()}


def _render_card(member: str, card: dict, jobs: list[dict], loops: list[dict],
                 names: Names) -> str:
    pulls: list[str] = []
    for job in jobs:
        for source in (job.get("action") or {}, job.get("detail") or {}):
            url = str(source.get("pr_url") or "")
            if url and url not in pulls:
                pulls.append(url)
    lines = [f"# Card {member}#{card['ref']} — {card.get('title') or '(untitled)'}", "",
             f"- ref: {card['ref']}",
             f"- state: {card.get('state') or '?'}"
             + (f" ({card['state_reason']})" if card.get("state_reason") else ""),
             f"- column: {card.get('column') or '(no column)'}",
             f"- labels: {', '.join(card.get('labels') or []) or '(none)'}",
             f"- assignees: {', '.join(card.get('assignees') or []) or '(none)'}",
             f"- asked by: {names.requester(card.get('requester'))}",
             f"- opened by product: {card.get('opened_by_product') or 'no — written on the board'}",
             "- readable: yes",
             f"- updated at: {card.get('updated_at') or '?'}",
             "- pull requests: " + (", ".join(pulls) if pulls else "(none linked)"),
             "", "## What it says", "", card.get("body") or "(the card has no body)", "",
             "## Its thread"]
    if "comments" not in card:
        lines.append("(not read for this message — see the manifest)")
    elif card["comments"] is None:
        lines.append("It could NOT be read — say the platform could not look, never that nobody "
                     "commented.")
    elif not card["comments"]:
        lines.append("Nobody has commented on it.")
    else:
        lines.append(f"{len(card['comments'])} comment(s), oldest first:")
        for c in card["comments"]:
            lines += ["", f"### {c.get('created_at') or '?'} — {c.get('author') or 'somebody'}", "",
                      str(c.get("body") or "")]
    lines += ["", "## Timeline", "", *_timeline(card, jobs, loops)]
    return "\n".join(lines) + "\n"


def _timeline(card: dict, jobs: list[dict], loops: list[dict]) -> list[str]:
    """What happened to the card, oldest first: its runs, its thread, what waited on it, and its
    last change. Each line carries its time — a timeline without one is a list."""
    events: list[tuple[str, str]] = []
    for job in jobs:
        if job.get("start_time"):
            events.append((str(job["start_time"]), "a job started on it"))
        if job.get("close_time"):
            events.append((str(job["close_time"]),
                           f"the job ended — {job.get('state') or 'finished'}"))
    for c in card.get("comments") or []:
        if c.get("created_at"):
            events.append((str(c["created_at"]), f"{c.get('author') or 'somebody'} commented"))
    for loop in loops:
        if loop.get("opened"):
            events.append((str(loop["opened"]), f"a {loop.get('kind')} loop opened on it"))
    if card.get("updated_at"):
        events.append((str(card["updated_at"]), "its last change on the tracker"))
    return [f"- {when} — {what}" for when, what in sorted(events)] or ["- nothing dated"]


def _render_pull(member: str, url: str, pull: dict) -> str:
    lines = [f"# Pull request {url}", "", f"Of {member}, as the forge answered for this message.",
             "", f"- ref: {pull.get('ref')}",
             f"- state: {pull.get('state') or 'could not be read'}",
             f"- readable: {_value(pull.get('readable'))}"]
    if pull.get("refused"):
        lines.append(f"- the forge refused its last merge, in its own words: {pull['refused']}")
    body, diff = pull.get("body"), pull.get("diff")
    lines += ["", "## Its description", "",
              "It could not be read." if body is None else body or "(empty)",
              "", "## Its reviews and events", "",
              *(_data(pull["events"]) if pull.get("events") else ["(none recorded)"]),
              "", "## Its changes", "",
              "They could not be read." if diff is None else diff or "(no changes)"]
    return "\n".join(lines) + "\n"


def _render_requirements(model: ProductModel, names: Names) -> str:
    lines = ["# The requirements, with who asked", "",
             "Every requirement of the product, superseded ones too, with the person who asked "
             "said as \"its requester\" — or \"you\" when it is the person you are talking to. "
             "Never name them: the requirement's file records who, for whoever maintains it.", "",
             "| req | status | title | affects | asked by | file |", "|---|---|---|---|---|---|"]
    for r in model.requirements or []:
        status = (r["status"] if r.get("superseded_by") is None
                  else f"superseded-by {int(r['superseded_by']):04d}")
        lines.append(f"| REQ-{int(r['number']):04d} | {status} | {r['title']} | "
                     f"{', '.join(r.get('affects') or []) or '—'} | "
                     f"{names.requester(r.get('asked_by'))} | `{r['path']}` |")
    if not model.requirements:
        lines.append("| — | — | (this product has no requirements written down yet) | — | — | — |")
    return "\n".join(lines) + "\n"


def documents_shown(documents: dict, audience: str) -> tuple[list[dict], int]:
    """`(listed, withheld)` — the unreadable documents a turn of `audience` may be shown BY NAME,
    and how many more it is told only the count of (#269). A document's name is content
    ("plano-de-demissoes.pdf"), so an internal one is listed only to an internal reader
    (`documents/record.py::turn_audience`); the rest of the turns hear a number."""
    from openfactory.contracts.document import may_read

    every = [*(documents.get("unreadable") or []), *(documents.get("unreadable_internal") or [])]
    listed = [doc for doc in every if may_read(str(doc.get("audience") or ""), audience)]
    return listed, len(every) - len(listed) + int(documents.get("internal_withheld") or 0)


def _render_documents(documents: dict, *, audience: str) -> str:
    """What the ingestion of the context repository found (#269 slice 1): how many documents were
    read, and every one that could not be — each EXISTS, and the file says so in as many words,
    because "could not read" must never become "nothing there" (#269 point 8). An internal one is
    NAMED only to a turn that may read it, and counted for every other (`documents_shown`)."""
    unreadable, withheld = documents_shown(documents, audience)
    lines = ["# The documents in the context repository", ""]
    checked = documents.get("checked_at")
    if not checked:
        lines.append(f"The documents of the product `{documents.get('product', '')}` have not "
                     "been read yet — no pass has run. Nothing here means nothing is known, not "
                     "that the repository is empty.")
        return "\n".join(lines) + "\n"
    lines += [f"As last read for the product `{documents.get('product', '')}`, checked at "
              f"{checked}: {documents.get('read', 0)} read, {len(unreadable) + withheld} could "
              f"not be read.", "",
              "Every document carries an audience label. `internal` is for the product's own "
              "people — its admins and its engineers — and never for a client; `client` may be "
              "shown to anybody. A document nobody labelled is internal.", ""]
    # WHAT WAS READ, NAMED (#335): the product owner's page lists the documents, and the role
    # reads what the page shows — by the same rule, an internal one only to a turn that may see it
    from openfactory.contracts.document import may_read

    read = [d for d in [*(documents.get("documents") or []),
                        *(documents.get("documents_internal") or [])]
            if may_read(str(d.get("audience") or "internal"), audience)]
    whole = documents.get("listed_all") is not False
    lines += ["## Read", ""]
    lines += [f"- `{d.get('path', '')}` — {d.get('title') or 'untitled'}; type: "
              f"{d.get('type', '')}; audience: {d.get('audience', '')}" for d in read]
    lines += [("" if read else "No document this conversation may see was read."), "",
              f"listed all: {'yes' if whole else 'no'} — "
              + ("every document read that this conversation may see is named here"
                 if whole else f"more were read than this list holds "
                               f"({documents.get('read', 0)} in all)"), ""]
    if withheld:
        lines += [f"{withheld} internal document(s) that could not be read are not listed here: "
                  f"they are named only to the product's own people, in a conversation of their "
                  f"own. Say that they exist, if it matters, and never guess what they are.", ""]
    if not unreadable:
        lines.append("Every document listed to this conversation could be read."
                     if withheld else "Every document in the repository could be read.")
        return "\n".join(lines) + "\n"
    lines += ["## Could not be read", "",
              "Each of these EXISTS in the context repository and could not be read. Never say "
              "one is absent, or that it says nothing: say it exists, that it could not be read, "
              "and why.", ""]
    for doc in unreadable:
        lines.append(f"- `{doc.get('path', '')}` — type: {doc.get('type', '')}; audience: "
                     f"{doc.get('audience', '')}; why: {doc.get('reason', '')}")
    return "\n".join(lines) + "\n"


def _members_said(model: ProductModel) -> str:
    if len(model.members) == 1:
        return f"its registry project `{model.members[0]}`"
    return "the union of its registry projects " + ", ".join(f"`{m}`" for m in model.members)
