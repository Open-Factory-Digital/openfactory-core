"""What a reader of the code asked the knowledge pipeline to describe — the `no-concept` signal
(ADR-0052 D22, #268 slice 3).

THE ROLE'S QUESTIONS ARE A MEASURE OF WHERE THE MAP IS MISSING. When the product role answers by
reading code no concept describes, that is a fact about the bundle taken from what people actually
ask — and until now it ended with the turn. It is kept here, as a REQUEST: the role proposes, it
never redefines what the code is (`docs/knowledge-layer.md` §6), and the knowledge layer changes
only through its pipeline. So the role writes nothing in the context repository and nothing in a
bundle; it drops a request in this inbox, and the pipeline takes it at its own entry.

IN THE PIPELINE'S OWN VOCABULARY. A request is a `Gap` of kind `no-concept` — ADR-0046's verdict
for a file of a kind nothing excuses that nothing describes (`gate.NO_CONCEPT`) — on one path of
one source repository, keyed by `gap_key` like every gap the pipeline records. When the refresh of
that source runs (`activities._do_refresh_knowledge`, after a merge and every six hours), it takes
the pending requests, merges them into the bundle's manifest BY KEY (`gaps.merge_gaps`: the same
gap raised again is the same gap, and an answered one stays answered) and publishes; from there the
index names it among what the bundle could not establish, and the budgeted paths that describe
code — the backfill, the renewal, the gate's covering — decide whether and when to describe it.
The signal is a request; the pipeline decides.

DEDUPLICATED, AND COUNTED. One file read on twenty turns is one request, and the number of times
it was asked rides beside it — the measure D22 is after. A request the pipeline has taken is kept
(until `KEEP` newer ones push it out) so a turn between the take and the publish does not queue it
again.

WHAT A REQUEST CARRIES, AND WHAT IT NEVER DOES: the repository, the path, the gap's fixed wording,
when it was first and last asked, and how many times. Never the question, the person or the
conversation — this file is read by a pipeline that serves every conversation of the product, and
a word of one conversation must not reach another through it.

WHERE IT LIVES: the product's state directory (`paths.product_state_dir`), which the worker and the
panel both mount — the product role's turn and the knowledge refresh run in different places, and
this is the one directory both already share. One file per product, under its lock.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path

from openfactory.knowledge.contracts import Gap
from openfactory.knowledge.gate import NO_CONCEPT

log = logging.getLogger("openfactory.knowledge.requests")

REQUESTS_FILE = "knowledge-requests.json"
#: How many requests the inbox keeps, taken ones included — the oldest go first.
KEEP = 2048
#: How long a turn or a refresh waits for the inbox's lock before it gives the signal up.
WAIT_SECONDS = 10.0

#: THE GAP'S WORDING, FIXED, because the key is derived from it (`contracts.gap_key`): a sentence
#: that varied with the turn would make every signal about one file a different gap.
DETAIL = ("read to answer a question about the product, and no concept describes it — the "
          "product role asked the knowledge pipeline to describe it")


def inbox_for(project) -> Path:
    """The inbox of `project`'s PRODUCT — one per context repository (`product.key`), so every
    registry project of one product signals into, and is refreshed from, the same file."""
    from openfactory.paths import product_state_dir
    from openfactory.product.key import product_key

    return product_state_dir(product_key(project)) / REQUESTS_FILE


def gap_for(path: str) -> Gap:
    """The gap a request is: `no-concept`, on `path`, in the fixed wording."""
    return Gap(kind=NO_CONCEPT, path=str(path).strip().strip("/"), detail=DETAIL)


def _slot(repo: str, gap: Gap) -> str:
    from openfactory.product.config import normalize_repo

    return f"{normalize_repo(repo) or repo.strip()}\n{gap.key}"


def _read(inbox: Path) -> dict[str, dict]:
    try:
        raw = json.loads(inbox.read_text(encoding="utf-8")) if inbox.is_file() else {}
    except (OSError, ValueError) as exc:
        log.warning("the knowledge requests at %s could not be read (%s) — treated as none",
                    inbox, exc)
        raw = {}
    rows = raw.get("requests") if isinstance(raw, dict) else None
    return {str(k): v for k, v in (rows or {}).items() if isinstance(v, dict)}


def _write(inbox: Path, rows: dict[str, dict]) -> None:
    from openfactory.util.filelock import replace_atomically

    kept = sorted(rows.items(), key=lambda kv: str(kv[1].get("last") or ""))[-KEEP:]
    replace_atomically(inbox, json.dumps({"requests": dict(kept)}, sort_keys=True, indent=1))


def _held(inbox: Path):
    from openfactory.util.filelock import lock_beside

    inbox.parent.mkdir(parents=True, exist_ok=True)
    return lock_beside(inbox).held(timeout=WAIT_SECONDS)


def request(inbox: Path, *, repo: str, path: str, at: str) -> bool:
    """Ask the pipeline to describe `path` of `repo`. True when this is a NEW request — False when
    the same one is already in the inbox (pending or taken), which is then counted once more.

    NEVER RAISES: a signal is a measurement about the answer, and it must never cost the answer.
    An inbox that cannot be locked or written loses this signal and says so in the log."""
    gap = gap_for(path)
    if not gap.path or not str(repo or "").strip():
        return False
    slot = _slot(repo, gap)
    try:
        with _held(Path(inbox)):
            rows = _read(Path(inbox))
            row = rows.get(slot)
            if row is not None:
                row["times"] = int(row.get("times") or 1) + 1
                row["last"] = at
                _write(Path(inbox), rows)
                return False
            rows[slot] = {"repo": str(repo).strip(), "gap": gap.model_dump(), "first": at,
                          "last": at, "times": 1, "taken": ""}
            _write(Path(inbox), rows)
            return True
    except (OSError, TimeoutError) as exc:
        log.error("OPENFACTORY_KNOWLEDGE_GAP_LOST repo=%s path=%s — the request could not be "
                  "recorded (%s)", repo, gap.path, exc)
        return False


def pending(inbox: Path, repo: str) -> list[Gap]:
    """The requests about `repo` the pipeline has not taken yet, oldest first."""
    from openfactory.product.config import repo_match

    rows = _read(Path(inbox))
    out = [(row.get("first") or "", Gap(**row["gap"])) for row in rows.values()
           if not row.get("taken") and isinstance(row.get("gap"), dict)
           and repo_match(str(row.get("repo") or ""), repo)]
    return [gap for _, gap in sorted(out, key=lambda pair: str(pair[0]))]


def taken(inbox: Path, repo: str, keys: Iterable[str], *, at: str) -> int:
    """Mark the requests `keys` about `repo` as taken by the pipeline — kept, so a turn that reads
    the same file before the publish lands does not queue it again. Returns how many."""
    from openfactory.product.config import repo_match

    wanted = set(keys)
    if not wanted:
        return 0
    try:
        with _held(Path(inbox)):
            rows = _read(Path(inbox))
            done = 0
            for row in rows.values():
                gap = row.get("gap") if isinstance(row.get("gap"), dict) else {}
                if (not row.get("taken") and gap.get("key") in wanted
                        and repo_match(str(row.get("repo") or ""), repo)):
                    row["taken"] = at
                    done += 1
            if done:
                _write(Path(inbox), rows)
            return done
    except (OSError, TimeoutError) as exc:
        log.warning("the knowledge requests at %s could not be marked taken (%s) — the next "
                    "refresh takes them again, and the merge by key keeps that a no-op", inbox, exc)
        return 0


__all__ = ["DETAIL", "KEEP", "REQUESTS_FILE", "gap_for", "inbox_for", "pending", "request",
           "taken"]
