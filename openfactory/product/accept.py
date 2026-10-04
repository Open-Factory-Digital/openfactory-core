"""The requester's "that's it", recorded against the head they tried, and what it lets happen
(#448, slice 3; ADR-0055 D1's `accepted`).

THE REQUESTER'S YES REACHED NOTHING. Measured on #448's run (card #1000007, 2026-09-30): the
requester tried the preview, and the only thing a "that's it" could do was be repeated to whoever
merges. Nothing recorded it, nothing showed it to the person merging, and on `merge_policy: auto`
with a required preview (ADR-0050 D9) nothing could turn it into the merge the look was holding:
"the person who merges is the acknowledgement", and on that path nobody merges.

WHAT THIS MODULE IS, and each half is why the next is safe:

    tried       the head the card's preview was BUILT from for the pull request the gate names —
                what the person actually tried — and whether the pull request still points at it.
                Never the pull request's head at the moment of the yes: a push after the preview
                is a change nobody looked at
    record      one `card_accepted` row in the platform's own store, `{card, pr_url, head, by, at,
                where}`, newest wins — never an unsealed field of the job, which anybody who can
                reach the engine could set
    standing    the acceptance that stands for a card's pull request, read back by the merge gate's
                surfaces: the floor bar, the inbox and the tech-lead (`at_the_gates`)
    merge       the gate's `merge`, through the seam every answer crosses (`adjust.answer_gate`):
                sealed, queried first, refused on a deaf gate

NOTHING HERE DECIDES WHO MAY, OR WHAT A PERSON IS TOLD. Who may accept is the module's
(`ProductModule.may_send_back`, #384's three — the same people who may send it back), and every
sentence is the voice's (`voice.accept_change_said`). A reason here is a WORD a sentence is
chosen by.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from openfactory.product.adjust import NOT_WAITING, UNREACHABLE, WORKING
from openfactory.product.authoring import WriteResult

log = logging.getLogger("openfactory.product.accept")

#: What the gate may say and there is nothing to accept (`adjust.WHY`): no person is asked, a pass
#: is replacing what was tried, or the engine could not be asked. A spent budget changes nothing
#: about a yes, and a gate that cannot hear an answer still shows the person who merges it.
NOTHING_TO_ACCEPT = frozenset({NOT_WAITING, WORKING, UNREACHABLE})

#: The store's kind for one acceptance (`observability/metrics.py::MetricKind`).
KIND = "card_accepted"

#: There is no preview of this card's change for the pull request the gate names — nothing was
#: tried, so a yes would stand for nothing anybody saw.
UNTRIED = "untried"
#: The pull request moved past the head the preview was built from (`demand.stale_of`'s judgement):
#: a yes now would stand for a push nobody looked at.
MOVED = "moved"
#: The acceptance could not be written down — nothing was recorded and nothing was answered.
UNRECORDED = "unrecorded"


@dataclass(frozen=True)
class Tried:
    """What the person tried: the head the preview was built from for one pull request."""

    head: str = ""
    #: why there is nothing to accept — `UNTRIED`, `MOVED`, or `adjust.UNREACHABLE` when the
    #: record could not be read; "" when `head` may be accepted
    why: str = ""
    #: whether the forge says the pull request still points at `head` — None when it could not
    #: be asked, which records the yes and never merges on it
    at_head: bool | None = None


def _number(card: str) -> str:
    """The card as the preview's record names it: its number, never a qualified `repo#N`."""
    from openfactory.contracts.refs import canonical_ref

    return canonical_ref(str(card or "")).rsplit("#", 1)[-1]


def tried(project, card: str, pr_url: str, *, fresh: bool = True) -> Tried:
    """The head the card's preview was BUILT from for `pr_url`, and whether the pull request still
    points at it — NEVER RAISES.

    THE RECORD THE PREVIEW WROTE WHEN IT WENT LIVE (`preview/steps.py::up`, `Preview.heads`), so an
    acceptance names what the person saw. A start resets it, so a preview being rebuilt has tried
    nothing yet; one taken down keeps it, so a person who tried it yesterday can say so today.
    `fresh` asks the forge past its minute of cache — the yes is recorded on it."""
    from openfactory import preview
    from openfactory.preview import demand

    name, number = str(getattr(project, "name", "") or ""), _number(card)
    try:
        token = preview.unit_of_card(name, number)
        was = preview.latest(name, token)
    except Exception as exc:  # noqa: BLE001 — a record that cannot be read records nothing
        log.warning("OPENFACTORY_ACCEPT_PREVIEW_UNREAD project=%s card=#%s (%s) — what the person "
                    "tried could not be read, so nothing was recorded", name, number,
                    str(exc)[:200])
        return Tried(why=UNREACHABLE)
    built = str((was.heads or {}).get(pr_url, "") or "") if was is not None and pr_url else ""
    if not built:
        return Tried(why=UNTRIED)
    now = str(demand.forge_state(project, token, was, fresh=fresh).heads.get(pr_url, "") or "")
    if now and now != built:
        return Tried(head=built, why=MOVED, at_head=False)
    return Tried(head=built, at_head=True if now else None)


# ── the record ───────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Acceptance:
    """One person's "that's it", against the head they tried."""

    card: str
    pr_url: str
    head: str
    by: str
    at: str = ""
    #: the conversation it was said in — where "it went in" is told when nobody's delivery names
    #: one (`events.merged_for_you`); "" from a surface that is not a conversation
    where: str = ""


def record(project_name: str, acc: Acceptance) -> bool:
    """Write the acceptance — True only when the row LANDED (`MetricsSink.record`). Never raises:
    a yes that could not be written is refused by name to the person, never claimed."""
    try:
        from openfactory.observability.metrics import MetricRecord
        from openfactory.observability.registry import deployment_metrics_sink

        return bool(deployment_metrics_sink().record(MetricRecord(
            project=project_name, ticket=_number(acc.card),
            ts=acc.at or datetime.now(UTC).isoformat(), kind=KIND, role=KIND,
            pr_url=acc.pr_url, extra={"card": _number(acc.card), "pr_url": acc.pr_url,
                                      "head": acc.head, "by": acc.by, "where": acc.where})))
    except Exception as exc:  # noqa: BLE001 — refused by name to the person who said it
        log.error("OPENFACTORY_ACCEPT_UNRECORDED project=%s card=#%s by=%s (%s) — a person "
                  "accepted a change and it could not be written down", project_name, acc.card,
                  acc.by, str(exc)[:200])
        return False


def standing(project_name: str, card: str, pr_url: str = "", *, rows=None) -> Acceptance | None:
    """The acceptance that stands for `card` — for `pr_url` when one is named — or None. NEWEST
    WINS: the store is append-only, and a person who accepts again accepts what they tried last.
    RAISES what the store raises (`StoreUnreadable`): the caller says "could not read", never "no".
    `rows` is the kind's rows already read, for a caller asking about several cards."""
    if rows is None:
        from openfactory.observability.query import records_of_kind

        rows = records_of_kind(project_name, KIND)
    number = _number(card)
    mine = [r for r in rows or []
            if _number(str(r.get("ticket", ""))) == number
            and (not pr_url or str((r.get("extra") or {}).get("pr_url", "")) == pr_url)]
    if not mine:
        return None
    row = max(mine, key=lambda r: str(r.get("ts", "")))
    extra = row.get("extra") or {}
    return Acceptance(card=number, pr_url=str(extra.get("pr_url", "") or ""),
                      head=str(extra.get("head", "") or ""), by=str(extra.get("by", "") or ""),
                      at=str(row.get("ts", "") or ""), where=str(extra.get("where", "") or ""))


def line(acc: Acceptance, *, current: bool | None = None) -> str:
    """The one sentence every surface at the merge gate renders: who accepted, on which head — and,
    when the preview now shows another, that this yes stands for an earlier one. The floor's and
    the tech-lead's words, so the head is named: an acceptance never stands for a later push."""
    said = f"accepted by {acc.by or 'somebody'} on {acc.head[:7] or 'an unknown head'}"
    if current is False:
        said += " — an earlier head than the preview shows now"
    return said


def _at_the_gate(job: dict) -> tuple[str, str, str] | None:
    """`(project, card, pull request)` of a job a PERSON is being asked to merge — or None."""
    action = job.get("action") or {}
    if job.get("state") != "awaiting_your_merge" or not isinstance(action, dict):
        return None
    pr_url = str(action.get("pr_url") or "")
    if action.get("auto") or action.get("working") or not pr_url:
        return None
    return str(job.get("project") or ""), str(job.get("issue") or ""), pr_url


def at_the_gates(jobs: list[dict]) -> list[dict | None]:
    """The acceptance standing at each job's merge gate, aligned with `jobs` — `{by, head, at,
    current, said}` or None. NEVER RAISES, and reads each project's rows once: the panel asks on
    every refresh of the floor, and the tech-lead on every question.

    `current` is whether the head accepted is the one the card's preview was built from now — False
    after a pass a person asked for rewrote the change and the preview was rebuilt from it, None
    when there is no preview record to compare with."""
    from openfactory import preview
    from openfactory.observability.query import records_of_kind

    out: list[dict | None] = []
    rows_of: dict[str, list | None] = {}
    for job in jobs or []:
        where = _at_the_gate(job)
        if where is None:
            out.append(None)
            continue
        project, card, pr_url = where
        if project not in rows_of:
            try:
                rows_of[project] = records_of_kind(project, KIND)
            except Exception as exc:  # noqa: BLE001 — the gate renders without it, and says so here
                log.warning("OPENFACTORY_ACCEPT_UNREAD project=%s (%s) — the merge gate is shown "
                            "without the requester's acceptance", project, str(exc)[:200])
                rows_of[project] = None
        rows = rows_of[project]
        acc = standing(project, card, pr_url, rows=rows) if rows else None
        if acc is None:
            out.append(None)
            continue
        current: bool | None = None
        try:
            was = preview.latest(project, preview.unit_of_card(project, _number(card)))
            built = str((was.heads or {}).get(pr_url, "") or "") if was is not None else ""
            current = (built == acc.head) if built else None
        except Exception as exc:  # noqa: BLE001 — the acceptance still stands; only "current" is unknown
            log.info("could not read #%s's preview to compare its acceptance with (%s)", card,
                     str(exc)[:160])
        out.append({"by": acc.by, "head": acc.head, "at": acc.at, "current": current,
                    "said": line(acc, current=current)})
    return out


# ── what the yes did ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Accepted(WriteResult):
    """An acceptance that was recorded: on which head, and whether it is going into the product.

    THE FACTS, NOT THE SENTENCE, like `adjust.Sent`: on success `detail` keeps the one meaning the
    confirmation path gives it — what did NOT land after the record (`confirm._unfinished`), here
    the note on the card. The headline is composed from these (`headline`)."""

    head: str = ""
    #: the look was all that held the merge, and the gate took the `merge` this yes gave
    merging: bool = False
    #: the look was all that held it and the gate did not take the answer — why (`adjust.WHY`)
    unmerged: str = ""


def headline(result, *, language: str | None = None) -> str:
    """What the person reads once their yes is recorded, in their language
    (`voice.accept_change_done`). READ WITH DEFAULTS: a module that is not this tree's answers a
    plain `WriteResult`."""
    from openfactory.product.voice import accept_change_done

    return accept_change_done(ref=getattr(result, "ref", ""),
                       merging=bool(getattr(result, "merging", False)),
                       unmerged=bool(getattr(result, "unmerged", "")), language=language)


@dataclass(frozen=True)
class Prepared:
    """What the conversation stages for the yes — or, when `ok` is False, what it says instead."""

    ok: bool = False
    said: str = ""
    head: str = ""
    pr_url: str = ""
    #: the look is all that holds the merge, so the yes puts the change into the product
    merges: bool = False


def merge(project, card: str, *, by: str) -> str:
    """The gate's `merge`, given by an acceptance — `""` when delivered, else why not (one of
    `adjust.WHY`). NEVER RAISES. Through `adjust.answer_gate`: sealed, queried first, and refused
    on a gate that cannot hear it, so the job acts on it as on a person's Merge."""
    from openfactory.product.adjust import answer_gate

    return answer_gate(project, card, answer="merge", by=by)
