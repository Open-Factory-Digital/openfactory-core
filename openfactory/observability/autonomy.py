"""Autonomy, as a number read off the card's record (#85, hole 4).

THE FACTS EXISTED AND NOTHING READ THEM. Every pass a job makes is an `agent_run` row tagged with
its role (`orchestrator/machine.py::_count`), and since ADR-0055 every card's life is a record of
transitions (`lifecycle/record.py`). Whether a card reached its merge on the factory's first try —
or took three repairs, a park and a person's adjustment — was in those rows for every card, and
"is the factory getting better?" was answered by opening twenty job pages. This reads them once.

A CARD IS MEASURED ONLY WHEN THE RECORD HOLDS ITS START. A measured card's record holds `promoted`
before its first `merged`: the moment the factory was handed the card, and the moment it landed.
Cards only carry `promoted` since #414 (2026-10-04), so every card merged before that — and any
card whose promotion the record does not hold — is counted on its own, by name, as BEFORE THE
RECORD, and never enters a rate. A yield over cards whose start nobody recorded is a yield over
whichever of them happened to be recorded.

THE DEFINITIONS, one decision each:

    first-pass      a measured merged card with NO repair-role pass and no `parked`, `resumed` or
                    `adjusted` between its promotion and its merge. `question_asked` and
                    `accepted` are gates the design puts in the road, not somebody stepping in.
    yield           first-pass cards over measured merged cards — `None` when there are none,
                    never 0: a factory that merged nothing did not fail every card
    rework rate     code-writing passes (the executor and the five repair roles) per measured
                    merged card; 1 is one pass each. The planner and the reviewer write no code
                    and are not rework
    repair depth    how many measured merged cards took 0, 1, 2 and 3+ repair passes
    park reasons    every `parked` row, read into the tech-lead's own taxonomy
                    (`techlead/classify.py`) from the note it recorded — said as "classified from
                    the recorded note", because the park did not declare its class (a park that
                    records one is a follow-up). A note nobody can read is `unknown`, never
                    `transient`: guessing "it passes on its own" is how a broken thing looks fine

A PASS BELONGS TO ITS CARD, NOT TO A WINDOW. The `agent_run` rows are written when the job ends,
which on the attended driver is AFTER the merge it handed back went through the door
(`cli._run_and_record`), so bounding them by the merge's time would drop every pass of a card the
job merged itself. Every pass recorded for the card counts; the record's sequence, not a clock,
bounds the interventions.

THE RECORD WINS OVER THE JOB'S ROW. A job row is written once, at the job's end, and says how far
THAT job got — `pr_open`, while the merge a person made an hour later is in the record. A job row
past the merge is read only to name a card BEFORE THE RECORD that the record never saw merge.

READ-ONLY AND PURE. Rows in, a dict out: it reads no store, writes nothing, calls no door and
starts nothing that spends. The CLI hands it `scan_all_or_raise`'s rows and the cost dashboard
the rows it already scanned, so `openfactory autonomy --json` and `/api/metrics`'s `autonomy`
block are one function's answer and cannot disagree.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime

#: The pass that writes the code the first time (`machine.py::_count(…, "executor")`).
EXECUTOR = "executor"

#: The passes that write code AGAIN because what was written did not hold — each tagged where it
#: runs: a validation that failed (`repair`), a suppression the gate refused, a review's findings,
#: a red CI, and a box that died mid-pass (`recovery`). Any one of them on a card means the card
#: did not land on the factory's first try.
REPAIR_ROLES = frozenset({"repair", "suppression_repair", "review_repair", "ci_repair",
                          "recovery"})

#: What counts as rework: every pass that writes code. The planner plans and the reviewer reads;
#: counting them would make a project that turned review on look like it repairs more.
WRITES_CODE = frozenset({EXECUTOR, *REPAIR_ROLES})

#: Somebody stepping in between the promotion and the merge: a park, its resumption, and the
#: release manager's adjustment. `question_asked` and `accepted` are not here — the design asks
#: them, and a card that waited at a gate it was meant to wait at did not need rescuing.
INTERVENTIONS = frozenset({"parked", "resumed", "adjusted"})

PROMOTED, MERGED, PARKED = "promoted", "merged", "parked"

#: The repair-depth buckets, in the order the table reads.
DEPTHS = ("0", "1", "2", "3+")


def _said(key: str, language: str | None, **params: object) -> str:
    from openfactory.techlead import voice

    return voice.say(voice.AUTONOMY, key, language, **params)


def _moment(value: object) -> datetime | None:
    """A row's time, as a moment — `None` for one that does not parse. A naive time is UTC: every
    writer here stamps an offset, and a test or a hand-written row that did not means UTC."""
    if isinstance(value, datetime):
        found = value
    else:
        try:
            found = datetime.fromisoformat(str(value or "").strip())
        except ValueError:
            return None
    return found if found.tzinfo else found.replace(tzinfo=UTC)


def _within(ts: object, start: datetime | None) -> bool:
    """Whether a row's time is in the window. With no window, every row is; with one, a row whose
    time does not parse is NOT — a card cannot be claimed for a week nobody can place it in."""
    if start is None:
        return True
    when = _moment(ts)
    return when is not None and when >= start


def _project_of(row: dict) -> str:
    return str(row.get("pk") or row.get("project") or "")


def _decimal(value: float, language: str | None) -> str:
    """A rate as a person in that language writes one: `1.67`, `1,67`."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") if (language or "").lower().startswith("pt") else text


def _labels(language: str | None) -> dict:
    keys = ("title", "yield", "rework", "measured", "before", "depth", "repairs", "cards",
            "parks", "cause", "count")
    return {k: _said(f"label.{k}", language) for k in keys}


def autonomy(records: Iterable[dict], project: str, *, since: object = None,
             language: str | None = None) -> dict:
    """The autonomy block for `project`, from `records` — the store's rows as a scan returns them,
    every project and every kind (it keeps its own).

    `since` (a moment, or an ISO time) narrows it to the cards whose first merge — and the parks —
    happened from then on; `None` is the whole record. `language` is the project's: the numbers
    are numbers, and every sentence and label beside them is in it."""
    from openfactory.contracts.refs import canonical_ref, ref_sort_key
    from openfactory.contracts.state import PAST_THE_MERGE
    from openfactory.lifecycle import record
    from openfactory.techlead.classify import CLASSES, classify

    start = _moment(since) if since is not None else None
    mine = [r for r in records if _project_of(r) == project]
    histories = record.histories([r for r in mine if r.get("kind") == record.KIND])

    # EVERY PASS ON ITS CARD, joined by the ref's one spelling: `#12` and `12` are one card, and
    # `DAR-12` is a card too — never reduced to a number that would drop it or meet another's
    roles: dict[str, list[str]] = {}
    job_merged: dict[str, str] = {}
    for row in mine:
        ticket = canonical_ref(row.get("ticket"))
        if row.get("kind") == "agent_run":
            roles.setdefault(ticket, []).append(str(row.get("role") or ""))
        elif row.get("kind") == "job" and str(row.get("state") or "") in PAST_THE_MERGE:
            ts = str(row.get("ts") or "")
            job_merged[ticket] = min(job_merged.get(ticket, ts), ts)

    measured: list[tuple[int, int, bool]] = []   # (repair passes, code passes, first-pass)
    before: list[str] = []
    reasons: Counter[str] = Counter()
    for card, history in histories.items():
        for row in history.rows:
            if row.event == PARKED and _within(row.ts, start):
                facts = row.facts or {}
                text = str(facts.get("note") or facts.get("reason") or row.why or "")
                state = str(facts.get("job_state") or "")
                reasons[classify(text, state=state).cause] += 1
        merged = next((r for r in history.rows if r.event == MERGED), None)
        if merged is None or not _within(merged.ts, start):
            continue
        promoted = next((r.seq for r in history.rows
                         if r.event == PROMOTED and r.seq < merged.seq), None)
        if promoted is None:
            before.append(card)
            continue
        stepped_in = any(r.event in INTERVENTIONS for r in history.rows
                         if promoted < r.seq < merged.seq)
        passes = roles.get(canonical_ref(card), [])
        repairs = sum(1 for role in passes if role in REPAIR_ROLES)
        code = sum(1 for role in passes if role in WRITES_CODE)
        measured.append((repairs, code, not repairs and not stepped_in))
    for card, ts in job_merged.items():
        held = histories.get(card)
        if held is not None and any(r.event == MERGED for r in held.rows):
            continue   # the record saw it merge, and the record has spoken above
        if _within(ts, start):
            before.append(card)

    n = len(measured)
    clean = sum(1 for _, _, first in measured if first)
    code_passes = sum(code for _, code, _ in measured)
    depth = Counter(DEPTHS[min(repairs, 3)] for repairs, _, _ in measured)
    window = (_said("window", language, day=start.date().isoformat()) if start is not None
              else "")
    rate = round(code_passes / n, 4) if n else None
    parks = sum(reasons.values())
    block = {
        "project": project,
        "readable": True,
        "since": start.isoformat() if start is not None else None,
        "measured": n,
        "first_pass": clean,
        "yield": round(clean / n, 4) if n else None,
        "code_passes": code_passes,
        "rework_rate": rate,
        "repair_depth": {d: depth.get(d, 0) for d in DEPTHS},
        "before_the_record": sorted(set(before), key=ref_sort_key),
        "parks": parks,
        "park_reasons": dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))),
    }
    block["said"] = {
        "title": _said("title", language, project=project),
        "headline": (_said("yield", language, clean=clean, merged=n, window=window,
                           pct=round(clean / n * 100)) if n
                     else _said("none", language, window=window)),
        "rework": (_said("rework", language, passes=code_passes, rate=_decimal(rate, language))
                   if rate is not None else ""),
        "before_the_record": (_said("before", language, count=len(block["before_the_record"]))
                              if block["before_the_record"] else ""),
        "scope": _said("scope", language),
        "parks": (_said("parks", language, count=parks, window=window) if parks
                  else _said("parks.none", language, window=window)),
        "labels": _labels(language),
        # EVERY CLASS THE CLASSIFIER HAS, each a word in the phrasebook — read from it, never a
        # copy, so the table never shows a class it cannot name (review of #545)
        "causes": {c: _said(f"cause.{c}", language) for c in CLASSES},
    }
    return block


def unread(project: str, cause: object, *, language: str | None = None) -> dict:
    """The block when the store would not answer: no number at all, and the sentence that says
    why and what to check. NEVER the empty record's block — "no card measured yet" from a store
    nobody could read is the factory claiming a fact it did not look at (#126)."""
    return {"project": project, "readable": False,
            "said": {"title": _said("title", language, project=project),
                     "headline": _said("unread", language, cause=str(cause).rstrip(".")),
                     "labels": _labels(language)}}
