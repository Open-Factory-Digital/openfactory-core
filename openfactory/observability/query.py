"""Reading telemetry by KIND instead of scanning everything (ADR-0021).

Every tech-lead round and every product sweep asks the same question — "what am I still waiting
on?" — and the only way to answer it was `scan_records()`: a full table scan across every project,
every agent run, every job, since the beginning, filtered in Python. That is fine at today's volume
and quietly worse every week, on the one read path all of the agents' memory depends on.

The table already had the keys for this; nothing was querying them. The `by_kind` index adds
`kind_ts`, so one partition read returns exactly the rows a caller asked for.

DEGRADES TO A SCAN, BUT NEVER SILENTLY. Before the index exists — a checkout ahead of its
deployment, a local dev box, the window between a code deploy and a terraform apply — the query
fails and this falls back to scanning, saying so. A memory that quietly got slow is a memory that
stays slow, because nothing ever reports it.
"""

from __future__ import annotations

import json
import logging
import math
import re
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger("openfactory.metrics.query")

INDEX = "by_kind"


class StoreUnreadable(RuntimeError):
    """The store could not be read. NOT "the store is empty" (#126).

    THE TWO USED TO BE ONE VALUE, and on the panel that cost both halves of every human gate at
    once. `messages.read` returned `[]` on failure — and its own guard was already dead code,
    because this module and `sqlite_metrics._query` had swallowed to `[]` a layer below. So an
    unreadable store rendered as:

      - a factory with nothing to say (the pending questions simply were not in the inbox);
      - and a click on a question that WAS there refused with 409 "answered already", which blames
        the person for a decision they never made.

    Both halves of a human gate, silently, from one exception nobody saw. It is the same family as
    `_waiting_on_a_human` (an empty floor that was actually a TypeError) and as the ticket and
    board reads in `techlead/conversation.py`, which pay for this lesson in prose: on any path that
    gates a human decision, "nothing" and "could not look" must never be the same value.

    READS ONLY. Writes keep the never-raise rule — a factory that cannot record what it said must
    still say it — and that asymmetry is deliberate: a lost write costs a row, while a read that
    lies costs a decision.
    """


def records_of_kind(project: str, kind: str, *, limit: int = 500,
                    table_name: str | None = None, region: str | None = None,
                    must_answer: bool = False) -> list[dict]:
    """Rows of one kind for one project, oldest first.

    RAISES `StoreUnreadable` when the store would not answer (#126). It used to return `[]` and a
    log line, on the reasoning that "only the log tells them apart" — which is true and is exactly
    the problem: no caller reads a log, so every one of them treated an outage as an empty memory.
    A caller that genuinely wants to degrade now says so in one line and MEANS it.

    `[]` still means empty, and one case is not a failure at all: no readable store configured. A
    deployment that never provisioned telemetry has nothing to read rather than something it
    cannot — and `metrics_view._configured_sink` says out loud when the configured sink is one
    that records and cannot be read back.

    THE SINK THE REGISTRY BUILT IS THE ONLY DOOR. This reader used to fall through to
    `OPENFACTORY_METRICS_TABLE` whenever the registry's sink could not read — so with the table
    variable set and the sink saying `null`, `memory` or a third-party row, a memory read reached
    for one vendor's client (probes A/B/D, 2026-08-24). An explicit `table_name` is the operator's
    override and is registry-shaped too: the CONFIGURED sink's kind pointed at that table
    (`configured_metrics_sink`), refused by name where that kind's add-on is absent — never a
    vendor's kind spelled here.

    `must_answer` IS FOR A CALLER THAT GATES ON THE ROWS (the people store: whether a door is
    open is decided by whether anybody is registered). For every other reader a sink this process
    cannot BUILD is "no data" with a warning, as it has always been; for that caller it is the
    same fold one layer up — a store that was named, may hold rows and cannot be asked, read as
    an empty one — so it raises `StoreUnreadable` instead. A deployment that declared NO store
    (`null`) still answers `[]` either way: nothing was ever kept there, so nothing is unread."""
    if table_name:
        from openfactory.observability.registry import configured_metrics_sink

        sink = configured_metrics_sink(table=table_name, region=region)
    else:
        from openfactory.api.metrics_view import _configured_sink

        # asked the old way unless the caller gates: doubles of this resolver take no keyword
        sink = _configured_sink(must_build=True) if must_answer else _configured_sink()
    if sink is None:
        return []
    return sink.records_of_kind(project, kind, limit=limit)


# ── the outcome aggregates, over a window (#356) ────────────────────────────────────────────────
#
# WHAT A DEPLOYMENT DID, AS COUNTS AND MEDIANS. The partner program certifies a deployment by what
# its factory delivered over a window — how many jobs ran, how they ended, why cards parked, what
# a merged ticket cost and how long a pull request took — and every one of those facts was already
# written down, in two places nobody read together: the job journals (`<OPENFACTORY_LOG_DIR>/
# <project>/<ref>-events.jsonl`) and the metrics store (the passes, the job rows, the card record).
#
# THREE RULES, each one a guard in `tests/test_the_outcomes_are_read_never_inferred.py`:
#
#     THE ENDING IS READ, NEVER INFERRED   A job's terminal state is the journal's ending line
#                                          (`_an_ending`), which `record_outcome` writes (#131). The
#                                          box's last progress mark is how far a job GOT; reading it
#                                          as how the job ended is the lie #131 was written to end
#     UNMEASURED IS NULL, NEVER ZERO       a measure that could not be read is `None`, and
#                                          `not_measured` says why — "no store", "unreadable",
#                                          "nothing in the window to take a median of". A zero is a
#                                          count somebody made
#     COUNTS AND MEDIANS ONLY              never an average a single large ticket can move, never
#                                          a ref, a title or a sentence anybody wrote: the block
#                                          goes into an evidence pack that names nobody
#
# THE DEFINITIONS SHARED WITH #85's AUTONOMY READING (`observability/autonomy.py` on
# `feat/85-the-factory-runs-alone`, not merged when this was written) are MATCHED EXACTLY, not
# imported, and named below where they are: the repair roles, the park taxonomy and how a park's
# note is read into it, the states past the merge, a pass belonging to its card, a ref's one
# spelling, and a naive time read as UTC. When #85 lands, these become imports of its names.

#: The passes that write code AGAIN because what was written did not hold — `autonomy.py`'s
#: `REPAIR_ROLES`, exactly: a failed validation, a suppression the gate refused, a review's
#: findings, a red CI, and a box that died mid-pass (`machine.py::_count`).
REPAIR_ROLES = frozenset({"repair", "suppression_repair", "review_repair", "ci_repair",
                          "recovery"})

#: The tech-lead's classes (`techlead/classify.py`), in the order it names them — `autonomy.py`'s
#: `CAUSES`, exactly. Every class is always present in a measured `parks`, so a zero is a zero.
PARK_CLASSES = ("transient", "credential", "environment", "requirement", "code", "policy",
                "project", "tree", "gate", "unknown")

#: The job states past the merge (`contracts/state.py`) — `autonomy.py`'s `_PAST_THE_MERGE`,
#: exactly. A job that ENDED in one of them landed its change.
PAST_THE_MERGE = frozenset({"merged", "staging_deploying", "staging_verifying",
                            "awaiting_prod_approval", "prod_releasing", "prod_verifying",
                            "rolling_back", "done"})

#: The endings the issue names, always present in a measured `ended`; any other state a job
#: ended in is counted under its own name beside them.
ENDINGS = ("merged", "done", "on_hold", "skipped", "failed")

#: The role `box prove` records its one harness question under (`box_prove._PROVE_ROLE`).
PROVE_ROLE = "prove"

#: Every measure the block carries, in the order it reads. Each is a value or `None`, and a
#: `None` has its reason in `not_measured`.
MEASURES = ("jobs", "ended", "past_the_merge", "without_a_recorded_ending", "parks",
            "cost_per_merged_ticket_usd", "pickup_to_pr_open_seconds", "review_rejections",
            "repair_passes", "needs_action", "versions", "proof_expiries", "reproofs")

#: Why each measure that can never be read here is `None`.
_NEVER_RECORDED = {
    "proof_expiries": "an expiry is judged each time a proof is read, against the image, the "
                      "toolbox and the commands as they are then, and it is never recorded as an "
                      "event, so the expiries inside a window cannot be counted; the state of "
                      "every proof now is in the pack's proofs",
}

_NO_STORE = ("this deployment keeps no readable metrics store (OPENFACTORY_METRICS_SINK is null "
             "or unset), so nothing the store records can be counted")
_UNREADABLE = "the metrics store would not answer, so nothing it records was counted"

#: What a version stamp may look like before it is carried — the platform's own spelling, never
#: free text a row happened to hold.
_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+-]{0,39}")
_BUILD = re.compile(r"[0-9a-f]{0,64}")


def _moment(value: object) -> datetime | None:
    """A row's or a line's time as a moment — `None` for one that does not parse. A naive time is
    UTC, `autonomy.py`'s `_moment` exactly: every writer here stamps an offset, and a row that did
    not means UTC."""
    if isinstance(value, datetime):
        found = value
    else:
        try:
            found = datetime.fromisoformat(str(value or "").strip())
        except ValueError:
            return None
    return found if found.tzinfo else found.replace(tzinfo=UTC)


def _an_ending(event: dict) -> bool:
    """Whether a journal line says how a job ENDED: a `state` line that carries `by`.

    TWO WRITERS PUT IT THERE AND NOTHING ELSE DOES. `record_outcome` (#131), at the job's one exit,
    signs it `the workflow`; a stop (`catalog._journal_the_stop`, #413) signs it with whoever
    stopped the job, because a terminated workflow never reaches its exit. The box's own state
    lines carry a `reason` and never a `by` (`machine._set_state`): they say how far the job got."""
    return event.get("kind") == "state" and isinstance(event.get("data"), dict) \
        and "by" in event["data"]


def _rejected(event: dict) -> bool:
    """A review line whose decision is `rejected` (`machine.py`: `"<decision> (score N)…"`) —
    advisory or blocking alike: the reviewer said no either way, and the mode only decides what
    happens next."""
    return event.get("kind") == "review" and \
        str(event.get("message") or "").strip().lower().startswith("rejected")


@dataclass
class _Job:
    """One job as its journal records it: from its first line to its ending, if one was recorded."""

    project: str
    ticket: str
    start: datetime
    last: datetime
    end: datetime | None = None
    state: str = ""
    pr_open: datetime | None = None
    rejections: int = 0


def _jobs_in(path: Path, project: str) -> list[_Job]:
    """The jobs one card's journal holds, in order. RAISES `OSError` when the file cannot be read.

    A JOURNAL IS ONE CARD'S, AND HOLDS EVERY JOB IT EVER HAD, appended. A job is the run of lines up
    to its ending; the next line opens the next job. An ending with no line before it since the
    last one is NOT a job: it is the card's later ending, which the deploy watch records after the
    job's own `merged` when the deploy was the card's last stage (`_the_last_stage`) — the job
    still ended where its own line says. Lines after the last ending are a job whose ending is not
    recorded: one running now, one the attended driver ran (it journals no ending), or one whose
    ending was lost. Consecutive jobs with no ending between them read as one.

    A line that is not JSON, or has no time, is skipped, as the panel skips it."""
    from openfactory.contracts.refs import canonical_ref

    jobs: list[_Job] = []
    current: _Job | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        when = _moment(event.get("ts"))
        if when is None:
            continue
        if _an_ending(event):
            if current is not None:
                current.end, current.state = when, str(event.get("message") or "").strip()
                jobs.append(current)
                current = None
            continue
        if current is None:
            current = _Job(project=project, ticket=canonical_ref(event.get("ticket_id")),
                           start=when, last=when)
        current.last = max(current.last, when)
        if event.get("kind") == "state" and event.get("message") == "pr_open" \
                and current.pr_open is None:
            current.pr_open = when
        if _rejected(event):
            current.rejections += 1
    if current is not None:
        jobs.append(current)
    return jobs


def _journals(names: list[str]) -> tuple[list[_Job], str]:
    """Every job the projects' journals hold, and why they could not be counted (`""` when they
    could). A project with no journal directory here has run nothing HERE — which is not the same
    as nothing: certify run where the journals are not mounted would read a busy deployment as an
    idle one. So when NO project has a directory, the journals are unread, not empty."""
    from openfactory.paths import project_log_dir
    from openfactory.registry import ProjectRegistry

    registry = ProjectRegistry()
    jobs: list[_Job] = []
    found, unread = 0, 0
    for name in names:
        try:
            where = project_log_dir(registry.get(name))
        except Exception as exc:  # noqa: BLE001 — an unresolvable project is an unread journal
            log.info("the journals of %s could not be located (%s)", name, str(exc)[:160])
            unread += 1
            continue
        if not where.is_dir():
            continue
        found += 1
        for path in sorted(where.glob("*-events.jsonl")):
            try:
                jobs.extend(_jobs_in(path, name))
            except OSError as exc:
                log.info("a journal of %s could not be read (%s)", name, str(exc)[:160])
                unread += 1
    if unread:
        return [], (f"{unread} journal(s) or project(s) could not be read, so the jobs cannot be "
                    f"counted without missing some")
    if names and not found:
        return [], ("no project has a journal directory where this ran: either no job has ever "
                    "run here, or the journals live elsewhere (OPENFACTORY_LOG_DIR names where "
                    "the deployment keeps them)")
    return jobs, ""


def _store_rows(names: list[str]) -> tuple[list[dict] | None, str]:
    """The store's rows for these projects, or `None` and why. ONE SCAN: every measure reads the
    same rows, so no two of them can disagree about what the store held."""
    from openfactory.api.metrics_view import _configured_sink

    try:
        sink = _configured_sink(must_build=True)
        if sink is None:
            return None, _NO_STORE
        rows = sink.scan()
    except StoreUnreadable as exc:
        log.warning("the outcome aggregates could not read the metrics store (%s)", exc)
        return None, _UNREADABLE
    wanted = set(names)
    return [r for r in rows if str(r.get("pk") or r.get("project") or "") in wanted], ""


def _median(values: list[float]) -> float:
    return float(statistics.median(values))


def _p90(values: list[float]) -> float:
    """The 90th percentile by NEAREST RANK: a value somebody actually paid, never one interpolated
    between two tickets."""
    ordered = sorted(values)
    return float(ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)])


def outcomes(project: str | Iterable[str], since: object, until: object, *,
             records: list[dict] | None = None) -> dict:
    """What the factory did between `since` and `until`, for one project or several read as one
    deployment — counts and medians, each `None` with its reason when it cannot be measured.

    `records` are the store's rows when the caller already holds them; otherwise the configured
    store is scanned once. The journals are read from where `paths.project_log_dir` puts them
    (`OPENFACTORY_LOG_DIR/<project>` on a deployment). READ-ONLY: it writes nothing anywhere.

    A JOB IS IN THE WINDOW WHEN IT ENDED THERE — its ending line's time — and a job with no
    recorded ending when its last line is there. A PASS BELONGS TO ITS CARD (`autonomy.py`'s rule):
    a merged ticket's cost is every pass recorded for it, and a job's repair passes are its card's
    passes recorded between its first line and its ending.

    THE CARD RECORD (ADR-0055) answers the parks and Needs Action, and it only exists since #414.
    It is read only when it covers the window — it began before the window did, or no job in the
    window started before it began — because a park nobody recorded is not a park that did not
    happen. A card parked before the record began and still waiting is not in it at all."""
    names = [project] if isinstance(project, str) else list(dict.fromkeys(project))
    start, end = _moment(since), _moment(until)
    if start is None or end is None:
        raise ValueError(f"a window needs two moments, not {since!r} and {until!r}")

    def inside(when: datetime | None) -> bool:
        return when is not None and start <= when <= end

    gaps: dict[str, str] = dict(_NEVER_RECORDED)
    block: dict = {m: None for m in MEASURES}

    jobs, journal_gap = _journals(names)
    if records is None:
        rows, store_gap = _store_rows(names)
    else:
        wanted = set(names)
        rows = [r for r in records if str(r.get("pk") or r.get("project") or "") in wanted]
        store_gap = ""
    closed = [j for j in jobs if j.end is not None and inside(j.end)]
    open_ = [j for j in jobs if j.end is None and inside(j.last)]

    # ── what the journals alone answer ──────────────────────────────────────────────────────────
    if journal_gap:
        for m in ("jobs", "ended", "past_the_merge", "without_a_recorded_ending",
                  "pickup_to_pr_open_seconds", "review_rejections"):
            gaps[m] = journal_gap
    else:
        block["jobs"] = len(closed)
        # EVERY STATE A JOB CAN BE IN, and nothing else: an ending outside them is counted as
        # `unrecognised`, never under whatever word a line held — the block carries no free text.
        from openfactory.contracts.state import JobState

        known = {s.value for s in JobState}
        ended: dict[str, int] = dict.fromkeys(ENDINGS, 0)
        for j in closed:
            word = j.state if j.state in known else "unrecognised"
            ended[word] = ended.get(word, 0) + 1
        block["ended"] = ended
        block["past_the_merge"] = sum(1 for j in closed if j.state in PAST_THE_MERGE)
        block["without_a_recorded_ending"] = len(open_)
        waits = [(j.pr_open - j.start).total_seconds() for j in closed if j.pr_open is not None]
        if waits:
            block["pickup_to_pr_open_seconds"] = {"median": round(_median(waits), 1),
                                                  "jobs": len(waits)}
        else:
            gaps["pickup_to_pr_open_seconds"] = (
                "no job ended in the window" if not closed else
                f"none of the {len(closed)} job(s) that ended in the window opened a pull request")
        if closed:
            said = [j.rejections for j in closed]
            block["review_rejections"] = {"total": sum(said), "median_per_job": _median(said),
                                          "jobs": len(said)}
        else:
            gaps["review_rejections"] = "no job ended in the window"

    # ── what the store answers ──────────────────────────────────────────────────────────────────
    if rows is None:
        for m in ("parks", "cost_per_merged_ticket_usd", "repair_passes", "needs_action",
                  "versions", "reproofs"):
            gaps[m] = store_gap
    else:
        _from_the_store(block, gaps, rows, names, start, end, inside, closed, open_,
                        journal_gap)

    measured = any(block[m] is not None for m in MEASURES)
    return {
        "status": "measured" if measured else "not_measured",
        "reason": (_MEASURED if measured else
                   "; ".join(dict.fromkeys(g for m, g in gaps.items()
                                           if m not in _NEVER_RECORDED))),
        "projects": len(names),
        **block,
        "not_measured": {m: gaps[m] for m in MEASURES if block[m] is None},
    }


#: What a measured block says it was read from.
_MEASURED = ("jobs and their endings are read from the job journals, at the line the workflow "
             "writes when a job ends; costs, passes, parks, Needs Action and version stamps from "
             "the metrics store and the card record. A measure that could not be read is null, "
             "and not_measured says why")


def _from_the_store(block: dict, gaps: dict, rows: list[dict], names: list[str],
                    start: datetime, end: datetime, inside, closed: list[_Job],
                    open_: list[_Job], journal_gap: str) -> None:
    """The measures the metrics store answers — the passes, the job rows, the card record — into
    `block`, and the reason for each it cannot, into `gaps`."""
    from openfactory.contracts.refs import canonical_ref
    from openfactory.lifecycle import record
    from openfactory.lifecycle.table import MOVES_NOTHING, State
    from openfactory.techlead.classify import classify

    # EVERY PASS ON ITS CARD, joined by the ref's one spelling (`autonomy.py`'s rule): `#12` and
    # `12` are one card, and a card is its project's — `12` here is not `12` there.
    passes: dict[tuple[str, str], list[tuple[datetime | None, str, object]]] = {}
    reproofs = 0
    seen: dict[tuple[str, str], int] = {}
    unstamped = 0
    for row in rows:
        kind, when = row.get("kind"), _moment(row.get("ts"))
        owner = str(row.get("pk") or row.get("project") or "")
        if kind == "agent_run":
            role = str(row.get("role") or "")
            if role == PROVE_ROLE:
                reproofs += 1 if inside(when) else 0
                continue
            passes.setdefault((owner, canonical_ref(row.get("ticket"))), []).append(
                (when, role, row.get("cost_usd")))
        elif kind == "job" and inside(when):
            stamp = (row.get("extra") or {}).get("platform") if isinstance(
                row.get("extra"), dict) else None
            version = str((stamp or {}).get("version") or "")
            build = str((stamp or {}).get("build") or "")
            if _VERSION.fullmatch(version) and _BUILD.fullmatch(build):
                seen[(version, build)] = seen.get((version, build), 0) + 1
            else:
                unstamped += 1
    block["reproofs"] = reproofs
    if seen:
        block["versions"] = {"seen": [{"version": v, "build": b, "attempts": n}
                                      for (v, b), n in sorted(seen.items())],
                             "unstamped": unstamped}
    else:
        gaps["versions"] = ("no job row in the window carries the version it ran on (job rows "
                            "are stamped since 0.6.0)" if unstamped else
                            "no job row was recorded in the window")

    # ── costs and repairs: the journals' jobs, the store's passes ───────────────────────────────
    if journal_gap:
        gaps["cost_per_merged_ticket_usd"] = gaps["repair_passes"] = journal_gap
    else:
        merged = sorted({(j.project, j.ticket) for j in closed if j.state in PAST_THE_MERGE})
        priced: list[float] = []
        for key in merged:
            costs = [cost for _, _, cost in passes.get(key, [])]
            if costs and all(isinstance(x, int | float) and not isinstance(x, bool)
                             for x in costs):
                priced.append(float(sum(costs)))
        if priced:
            block["cost_per_merged_ticket_usd"] = {
                "median": round(_median(priced), 4), "p90": round(_p90(priced), 4),
                "tickets": len(priced), "unpriced": len(merged) - len(priced)}
        else:
            gaps["cost_per_merged_ticket_usd"] = (
                "no ticket merged in the window" if not merged else
                f"none of the {len(merged)} ticket(s) merged in the window has every pass priced "
                f"(a pass whose harness reports no cost is unknown, never free)")
        repairs: list[int] = []
        for j in closed:
            mine = [role for when, role, _ in passes.get((j.project, j.ticket), [])
                    if when is not None and j.start <= when <= j.end]
            if mine:
                repairs.append(sum(1 for role in mine if role in REPAIR_ROLES))
        if repairs:
            block["repair_passes"] = {"total": sum(repairs), "median_per_job": _median(repairs),
                                      "jobs": len(repairs),
                                      "unrecorded": len(closed) - len(repairs)}
        else:
            gaps["repair_passes"] = (
                "no job ended in the window" if not closed else
                f"no pass is recorded for any of the {len(closed)} job(s) that ended in the window")

    # ── the card record: parks and Needs Action, only where it covers the window ────────────────
    by_project: dict[str, list[dict]] = {}
    for row in rows:
        if row.get("kind") == record.KIND:
            by_project.setdefault(str(row.get("pk") or row.get("project") or ""), []).append(row)
    histories = [h for owner in names for h in record.histories(by_project.get(owner, [])).values()]
    began = min((t for h in histories for r in h.rows if (t := _moment(r.ts)) is not None),
                default=None)
    if journal_gap:
        cover = ("the journals could not be read, so whether the card record covers the window "
                 "cannot be told")
    else:
        mine = closed + open_
        before = [j for j in mine if began is None or j.start < began]
        if began is not None and began <= start:
            before = []
        cover = "" if not before else (
            f"the card record holds nothing on this deployment, and {len(before)} job(s) ran in "
            f"the window" if began is None else
            f"the card record began inside the window, after {len(before)} of its job(s) had "
            f"started, so their parks were never recorded")
    if cover:
        gaps["parks"] = gaps["needs_action"] = cover
        return

    # PARKS, read exactly as `autonomy.py` reads them: every `parked` row in the window, its
    # recorded note read into the tech-lead's taxonomy. A note nobody can read is `unknown`.
    parks: dict[str, int] = dict.fromkeys(PARK_CLASSES, 0)
    for history in histories:
        for row in history.rows:
            if row.event == "parked" and inside(_moment(row.ts)):
                facts = row.facts or {}
                text = str(facts.get("note") or facts.get("reason") or row.why or "")
                state = str(facts.get("job_state") or "")
                cause = classify(text, state=state).cause
                parks[cause if cause in parks else "unknown"] += 1
    block["parks"] = parks

    # NEEDS ACTION AT THE END OF THE WINDOW: a card whose last move by then left it waiting on a
    # person, aged from the move that began that wait — a question asked of a parked card does not
    # restart its clock.
    waiting = State.WAITING_ON_A_PERSON.value
    ages: list[float] = []
    for history in histories:
        moves = [(r, t) for r in history.rows
                 if r.event not in MOVES_NOTHING and (t := _moment(r.ts)) is not None and t <= end]
        if not moves or moves[-1][0].after != waiting:
            continue
        began_waiting = moves[-1][1]
        for r, t in reversed(moves):
            if r.after != waiting:
                break
            began_waiting = t
        ages.append((end - began_waiting).total_seconds() / 86400)
    block["needs_action"] = {"cards": len(ages),
                             "oldest_days": round(max(ages), 1) if ages else 0.0}
