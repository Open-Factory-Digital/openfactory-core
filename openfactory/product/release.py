"""The client's "funcionou" is what releases production (ADR-0025, board #6).

WHAT IT REPLACED. The pipeline parked at `AWAITING_PROD_APPROVAL` for days waiting for a signal
FROM THE PANEL, with a password, given by an operator. The person who knows whether the change is
right is the client — and they were the only one not asked. Nothing on this board contradicted "no
dev needed" harder: a factory that needs an operator to cut a release is not the factory being
sold.

THE PIECES ALL EXISTED, and that is why this module is small. The workflow already parks durably
on a signal (days, no compute burned). `temporal_view.approve_job` already queries the gate BEFORE
signalling, so an approval is never silently dropped. The acceptance loop already asks a client
whether something worked and reads the answer with a model judge (ADR-0029). What was missing was
the wire between them.

WHY IT IS NOT `bot.act_job`. That function carries a deliberate hard guardrail — Slack may only
ever `resume`/`skip`/`ack`, so a prod release "can never be driven from here even if a caller
asks". That guardrail is about the TECH-LEAD surface, which is an operator's, and it stays exactly
as it is. This is the other surface (ADR-0026): a different channel, a different gate
(`may_act` over the deployment's declared product admins), and a staged confirmation the person
either types or clicks. Punching a hole in the operator path to reach the client's decision would
have merged the two surfaces the platform keeps apart on purpose.

NOTHING HERE DECIDES ANYTHING. This module observes what is parked and delivers a decision somebody
already made in the channel. The authorisation happened before it was called, and the observation
is the workflow's own answer — never this module's belief about it.
"""

from __future__ import annotations

import logging

log = logging.getLogger("openfactory.product")

#: How the version is derived when the client releases. The panel lets an operator type one; a
#: client has no reason to know what a version string is, and asking them for one would be the
#: operator's vocabulary reappearing at the last step of the flow it was removed from.
_VERSION_PREFIX = "req"


def version_for(issue: str) -> str:
    """A deterministic version for a client-approved release.

    Deterministic, so a retried approval tags the SAME release rather than minting a second one:
    the tag is what `release_prod` creates, and two tags for one approval is a history nobody can
    read backwards."""
    return f"{_VERSION_PREFIX}-{str(issue).lstrip('#')}"


def _job_id(project_name: str, issue: str) -> str:
    return f"openfactory-{project_name}-{str(issue).lstrip('#')}"


async def _awaiting(client, project_name: str, issue: str) -> bool:
    handle = client.get_workflow_handle(_job_id(project_name, issue))
    return bool(await handle.query("awaiting_approval"))


async def parked_for_release(client, project_name: str) -> list[tuple[str, str]]:
    """`(issue, where a person looks)` for every job parked waiting for a production approval.

    THE ADDRESS COMES FROM THE JOB, not from the deployment (#122). `ProductConfig.staging_url` —
    one string, on the deployment's own registry, with no command that writes it — cannot express
    `dev` + `qa` + `producao`, which is exactly the shape a declared promotion chain has. The
    manifest declares it per stage; the promotion reads that manifest inside the box it runs in
    and hands the answer back, and `where_to_look` is how a parked job is asked for it here.

    `""` for a job that declares no address, and the caller must NOT invent one — that is the
    acceptance criterion this card was opened with. A message telling somebody to go and try
    something, with nowhere to go, is worse than one that admits the project never said where.

    ASKED OF THE WORKFLOWS, never of a stored snapshot — the question is what is true NOW, and a
    park nobody answered fires no event a listener could have cached. A job that cannot answer is
    left out rather than guessed at: the cost of missing one is that the next round asks, and the
    cost of inventing one is telling a client something is ready to try when nothing is.

    THE SECOND COPY OF THE DIGITS-ONLY MATCHER (#69). This carried the same
    `^openfactory-{project}-(\\d+)$` the tech-lead's rounds did, and it is reached FROM those
    rounds —
    so on a Jira/ADO deployment
    the client-facing staging bridge was blind too: a job parked waiting for the client's "pode
    subir" was never found, and they were never asked. Now on the shared parser, which also brings
    the sibling-project guard (`openfactory-acme-web-478` is not project `acme`) that the
    hand-rolled
    regex's own comment cited as its reason to exist.
    """
    from openfactory.runtime.temporal.view import parse_job_id

    out: list[tuple[str, str]] = []
    async for wf in client.list_workflows(
            'WorkflowType = "JobWorkflow" AND ExecutionStatus = "Running"'):
        project_of, issue = parse_job_id(str(wf.id), known_projects=[project_name])
        if project_of != project_name or not issue:
            continue
        try:
            handle = client.get_workflow_handle(wf.id)
            if not await handle.query("awaiting_approval"):
                continue
            where = ""
            try:
                look = await handle.query("where_to_look")
                where = str((look or {}).get("url") or "")
            except Exception as exc:  # noqa: BLE001 — a job started before this query existed
                # NOT a reason to skip the job. The client still needs asking; they just get the
                # sentence that admits no address rather than one carrying a wrong guess.
                log.info("release watch: %s could not say where to look (%s)", wf.id, exc)
            out.append((issue, where))
        except Exception as exc:  # noqa: BLE001 — one that cannot answer is not one that is ready
            log.info("release watch: %s did not answer (%s) — not offered", wf.id, exc)
    return sorted(out)


def release(project, issue: str, *, approver: str, comment: str = "") -> tuple[bool, str]:
    """Deliver the client's approval to the parked job. `(ok, what to say)` — NEVER raises.

    THE GATE IS RE-ASKED HERE, and that is the whole safety of this call. Between the message that
    asked the client and the answer that arrives, the job may have timed out of its approval window
    or been released by somebody else. `approve_job` queries before signalling, so a stale yes
    lands on nothing — and this returns the honest sentence rather than the reassuring one. A
    client told "subiu" over a signal that reached no workflow is the single worst outcome
    available on this path.

    The caller has ALREADY authorised the person (`may_act`) and consumed a staged confirmation.
    Nothing here re-decides that; this is the pen, not the judgement.
    """
    import asyncio

    name = getattr(project, "name", "") or ""

    async def _run() -> tuple[bool, str]:
        from openfactory.runtime.temporal.connection import connect
        from openfactory.runtime.temporal.view import approve_job

        client = await connect()
        if not await _awaiting(client, name, issue):
            # Not a failure of ours and not something to hide: the client answered honestly and the
            # world moved. Saying so is what keeps "I released it" a sentence that means something.
            return False, (f"o #{str(issue).lstrip('#')} não está mais esperando essa liberação — "
                           f"ou já subiu, ou a janela de espera fechou. Não mexi em nada; me diga "
                           f"e eu verifico em que pé está.")
        await approve_job(client, name, str(issue).lstrip("#"),
                          version=version_for(issue), approver=approver, comment=comment)
        return True, ""

    try:
        return asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 — a chat listener must never see a traceback
        # ERROR, not warning: a client said yes to a production release and the platform could not
        # deliver it. Nobody is watching a log for this, so it also has to be greppable.
        log.error("OPENFACTORY_RELEASE_SIGNAL_FAILED project=%s issue=%s approver=%s (%s) — the "
                  "client "
                  "approved and the job was not told", name, issue, approver, str(exc)[:200])
        return False, ("não consegui levar a sua liberação até a esteira agora. **Nada subiu** — "
                       "o time já foi avisado e eu volto a você assim que resolver.")
