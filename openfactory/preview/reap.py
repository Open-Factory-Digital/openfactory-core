"""Ending a preview: the rules the reaper applies every tick, through the deployment's runtime row
(ADR-0050 D10; the design on #265, §5.2 "The reaper").

WHAT IS RUNNING IS ASKED OF THE RUNTIME, NOT OF THE RECORDS. The records say what the worker
MEANT; the runtime's `running()` says what is on the daemon — exited stacks included, because a
crashed preview is exactly the one nobody else will ever take down. Each unit it reports is ended
when:

- its time is up (the expiry the assembler wrote into its labels — a unit without one is ended:
  nothing the factory starts lacks it);
- EVERY pull request of the unit was merged or closed. A pull request whose state could not be
  read keeps the preview until its time is up — never the reverse;
- an exposed service is not running, once the unit has been `failed` for `keep_failed_minutes`
  (long enough for a person to read why). The first tick that sees it records `failed` if the
  watch did not;

and, from the records: a `starting` record older than `start_timeout_minutes` is a start that
will never finish (the worker restarted during the build), and is ended with that sentence.

LOGS BEFORE EVERY DOWN, and it is an ordering, not a nicety: a stack taken down first leaves
nobody able to say why it failed. Then the orphans — a `openfactory-pv-*` work directory under the
work root, older than the longest a preview may live, with no compose project behind it — and,
where the runtime keeps caches between units, a prune.

Docker-free: the runtime is handed in, and so is everything else that reads the world, so every
rule is a table-driven test.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping

from openfactory import preview
from openfactory.adapters.preview.base import PREFIX, PreviewRuntime, PrunesCaches
from openfactory.contracts.project import PreviewPolicy

log = logging.getLogger("openfactory.preview.reap")

#: The longest a preview may live, in hours — `PreviewPolicy.hours` is clamped to a week — and so
#: how old an orphaned work directory must be before it is swept.
MAX_TTL_HOURS = 24 * 7


def reap(runtime: PreviewRuntime, *, policies: Mapping[str, PreviewPolicy],
         latest_of: Callable[[str], Mapping[str, preview.Preview]],
         pr_status: Callable[[str, str], str], record: Callable[[preview.Preview], object],
         now: float, work_root: str, log_dir: Callable[[str, str], str]) -> list[str]:
    """End every preview that should not be up any more, and say which, one line each.

    `policies` — every registered project's preview policy (default when it declares none);
    `latest_of(project)` — its newest record per unit token; `pr_status(project, url)` — "merged"
    | "closed" | "open", and it may raise; `record` — writes a record; `log_dir(project, token)`
    — where a unit's logs are kept."""
    ended: list[str] = []
    seen: set[str] = set()
    records: dict[str, Mapping[str, preview.Preview]] = {}

    def recs(project: str) -> Mapping[str, preview.Preview]:
        if project not in records:
            try:
                records[project] = latest_of(project) or {}
            except Exception as exc:  # noqa: BLE001 — an unreadable store ends nothing by itself
                log.warning("OPENFACTORY_PREVIEW_REAPER could not read %s's preview records (%s)",
                            project, exc)
                records[project] = {}
        return records[project]

    def end(cp: str, project: str, token: str, why: str, was: preview.Preview | None) -> None:
        where = log_dir(project, token)
        runtime.logs(cp, where)             # before ANY down
        runtime.down(cp, os.path.join(work_root, cp))
        base = was or preview.Preview(project=project, unit=token, state=preview.ENDED)
        record(base.model_copy(update={"state": preview.ENDED, "why": why, "log_dir": where,
                                       "ended_at": int(now)}))
        ended.append(f"{project} {token}: {why}")

    for rp in runtime.running():
        cp = rp.compose_project
        if not cp.startswith(PREFIX):
            continue
        seen.add(cp)
        project, token = rp.project, rp.unit
        policy = policies.get(project) or PreviewPolicy()
        was = recs(project).get(token) if project else None
        why = ""
        if not rp.expires_at or rp.expires_at <= now:
            why = "its time was up"
        else:
            urls = tuple(rp.pr_urls or (was.pr_urls if was else ()))
            if urls and _all_settled(project, urls, pr_status):
                why = ("its pull request was merged or closed" if len(urls) == 1
                       else "every pull request of it was merged or closed")
        if not why and rp.state != "running" and not (was and was.state == preview.STARTING):
            if was and was.state == preview.FAILED:
                since = was.ended_at or was.started_at
                if now - since >= policy.keep_failed_minutes * 60:
                    why = (f"it failed and was kept {policy.keep_failed_minutes} minutes for a "
                           f"person to read why")
            elif was and was.state == preview.ENDED:
                why = "it had ended and was still on the daemon"
            else:
                base = was or preview.Preview(project=project, unit=token, state=preview.FAILED)
                record(base.model_copy(update={
                    "state": preview.FAILED, "ended_at": int(now),
                    "why": "an exposed service stopped — its log is kept until the preview is "
                           "taken down"}))
        if why:
            end(cp, project, token, why, was)

    # a start that will never finish: the worker restarted during the build
    for project, policy in sorted(policies.items()):
        for token, was in sorted(recs(project).items()):
            if was.state != preview.STARTING:
                continue
            if now - (was.started_at or 0) < (policy or PreviewPolicy()).start_timeout_minutes * 60:
                continue
            cp = preview.compose_project(project, token)
            end(cp, project, token, "the worker restarted during the build — it was starting for "
                                    f"more than {policy.start_timeout_minutes} minutes", was)
            seen.add(cp)

    # work directories nothing runs behind any more
    horizon = now - MAX_TTL_HOURS * 3600
    try:
        entries = list(os.scandir(work_root))
    except OSError:
        entries = []
    for entry in entries:
        if (not entry.name.startswith(PREFIX) or entry.name in seen or entry.is_symlink()
                or not entry.is_dir(follow_symlinks=False)):
            continue
        try:
            if entry.stat(follow_symlinks=False).st_mtime > horizon:
                continue
        except OSError:
            continue
        if runtime.down(entry.name, entry.path):
            ended.append(f"{entry.name}: its work directory outlived every preview")

    if isinstance(runtime, PrunesCaches):
        try:
            ended += runtime.prune()
        except Exception as exc:  # noqa: BLE001 — a prune that failed is a line, never a tick lost
            log.warning("OPENFACTORY_PREVIEW_REAPER could not prune (%s)", exc)
    return ended


def _all_settled(project: str, urls: tuple[str, ...],
                 pr_status: Callable[[str, str], str]) -> bool:
    """Every pull request merged or closed. One that could not be read is OPEN for this purpose:
    a preview ends on a fact, never on the absence of one."""
    for url in urls:
        try:
            status = pr_status(project, url)
        except Exception as exc:  # noqa: BLE001 — unread is not closed
            log.warning("OPENFACTORY_PREVIEW_REAPER could not read %s (%s) — its preview stays "
                        "until its time is up", url, exc)
            return False
        if status not in ("merged", "closed"):
            return False
    return True


def latest_by_unit(rows: list[dict]) -> dict[str, preview.Preview]:
    """The newest record per unit token out of a project's preview rows (the store is
    append-only, so the newest row is the truth)."""
    newest: dict[str, dict] = {}
    for row in rows:
        extra = row.get("extra") or {}
        token = str(extra.get("unit") or "")
        if token and str(row.get("ts", "")) >= str(newest.get(token, {}).get("ts", "")):
            newest[token] = row
    out: dict[str, preview.Preview] = {}
    for token, row in newest.items():
        try:
            out[token] = preview.Preview.model_validate(row.get("extra") or {})
        except ValueError:
            log.warning("OPENFACTORY_PREVIEW_REAPER the record of %s could not be read back",
                        token)
    return out
