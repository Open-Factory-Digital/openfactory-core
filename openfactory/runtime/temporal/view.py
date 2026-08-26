"""The domain's window into Temporal — read live job state, launch, approve, signal.

This is the "our panel is the product surface" half of the runtime document that ships with
the openfactory-aws add-on package (docs/architecture.md in the core):
a caller speaks the domain (project/issue/state) while the durable truth lives in
Temporal. We READ from the engine and LINK to its UI for deep debug — we don't
rebuild it. Kept out of any front end's import path so the panel still serves when
the `runtime` extra (temporalio) isn't installed.

IT LIVED AT `openfactory/api/temporal_view.py` UNTIL C-23, and the filename was the lie: the Slack
bot
(`_gather_jobs`) and the product role (`product/release.py`) had both been importing "the panel's
module" for months, because it was never the panel's — it is the engine's, and the panel was
merely its first caller. That mattered the moment the action layer arrived: C-23's guard is *no
capability lives inside a front end*, and a guard that has to carve out
`openfactory/api/temporal_view.py`
as "a front-end file that is not really a front-end file" is a guard the next person deletes.
"""

from __future__ import annotations

import logging
import os

from temporalio.client import Client, WorkflowExecutionStatus

from openfactory.contracts.state import JobState
from openfactory.runtime.temporal import TASK_QUEUE
from openfactory.runtime.temporal.io import JobParams
from openfactory.runtime.temporal.workflow import JobWorkflow
from openfactory.util.bounded import BoundedDict

log = logging.getLogger("openfactory.panel.temporal")

_WF_ID_PREFIX = "openfactory-"


def temporal_config() -> tuple[str, str]:
    """(address, namespace) — ASKED OF `connection`, not re-derived here (#163).

    This read the same two variables in the OPPOSITE precedence, with its own localhost default:
    two answers to "where is the engine", and a deployment that set both would have the panel
    linking to one while the worker connected to the other. It raises when nobody declared,
    exactly as `connection.address()` does — every caller here already degrades honestly.
    """
    from openfactory.runtime.temporal import connection

    return connection.address(), connection.namespace()


#: Temporal Cloud's gRPC endpoints, both forms. `*.tmprl.cloud` is the original and the only one
#: this recognised; `<region>.<cloud>.api.temporal.io` is the current one — documented in
#: `connection.py`'s own header, one module over, while this inferred "not the cloud" from it and
#: deep-linked a production panel at `http://localhost:8233` (#163).
_CLOUD_HOSTS = ("tmprl.cloud", "api.temporal.io")


def ui_base() -> str:
    """Where the Temporal Web UI lives. Explicit TEMPORAL_UI_URL wins; otherwise infer from the
    endpoint — a Temporal Cloud endpoint maps to the Cloud console, and anything else to the local
    dev-server UI. This is what makes the panel's 'Temporal ↗' deep-links land on the real console
    instead of localhost.

    AN UNDECLARED ENGINE IS NOT A LOCAL ONE, but it is not worth an exception either: this decides
    a LINK, and the caller that renders it has no gate to fail. It answers the local UI, which is
    the honest reading of "nothing is configured on this machine" — and `temporal_config()`, one
    function up, is what makes that state loud where it matters.
    """
    if explicit := os.environ.get("TEMPORAL_UI_URL"):
        return explicit
    endpoint = os.environ.get("TEMPORAL_ENDPOINT") or os.environ.get("TEMPORAL_ADDRESS", "")
    if any(host in endpoint for host in _CLOUD_HOSTS):
        return "https://cloud.temporal.io"
    return "http://localhost:8233"


def job_id(project: str, issue: str) -> str:
    return f"{_WF_ID_PREFIX}{project}-{issue}"


def _registered_projects() -> list[str]:
    from openfactory.registry import ProjectRegistry

    return [p.name for p in ProjectRegistry().list()]


def parse_job_id(wf_id: str, *, known_projects: list[str] | None = None
                 ) -> tuple[str | None, str | None]:
    """`openfactory-acme-189` → `('acme', '189')`. `(None, None)` for ids of another shape.

    A ref is the PROVIDER's string, and a Jira one contains a hyphen — so the old
    `rpartition("-")` turned `openfactory-demo-CONT-412` into project `demo-CONT`, ref `412`.
    Silently:
    the panel files the job under a project that does not exist, the tech-lead never finds it, and
    nothing raises. It worked only because every ref so far has been numeric, and it worked for a
    hyphenated PROJECT NAME by luck — `rpartition` splits at the last hyphen, so a hyphenated
    project is fine and a hyphenated ref is not.

    So the split is anchored on the one part we can actually know: the registered project names,
    longest first (`demo` and `demo-api` can both exist, and matching the shorter one would file
    every `demo-api` job under `demo`). The remainder is the ref, verbatim.

    DEGRADES, NEVER REFUSES. An unregistered project — one since removed, or a registry that will
    not read — falls back to the old split. A job that vanished from the panel because its project
    was deleted would be a worse answer than an imperfectly parsed one.
    """
    if not wf_id.startswith(_WF_ID_PREFIX):
        return None, None
    rest = wf_id[len(_WF_ID_PREFIX):]
    if known_projects is None:
        try:
            known_projects = _registered_projects()
        except Exception as exc:  # noqa: BLE001 — a convenience here, not a dependency
            # Degrade to the old split rather than fail a job listing, but never in silence: with
            # the registry unreadable, a hyphenated ref parses wrongly and the panel would file
            # the job under a project that does not exist, looking merely empty.
            log.warning("could not read the project registry (%s) — parsing %r by its last "
                        "hyphen, which is wrong for a ref that contains one", exc, wf_id)
            known_projects = []
    for name in sorted(known_projects, key=len, reverse=True):
        if rest.startswith(f"{name}-"):
            return name, (rest[len(name) + 1:] or None)
    project, _, issue = rest.rpartition("-")
    return (project or None), (issue or None)


_STATUS = {
    WorkflowExecutionStatus.RUNNING: "running",
    WorkflowExecutionStatus.COMPLETED: "completed",
    WorkflowExecutionStatus.FAILED: "failed",
    WorkflowExecutionStatus.CANCELED: "canceled",
    WorkflowExecutionStatus.TERMINATED: "terminated",
    WorkflowExecutionStatus.CONTINUED_AS_NEW: "continued",
    WorkflowExecutionStatus.TIMED_OUT: "timed_out",
}


def status_label(status: WorkflowExecutionStatus | None) -> str:
    return _STATUS.get(status, "unknown")


def temporal_url(wf_id: str, run_id: str, namespace: str) -> str:
    return f"{ui_base()}/namespaces/{namespace}/workflows/{wf_id}/{run_id}/history"


def _row(wf, namespace: str) -> dict:
    project, issue = parse_job_id(wf.id)
    return {
        "workflow_id": wf.id,
        "run_id": wf.run_id,
        "project": project,
        "issue": issue,
        "status": status_label(wf.status),
        "start_time": wf.start_time.isoformat() if wf.start_time else None,
        "close_time": wf.close_time.isoformat() if wf.close_time else None,
        "temporal_url": temporal_url(wf.id, wf.run_id, namespace),
    }


# The DOMAIN outcome (merged / needs_refinement / on_hold / paused / awaiting_approval /
# failed) is what an operator actually needs — the raw Temporal status can't tell a clean
# merge from a needs-refinement (both "completed"). A closed workflow's result is
# immutable, so cache it forever and fetch each one at most once. (engineering.md #8.)
ATTENTION_STATES = {
    "failed", "needs_refinement", "on_hold", "blocked", "paused", "awaiting_prod_approval",
    "awaiting_your_merge",  # the PR is ready and only the OPERATOR's merge advances the queue
}
#: The `action.kind` a job carries while its pull request waits for a person.
#:
#: THREE SURFACES READ THIS ONE STRING and they must never disagree about it: the panel paints the
#: `Merge · Adjust… · Discard` row from it, the chat decides from it which job a typed "merge" is
#: about, and the attention bar counts it. It is a constant here, beside the only line that
#: produces it, because a second spelling would not fail — it would quietly mean "nothing is
#: waiting", which is a sentence every one of those surfaces is willing to say.
MERGE_WAIT = "merge_wait"


def _wedged_after() -> float:
    """How long a job may run, at no gate, before the platform calls it stuck.

    READ FROM THE TECH-LEAD'S OWN CONSTANT so the button and the alarm cannot disagree — the
    rounds raise `LONG_RUNNING_HOURS` and this decides whether a `Stop` appears; two numbers would
    mean an operator being told a job is wedged on a screen that offers them nothing (#127).

    Imported lazily and with a floor of its own: `techlead` is an application layer and this module
    is read by the panel, which must keep working if that import ever grows a dependency it does
    not have."""
    try:
        from openfactory.techlead.watch import LONG_RUNNING_HOURS

        return float(LONG_RUNNING_HOURS)
    except Exception as exc:  # noqa: BLE001 — a missing constant must not blank the floor
        log.warning("could not read LONG_RUNNING_HOURS (%s) — the Stop button uses 8h", exc)
        return 8.0


_WEDGED = _wedged_after()


def is_wedged(row: dict, *, live: bool) -> bool:
    """Is this job running, at no gate, for longer than any real pass takes? (#127)

    A FUNCTION RATHER THAN AN EXPRESSION INSIDE `list_jobs`, because it is a rule and rules get
    tested. Inline, the only thing a guard could assert was that the assignment existed — and a
    mutation replacing it with `False` passed every one of them while the Stop button vanished
    from a floor nobody could clear.

    THREE CONDITIONS, ALL LOAD-BEARING. `live` keeps a closed workflow from being offered a
    terminate. `action is None` is what separates wedged from WAITING: a job at a gate or in a
    park is the platform working, and it has its own verbs. The hours are the tech-lead's own
    constant, so the alarm and the button cannot disagree about what stuck means."""
    return (bool(live)
            and (row.get("action") or None) is None
            and _hours_since(row.get("start_time")) > _WEDGED)


def _hours_since(when: str | None) -> float:
    """Hours since an ISO timestamp, or 0 when there is none to measure from.

    ZERO, NOT INFINITY. A job whose start time we cannot read is not a job that has been running
    for ever — and offering to terminate one on the strength of an unparseable string is the
    expensive direction of this whole feature."""
    if not when:
        return 0.0
    try:
        from datetime import UTC, datetime

        started = datetime.fromisoformat(str(when))
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        return (datetime.now(UTC) - started).total_seconds() / 3600.0
    except (TypeError, ValueError):
        return 0.0

#: The workflow queries that mean "a PERSON, not the factory, is what this job is waiting for" —
#: mapped to the name the readers use for that gate.
#:
#: ONE LIST, BECAUSE THE PARK QUERY IS NOT THE WHOLE ANSWER. `awaiting_action` covers impediments
#: only; a job at the merge gate or the production gate answers it falsy and is otherwise
#: indistinguishable from a job that is genuinely working. The hourly rounds asked the park query
#: alone, so a pull request waiting overnight for its author was reported as *"rodando há 10h …
#: não consegui identificar a causa"* (pilot, 2026-08-16) — an alarm about a healthy job, sent to
#: the person it was waiting for.
#:
#: A gate added to `JobWorkflow` and not added here would recreate that silence exactly, so a
#: guard derives this mapping from the workflow's own `awaiting_*` queries.
HUMAN_GATES = {"awaiting_merge": "merge", "awaiting_approval": "prod_approval"}
#: One entry per job that ever reached a terminal state. Terminal states never change, so
#: memoising is right — but the panel process never restarts, so the memo needs a floor.
_state_cache: BoundedDict[tuple[str, str], str] = BoundedDict(2000)


async def _true_status(client: Client, wf) -> WorkflowExecutionStatus | None:
    """The workflow's REAL status. The visibility store `list_workflows` reads from LAGS —
    it reports a just-terminated/completed workflow as RUNNING for up to minutes, which the
    panel then paints as a ghost 'in production' card that never clears (the operator sees a
    finished run frozen at its last station). `describe()` hits the mutable state directly, so
    it is authoritative. Only paid for running-LOOKING jobs (≤1 on the single line), never for
    the cached closed history. None → the workflow is gone entirely (aged out)."""
    if wf.status != WorkflowExecutionStatus.RUNNING:
        return wf.status
    try:
        desc = await client.get_workflow_handle(wf.id, run_id=wf.run_id).describe()
        return desc.status
    except Exception as exc:  # noqa: BLE001
        # never assert 'running' from a read we could not make: the panel would show a job holding
        # the floor that is not there, and nobody would go looking for the real state
        log.info("could not confirm %s is still running (%s) — treating it as gone", wf.id, exc)
        return None


async def _domain_state(client: Client, wf) -> tuple[str, dict | None, bool]:
    """The job's domain state, any operator ACTION it's parked on, and whether the workflow is
    genuinely LIVE. Running: a single-line park (impediment/rate-limit) surfaces its real state
    ('on_hold'/'needs_refinement'/'paused') plus the action payload {kind,state,note} so the
    panel can offer Resume/Skip; else the prod-approval gate, else 'running'. Closed: the
    RunResult's state (cached), or 'failed'. A visibility-lagged 'running' that describe()
    reveals as closed/gone is corrected here (live=False) — never the stale 'in production'
    ghost. live distinguishes a truly-running park from a COMPLETED-with-that-result run (both
    read e.g. 'on_hold'), so the caller can trust it for the live-card decision."""
    true = await _true_status(client, wf)
    if true == WorkflowExecutionStatus.RUNNING:
        try:
            handle = client.get_workflow_handle(wf.id, run_id=wf.run_id)
            act = await handle.query(JobWorkflow.awaiting_action)  # parked (impediment/pause)?
            if act:
                return (act.get("state") or "on_hold"), act, True
            mw = await handle.query(JobWorkflow.awaiting_merge)  # PR open, in the merge watch?
            if mw:
                # A PASS IS RUNNING ON IT (#151) — the operator already answered and the machine
                # is acting on that answer, so nobody is being asked anything. Reading this as a
                # gate is how "Needs you" appeared over a job an agent was actively rewriting,
                # with Merge and Discard live beside it.
                if mw.get("working"):
                    return JobState.REPAIRING.value, {"kind": MERGE_WAIT, **mw}, True
                # human path (auto=False) NEEDS the operator: review + merge the PR. The auto
                # path is just CI/auto-merge pending — informative, not attention.
                state = "merging" if mw.get("auto") else "awaiting_your_merge"
                return state, {"kind": MERGE_WAIT, **mw}, True
            if await handle.query(JobWorkflow.awaiting_approval):
                return "awaiting_prod_approval", None, True
        except Exception as exc:  # noqa: BLE001 — the panel degrades, never 500s
            # The panel now shows a state derived without asking the job. A workflow that cannot be
            # queried is usually one whose worker is gone, which is worth seeing.
            # `wf.id`, NOT `job_id` — that name is the module-level FUNCTION at the top of this
            # file, so the one log line whose entire purpose is to name the workflow that will not
            # answer printed `<function job_id at 0x…>`. Same class as the `namespace()` call that
            # swallowed the pilot's merge, and invisible for the same reason: it is a plausible
            # value in a message nobody diffs.
            log.warning("could not query %s for its state (%s)", wf.id, str(exc)[:120])
        return "running", None, True
    if true is None:
        return "gone", None, False  # aged out of retention — not a live card
    key = (wf.id, wf.run_id)
    if key not in _state_cache:
        state = "failed"
        if true == WorkflowExecutionStatus.COMPLETED:
            try:
                result = await client.get_workflow_handle(wf.id, run_id=wf.run_id).result()
                state = (result.get("state") if isinstance(result, dict) else None) or "done"
            except Exception as exc:  # noqa: BLE001 — the panel degrades, it never blanks
                # "failed" is what the panel shows either way, but a workflow we cannot READ and a
                # workflow that failed are different problems and only the log tells them apart.
                log.info("could not read the result of %s (%s) — showing it as failed", wf.id, exc)
                state = "failed"
        _state_cache[key] = state
    return _state_cache[key], None, False


# The post-merge deploy-watch (ADR-0005) runs as a SEPARATE abandoned child workflow
# (openfactory-deploy-<project>-<issue>) that only notifies. Its outcome is invisible on the
# JobWorkflow card (the job is "merged" the moment it merges), so the panel reads the child
# directly and shows the deploy status too. A terminal deploy result is immutable → cache it.
_DEPLOY_LABEL = {"success": "deployed", "failure": "deploy_failed", "timeout": "deploy_timeout"}
_deploy_cache: BoundedDict[str, str] = BoundedDict(2000)


async def _deploy_state(client: Client, project: str, issue: str) -> str | None:
    """The deploy-watch outcome for a merged job: 'deploying' (watch still observing),
    'deployed' / 'deploy_failed' / 'deploy_timeout' (terminal), or None when the job has no
    watch (not opted in, or older than ADR-0005). Reads the child workflow directly; terminal
    outcomes are cached so a shipped job is described at most once."""
    wf_id = f"openfactory-deploy-{project}-{issue}"
    if wf_id in _deploy_cache:
        return _deploy_cache[wf_id]
    try:
        desc = await client.get_workflow_handle(wf_id).describe()
    except Exception as exc:  # noqa: BLE001 — usually genuinely absent (not opted in)
        log.debug("no deploy-watch for %s (%s)", wf_id, exc)
        return None
    if desc.status == WorkflowExecutionStatus.RUNNING:
        return "deploying"  # not cached — re-checked until it settles
    label = "deploy_failed"  # a failed/terminated/timed-out child reads as a deploy failure
    if desc.status == WorkflowExecutionStatus.COMPLETED:
        try:
            result = await client.get_workflow_handle(wf_id).result()
            label = _DEPLOY_LABEL.get(str(result), "deploy_failed")
        except Exception as exc:  # noqa: BLE001 — same degrade as above
            log.info("could not read deploy %s (%s) — showing it as failed", wf_id, exc)
            label = "deploy_failed"
    _deploy_cache[wf_id] = label
    return label


async def _memo_title(wf) -> str:
    """The ticket title the workflow stamped into its memo (ADR-0005 companion) — decoded from
    the raw memo the list response already carried, so no extra RPC. '' when absent (older jobs
    started before titles were stamped, or a title lookup that failed)."""
    try:
        return str((await wf.memo()).get("title") or "")
    except Exception as exc:  # noqa: BLE001 — a title is decoration; the number identifies the job
        log.debug("no memo title (%s)", exc)
        return ""


def _why(state: str, result: dict) -> str:
    """A plain-but-technical explanation of WHY the job is in this state — so the panel's
    card modal answers "why didn't this merge / why does it need me", instead of a bare
    `pr_open`. Derived deterministically from the RunResult (no LLM call per open)."""
    supp = result.get("added_suppressions") or []
    review = result.get("review") or {}
    note = result.get("note")
    if state == "merged":
        return ("Merged — every gate passed, the review didn't reject it, and the merge "
                "policy allowed it.")
    if state == "pr_open":
        if supp:
            kinds = ", ".join(sorted(set(supp)))
            return (f"Not auto-merged: the diff ADDS gate-suppression(s) [{kinds}]. A suppression "
                    f"tells a quality gate to ignore some code (e.g. `pragma: no cover` exempts it "
                    f"from the coverage requirement). You can't pass a gate by silencing it, "
                    f"so any added suppression is always sent to a human — confirm it's "
                    f"legitimate (test/"
                    f"defensive code) and not hiding untested production code, then merge.")
        if review.get("decision") == "rejected":
            return (f"The independent review REJECTED it (score {review.get('score')}). "
                    f"{review.get('summary') or ''}").strip()
        return ("Handed to human review — the project's merge policy requires a human, or a "
                "high-risk component was touched.")
    if state == "on_hold":
        return note or "On hold for a human (gates unfixable, a merge conflict, or a deadline)."
    if state == "needs_refinement":
        return note or "Sent back for refinement — the spec was unclear or the plan was too large."
    if state == "paused":
        return note or "Paused on a usage/rate limit — resumes on its own (durable timer)."
    return note or state


async def job_detail(client: Client, project: str, issue: str, namespace: str) -> dict:
    """The card-click briefing: runtime, cost, PR, WHY it's in this state, the review verdict
    + findings, the added suppressions (with location), and the gate results. Reads the
    JobWorkflow's result once; running/older jobs return what's available."""
    wf_id = job_id(project, issue)
    handle = client.get_workflow_handle(wf_id)
    out: dict = {"project": project, "issue": issue, "workflow_id": wf_id}
    try:
        desc = await handle.describe()
    except Exception as exc:
        return {**out, "error": f"job not found: {str(exc)[:120]}"}
    out["status"] = status_label(desc.status)
    out["title"] = await _memo_title(desc)
    out["temporal_url"] = temporal_url(wf_id, desc.run_id, namespace)
    start, close = getattr(desc, "start_time", None), getattr(desc, "close_time", None)
    out["runtime_ms"] = int((close - start).total_seconds() * 1000) if start and close else None
    if desc.status == WorkflowExecutionStatus.RUNNING:
        # ASK THE JOB, DO NOT READ ITS TEMPORAL STATUS (#174, measured on the pilot).
        #
        # A job parked at a gate IS still RUNNING as a workflow — that is the design: single-line
        # strict holds the floor until the merge lands (ADR-0007). So this branch returned
        # `running` / "Still running." for EVERY parked job — the merge gate, the production
        # approval, an impediment, a decision — on the one screen where a person is deciding.
        #
        # Measured at one instant, three readers of one job:
        #     /api/temporal/jobs   awaiting_your_merge   action merge_wait
        #     /api/inbox           awaiting_your_merge   "Review rejected it"
        #     this                 running               "Still running."
        #
        # The queries were there the whole time — `list_jobs` asks them through `_domain_state`,
        # and `verdict` was published for exactly this (#149: a rejected pull request must not
        # look like an approved one). This is the same one-question-two-answers class as the floor
        # and the inbox (#164), and the poorer answer was on the deciding surface.
        state, action, _live = await _domain_state(client, desc)
        out["state"] = state
        out["action"] = action
        if action and action.get("pr_url"):
            out["pr_url"] = action["pr_url"]
        try:  # THE VERDICT IS A QUERY, so it exists long before the workflow completes
            out["review"] = await handle.query(JobWorkflow.verdict)
        except Exception as exc:  # noqa: BLE001 — the card degrades, it never 500s
            log.info("could not read %s's review verdict (%s)", wf_id, str(exc)[:120])
            out["review"] = None
        # `pr_open` IS THE PHRASE THE EXPLANATION IS WRITTEN FOR — it is what a merge gate is, and
        # `_why` says which of its three causes this one is (a suppression, a rejected review, or
        # the policy). The domain state a live gate reports is the narrower `awaiting_your_merge`.
        out["why"] = _why("pr_open" if state == "awaiting_your_merge" else state,
                          {"note": (action or {}).get("note") or "",
                           "review": out["review"] or {}})
        out["ci_checks"] = await _pr_checks(project, out.get("pr_url")) if out.get("pr_url") else []
        out["ci_provider"] = _ci_provider(project)
        return out
    if desc.status != WorkflowExecutionStatus.COMPLETED:
        out["state"] = "failed"
        out["why"] = "The workflow itself failed."
        return out
    try:
        r = await handle.result()
    except Exception as exc:  # noqa: BLE001
        log.info("could not read the result of %s (%s) — reporting it as failed", handle.id, exc)
        return {**out, "state": "failed", "why": "The workflow failed before producing a result."}
    r = r if isinstance(r, dict) else {}
    state = r.get("state") or "done"
    out.update({
        "state": state,
        "cost_usd": r.get("total_cost_usd"),
        "pr_url": r.get("pr_url"),
        "note": r.get("note"),
        "repair_attempts": r.get("repair_attempts"),
        "review": r.get("review"),
        "suppressions": r.get("suppression_details") or [],
        "added_suppressions": r.get("added_suppressions") or [],
        "gates": [{"name": v.get("name"), "passed": v.get("passed")}
                  for v in (r.get("validations") or [])],
        "why": _why(state, r),
    })
    out["deploy"] = await _deploy_state(client, project, issue) if state == "merged" else None
    out["ci_checks"] = await _pr_checks(project, r.get("pr_url")) if r.get("pr_url") else []
    out["ci_provider"] = _ci_provider(project)
    return out


#: How a forge kind reads to a human. A kind with no entry shows its own name — a new provider must
#: not need this table to be displayed HONESTLY, only to be displayed prettily.
_FORGE_LABELS = {"github": "GitHub", "azure_devops": "Azure Pipelines", "gitlab": "GitLab"}


def _ci_provider(project: str) -> str:
    """Whose CI these checks came from, for the panel's own heading.

    THE PANEL SAID "CI checks (GitHub)" TO EVERY READER. It is a hardcoded vendor name on the
    surface ADR-0038 calls the REFERENCE one, in the same class the product owner flagged when the
    cockpit told an OpenCode-on-Bedrock project it was running Claude Code: *"this is a
    multi-harness product — hardcoded things at this point are not acceptable."* An Azure Repos
    project fills this list from Azure Pipelines and was labelled GitHub, which is not a cosmetic
    error — it is the panel asserting a fact about a client's infrastructure that is false, and an
    operator debugging a red check would have gone looking on github.com.

    "" when it cannot be resolved, and the panel then writes a bare "CI checks" — no name is
    strictly better than the wrong name."""
    try:
        from openfactory.adapters.forge.registry import forge_kind
        from openfactory.registry import ProjectRegistry

        kind = forge_kind(ProjectRegistry().get(project))
        return _FORGE_LABELS.get(kind, kind)
    except Exception as exc:  # noqa: BLE001 — a heading must never take the cockpit down
        log.info("could not resolve the CI provider label for %s (%s)", project, exc)
        return ""


async def _pr_checks(project: str, pr_url: str) -> list[dict]:
    """The PR's CI checks (e2e / vitest / pg_integration / …) — the other half of the picture the
    sandbox gates don't show. Best-effort: [] on any error (no creds, gh missing)."""
    import asyncio

    def _fetch() -> list[dict]:
        try:
            from openfactory.adapters.forge.registry import build_forge
            from openfactory.credentials import forge_token_for
            from openfactory.factory import _bot_token_provider
            from openfactory.registry import ProjectRegistry

            # PER PROJECT. `forge_token()` is one process-wide value, so this handed an Azure Repos
            # project the deployment's GitHub credential — presented as HTTP Basic to
            # dev.azure.com, read back as a 401, and swallowed into "no checks shown".
            proj = ProjectRegistry().get(project)
            tok = forge_token_for(proj)
            forge = build_forge(proj, token=tok,
                                token_provider=None if tok else _bot_token_provider())
            return forge.pr_checks(pr=pr_url)
        except Exception as exc:  # noqa: BLE001 — the panel degrades to "no checks shown"
            log.info("could not read PR checks for %s (%s)", pr_url, exc)
            return []

    return await asyncio.to_thread(_fetch)


async def connect() -> Client:
    from openfactory.runtime.temporal.connection import connect as _connect

    return await _connect()  # dev-server or Temporal Cloud, per env


async def intake(client: Client) -> dict:
    """Whether the thing that PICKS UP work is switched on: `{on, note, known}`.

    THE PANEL COULD NOT ANSWER THIS, and its header implied it could. "engine live" means the
    platform can reach Temporal — a different fact entirely from "the poller is running". A
    PAUSED poller with a reachable engine renders exactly like a healthy factory, under a line
    that reads "a new card in TO-DO goes into production on its own (scanned every 3 min)". That
    sentence is then false, on screen, with nothing contradicting it: cards sit in TO-DO, the
    floor stays idle, and the only way to find out was to run a script from a laptop with the
    cloud credentials sourced — which is not an answer a product can rely on somebody having.

    Not hypothetical: pausing this schedule is the ONLY real way to hold the queue (emptying
    TO-DO does not, because auto-split refills it), so it is a lever an operator genuinely pulls,
    and the live schedule still carries the note from the last time it was pulled.

    `known=False` when the schedule cannot be read. Never guessed as ON: a header claiming intake
    is running when we could not ask is the same lie one layer down.

    AND WHETHER IT IS ACTUALLY TICKING, not merely switched on (#140). "Not paused" is a setting;
    a poller that fires every three minutes is a fact, and only the second one lets a screen
    promise that the next card in TO-DO gets picked up. `describe()` already returns all of it —
    this function read `.schedule.state` and threw the rest away, so the panel hard-coded
    "scanned every 3 min" and had no way to notice a schedule that had stopped firing.

    THE HONESTY CEILING, and it is written here because the copy downstream depends on it:
    `recent_actions` proves a tick FIRED — that the poll workflow was STARTED. It does not prove
    a scan COMPLETED. A dead worker leaves the schedule firing happily into an empty task queue.
    So a reader of these fields may say "the poller last fired X ago" and must never say "the
    last scan completed X ago".

    SECONDS, COMPUTED HERE. The browser's clock is not this deployment's clock: a laptop four
    minutes fast would read a healthy three-minute poller as stalled, and a slow one would read a
    dead poller as fresh — the reassuring direction, which is the expensive one. ISO strings ride
    along for display only, never for arithmetic.
    """
    from openfactory.runtime.temporal.schedule import SCHEDULE_ID

    #: The shape every branch returns, so a caller never has to ask whether a key is present.
    #: `None` is the answer for "this deployment's engine did not tell us", which is a different
    #: thing from zero and must stay tellable apart from it.
    unread = {"fired_ago_s": None, "next_in_s": None, "every_s": None,
              "num_actions": None, "running_now": None, "created_ago_s": None,
              "fired_at": None, "next_at": None}

    async def _one(schedule_id: str) -> dict:
        try:
            desc = await client.get_schedule_handle(schedule_id).describe()
            state = desc.schedule.state
        except Exception as exc:  # noqa: BLE001 — the panel degrades, it never 500s
            log.warning("could not read the schedule %s (%s)", schedule_id, str(exc)[:120])
            return {"known": False, "on": None, "note": "", **unread}
        # THE SWITCH IS THE PART THAT MUST NEVER FAIL; the cadence is the part that is allowed to
        # be unknown. An older Temporal server, and every test double in this suite, exposes
        # `.schedule.state` and nothing else — and `getattr(desc, "info", None)` is NOT enough on
        # its own, because it only swallows AttributeError: a property that raises anything else
        # takes the whole intake answer down with it, turning every floor Unknown on a server
        # version difference. Caught here, so an enrichment can never cost the answer.
        try:
            cadence = _cadence(getattr(desc, "info", None), getattr(desc.schedule, "spec", None),
                               unread)
        except Exception as exc:  # noqa: BLE001 — an unreadable cadence is reported, not raised
            log.warning("could not read the cadence of %s (%s) — the switch still answers",
                        schedule_id, str(exc)[:120])
            cadence = dict(unread)
        return {"known": True, "on": not state.paused, "note": str(state.note or ""), **cadence}

    out = await _one(SCHEDULE_ID)
    # THE OTHER TWO STANDING LOOPS (#24 item 6). Only the poller was proven alive; the product
    # sweep and the tech-lead's rounds — the loop that carries the release bridge — could stop
    # (or never be scheduled) and nothing anywhere would say so, because both are SILENT when
    # they have nothing to report: a dead watcher and a quiet week render identically. Carried
    # on the same payload the header already reads, keyed by schedule id, so the panel can name
    # exactly which loop is dark.
    out["watchers"] = {sid: await _one(sid) for sid in _watcher_schedule_ids()}
    return out


def _cadence(info, spec, unread: dict) -> dict:
    """What the schedule's own history says about whether it is ticking (#140).

    Its own function so it can be tested against the shapes a Temporal server really returns,
    without standing up a client — and so the "not told" answer has exactly one definition.
    """
    from datetime import UTC, datetime

    if info is None and spec is None:
        return dict(unread)
    now = datetime.now(UTC)

    def _ago(when) -> float | None:
        """Seconds since `when`, clamped at zero. A negative age means the two clocks disagree,
        and reporting one would make a caller compute a poller that fired in the future."""
        return None if when is None else max(0.0, (now - when).total_seconds())

    recent = list(getattr(info, "recent_actions", None) or [])
    # `scheduled_at` is the tick this action BELONGS to; `started_at` is when the worker picked
    # it up. Prefer the first — it is the cadence question — and fall back to the second.
    fired = max((r.scheduled_at or r.started_at for r in recent
                 if (r.scheduled_at or r.started_at)), default=None)
    nxt = next(iter(getattr(info, "next_action_times", None) or []), None)
    every = next((i.every for i in (getattr(spec, "intervals", None) or [])), None)
    created = getattr(info, "created_at", None)
    return {
        "fired_ago_s": _ago(fired),
        # NOT clamped: a next tick already in the past is exactly the signal that the schedule
        # has stopped being serviced, and clamping it to zero would hide that.
        "next_in_s": None if nxt is None else (nxt - now).total_seconds(),
        "every_s": None if every is None else every.total_seconds(),
        "num_actions": getattr(info, "num_actions", None),
        "running_now": len(getattr(info, "running_actions", None) or []),
        "created_ago_s": _ago(created),
        "fired_at": fired.isoformat() if fired else None,   # display only
        "next_at": nxt.isoformat() if nxt else None,        # display only
    }


def _watcher_schedule_ids() -> list[str]:
    """The per-project standing loops this deployment SHOULD have running."""
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal.schedule import PRODUCT_SCHEDULE_PREFIX, WATCH_SCHEDULE_PREFIX

    ids: list[str] = []
    try:
        for p in ProjectRegistry().list():
            if not p.enabled:
                continue
            ids.append(f"{WATCH_SCHEDULE_PREFIX}-{p.name}")
            if getattr(p, "product", None) is not None:
                ids.append(f"{PRODUCT_SCHEDULE_PREFIX}-{p.name}")
    except Exception as exc:  # noqa: BLE001 — an unreadable registry must not take the panel down
        log.warning("could not list the projects for the watcher check (%s)", exc)
    return ids


async def list_jobs(
    client: Client, namespace: str, *, limit: int = 50, query: str | None = None
) -> list[dict]:
    """Recent jobs, newest first, each enriched with its domain `state`. `query` is an
    optional Temporal list filter (e.g. a StartTime range) for searchable history."""
    base = 'WorkflowType = "JobWorkflow"'
    full = f"{base} AND ({query})" if query else base
    rows: list[dict] = []
    async for wf in client.list_workflows(full):
        row = _row(wf, namespace)
        row["state"], row["action"], live = await _domain_state(client, wf)
        if row["state"] == "gone":
            continue  # visibility still lists it but the workflow aged out — not a real card
        # Reconcile the visibility status (which LAGS) with the truth: the panel paints an
        # 'in production' machine card for any job whose status=='running', so a lagged
        # 'running' on an already-closed workflow was the frozen ghost. Only a genuinely live
        # workflow keeps 'running'; a closed one is stamped 'closed' so the card clears.
        if not live and row["status"] == "running":
            row["status"] = "closed"
        # ATTENTION means "a human must act on a LIVE job". A closed workflow (completed/
        # terminated/gone) can still carry a cached parked-ish state (e.g. a run that was
        # on_hold then terminated, or needs_refinement then completed) — gate on `live` so a
        # finished job never shows a phantom "needs attention" in the panel/Slack count.
        row["attention"] = live and row["state"] in ATTENTION_STATES
        row["title"] = await _memo_title(wf)  # panel shows it beside the #number
        # WEDGED: running, at no gate, for longer than any real pass takes (#127). A job in this
        # state holds the single-slot floor and no verb could reach it — `resume`/`skip` answer a
        # park and the engine refuses them, the merge verbs answer a gate — so the honest exit was
        # "open Temporal and terminate", a raw-engine operation on the one surface this product
        # promises an operator will never need.
        #
        # DECIDED HERE, not in the browser, and against the SAME constant the tech-lead's rounds
        # use to raise the alarm. Two readings of "stuck" would disagree by next month, and the
        # one on the button is the one that matters.
        row["wedged"] = is_wedged(row, live=live)
        # surface the post-merge deploy outcome (ADR-0005) so the watch isn't invisible when
        # no external notifier is configured — only merged jobs can have a deploy running.
        row["deploy"] = await _deploy_state(client, row["project"], row["issue"]) \
            if row["state"] == "merged" and row["project"] and row["issue"] else None
        rows.append(row)
        if len(rows) >= limit:
            break
    # stable order (newest first) so the SSE frame doesn't churn on list reordering — an
    # unstable order made the panel re-render (and reset) a running job's card each tick.
    rows.sort(key=lambda r: r.get("start_time") or "", reverse=True)
    return rows


async def coordinator_messages(client: Client) -> list[dict]:
    """The recent updates the project tech-lead coordinators have NARRATED (pickup / merge /
    deploy), across projects — the panel toasts what's new; a Slack/PO bot reads the same feed.
    Each: {project, id, text, kind}. Best-effort per coordinator (a query miss is skipped)."""
    out: list[dict] = []
    try:
        wfs = client.list_workflows(
            "WorkflowType = 'CoordinatorWorkflow' AND ExecutionStatus = 'Running'")
    except Exception as exc:  # noqa: BLE001
        log.warning("could not list the coordinators (%s) — no narration will reach the panel "
                    "or Slack this round", exc)
        return out
    pfx = "openfactory-coordinator-"
    async for wf in wfs:
        project = wf.id[len(pfx):] if wf.id.startswith(pfx) else wf.id
        try:
            msgs = await client.get_workflow_handle(wf.id, run_id=wf.run_id).query("recent")
        except Exception as exc:  # noqa: BLE001 — one coordinator missing is not all of them
            log.info("coordinator %s did not answer (%s) — its updates are missing this round",
                     wf.id, exc)
            continue
        for m in (msgs or []):
            out.append({"project": project, **m})
    out.sort(key=lambda m: (m.get("project", ""), m.get("id", 0)))
    return out


async def start_job(client: Client, params: JobParams) -> str:
    wf_id = job_id(params.project, params.issue)
    await client.start_workflow(JobWorkflow.run, params, id=wf_id, task_queue=TASK_QUEUE)
    return wf_id


async def approve_job(
    client: Client, project: str, issue: str, *, version: str, approver: str, comment: str = ""
) -> None:
    """Deliver the prod approval as a durable signal to the parked workflow (D-12). Checks
    the workflow is actually at the gate first, so an approval is never silently lost."""
    handle = client.get_workflow_handle(job_id(project, issue))
    if not await handle.query(JobWorkflow.awaiting_approval):
        raise RuntimeError("job is not awaiting prod approval")
    await handle.signal(JobWorkflow.approve_prod, args=[version, approver, comment])


async def answer_merge_gate(client: Client, project: str, issue: str, *, answer: str,
                            instruction: str = "", by: str = "") -> dict:
    """Deliver a human's answer to a PR waiting on them (#68). Returns the merge-wait dict.

    QUERY BEFORE SIGNAL, exactly as `approve_job` does above and for the same reason: a signal is
    fire-and-forget, so without the query a stale answer — to a PR that already merged, or to a
    job that never opened one — would be accepted and reported as done. Telling somebody the
    factory acted when it did not is worse than refusing.

    THE MERGE GATE IS NOT A PARK, which is why this exists at all rather than reusing `act_job`.
    During the merge watch `_paused` is never set, so `awaiting_action` is None and every existing
    answer path refuses. `awaiting_merge` is the gate's own query and this is its own signal."""
    if answer not in ("merge", "adjust", "discard", "review"):
        raise ValueError("answer must be 'merge', 'adjust', 'discard' or 'review'")
    handle = client.get_workflow_handle(job_id(project, issue))
    gate = await handle.query(JobWorkflow.awaiting_merge)
    if not gate:
        raise RuntimeError("this job is not waiting on a merge")
    deaf = gate_cannot_hear(gate)
    if deaf:
        raise GateDeaf(deaf)
    await handle.signal(JobWorkflow.human_merge_gate, args=[answer, instruction, by])
    return dict(gate)


class GateDeaf(RuntimeError):
    """The job IS waiting on a merge — but its run can never consume an answer. A distinct type
    because the generic RuntimeError above means the opposite ('not waiting on a merge'), and a
    caller folding the two into one sentence tells the operator the PR may have merged when the
    truth is the gate is deaf."""


def gate_cannot_hear(gate: dict) -> str:
    """Why this merge-wait can never consume an answer, or "" when it can (or when the workflow
    is too old to say).

    THE ANSWER MUST NOT OUTRUN THE EAR. A job whose history predates the `human-merge-gate`
    patch replays with `patched()` memoized off — it polls the PR forever and no code in that
    run ever reads the signal. Before this check, such a job's gate still LOOKED answerable:
    the panel showed the buttons, the API accepted the click and said "sent back for one pass",
    and the answer sat unread in workflow state until the 14-day deadline. Found live on
    fx-mono#1 after a deploy replaced the gate-holder mid-wait. Refusing here — at the one seam
    every surface goes through — turns the lie into a sentence with the two real ways out.

    `gate_live` absent means the workflow's binary predates the flag: assume answerable rather
    than refuse work the gate may well consume (absence reads as the OLD behavior, not as
    evidence of deafness)."""
    if gate.get("gate_live") is False:
        return ("this job started before the merge gate existed, so no answer can reach it — "
                "merge or close the PR on the forge itself, or reset the job's workflow to a "
                "point before the merge watch so it re-arms with the gate on")
    if gate.get("working"):
        # A PASS IS REWRITING THE BRANCH RIGHT NOW, because a human already answered `adjust`
        # (#151). The gate is still open — the run consumes an answer the moment the pass ends —
        # so this is not deafness; it is an answer that would land on a diff nobody has seen. A
        # merge here lands whatever the agent has pushed so far; a discard throws away a pass the
        # operator is paying for. Both surfaces used to offer the buttons anyway, and an API call
        # or a stale page still would: the refusal has to live at the seam every surface crosses.
        return ("a repair pass is rewriting this pull request right now — the answer you give "
                "would land on a diff nobody has read. It will ask again when the pass ends, and "
                "the panel shows what it is doing meanwhile")
    return ""


async def act_job(client: Client, project: str, issue: str, *, action: str,
                  choice: str = "") -> None:
    """Single-line strict (ADR-0010): deliver the operator's (or a bot's) decision on a PARKED
    job as a durable signal — 'resume' (re-run / retry a rate-limit now / proceed with a chosen
    option) or 'skip' (free the floor). `choice` is the DecisionRequest option key when the park
    carried options. Checks the job is actually parked first, so the action is never silently
    lost."""
    if action not in ("resume", "skip"):
        raise ValueError("action must be 'resume' or 'skip'")
    handle = client.get_workflow_handle(job_id(project, issue))
    parked = await handle.query(JobWorkflow.awaiting_action)
    if not parked:
        raise RuntimeError("job is not parked (no impediment/pause awaiting an action)")
    # A PARK THAT ASKS A QUESTION IS NOT RESUMED BLINDLY (#24 item 1). The workflow only injects
    # the picked option when one arrives; a bare resume on a decision park used to be ACCEPTED,
    # run a whole agent pass, and re-park on the same question — the platform reporting it acted
    # while the wait continued. Refused here, at the one seam every front end goes through, with
    # the keys a person can actually answer with. A wrong key is refused for the same reason: an
    # answer to a question that was not asked must not be recorded as if it were.
    decision = (parked.get("decision") or {}) if isinstance(parked, dict) else {}
    options = [str(o.get("key") or "") for o in (decision.get("options") or [])]
    if action == "resume" and options:
        if not choice:
            raise RuntimeError(
                "this park asks a question — resuming without an answer would re-park on the "
                f"same question after a full agent pass. Answer with one of: {', '.join(options)} "
                f"(no Slack: `decisão: <opção>`; no painel: o botão da opção)")
        if choice not in options:
            raise RuntimeError(
                f"{choice!r} is not one of this park's options ({', '.join(options)}) — "
                f"the question on the ticket names what each one means")
    await handle.signal(JobWorkflow.act_on_impediment, args=[action, choice])
