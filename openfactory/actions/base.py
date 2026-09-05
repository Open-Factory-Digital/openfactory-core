"""What an action IS — the vocabulary the front ends and the catalog share (C-23).

Three types and nothing else, because every one of them exists to stop a specific thing from
leaking across the seam:

    Actor       who asked, so an action never has to guess and a front end never has to decide
    Outcome     values out — no HTTP status, no mrkdwn, no emoji, no exception
    ActionSpec  a row in a table, so "which actions exist" is data a test can walk

**Outcome, not exceptions.** Both front ends already had a hard rule that they must always reply —
the Slack bot's `act_job` docstring says "NEVER raises (the bot must always reply)" and the panel
turns everything into an `HTTPException` by hand. Two front ends, two hand-written translations of
the same failures, and they disagreed: a job that is not parked is a 409 in the panel and the
sentence "não está parado esperando ação" in Slack, with no shared notion that those are the same
answer. `code` is that shared notion; rendering it stays each front end's job, which is the only
part that is genuinely theirs.

**`ok` is about the platform, not about the answer.** `scan` finding nothing in TO-DO is `ok=True`
with a message saying so — nothing went wrong, the queue is empty. `ok=False` means the platform
could not do the thing it was asked to do. Getting this backwards would make every empty queue
look like an outage in whatever dashboard reads these.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

# ── the codes a front end maps ───────────────────────────────────────────────────────────────────
#
# A CLOSED SET, and `openfactory/api/app.py` holds a status for every member — asserted by a test,
# because
# a code with no mapping is a 500 wearing an action's name. Adding one here without adding it there
# fails the suite rather than production.

OK = ""
#: the caller asked for something malformed — a missing parameter, a ref no tracker could issue
INVALID = "invalid"
#: the caller is not allowed to do this
DENIED = "denied"
#: the project, ticket or job named does not exist
NOT_FOUND = "not_found"
#: the world is not in a state where this makes sense — a job not parked, one already running
CONFLICT = "conflict"
#: a dependency the platform needs is not answering — the durable engine, the forge
UNAVAILABLE = "unavailable"
#: it was attempted and it did not work
FAILED = "failed"
#: the action is catalogued but its implementation has not been moved into the layer yet
UNIMPLEMENTED = "unimplemented"

CODES = frozenset({OK, INVALID, DENIED, NOT_FOUND, CONFLICT, UNAVAILABLE, FAILED, UNIMPLEMENTED})


# ── where an action lives, and where a credential may go ─────────────────────────────────────────
#
# TWO AREAS TODAY, and the split is the one the product owner drew: *"if the person wants to write
# the tickets and drop them in TO-DO, fine — but the product role is available ON THE PLATFORM"*.
# A business analyst writing requirements is not an operator of the floor, and the panel's posture
# until now was that holding its credential made you both.

#: Jobs, the board, merges, the engine — the operator's console. The default for every row.
FLOOR = "floor"
#: The product role: requirements, their drafting, sign-off and withdrawal.
PRODUCT = "product"

#: Every area a row may declare. A registry rather than a free string, for the reason every other
#: registry in this codebase exists: a typo'd scope would otherwise be an area nobody can reach and
#: nothing would say so.
SCOPES = frozenset({FLOOR, PRODUCT})


# ── who asked ────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Actor:
    """The human (or bot) on whose behalf an action runs.

    EVERY ACTION TAKES ONE, including the read-only ones. Not because they all check it today —
    most do not — but because the parameter is the seam C-26 fills, and a parameter added later to
    forty call sites is a migration, while a parameter carried from the start is a rename. It is
    also already useful: `perform` writes one audit line per action naming this, which is the first
    time this platform can answer *who approved that production release*.

    `admin` IS DECIDED BY THE TRANSPORT TODAY, and that is a stated limitation rather than a
    design. Slack knows its answer (`project.admins`), the panel's answer is "did they hold the
    panel token", and the CLI's is "they have a shell on the host, which outranks every action
    here". C-26 (#55) moves the decision behind this field into a policy the Core owns; until then
    the field is where the three front ends' three different answers meet, which is already one
    place fewer than before.
    """

    #: Stable id in whatever namespace the transport owns: a Slack user id (`U04…`), a panel
    #: principal, `cli`. Not required to be globally unique across transports — `via` disambiguates.
    id: str
    #: What to write in a note a human reads. Falls back to `id` when the transport has no name.
    display: str = ""
    #: Which front end carried the request: `panel`, `slack`, `cli`, `test`.
    via: str = ""
    #: Whether this actor may run an action marked `needs_admin`. See the caveat above.
    admin: bool = False
    #: WHICH AREAS OF THE PLATFORM this credential may act in at all, or `None` for one that is
    #: not scoped. `None` and `frozenset()` are different answers and the distinction is the whole
    #: point: `None` means nobody restricted this caller (the CLI, a Slack admin, the panel's own
    #: token — every actor that existed before scopes did, which is why the default cannot be
    #: `frozenset()` without denying all of them); `frozenset()` means somebody scoped it to
    #: nothing. The same `None` vs `[]` rule this codebase pays for everywhere else.
    #:
    #: WHY THIS IS NOT `admin`. A business analyst who writes requirements needs `needs_admin` to
    #: be TRUE for `product_accept` — accepting is the most consequential act on that surface — and
    #: needs `merge` to be refused outright. Those are two different questions: *how much authority
    #: within an area*, and *which areas at all*. Folding them into one flag is how handing a BA a
    #: credential to write a requirement also handed them the button that lands a pull request.
    scopes: frozenset[str] | None = None
    #: THE CONVERSATION THIS ACTOR IS IN, when the transport keys one per person (#33). On Slack
    #: a thread comes free and the rows take it as `thread`; on the web nothing did, so every
    #: person who typed into the panel's box wrote into ONE conversation keyed by the project's
    #: name, and the product role read A and B as one person. The panel fills this from the
    #: subject it resolved — `person:<id>` for somebody known, `visitor:<cookie>` for a browser
    #: nobody has identified yet — and a product row uses it when the caller passed no thread.
    #: Empty means the transport keys nothing, which is every actor that predates this.
    conversation: str = ""

    def may_enter(self, scope: str) -> bool:
        """Whether this actor may act in `scope`. Unscoped actors may enter anywhere."""
        return self.scopes is None or scope in self.scopes

    def __str__(self) -> str:
        who = self.display or self.id or "anonymous"
        return f"{who} (via {self.via})" if self.via else who


#: For the paths that genuinely have no subject yet — a scheduled poll, an internal call. Kept as a
#: named constant rather than `Actor("")` at each site so a grep for it finds every place the
#: platform acts on nobody's behalf, which is exactly the list C-26 will want.
SYSTEM = Actor(id="system", display="the factory", via="internal", admin=True)


# ── what comes back ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Outcome:
    """Values out. No status code, no markup, no vendor.

    `message` is ONE human sentence in plain text. It may be shown to a client, so it says what
    happened and — when something is wrong — what to do about it, in the register the rest of this
    platform uses. It must not contain mrkdwn, HTML, or a provider's link syntax: the front end
    that knows the surface decorates it, and a message pre-decorated for Slack renders as literal
    asterisks in the panel (which is how the first version of the impediment alert shipped).
    """

    ok: bool
    message: str
    #: Values for a machine — what a panel renders as a table, what a script greps. Free-form per
    #: action and documented on its spec.
    data: Mapping[str, object] = field(default_factory=dict)
    #: One of CODES. Empty when `ok`.
    code: str = OK


def done(message: str, **data: object) -> Outcome:
    """It worked. `data` carries whatever the caller may want to render."""
    return Outcome(ok=True, message=message, data=data, code=OK)


def refused(code: str, message: str, **data: object) -> Outcome:
    """It did not work, and this is why — in a word a front end can map and a sentence a human can
    read. Both are required: the word alone gives an operator nothing, and the sentence alone makes
    every front end parse prose to decide a status."""
    if code not in CODES or code == OK:
        raise ValueError(f"unknown outcome code {code!r} — one of {sorted(CODES - {OK})}")
    return Outcome(ok=False, message=message, data=data, code=code)


# ── the table ────────────────────────────────────────────────────────────────────────────────────

#: The signature every action has. Keyword-only, always async, always returns an Outcome.
Runner = Callable[..., Awaitable[Outcome]]


#: WHAT TO PUT IN EACH PARAMETER, keyed by its name — the vocabulary of the action layer (#172).
#:
#: SHARED RATHER THAN PER ROW, because `project` is required by 38 of the 40 rows and `issue` by
#: 12. Forty copies of "the project this concerns" is thirty-nine chances to drift, and the one
#: that drifts is the one somebody reads. A row that means something DIFFERENT by a shared word
#: says so on itself, in `ActionSpec.params`, and that override is the signal to a reader that this
#: row is unusual.
#:
#: THE AUDIENCE IS SOMEBODY WHO MUST FILL THE VALUE IN, which is why these say what goes in rather
#: than what the word denotes. Since #170 that audience includes a model composing a proposal for a
#: button a human presses: `adjust` required an `instruction` and nothing anywhere said what an
#: instruction should contain, so the only guidance was the English of the word.
PARAMS: dict[str, str] = {
    # the two nearly every row takes
    "project": "the project's name in this deployment's registry, e.g. `podbeam`",
    "issue": "the ticket's number on the client's board, digits only, e.g. `87`",
    # confirmation and shape
    "yes": "`true` to actually do it — without it the action reports what it WOULD do",
    "number": "the ticket's number on the client's board, digits only",
    "numbers": "the ticket numbers, comma-separated, e.g. `87,88,91`",
    "limit": "how many rows to return at most; the default is this deployment's",
    "force": "`true` to proceed past a check that would otherwise stop it — say why in `reason`",
    # words a human will read afterwards
    "reason": "one sentence a person will read later, saying WHY — it is stored and shown",
    "comment": "a sentence posted on the pull request as this platform's own voice",
    "instruction": "WHAT TO CHANGE, in one or two concrete sentences the coding pass will work "
                   "from: name the file or behaviour and the change wanted, not the symptom. It "
                   "is shown on the button a person presses, so it must be readable by them too",
    "message": "what you want to say, in your own words",
    "question": "the question, in one sentence",
    "query": "what to look for — a few words, a card number, a name",
    "answer": "the answer, in your own words",
    "answers": "answers to the questions asked, one per line as `field: value`",
    "choice": "which of the options the parked job offered — its exact label",
    "enabled": "`true` to let this project pick work up, `false` to hold it",
    # the release gate
    "version": "the version being released, exactly as it is tagged",
    "approver": "who is approving, by name — it is written into the release record",
    "password": "the release password this deployment was configured with",
    "promote": "`true` to carry the change on through the promotion chain after it lands",
    "sandbox": "`true` to run the job without letting it write anywhere real",
    "durable": "`true` to run on the durable engine rather than in this process",
    # the product role
    "token": "the token identifying the proposal being answered — copy it from the proposal",
    "thread": "the conversation this turn belongs to, if continuing one",
    "in_favour_of": "the number of the card that STAYS — the one this duplicates",
    "requirement": "the requirement's id in its register, e.g. `REQ-014`",
    "decision": "the decision, stated as what will now be true",
    "term": "the word or phrase being defined, as the business says it",
    "body": "what it means, in the business's own words",
    "restated": "the broken promise, restated as what should happen and what happens instead",
    "title": "what the card is called, in the person's own words — short",
    "violates": "the id of the requirement this breaks, if one is known",
    "severity": "how bad it is: `low`, `medium` or `high`",
    # reading a repository
    "target": "the repository to read, as a URL or an `owner/name`",
    "ask": "a specific question to answer about the repository, if you have one",
    "write": "`true` to write the result into the repository rather than only report it",
    "accept": "which proposed fields to keep, comma-separated — the rest are dropped",
    "out": "where to write the file, if not the default place",
    "pr": "`true` to open a pull request with the change instead of committing directly",
}


@dataclass(frozen=True)
class ActionSpec:
    """One row of the catalog: a name, what it needs, and the one implementation.

    `required`/`optional` are declared rather than read off the function signature by
    introspection. Introspection would be shorter and would also mean `perform` cannot tell a
    parameter it forgot to pass from one the action does not want — and the whole reason the
    parameters are checked centrally is that the two front ends validated different things.
    """

    name: str
    #: One line, present tense, for `openfactory act --list` and `GET /api/actions`. This is the
    #: text an operator reads when deciding what to run, so it says what happens, not what it is
    #: called.
    summary: str
    run: Runner
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    #: Whether `Actor.admin` is required. Default True: an action exists to CHANGE something, and
    #: the read-only ones say so explicitly. A default of False would mean a new action is
    #: unguarded unless somebody remembers, which is the wrong way round for this class of mistake.
    needs_admin: bool = True
    #: WHICH AREA of the platform this row belongs to — see `Actor.scopes`. Defaults to the floor
    #: (jobs, the board, merges, the engine), so a row added without thinking about scope lands in
    #: the area a scoped credential CANNOT reach. Same direction as `needs_admin`'s default: the
    #: forgetful case is the closed one.
    scope: str = FLOOR
    #: WHEN A PROPOSER SHOULD PICK THIS ROW over its neighbours — the judgment, not the definition
    #: (#172). `summary` says what the row does; this says when it is the right answer, which is a
    #: different question and the one that actually decides. It lived in a private map inside
    #: `techlead/conversation.py`, where it could disagree with the row it described — and did:
    #: `adjust` had no entry at all, so the verb that most needed the guidance had the least.
    #: Empty is honest for the rows nobody may propose; `proposable` is a much smaller set than
    #: the catalogue and only it is offered as a choice.
    choose_when: str = ""
    #: WHAT THIS ROW means by a parameter, when the shared `PARAMS` word is wrong for it. An
    #: override rather than a copy: a row that agrees says nothing, so the diff of this field is a
    #: list of the rows that are unusual.
    params: Mapping[str, str] = MappingProxyType({})

    def prose_for(self, param: str) -> str:
        """What to put in `param`, or `""` when nobody has said (#172).

        THREE ANSWERS COLLAPSED TO TWO ON PURPOSE, unlike the reads elsewhere in the platform: a
        parameter nobody wrote prose for and a parameter that needs no explanation are the same
        thing to the person filling it in. What must NOT happen is inventing a sentence from the
        name, which is what every front end would do on its own."""
        return self.params.get(param) or PARAMS.get(param, "")

    @property
    def described(self) -> dict[str, str]:
        """Every parameter this row takes, each with what to put in it — the shape a front end
        renders and `/api/actions` serves. Includes the ones with no prose, as empty strings: a
        parameter missing from this mapping would read as one the action does not take."""
        return {p: self.prose_for(p) for p in self.parameters}

    @property
    def pending(self) -> str:
        """Where the implementation still lives, or `""` when it has been moved into the layer.

        Not a boolean: an operator who hits `unimplemented` needs to know which old route still
        works, and a test needs to see the migration shrink."""
        return getattr(self.run, "moved_from", "")

    @property
    def parameters(self) -> tuple[str, ...]:
        return self.required + self.optional


def not_moved_yet(name: str, *, still_in: str) -> Runner:
    """A placeholder implementation that REFUSES, naming where the working path is.

    WHY A REFUSING RUNNER RATHER THAN AN ABSENT ROW. The catalog is what the guards walk, what the
    panel lists and what `openfactory act --list` prints. An action left out of it until somebody
    moves the code is invisible: no test can assert it is missing, and the migration has no
    measurable end. A row that refuses is visible in all three places and its refusal is a sentence
    somebody can act on, which is the same standard every other wait in this platform is held to.
    """

    async def run(**_params: object) -> Outcome:
        return refused(
            UNIMPLEMENTED,
            f"'{name}' is catalogued but its implementation has not moved into the action layer "
            f"yet — it still lives in {still_in}, which is where it works today (C-23).",
        )

    run.moved_from = still_in  # type: ignore[attr-defined]
    return run
