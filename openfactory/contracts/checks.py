"""What a pull request's checks ARE — typed by the forge's row, decided on in one table (#184).

THE CORE HAD ONE BIT FOR "THE PR'S CHECKS", AND IT DROVE AN AGENT. The port answered a four-valued
aggregate (`pr_ci_status` → success | failure | pending | none) and the durable merge watch turned
`failure` straight into a code repair (ADR-0004). Found on a live Azure DevOps deployment,
2026-09-18: a pull request whose only evaluations were two NON-blocking repository policies — one
of them *Work item linking*, which that team never satisfies, so it is `rejected` on every pull
request — read `failure` one second after it opened. No build had run, on the source branch or on
the merge ref. The repair pass fetched the failing logs (empty: there was no build), launched the
executor anyway with a brief that asserted a failure it could not show, did it again, and parked
the card `CI still failing after 2 repair attempt(s)`. Every card on that repository would have
taken the same path, at two paid agent passes each, over a reviewed diff.

"A CHECK FAILED" IS THREE QUESTIONS, and each has a different right answer:

    does it BLOCK the merge?      an advisory check that fails is information
    is it about the CODE?         a build can be fixed by editing files; a linked work item, a
                                  resolved comment, a required reviewer, a CLA cannot — ADR-0004's
                                  own rule: "whatever needs a human, ask"
    is there EVIDENCE to act on?  a repair with no failure log is a guess

The port carried none of the three, so each adapter answered whichever it had been bitten by: the
GitHub row learned *blocking* (`--required`) after an advisory e2e triggered repairs, then learned
that "no REQUIRED checks" means `none` (F-02); the Azure row learned that empty evaluations mean
`none`. One cell at a time, and the next forge — or the next kind of check — started over.

SO THE ROW SAYS WHAT EACH CHECK IS, AND THE CORE DECIDES ONCE. `pr_checks` rows grew three answers
(`blocking`, `kind`, and where the vendor has one a `remedy` and a `url`); `read` turns them into
`Check`s and attaches the failure log; `decide` is the only place a check becomes an act:

    a blocking CODE check failing, with evidence      → repair
    a blocking code check failing, WITHOUT evidence   → ask a person, naming the check
    a blocking PROCESS check failing                  → ask a person, with the check's remedy
    a NON-blocking check, whatever it says            → never changes the job's path; shown advisory

`unknown` is a kind, and an honest one: a status posted by an app this core has never heard of may
be a build or a CLA. It is repaired only when there is a failure log to act on — which is the one
fact that makes it about code — and asked about otherwise.

A ROW THAT HAS NEVER HEARD OF THIS KEEPS WORKING. A forge add-on written against the old port
answers `{name, bucket, state}` rows and the aggregate. It does not declare `checks_are_typed`, so
its aggregate is taken as its own statement about what blocks, the kind is `unknown`, and the same
table applies: a repair needs the log, and without one a person is asked. Nothing is widened on
the `ForgeAdapter` Protocol — the declaration is an attribute asked with `getattr`, the way #179's
`item_space` is — and a test double is not a declaration: only a literal `True` counts.

"NOTHING GATES THIS MERGE" WAS STILL TWO FACTS IN ONE WORD. `none` answered both a pull request
nothing had looked at and one whose checks all ran and none of them blocks — the case this issue
was found on. The first is not a green pull request, and the merge watch's self-merge read it as
one. So the verdict says which of the four it is:

    failure    a check that BLOCKS the merge is failing (the rows say what it is about)
    advisory   checks ran, and not one of them can stop the merge — said, never acted on
    none       nothing ran: no row, or only optional rows the forge skipped — waited on, then
               said, except on a forge that declares no check ever runs on it
    pending    a blocking check is still running
    success    every blocking check passed, or was skipped by the repository's own rules

A SKIPPED BLOCKING CHECK IS SATISFIED (review of #320). A required workflow a path filter leaves
out of this diff did not run, and the repository's own rules say it had nothing to verify here:
GitHub's branch protection reads it as satisfied and says `clean`. Reading it as `none` withheld
the self-merge from every such pull request, for ever — a fully autonomous deployment turning
person-gated on one of the commonest setups there is. `none` is for a pull request nothing was
asked of, and a forge that KNOWS nothing is ever asked of one (`checks_never_run`, the local
forge) is not waited on for it either.

AND THE LOG IS THE BUILDS'. A forge that types its rows answers `failed_ci_logs` from its own
failing blocking builds (`forge/base.py`), so that log is evidence about its `code` rows only. It
was attached to every blind check a repair could be about, `unknown` included — so a required
status another app posted, red beside some failed build, was "repaired" from the build's log.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from pydantic import BaseModel, Field

log = logging.getLogger("openfactory.checks")

#: What a check is ABOUT. `code` can be fixed by editing files; `process` is settled by a person on
#: the forge; `unknown` is a row that cannot tell — and says so rather than guessing.
CODE, PROCESS, UNKNOWN = "code", "process", "unknown"
KINDS = (CODE, PROCESS, UNKNOWN)

#: How a check stands, in the port's own four buckets (the `bucket` a row always carried).
PASS, FAIL, PENDING, SKIP = "pass", "fail", "pending", "skip"

#: Vendor spellings of the four buckets that already reach the panel through `pr_checks`. `cancel`
#: is a failure on purpose: a cancelled required check must never read as green.
_BUCKETS = {"pass": PASS, "fail": FAIL, "cancel": FAIL, "pending": PENDING,
            "skip": SKIP, "skipping": SKIP}

#: What `decide` can conclude. `wait` is every answer that leaves the job on its path.
REPAIR, ASK, WAIT = "repair", "ask", "wait"

#: The two verdicts "nothing gates this merge" splits into: nothing RAN, or what ran is ADVISORY.
NOTHING_RAN, ADVISORY = "none", "advisory"

#: Why a person is asked.
NO_EVIDENCE = "no-evidence"


class Check(BaseModel):
    """One check on a pull request, as its forge's row describes it."""

    name: str = "check"
    bucket: str = PENDING
    #: The vendor's own word for the state, kept for display only — never decided on.
    state: str = ""
    #: Whether this check can stop the merge. True when a row does not say: a gate nobody can
    #: read is not an advisory one, and the table never repairs or asks on a non-failure anyway.
    blocking: bool = True
    kind: str = UNKNOWN
    #: The failure log an agent could act on, or "". Attached by `read`; a row may bring its own.
    evidence: str = ""
    #: Where a person reads this check on the forge, or "".
    url: str = ""
    #: For a check a person settles: what they do, in the vendor's words. "" when the row has none.
    remedy: str = ""

    @property
    def failing(self) -> bool:
        return self.bucket == FAIL

    @property
    def advisory(self) -> bool:
        return not self.blocking


def from_row(row: object) -> Check | None:
    """One `pr_checks` row as a `Check`, or None for something that is not a row.

    LENIENT ABOUT WHAT IS MISSING, STRICT ABOUT WHAT IS SAID. A row from before #184 carries
    `{name, bucket, state}` and reads as blocking and `unknown`; a `blocking` that is not a bool or
    a `kind` outside the three is a row that did not say, not a value to act on."""
    if not isinstance(row, dict):
        return None
    blocking = row.get("blocking")
    kind = row.get("kind")
    return Check(
        name=str(row.get("name") or "check"),
        bucket=_BUCKETS.get(str(row.get("bucket") or "").lower(), PENDING),
        state=str(row.get("state") or ""),
        blocking=blocking if isinstance(blocking, bool) else True,
        kind=kind if kind in KINDS else UNKNOWN,
        evidence=str(row.get("evidence") or ""),
        url=str(row.get("url") or ""),
        remedy=str(row.get("remedy") or ""),
    )


class CiDecision(BaseModel):
    """What the merge watch does about a pull request's checks, and what it says while doing it."""

    #: The port's aggregate: `failure` | `pending` | `success` over the BLOCKING checks; when none
    #: blocks, `advisory` if checks ran and `none` if nothing did.
    verdict: str = NOTHING_RAN
    action: str = WAIT
    #: The blocking checks the action is about, by name.
    checks: list[str] = Field(default_factory=list)
    #: Why a person is asked: `process` or `no-evidence`. "" otherwise.
    why: str = ""
    #: One sentence a person can act on, when the action is `ask`.
    note: str = ""
    #: The failure statement a repair pass is given, when the action is `repair`.
    evidence: str = ""
    #: Non-blocking checks that are failing — shown, never acted on.
    advisory: list[str] = Field(default_factory=list)
    #: The forge declares that no check ever runs on it (`declares_no_checks`): `none` is then its
    #: whole answer, not a pull request nobody has looked at yet, and the merge watch does not
    #: wait on it. False on every other forge, and in every history recorded before it existed.
    nothing_expected: bool = False


def _names(checks: list[Check]) -> str:
    return ", ".join(f"'{c.name}'" for c in checks)


def decide(checks: list[Check]) -> CiDecision:
    """THE table. Pure: the same checks always give the same act, and no forge is named here."""
    required = [c for c in checks if c.blocking]
    blocking = [c for c in required if c.bucket != SKIP]
    advisory = [c.name for c in checks if c.advisory and c.failing]
    failing = [c for c in blocking if c.failing]
    if not failing:
        if not blocking and required:
            # EVERY BLOCKING CHECK WAS SKIPPED, by the repository's own rules: nothing it asks of
            # this change is left undone, which is how the forge's branch protection reads it.
            verdict = "success"
        elif not blocking:
            # NOTHING GATES THIS MERGE, AND THAT IS TWO FACTS: checks ran and none can stop it, or
            # nothing ran at all. A skipped optional check did not run.
            verdict = ADVISORY if any(c.bucket != SKIP for c in checks) else NOTHING_RAN
        elif any(c.bucket == PENDING for c in blocking):
            verdict = "pending"
        else:
            verdict = "success"
        return CiDecision(verdict=verdict, advisory=advisory)

    # WHAT THE FACTORY CAN DO COMES FIRST. With a build and a process check both red, the repair
    # costs the machine's time and the question costs a person's — so the person is asked once,
    # afterwards, about whatever is still in the way.
    fixable = [c for c in failing if c.kind != PROCESS and c.evidence.strip()]
    if fixable:
        return CiDecision(
            verdict="failure", action=REPAIR, checks=[c.name for c in fixable],
            evidence="\n\n".join(dict.fromkeys(c.evidence.strip() for c in fixable)),
            advisory=advisory)

    process = [c for c in failing if c.kind == PROCESS]
    blind = [c for c in failing if c.kind != PROCESS]
    said: list[str] = []
    if process:
        remedies = list(dict.fromkeys(c.remedy.strip() for c in process if c.remedy.strip()))
        said.append(
            f"{_names(process)} must pass before this pull request can merge, and no change to "
            f"the code settles {'it' if len(process) == 1 else 'them'} — a person does, on the "
            f"forge" + (f": {' '.join(remedies)}" if remedies else "."))
    if blind:
        where = next((c.url for c in blind if c.url), "")
        said.append(
            f"{_names(blind)} {'is' if len(blind) == 1 else 'are'} failing and the forge has no "
            f"failure log for {'it' if len(blind) == 1 else 'them'}, so there is nothing a repair "
            f"pass could act on — read {'it' if len(blind) == 1 else 'them'} on the forge"
            + (f" ({where})" if where else "") + " and fix or re-run what is behind "
            f"{'it' if len(blind) == 1 else 'them'}.")
    return CiDecision(
        verdict="failure", action=ASK, checks=[c.name for c in failing],
        why=PROCESS if process else NO_EVIDENCE, note=" ".join(said), advisory=advisory)


def declares_no_checks(forge: object) -> bool:
    """Whether `forge` says no check EVER runs on it — `checks_never_run = True` on the row, a
    literal `True` and nothing else, as with `checks_are_typed`. The local forge is a directory on
    this machine: its `[]` is the whole answer, the way its `merge_gates` `[]` is "asked, and
    nothing gates a merge here", and not a pull request no check has reported on yet."""
    return getattr(forge, "checks_never_run", False) is True


def declares_typed_checks(forge: object) -> bool:
    """Whether `forge`'s `pr_checks` rows say what each check is. A literal `True` on the row and
    nothing else: a `MagicMock` answers every attribute with a truthy mock, and a test double is
    not a declaration (#179's rule, for the same reason)."""
    return getattr(forge, "checks_are_typed", False) is True


def read(forge: object, pr: str) -> list[Check]:
    """The pull request's checks, typed, with the failure log attached where one is needed.

    RAISES WHAT THE FORGE RAISES. An unreadable gate is not an absent one — the caller degrades
    (the merge watch treats it as pending and says so), it does not get an empty list that reads
    as "nothing gates this merge".

    THE LOG IS READ ONLY WHEN A BLOCKING CHECK THAT COULD BE ABOUT CODE IS RED, and once. It is the
    expensive read on every forge, and it is the fact the table turns on: `failed_ci_logs` empty
    is exactly "there is nothing a repair could act on".

    AND IT IS ATTACHED ONLY WHERE IT IS EVIDENCE. A typed row answers the log of its failing
    blocking BUILDS, so on such a forge it describes the `code` rows and no other: an `unknown`
    one — a status another app posted — keeps only what its own row brought. A row that only
    answers the aggregate cannot say which red check its log is about, so there it goes to every
    blind check, as its aggregate is its own statement."""
    typed = declares_typed_checks(forge)
    if typed:
        checks = [c for c in map(from_row, forge.pr_checks(pr=pr) or []) if c is not None]
    else:
        checks = _from_the_aggregate(forge, pr)
    blind = [c for c in checks
             if c.blocking and c.failing and not c.evidence.strip()
             and (c.kind == CODE if typed else c.kind != PROCESS)]
    if blind:
        logs = str(forge.failed_ci_logs(pr=pr) or "")
        for c in blind:
            c.evidence = logs
    return checks


def _from_the_aggregate(forge: object, pr: str) -> list[Check]:
    """A row that only answers the old aggregate, read for what it can honestly say.

    Its `pr_ci_status` is its own statement about what blocks the merge, so that is kept; WHAT the
    red check is about it cannot say, so the kind is `unknown` and the table decides on the log.
    Its per-check rows, when it has them, only lend the failing names to the sentence."""
    verdict = str(forge.pr_ci_status(pr=pr) or "")
    bucket = {"success": PASS, "failure": FAIL, "pending": PENDING}.get(verdict)
    if verdict == NOTHING_RAN:
        return []
    if verdict == ADVISORY:
        # Checks ran and none of them gates the merge — which ones, this row cannot say.
        return [Check(name="the forge's checks", bucket=PASS, state=verdict, blocking=False)]
    if bucket is None:
        # A word outside the port's four (an add-on answering "unknown") is a gate that could not
        # be read — pending, which waits, and never green.
        return [Check(name="the forge's checks", bucket=PENDING, state=verdict)]
    if bucket == FAIL:
        try:
            rows = [c for c in map(from_row, forge.pr_checks(pr=pr) or []) if c is not None]
        except Exception as exc:  # noqa: BLE001 — the names are a courtesy; the verdict stands
            log.info("could not read the failing checks' names for %s (%s)", pr, str(exc)[:120])
            rows = []
        red = list(dict.fromkeys(c.name for c in rows if c.failing))
        if red:
            return [Check(name=name, bucket=FAIL, state=verdict) for name in red]
    return [Check(name="the forge's required checks", bucket=bucket, state=verdict)]


def advisory_note(names: list[str]) -> str:
    """What the card says about checks that are failing and cannot stop the merge — "" for none.

    SAID, because a red chip nobody explains reads as a gate the factory is about to act on or
    has missed; and NEVER ACTED ON, which the sentence says too."""
    if not names:
        return ""
    one, quoted = len(names) == 1, ", ".join(f"'{n}'" for n in names)
    return (f"{quoted} {'is' if one else 'are'} failing and cannot "
            f"stop this merge — advisory, so nothing is repaired for {'it' if one else 'them'}")


def nothing_ran_note(quiet: timedelta, bound: timedelta) -> str:
    """What the card says while no check has reported on the pull request (`none`).

    Inside `bound` it is waited on, because a pull request a second old has had no time to be
    looked at. Past it, the sentence is the fact a person merging needs: nothing on the forge has
    verified this change."""
    if quiet < bound:
        return "no check has reported on this pull request yet"
    seconds = int(bound.total_seconds())
    span = f"{seconds // 60} minutes" if seconds >= 60 else f"{seconds} seconds"
    return (f"no check has run on this pull request in {span} — nothing on the forge has "
            f"verified it, so the factory will not merge it on its own")


def as_rows(checks: list[Check]) -> list[dict]:
    """The checks as the panel's rows: what `pr_checks` always answered, plus what each one is.
    The log is left out — it is a repair's input, and the panel draws chips."""
    return [{"name": c.name, "bucket": c.bucket, "state": c.state, "blocking": c.blocking,
             "advisory": c.advisory, "kind": c.kind, "url": c.url, "remedy": c.remedy}
            for c in checks]
