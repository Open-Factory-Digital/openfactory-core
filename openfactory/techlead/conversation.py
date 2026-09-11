"""The tech-lead answering a question about a project — the capability, with no channel in it.

WHY THIS MOVED (C-24). This code was written inside `runtime/slack/bot.py`, and it never had a
line of Slack in it: it reads Temporal, cross-references the forge and the board, clones the
repository, and runs the read-only chat agent. An application living inside one provider is the
layer model upside down — and this one *acts*, so the deployment that does not buy Slack had no
tech-lead at all rather than a quieter one.

The same disease `roles.py::ask()` cured on the harness axis: the capability is neutral, and the
channel *delivers* it.

WHAT THE CHANNEL STILL OWNS. Where to post, who is allowed to act, how long a staged suggestion
lives, and how wide a message may be. `answer()` takes a cap because renderers differ; it does
not know what a thread is.

AND NO VENDOR EITHER (#91). Taking Slack out left the other half of the same disease untouched:
every read here was `gh`. The issue index shelled out to `gh issue list`, the checkout built
`https://…@github.com/<repo>.git`, and both carried the FORGE's credential to whatever host the
TRACKER lives on. On the Azure Boards + Azure Repos deployment that exists as of today that is not
an error — `answer()` never raises, deliberately — it is a tech-lead that cannot see the tickets or
the code and says something thinner instead. A poorer answer is the failure shape nobody reports.

So the tickets are read through `TrackerAdapter`, the checkout URL through
`forge.registry.clone_url_for`, and the board through `BoardAdapter`, which it already did. What
each read CANNOT do is now said out loud in the snapshot rather than rendered as an absence: an
unreadable ticket is not an open one, and an unreadable board is not a board with no columns.

AND THE COMMENT HISTORY IS BACK (#97). One capability did not survive that migration: this module
used to read the last three comments on every parked ticket, through `gh issue view`, and the port
had no read side to move it to — so it was deleted and replaced with a sentence telling the model
the history *"is NOT available to you"*. That sentence was honest for as long as it was true, and
it cost the tech-lead the only question worth asking before proposing anything: has somebody
already tried this? `TrackerAdapter.comments()` exists now, on every vendor, so the sentence is
gone and the thread is here — with WHO wrote each comment and WHEN, because the whole job is
telling a human's instruction from the platform's own earlier note, and a wall of undifferentiated
text cannot. When the read fails the model is told THAT, in those words: `None` from the port is
"I could not look", never "nobody has commented".

THE SUGGESTION IS RETURNED, NOT SMUGGLED. The agent is asked to end with a hidden
`[[SUGGEST resume #NN]]` tag, because a free-text model has no other way to hand back a structured
decision. That tag is a wire format between this module and the model — it must never reach a
reader, and it must never be re-parsed downstream. `Answer.suggestion` is the parsed decision, so
a caller that caps or reformats the prose cannot amputate it. The previous arrangement returned
one string carrying both, and capping it either cut the approvable action off the end (the prose
still said "responda ok" and the ok found nothing staged) or sliced a tag in half and posted the
remainder.
"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from openfactory.adapters.forge.registry import repo_of
from openfactory.adapters.tracker.base import TicketComment
from openfactory.techlead import pack
from openfactory.util import scratch

log = logging.getLogger("openfactory.techlead")

#: The verbs a suggestion may name when the caller did not say which the asker may perform.
#:
#: THE OLD PAIR, KEPT AS THE FLOOR. `answer()` is reachable from a test, a script and any future
#: front end, and a default of "everything" would let a caller that never thought about authority
#: stage a merge. Two read-mostly verbs is the safe direction for a forgotten parameter — the same
#: reasoning `ActionSpec.needs_admin` defaults True for.
_DEFAULT_PROPOSABLE = ("resume", "skip")


def _suggest_re(can: tuple[str, ...]) -> re.Pattern[str]:
    """The hidden marker the agent ends with when it proposes one concrete action.

    THE VERBS ARE THE ASKER'S, NOT THIS MODULE'S (#121). `(resume|skip)` was hardcoded here while
    the guidance told the model *"never suggest prod/merge actions"* — a rule written before the
    catalogue had a merge row. #120 added one, gated, reachable from this very chat, and both the
    prompt and the parser went on pretending it did not exist. Now `actions.proposable` decides,
    from the catalogue and the asker's own credential, and this pattern is built from the answer:
    a verb the asker could not perform cannot be parsed out of the model's message, so it is
    stripped as malformed instead of staged and then refused.

    THE REF IS THE PROVIDER'S (C-05). `#?(\\d+)` sat here, so on a tracker that does not number its
    tickets the tag never matched, the suggestion was silently swept as malformed, and the one
    feature that turns an answer into an act was missing with nothing logged about a ticket. The
    character class is bounded by the closing `]]`, so widening it cannot run away into prose.
    """
    verbs = "|".join(re.escape(v) for v in (can or _DEFAULT_PROPOSABLE))
    return re.compile(
        r"\[\[\s*SUGGEST\s+(" + verbs + r")\s+#?([A-Za-z0-9][A-Za-z0-9._-]*)\s*\]\]",
        re.IGNORECASE)

#: Anything else `[[…]]`-shaped. A malformed tag is a LOST SUGGESTION, not channel plumbing — it
#: is stripped and logged rather than posted to whoever asked.
#:
#: MULTILINE-TOLERANT SINCE #170, and the reason is the instruction. `[^\n]` made this
#: single-line BY CONSTRUCTION, which was fine while a tag was one verb and one ticket; now a tag
#: can carry a sentence somebody typed, and a sentence with a newline in it produced a tag the
#: parser refused AND the sweeper could not see — so the raw `[[SUGGEST …]]` plumbing went to a
#: human as prose. Bounded to a few lines rather than unbounded: `[\s\S]*` across a whole answer
#: would swallow the prose between two bracketed things a model wrote for other reasons.
_ANY_TAG_RE = re.compile(r"\[\[(?:(?!\]\])[^\n]|\n(?!\n)){0,600}\]\]")

#: At most this many questions answered at once. Each one spawns a repo clone plus an agent
#: process on the same box that runs the factory's activities; extra questions queue here, and
#: their acknowledgement has already gone out, so the answer simply arrives a little later.
_ANSWER_SEM = threading.Semaphore(2)

#: States that mean a job is waiting on a person rather than working.
_PARKED_STATES = ("failed", "on_hold", "needs_refinement", "blocked")

#: `action.kind` while a pull request waits — the one `view.MERGE_WAIT` produces. Spelled here
#: because importing `runtime.temporal.view` costs `temporalio`, which this module is careful never
#: to need at import time (the panel serves without the runtime extra). A guard pins the two
#: together, so a rename fails the suite rather than quietly meaning "not a merge".
_MERGE_WAIT_KIND = "merge_wait"

#: `action.kind` → what the job is waiting on, in words a person reads.
#:
#: A KIND WITH NO ENTRY RENDERS ITS OWN NAME. That is the whole design of this table: the previous
#: version of this snapshot did not render `action` at all, so a job parked at the merge gate — the
#: single most human-dependent state this platform has — was indistinguishable from one that was
#: working. A new park kind added upstream must arrive here as thin prose, never as silence.
_WAITING_ON = {
    _MERGE_WAIT_KIND: "a person to merge or discard the pull request",
    "impediment": "a person's decision",
    "rate_limit": "a usage limit to clear (it resumes on its own)",
    "self_healing": "the factory's own retry",
}

#: Every key a job row can carry, and what the snapshot does with it (#121).
#:
#: THE GUARD THAT WALKS THIS IS THE POINT. `action` and `deploy` were computed on every panel
#: refresh, handed to this module, and dropped on the floor — for months, silently, because nothing
#: anywhere related "what a row carries" to "what the tech-lead is shown". A field is either in
#: `_RENDERED` or it is in `_NOT_RENDERED` with a reason somebody wrote down; a field in neither
#: fails the suite. The reason column is not documentation, it is the deliberate half of the
#: decision — dropping `run_id` is correct and dropping `action` was not, and only a sentence can
#: tell those apart.
_RENDERED = frozenset({
    "issue", "title", "state", "attention", "action", "deploy",
    "board", "board_unread", "ticket_state", "ticket_unread",
    "verdict", "verdict_unread", "wedged",
})

_NOT_RENDERED: dict[str, str] = {
    "workflow_id": "the ticket ref identifies the job to a person; an engine id does not",
    "run_id": "an attempt's identity inside the engine — nothing an operator acts on",
    "project": "every job in this snapshot belongs to the project being asked about",
    "status": "the RAW Temporal status, which disagrees with `state` by design (a merge and a "
              "needs-refinement are both COMPLETED). `state` is the domain answer and showing "
              "both invites the model to average two readings of the same job",
    "start_time": "an ISO timestamp invites date arithmetic the model gets wrong; the scheduled "
                  "round is what watches ages, and it computes them",
    "close_time": "same reason as start_time",
    "temporal_url": "the guidance tells the tech-lead to read what a HUMAN sees, not the engine",
    "comments": "rendered by `comment_digest` as its own section, with authors and times — a "
                "thread flattened onto one line loses exactly what makes it worth reading",
}


@dataclass(frozen=True)
class Answer:
    """What the tech-lead worked out. `text` is for a reader; `suggestion` is for the machine."""

    text: str
    #: `(action, ticket ref)` the tech-lead proposes and a human could approve — or None. The ref
    #: is the tracker's own string, never coerced to a number.
    suggestion: tuple[str, str] | None = None
    #: WHAT THE ANSWER COST, and it was thrown away (#167). `AgentRunResult` has carried
    #: `cost_usd`/`num_turns`/tokens all along; this call site read `text` off it and dropped the
    #: rest, so the one role the operator talks to most was the one pass nobody could price —
    #: while `MetricRecord.role` has listed `chat` as a valid value since it was written. A number
    #: nobody records is a number nobody can tighten a budget against.
    spend: dict[str, object] | None = None


def _spent(res) -> dict[str, object]:
    """The pass's own numbers, as the adapter reported them. Absent fields stay absent — a zero
    would read as "this was free", which is the one thing it never is."""
    fields = ("cost_usd", "num_turns", "input_tokens", "output_tokens", "model", "harness")
    return {f: getattr(res, f, None) for f in fields if getattr(res, f, None) is not None}


def _record_chat_spend(project, spend: dict[str, object]) -> None:
    """One `agent_run` row with `role="chat"` — the value `MetricRecord` has documented since it
    was written and nothing has ever produced.

    BEST EFFORT AND SILENT ON FAILURE, like every other write on this path: a telemetry row that
    will not land must not cost the asker their answer.
    """
    if not spend:
        return
    try:
        from datetime import UTC, datetime

        from openfactory.observability.metrics import MetricRecord
        from openfactory.runtime.temporal.activities import _metrics_sink

        _metrics_sink().record(MetricRecord(
            project=getattr(project, "name", "") or "", ticket="chat",
            ts=datetime.now(UTC).isoformat(), kind="agent_run", role="chat",
            model=str(spend.get("model") or ""), harness=str(spend.get("harness") or ""),
            cost_usd=spend.get("cost_usd"), num_turns=spend.get("num_turns"),
            input_tokens=spend.get("input_tokens"), output_tokens=spend.get("output_tokens")))
    except Exception as exc:  # noqa: BLE001 — a lost row is a bad day, a lost answer is worse
        log.warning("could not record what the tech-lead's answer cost (%s)", str(exc)[:160])


def answer(project, question: str, *, cap: int | None = None,
           can: tuple[str, ...] = (), thread: str = "") -> Answer:
    """The tech-lead's read-only answer about THIS project.

    Gathers a live factory-state snapshot from Temporal plus a shallow checkout of the repository
    (so the agent can verify claims against the code), then runs the read-only chat agent. Both
    context sources are best-effort: if either is unavailable the agent is TOLD so and answers
    from what it has, rather than asserting an idle factory it cannot see.

    NEVER RAISES. Any trouble degrades to a sentence the asker can read. A tech-lead that answers
    a question with a traceback has not answered it.

    `cap` bounds the prose only. The suggestion rides back in its own field precisely so that
    bounding the prose cannot lose it.

    `can` is what the ASKER may perform — `actions.proposable(by)`, decided at the door where the
    actor came through, never re-derived here. This module has no idea who is asking and must not
    acquire one: authority resolved down here would be authority invented down here, which is the
    rule `_floor_say_as_an_intent` states for the same seam. Empty falls back to resume/skip.
    """
    with _ANSWER_SEM:
        return _answer(project, question, cap=cap, can=tuple(can), thread=thread)


def _answer(project, question: str, *, cap: int | None, can: tuple[str, ...] = (),
            thread: str = "") -> Answer:

    from openfactory.adapters.agent import build_techlead
    from openfactory.adapters.sandbox.base import Workspace
    from openfactory.adapters.sandbox.registry import judging_worktree

    jobs = gather_jobs(project)
    snapshot = state_snapshot(jobs)
    if not jobs:
        # Distinguish "no jobs" from "could not reach Temporal": the snapshot already reads as the
        # former, so the latter has to be said out loud or the agent asserts an idle factory.
        snapshot += "\n(Note: live job state may be incomplete if Temporal was unreachable.)"
    # SILENCE IS NOT EVIDENCE OF SILENCE, and this is where that used to be an apology. The last
    # few comments on each parked ticket were read here — through `gh`, so on one provider only —
    # and reading them is how the tech-lead explained a re-scope, a hand-off, or a fix somebody
    # already tried and watched fail. The port had no read side, so the capability was replaced by
    # a sentence saying so; it has one now (#97), and `comment_digest` renders the real thing,
    # INCLUDING the case where the tracker would not answer.
    #
    # RENDERED OUTSIDE THE TRY THAT GUARDS THE AGENT, exactly like the snapshot, and total for the
    # same reason: `answer()` never raises, so anything on this path must be a text function over
    # dicts. Every provider call it could have made was already made and already caught, inside
    # `gather_jobs`.
    comments = comment_digest(jobs)

    tmp, cloned = clone_repo(project)
    # THE THREAD FIRST, AND AS EVIDENCE RATHER THAN INSTRUCTION (#168). Every question used
    # to be turn one — the store was written on both halves of every exchange and read by
    # nobody — so the tech-lead could not know what it had already said, already been
    # corrected on, or already been told was impossible. It goes ABOVE the snapshot because
    # it is the only part of this prompt the person on the other side can check.
    # THE FACTS AS FILES (#169). The prompt used to carry every comment thread and every verdict
    # whether the question was about them or not — ~20-25k characters, capped at 30 tickets / 8
    # threads / 8 verdicts, with the caps LOGGED and invisible to the model. Written into the
    # workspace they become tools on all four harnesses (every judging role here is a read-only
    # loop over the checkout), the prompt shrinks to the index the question is chosen from, and
    # the model pays only for what it opens.
    #
    # ONLY IF THE PACK LANDED. A shrunk prompt plus an unwritten pack is a tech-lead answering
    # from nothing while believing it has files to open — absence reading as compliance, which is
    # the failure this codebase names by memory.
    #
    # AND THE KNOWLEDGE BUNDLE, WHICH LIVES IN A REPOSITORY THIS CLONE IS NOT. `clone_repo` fetches
    # the SOURCE; the concepts are published into the project's CONTEXT repository, so reaching
    # them costs a second shallow clone — of a documents repository, on a path that already clones
    # the client's entire source history. Only when there will be a pack at all: with no checkout
    # there is nowhere to put it and nothing that would read it.
    bundle, bundle_gaps = _bundle_for(project, source=tmp) if cloned else (None, [])
    try:
        facts = pack.write_pack(tmp, floor=snapshot, board=_board_block(jobs), thread=thread,
                                comments=_comment_files(jobs), verdicts=_verdict_files(jobs),
                                diffs=_diff_files(jobs), gaps=_gaps(jobs) + bundle_gaps,
                                bundle=bundle) if cloned else None
    finally:
        # `write_pack` COPIED the bundle into the pack; what is left here is the temp checkout it
        # arrived in, and one of those per question fills the worker's disk.
        from openfactory.knowledge.pipeline import discard_fetched_bundle

        discard_fetched_bundle(bundle)
    if facts is not None:
        context = _guidance(can) + (
            "Current jobs (Temporal × what each is waiting on × the factory's own review and "
            "gates × the tracker's real ticket state × board column × title):\n") + snapshot + (
            "\n\n") + (facts / "README.md").read_text(encoding="utf-8") + (
            "\n\nThe repository is checked out at the workspace root — open files to verify.")
    else:
        context = ((thread + "\n\n") if thread else "") + _guidance(can) + (
            "Current jobs (Temporal × what each is waiting on × the factory's own review and "
            "gates × the tracker's real ticket state × board column × title):\n") + snapshot + (
            "\n\n") + comments + (
            "\n\nThe repository is checked out at the workspace root — open files to verify."
            if cloned else "\n\n(The repo could not be checked out — reason from the state above.)"
        )
    try:
        res = build_techlead(project).chat(
            sandbox=judging_worktree(project, root=tmp),
            workspace=Workspace(path=tmp, branch="main", base_branch="main"),
            question=question,
            context=context,
        )
        text = answer_text(res).strip()
        spend = _spent(res)
        _record_chat_spend(project, spend)
    except Exception as exc:  # noqa: BLE001 — the tech-lead must always reply, agent trouble or not
        log.exception("the tech-lead could not answer a question about %s",
                      getattr(project, "name", "?"))
        return Answer(f"Sorry — I couldn't work that out just now ({str(exc)[:120]}).")
    finally:
        # Every question clones the repository into a fresh tmp dir. Without this, each one leaks a
        # full checkout on the worker's finite disk until the task dies of a full volume.
        #
        # `scratch.discard`, NOT a bare rmtree: `clone_repo` is a seam, and a seam that hands back
        # a path this line will recursively delete has no floor. Three tests stubbed it with the
        # string "/tmp", so the suite ran `rmtree("/tmp")` — invisible on macOS, and on Linux it
        # deleted pytest's own temp root and failed 898 later tests (2026-08-21). See util/scratch.
        scratch.discard(tmp)

    if not text:
        return Answer("Sorry — I couldn't produce an answer for that one.", spend=spend)
    prose, suggestion = extract_suggestion(text, can=can)
    if cap is not None and len(prose) > cap:
        prose = prose[:cap].rstrip() + " …(truncated)"
    return Answer(prose, suggestion, spend=spend)




def _verb_block(verbs) -> str:
    """The actions this asker may propose, each with when to choose it and what it needs (#172).

    READ FROM THE CATALOGUE ROW rather than from a map beside this prompt. The map that used to
    live here answered the same question the catalogue answers — and disagreed with it: `adjust`
    was added to `proposable` in #170 and never added here, so the verb that most needed the
    guidance was the one described by two words.

    THE PARAMETERS ARE NAMED, which the old map could not do at all. `adjust` requires an
    `instruction`, and a model told only the verb's English composes whatever reads like a sentence
    — onto a button a human presses. `project` and `issue` are omitted because they are not a
    choice: this loop knows both, and listing them invites a proposal that restates them.
    """
    from openfactory import actions

    out = []
    for verb in verbs:
        spec = actions.CATALOG.get(verb)
        if spec is None:  # pragma: no cover — `proposable` only yields catalogue rows
            continue
        out.append(f"    · {verb}: {spec.choose_when or spec.summary}\n")
        for param in spec.required:
            if param in ("project", "issue"):
                continue
            out.append(f"        ‣ needs {param} — {spec.prose_for(param)}\n")
    return "".join(out)


def _board_block(jobs: list[dict]) -> str:
    """The board column each job's ticket sits in — the HUMAN's authoritative view."""
    rows = [f"- {j.get('issue') or '?'}: {j.get('board')}" for j in (jobs or []) if j.get("board")]
    return "# Board columns\n" + ("\n".join(rows) if rows else "- (no column was readable)")


def _comment_files(jobs: list[dict]) -> dict[str, str]:
    """One file per PARKED ticket's thread, keyed by its ref. Per TICKET, not per job — several
    runs of one ticket are several jobs, and `comment_digest` learned that the expensive way."""
    out: dict[str, str] = {}
    for job in (jobs or []):
        if not parked(job):
            continue
        ref = str(job.get("issue") or "")
        rows = job.get("comments")
        if not ref or ref in out or rows is None or not rows:
            continue
        out[ref] = f"# What has been said on {ref}\n\n" + render_comments(rows)
    return out


def _verdict_files(jobs: list[dict]) -> dict[str, str]:
    """One file per job that has a verdict — this platform's own review and gates."""
    out: dict[str, str] = {}
    for job in (jobs or []):
        ref = str(job.get("issue") or "")
        line = verdict_line(job)
        if ref and line and ref not in out:
            out[ref] = f"# The factory's own review of {ref}\n\n{line}\n"
    return out


def _diff_files(jobs: list[dict]) -> dict[str, str]:
    """One file per pull request at a human merge gate — the change itself (#171).

    AN EMPTY DIFF IS A FACT AND GETS ITS OWN SENTENCE. `""` means the platform looked and the pull
    request changes nothing, which is worth saying out loud: a reader handed no file resolves it as
    "I was not shown the diff", and that is the opposite conclusion.
    """
    out: dict[str, str] = {}
    for job in (jobs or []):
        ref = str(job.get("issue") or "")
        if not ref or ref in out or "diff" not in job:
            continue
        body = str(job.get("diff") or "")
        out[ref] = (f"# The changes in {ref}\n\n" + body) if body else (
            f"# The changes in {ref}\n\nThe platform read this pull request and it changes "
            f"NOTHING. This is a successful read of an empty diff, not a diff nobody fetched.\n")
    return out


def _gaps(jobs: list[dict]) -> list[str]:
    """Every fact the platform tried to read and could not — named, with the ref.

    THE HALF A DIRECTORY LISTING CANNOT CARRY. A missing `comments/87.md` reads exactly like a
    ticket nobody has commented on, and that is a claim about the client's ticket made from a read
    that failed. `comments_for` and `_verdicts` both return an option type precisely so this can be
    said out loud (UNREADABLE is not absence); a file tree is where that discipline would quietly
    break.
    """
    gaps: list[str] = []
    for job in (jobs or []):
        ref = str(job.get("issue") or "?")
        if parked(job) and job.get("comments") is None:
            gaps.append(f"the ticket thread for {ref} could not be read")
        if job.get("verdict_unread"):
            gaps.append(f"the review verdict for {ref} could not be read")
        if job.get("diff_unread"):
            gaps.append(f"the changes in {ref} could not be read — this is NOT 'no changes'")
    return gaps


#: What the tech-lead is shown when the bundle could not be fetched, worded like every other gap:
#: a failed read named as one. "This project has no knowledge bundle" is a claim about the client's
#: codebase, and it is not a claim a clone that never came back is entitled to make.
_BUNDLE_GAP = ("the project's knowledge bundle could not be read from its context repository — "
               "this is NOT 'this project has no knowledge bundle'")


def _bundle_for(project, *, source: Path | None = None) -> tuple[Path | None, list[str]]:
    """The published knowledge bundle for this project's source repo, and the gap a failed fetch
    leaves behind — or the gap a STALE bundle leaves behind, when there is a checkout to check it
    against.

    RE-VERIFIED AGAINST THE CHECKOUT THIS ROLE JUST CLONED, and this is the first place anything
    reads `ConceptSource.fingerprint` back (ADR-0045: two writers, zero readers, measured
    2026-09-04). This role is the one reader that holds BOTH halves at once — the bundle from the
    context repository and the source it describes — so it is where "the bytes moved, the concept
    is stale" can be a fact rather than a promise. `source` is optional only so a caller with no
    checkout is not lied to by a check that could not be made.

    A STALE BUNDLE IS KEPT AND NAMED, NOT DROPPED. The module map is thrown away whole when stale
    because it is regenerated in a quarter of a second; a concept cost a model call under a budget
    the project declared, and one moved file must not cost the tech-lead the other thirty-nine.
    The pack carries the bundle and its README names, by title, the concepts that no longer match
    — which is the gaps section doing exactly what it exists for.

    WHY THIS ROLE FETCHES IT AND THE PRODUCT ROLE DOES NOT. The context repository is already
    mounted for the product role, so the concepts are on its disk before it is asked anything.
    This one clones the SOURCE repository and nothing else, so the bundle has to be carried here —
    one shallow clone of a documents repository, on a path that already clones the client's whole
    source history.

    AN ABSENCE IS NOT A GAP, AND THIS IS WHY `fetch_bundle` EXISTS. A project with no context
    repository, and one whose backfill has simply never run, have nothing to report: every project
    is in that state until its first backfill, and a warning printed on all of them is a warning
    nobody reads. Only a read that FAILED comes back with words, and then it must be said — the
    tech-lead handed no `okf/` resolves it as "this codebase has no map", which is a claim
    produced by a failed read.

    NEVER RAISES, like everything else `answer()` stands on: a tech-lead that replies to a
    question with a traceback has not answered it.
    """
    from openfactory.adapters.forge.registry import clone_url_for
    from openfactory.credentials import deployment_forge_token, forge_token_for
    from openfactory.knowledge.pipeline import fetch_bundle, okf_subpath
    from openfactory.util.causes import scrubbed

    docs_repo = (getattr(getattr(project, "product", None), "docs_repo", "") or "").strip()
    repo = repo_of(project)
    if not docs_repo or not repo:
        # Nothing was attempted, so there is nothing to report: a project onboarded before context
        # repositories existed has no bundle to fail to read.
        return None, []
    token = ""
    try:
        # THE RUNTIME CREDENTIAL — `clone_repo`'s, never onboarding's. `onboard.py`'s own resolver
        # warns that the two can be different credentials with different repository visibility,
        # and this is a runtime read like every other on this path.
        token = forge_token_for(project) or deployment_forge_token(project) or ""
        # RESOLVING THE URL IS ITSELF FALLIBLE and is inside the guard for `clone_repo`'s reason:
        # the registry raises on a forge kind it does not know, and an answer lost to that
        # ValueError would be a worse trade than an answer without a map.
        got = fetch_bundle(clone_url_for(project, docs_repo, token=token),
                           subpath=okf_subpath(repo))
    except Exception as exc:  # noqa: BLE001 — a missing map costs the map, never the answer
        log.warning("could not reach the knowledge bundle for %s: %s",
                    getattr(project, "name", "?"),
                    scrubbed(_URL_CREDENTIAL.sub(r"\1***@", str(exc)), token))
        return None, [_BUNDLE_GAP]
    if got.unreadable:
        log.warning("the knowledge bundle for %s could not be read: %s",
                    getattr(project, "name", "?"), got.unreadable)
        return None, [_BUNDLE_GAP]
    if got.path is None or source is None:
        return got.path, []
    from openfactory.knowledge.check import check_concepts, stale_bundle_gap

    report = check_concepts(got.path, source)
    log.info("knowledge bundle for %s: %s", getattr(project, "name", "?"), report.summary())
    gap = stale_bundle_gap(report)
    return got.path, [gap] if gap else []


def _guidance(can: tuple[str, ...] = ()) -> str:
    """How the tech-lead is asked to answer, for an asker who may perform `can`.

    Prose, deliberately: this is the ROLE's instruction, and it lives beside the code that composes
    the context rather than in whichever front end happened to ask — which is how the two drift and
    one channel gets a different tech-lead from the other.

    COMPOSED RATHER THAN CONSTANT, because the constant version was WRONG about this platform. It
    ended with *"Only resume/skip on a parked job act from here; never suggest prod/merge
    actions"* — true when it was written, and false since #120 gave the chat a gated merge row that
    the panel's own button posts to. The pilot asked "pode fazer o merge" with the Merge button on
    screen and was told merge is not something the tech-lead does. A capability the product ships
    and its own instructions deny is worse than one it does not ship.

    So the vocabulary comes from `actions.proposable(by)` — the catalogue, filtered by the asker's
    credential — and the prod gate stays shut for the reason it always did: `approve_prod` is not
    addressable by a ticket ref and is not in any grammar a human types at the floor, so it can
    never appear in `can`. The rule is enforced by the catalogue now instead of by a sentence.
    """
    verbs = tuple(can) or _DEFAULT_PROPOSABLE
    return (
    "How to answer as the tech lead:\n"
    "- A job is PARKED only if its workflow shows as RUNNING/parked in the live state above. An "
    "on_hold or failed entry in run HISTORY is a finished attempt — do not call it a queue-holder "
    "and do not suggest resume/skip for it (the engine would refuse; the floor pill already says "
    "whether anything is held).\n"
    "- Reply in the SAME language the person asked in — if they wrote Portuguese, answer in "
    "Brazilian Portuguese. NEVER switch to another language (no Spanish).\n"
    "- Read what a HUMAN sees, not raw Temporal. Each job lists its Temporal state, its real "
    "TICKET state (from the tracker), and its BOARD column. The BOARD column is the authoritative "
    "human view — trust it over stale Temporal.\n"
    "- UNREADABLE is not a state. A line saying the ticket or the board could not be read means "
    "the provider did not answer — say so plainly if it matters to the question, and never treat "
    "it as open, closed, or empty.\n"
    "- READ THE COMMENT THREADS before you propose anything. Each parked ticket carries its last "
    "few comments, oldest first, with the author and the time. VERIFY them — a prior fix may be "
    "wrong, and it may be YOURS. Who wrote a comment changes what it is: a human's is an "
    "instruction and a constraint you must respect; the platform's own earlier note (a bot or app "
    "login, e.g. one ending in '[bot]') is a hypothesis to re-examine, not evidence. If the thread "
    "shows something has already been tried and failed, do not propose it again — say it was "
    "tried, and go further.\n"
    "- 'Comments UNREADABLE' means the tracker did not answer. It is NOT 'nobody has commented': "
    "never conclude from it that nobody has looked at the ticket, and say you could not see the "
    "history if it matters. Only tickets of PARKED jobs have threads here — a ticket with no "
    "thread was not asked about.\n"
    "- Three realities, don't confuse them: (a) ticket CLOSED but workflow still PARKED "
    "= ORPHANED (the job was left hanging, holding the floor) → recommend SKIP to clean it up; "
    "(b) ticket CLOSED and not parked = truly resolved → ignore; (c) ticket OPEN and parked = "
    "genuine work needing a human. Use its WAITING ON line to explain WHY.\n"
    "- A 'WAITING ON' line says what a job is stopped for, and it is the answer to most questions "
    "about that job. A job waiting on a person is NOT stuck and NOT failing — it is working "
    "exactly as designed, and the thing it is waiting for is named on that line, with the pull "
    "request's address when there is one. If somebody asks what to do about such a job, the "
    "answer is the named thing, not a diagnosis.\n"
    "- THE REVIEW AND GATES ON A JOB'S LINE ARE THIS PLATFORM'S OWN, not somebody else's opinion: "
    "an independent reviewer read the whole diff and the gates were run by the factory. Use them. "
    "Never say a change is 'waiting for review' when a review line is right there, and never "
    "guess at quality when the gates are printed. 'review: UNREADABLE' means the engine did not "
    "answer — it does NOT mean unreviewed, and it is not evidence of anything. "
    "'review: OUT OF DATE' means the diff was REWRITTEN after the reviewer read it, and EVERY "
    "clause marked 'was:' after it describes the OLD diff — findings, gates and gate-suppressions "
    "alike. You may not recommend discarding or reworking on their strength, and you may not "
    "report a 'was:' clause as something that is true of the pull request now. Say the review is "
    "stale, say what it USED to find, and send the person to the diff.\n"
    "- NEVER SEND SOMEBODY TO ASK FOR SOMETHING THIS PLATFORM CANNOT DO — advice nobody can take "
    "is worse than none. When the only reading you have is stale there are three honest options, "
    "and `review` is usually the first: it re-reads the pull request AS IT STANDS and REPLACES "
    "the stale verdict, changing no code. The other two are a person reading the diff, and a "
    "repair pass spent on a NAMED change. A re-review is a paid model pass, so offer it as a "
    "choice with that cost said out loud, never as a formality on a verdict that is current.\n"
    "- ALWAYS name each task by its TITLE, not just the number (the reader may be on mobile): "
    "e.g. '#69 Plan 88.1 — Spreadsheet import', never just '#69'.\n"
    "- WHAT YOU CAN ACTUALLY DO for the person asking, and it is only this list — an action that "
    "is not here is one their credential cannot perform, so offering it wastes their time:\n"
    + _verb_block(verbs)
    + "  Do not offer to do anything else on their behalf. You can still SAY what a person would "
    "have to do elsewhere — that is information, not an offer.\n"
    "- For anything GENUINELY needing a human, propose ONE concrete next action from that list "
    "and offer to do it. Choose by JUDGMENT, not reflex, and say what the choice rests on.\n"
    "- If EXACTLY ONE job clearly warrants one of those actions, end your message with a hidden "
    "tag on its own last line: [[SUGGEST <action> #NN]], using an action from the list above. "
    "The reader won't see it; it lets them reply 'ok' to have you do it. Only when you truly "
    "recommend it; at most one. A production release is never one of these.\n"
    # NO CONCRETE VERB IN THIS RULE, deliberately: it is composed into a block that must offer
    # only what the asker's own credential can perform, and an illustration naming `merge` to a
    # resume/skip asker is the very thing the block above forbids — measured by that guard, on
    # this line, minutes after it was written.
    "- NEVER SAY YOU HAVE DONE IT, OR THAT YOU ARE ABOUT TO. A suggestion is an OFFER waiting on "
    "one more word from the reader — nothing happens until they answer. 'I can do it, say the "
    "word' and 'shall I?' are true; 'I'll do it' and 'doing it now' are not. The reader closes "
    "the tab believing the gate is cleared and the job sits exactly where it was. Say what is "
    "true right now, and what you are offering to do next.\n"
    "- Be concise and honest; group into what's done, needs attention, and in flight.\n\n"
    )


def extract_suggestion(text: str, *,
                       can: tuple[str, ...] = ()) -> tuple[str, tuple[str, str] | None]:
    """`(prose with every tag removed, (action, ref) or None)`.

    The tag is how a free-text model hands back a concrete, approvable action; the reader never
    sees it — they just reply "ok". Anything `[[…]]`-shaped that did NOT parse is stripped too,
    and logged: posting a half-understood machine marker to a person is worse than losing it.

    `can` is the asker's own vocabulary — a tag naming an action they could not perform does not
    parse, so it is swept with the malformed ones rather than staged and refused a click later."""
    pattern = _suggest_re(can)
    m = pattern.search(text or "")
    suggestion = (m.group(1).lower(), m.group(2)) if m else None
    stripped = pattern.sub("", text or "")
    swept = _ANY_TAG_RE.sub("", stripped)
    if swept != stripped:
        log.warning("OPENFACTORY_TECHLEAD_LOST_TAG a malformed [[...]] tag was stripped instead of "
                    "posted")
    return swept.strip(), suggestion


def answer_text(res) -> str:
    """The agent's final free-text message, un-truncated. One shared reader (agent/base)."""
    from openfactory.adapters.agent.base import final_text

    return final_text(res)


# ── the evidence ────────────────────────────────────────────────────────────────────────────────

def parked(job: dict) -> bool:
    """Is this job waiting on a PERSON rather than working?

    ONE DEFINITION, because there are now two readers of it and they must agree. The snapshot uses
    it to reach the ORPHANED verdict, and `comments_for` uses it to decide which tickets are worth
    a provider round trip. Two spellings would mean a job the snapshot calls parked whose thread
    was never fetched — and the digest, which lists only parked jobs, would then be silently
    missing a ticket the model is being asked to judge. Absence reading as compliance is this
    codebase's cheapest way to lose an answer."""
    state = job.get("state") or job.get("status") or "unknown"
    return bool(job.get("attention")) or state in _PARKED_STATES


def waiting_on(job: dict) -> str:
    """What this job is waiting on, with the address of the thing to act on — or "".

    DERIVED FROM `action`, NEVER FROM A LIST OF STATES. The payload is what the panel paints its
    buttons from, so a job the panel shows `View PR · Merge · Discard` for is one this sentence
    describes; two readings of the same dict cannot disagree about which job is waiting.

    AND THE NOTE COMES FROM HERE TOO. `state_snapshot` read `job["note"]` and rendered its first
    line — except no row has ever carried a `note`: `view._row` does not set one and neither does
    `list_jobs`. The park reason lives INSIDE this payload, which nothing read. So the guidance
    telling the tech-lead to "use its park note to explain WHY" was pointing at a field that was
    always empty, on every job, on every question ever asked.
    """
    action = job.get("action") or {}
    if not isinstance(action, dict) or not action:
        return ""
    kind = str(action.get("kind") or "").strip()
    # The kind's own name when nobody has written prose for it — thin, never absent.
    what = _WAITING_ON.get(kind, kind or "something it did not name")
    out = f"WAITING ON {what}"
    url = str(action.get("pr_url") or "").strip()
    if url:
        out += f" ({url})"
    note = str(action.get("note") or "").strip()
    if note:
        out += f" — {note.splitlines()[0][:160]}"
    # A DECISION IS A QUESTION SOMEBODY WAS ASKED. Saying a job is parked without saying it asked
    # something is how a park reads as a failure.
    decision = action.get("decision") or {}
    if isinstance(decision, dict) and decision.get("question"):
        out += f" — it ASKED: {str(decision['question'])[:200]}"
    return out


def verdict_line(job: dict) -> str:
    """What the factory's OWN review and gates concluded about this job — or "".

    This is the read the tech-lead never made. Asked to merge, it answered that the pull request
    was "waiting for human review" and that a merge needed "somebody with GitHub access" — two
    confident claims about a job whose independent review had already scored the whole diff, and
    whose gate results were sitting in the same workflow.

    THE RENDERING MOVED (#149) to `openfactory/review/verdict.py`, and this is now the mapping onto
    it. It moved because the merge gate — the one screen where a person is actually deciding —
    showed none of this, and adding a second reading of the same dict beside the first is how two
    surfaces come to disagree about one review. One definition, renderers.
    """
    from openfactory.review import verdict as verdict_read

    if job.get("verdict_unread"):
        return verdict_read.line({}, unread=True)
    return verdict_read.line(job.get("verdict") or {})


def state_snapshot(jobs: list[dict]) -> str:
    """A compact text summary of a project's live jobs — one line each: issue · state · what it is
    WAITING ON · what the factory's own review and gates found · the board and ticket a human sees.
    Missing values are tolerated. An empty list becomes an explicit "no active jobs" so the agent
    does not confabulate work that is not there.

    EVERY FIELD A ROW CARRIES IS ACCOUNTED FOR — see `_RENDERED` and `_NOT_RENDERED`, and the guard
    that walks both against what `view.list_jobs` actually produces."""
    if not jobs:
        return "No jobs are currently tracked for this project."
    lines: list[str] = []
    for j in jobs:
        issue = j.get("issue") or j.get("workflow_id") or "?"
        state = j.get("state") or j.get("status") or "unknown"
        title = (j.get("title") or "").strip() or "(untitled)"
        ticket = j.get("ticket_state")  # the tracker's real ticket state: open | closed | None
        board = j.get("board")  # the HUMAN's authoritative view (Needs Action / In progress / …)
        waiting = parked(j)
        parts = [f"- #{issue} {title}: Temporal {state}"]
        if j.get("attention"):
            parts.append(" ⚠️needs-attention")
        # AN UNREADABLE PROVIDER IS SAID, NOT OMITTED. Both of these used to render as nothing at
        # all, and nothing is what a board with no card on it and a ticket nobody asked about also
        # render as — so the agent read "could not ask" as "open", or as "this project has no
        # board", and answered confidently from a hole. Absence is the one thing a failure must
        # never look like here, because this text is the whole of what the model gets to see.
        if board:
            parts.append(f" · board: {board}")
        elif j.get("board_unread"):
            parts.append(" · board: UNREADABLE (the board did not answer — not 'no column')")
        if ticket:
            parts.append(f" · ticket: {ticket}")
        elif j.get("ticket_unread"):
            parts.append(" · ticket: UNREADABLE (the tracker did not say — not 'open')")
        # Three distinct realities so the agent stops confusing them: (a) closed+still-parked = an
        # ORPHANED workflow (ticket done, job left hanging, holding the floor) → skip to clean up;
        # (b) closed+not-parked = resolved, ignore; (c) open+parked = genuine work for a human.
        # All three are gated on a state we actually READ; an unreadable ticket reaches none of
        # them, which is why they test for "closed" rather than for "not open".
        if ticket == "closed" and waiting:
            parts.append(" [ORPHANED: ticket closed but workflow still parked — skip to clean up]")
        elif ticket == "closed" and state not in ("merged", "done", "closed"):
            parts.append(" [likely resolved — ticket closed]")
        # THE DEPLOY OUTCOME, INCLUDING THE ONE IN FLIGHT. `deploying` matters as much as the
        # terminal ones: a job that merged four minutes ago is not a job whose deploy went missing,
        # and without this line the two are the same sentence.
        deploy = str(j.get("deploy") or "").strip()
        if deploy:
            parts.append(f" · deploy: {deploy}")
        if j.get("wedged"):
            # A JOB NOTHING CAN ADVANCE, and the one state where `stop` is the right answer. The
            # tech-lead has to be able to tell it from a job that is merely slow, or it proposes
            # terminating work that is progressing (#127).
            parts.append(" [WEDGED: running with no gate and no park for hours — nothing but "
                         "`stop` can advance it, and stopping does not resume]")
        for extra in (waiting_on(j), verdict_line(j)):
            if extra:
                parts.append(f"\n    {extra}")
        lines.append("".join(parts))
    return "\n".join(lines)


def tracker_for(project):
    """This project's tracker, carrying the TRACKER axis's own credential — or None.

    ONE PER ANSWER, BUILT ONCE AND PASSED DOWN. Every ticket read below is a question for the same
    object, and constructing one per question re-resolves the credential (and, where the deployment
    authenticates as a GitHub App, mints a fresh installation token) once per ticket.

    NONE RATHER THAN A RAISE, because the caller is the tech-lead: `answer()` promises never to
    answer a question with a traceback, and a registry row naming a tracker nobody implements is
    exactly the shape that would break that promise on the panel's hottest read."""
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.credentials import deployment_tracker_token, tracker_token_for

    try:
        return build_tracker(
            project, token=tracker_token_for(project) or deployment_tracker_token(project) or None)
    except Exception as exc:  # noqa: BLE001 — a bad provider row makes the answer thinner, not fatal
        log.warning("no tracker for %s (%s) — answering with no ticket state at all",
                    getattr(project, "name", "?"), exc)
        return None


#: How many DISTINCT tickets one answer reads, and how many at a time.
#:
#: THE BULK READ WAS A VENDOR FEATURE AND THIS TRADE IS DELIBERATE. `gh issue list --limit 300`
#: fetched a whole repository's issues in one request — cheap, and available on exactly one
#: provider. `TrackerAdapter` answers per ticket (`get_ticket`), so the read is now one request per
#: ticket the floor actually has: deduplicated first, because several runs of the same ticket are
#: several jobs and used to be several rows against one index, and capped, because this runs on
#: every operator question and the poller shares the same credential's rate limit.
#:
#: Past the cap a job simply renders without its real ticket state, and the snapshot SAYS
#: UNREADABLE rather than leaving a hole — see `state_snapshot`. A bulk `TrackerAdapter` read would
#: restore the single request for every provider; it does not exist yet and is reported, not
#: guessed at here.
_TICKET_READ_CAP = 30
_TICKET_READ_WORKERS = 6


def ticket_index(project, refs, *, tracker=None) -> dict[str, dict]:
    """The tracker's REAL state and title for each ref it answered for:
    `{"69": {"state": "closed", "title": "Plan 88.1 — Spreadsheet import…"}}`.

    THE OLD NAME WAS THE FINDING. This was `github_issue_index` and it shelled out to `gh issue
    list`, so a deployment whose tickets live on Azure Boards or Jira got `{}` on every question:
    no ticket state, no fresh title, and no error anywhere — the tech-lead simply said something
    vaguer. Cross-referencing the tracker is what lets it say what is REALLY happening, because a
    Temporal workflow sits in failed/pr_open long after the ticket was closed or merged.

    A MISSING KEY MEANS "COULD NOT ASK", NEVER "OPEN". The caller marks those jobs `ticket_unread`
    and the snapshot prints it, because this whole function's output is fed to a model that cannot
    tell an absent field from a negative answer.

    Best-effort per ref: one ticket the provider refuses does not cost the other twenty-nine."""
    wanted: list[str] = []
    seen: set[str] = set()
    for raw in refs:
        ref = str(raw or "").strip()
        if ref and ref not in seen:
            seen.add(ref)
            wanted.append(ref)
    if not wanted:
        return {}
    tracker = tracker_for(project) if tracker is None else tracker
    if tracker is None:
        return {}
    if len(wanted) > _TICKET_READ_CAP:
        log.warning("%s has %d distinct tickets on the floor — reading the first %d; the rest "
                    "will render as UNREADABLE rather than as open",
                    getattr(project, "name", "?"), len(wanted), _TICKET_READ_CAP)
        wanted = wanted[:_TICKET_READ_CAP]

    def _one(ref: str) -> tuple[str, dict | None]:
        try:
            ticket = tracker.get_ticket(ref)
        except Exception as exc:  # noqa: BLE001 — one ticket's failure is not the floor's
            log.info("could not read ticket %s on %s (%s) — it will be shown as UNREADABLE",
                     ref, getattr(project, "name", "?"), str(exc)[:160])
            return ref, None
        return ref, {"state": str(getattr(ticket, "state", "") or "").lower(),
                     "title": str(getattr(ticket, "title", "") or "").strip()}

    # THREADS BECAUSE THE PORT IS ONE-AT-A-TIME AND A PERSON IS WAITING. Both implementations spend
    # the whole call blocked on IO (a `gh` subprocess, an HTTPS request), so the pool is bounded by
    # politeness to the provider rather than by CPU. Sequentially this is thirty round trips in
    # front of an answer somebody asked for in a chat.
    with ThreadPoolExecutor(max_workers=min(_TICKET_READ_WORKERS, len(wanted))) as pool:
        return {ref: meta for ref, meta in pool.map(_one, wanted) if meta}


# ── the comment history, which is the answer to "has somebody already tried this?" ──────────────

#: How much CONVERSATION one answer reads, and what it costs.
#:
#: ONE PROVIDER ROUND TRIP PER TICKET, WITH A PERSON WAITING. `comments()` is a per-ticket read
#: like `get_ticket` — the port has no bulk form — so this is the SECOND N-request read inside one
#: answer, on the same credential the poller and every running job share, and a full board sweep
#: on that credential already exhausted this deployment's hourly quota once (2026-07-27). The
#: ticket index deduplicates and caps for exactly that reason and this matches its discipline, with
#: a tighter number for two reasons the index does not have:
#:
#:   · a thread costs hundreds of characters of PROMPT where a ticket state costs one word, and the
#:     prompt is the budget that actually binds here — the requests run six at a time, so eight of
#:     them is two waves, roughly one extra round trip of latency in a chat;
#:   · only PARKED tickets are worth it. A parked job is the one a person is asking about; a
#:     running job's thread answers a question nobody asked. A floor with more than eight jobs
#:     parked at once has a worse problem than a thin answer, and the ones past the cap are
#:     reported as unread rather than quietly dropped.
#:
#: Worst case: 8 × 3 × `_COMMENT_BODY_CHARS` ≈ 10k characters of context, ~2.5k tokens, on a
#: question a human asked and is waiting on.
_COMMENT_READ_CAP = 8
#: THREE, which is what this module read before the `gh` removal took the capability with it. The
#: number is not arbitrary: "has somebody already tried this?" is answered at the END of a thread,
#: and `comments(limit=N)` is defined to hand back the most recent N — still oldest-first, so what
#: arrives is the last three turns of the argument in the order they were made.
_COMMENTS_PER_TICKET = 3
#: Enough for a park note, a human's instruction, or a review verdict; short of a pasted stack
#: trace or a full HandOff markdown block, both of which this platform posts on tickets itself.
#: The cut is MARKED in the rendered text, because a model that cannot see a truncation reads the
#: missing tail as a comment that ended there.
_COMMENT_BODY_CHARS = 400


def comments_for(project, jobs, *, tracker=None) -> dict[str, list[TicketComment] | None]:
    """The last few comments on each PARKED job's ticket, keyed by the ref the job carries.

    WHAT CAME BACK (#97/#91). This function existed, read three comments per parked ticket through
    `gh issue view`, and was deleted rather than ported when the `gh` path came off — the port had
    no read side to port it TO. Its absence is why both prompts in this package carried a sentence
    apologising for a capability nobody had rebuilt.

    THE THREE ANSWERS A CALLER MUST BE ABLE TO TELL APART, and the only reason this returns a dict
    of options rather than a dict of lists:

        `[…]`      read, and this is what has been said
        `[]`       read, and nobody has commented — a FACT the answer may state
        `None`     not read (the tracker refused, or it was past the cap) — an obligation to SAY so

    Absent from the dict means the same as `None` to every consumer here, and `comment_digest`
    renders both as UNREADABLE. That is deliberate: the ticket a model is not shown a thread for is
    the one it will assume nobody has looked at.

    Best-effort per ref: one ticket the provider refuses does not cost the other seven."""
    wanted: list[str] = []
    seen: set[str] = set()
    for j in jobs or []:
        # The parked test comes FIRST, so a floor of fifty running jobs spends nothing at all here.
        if not parked(j):
            continue
        ref = str(j.get("issue") or "").strip()
        if ref and ref not in seen:
            seen.add(ref)
            wanted.append(ref)
    if not wanted:
        return {}
    tracker = tracker_for(project) if tracker is None else tracker
    if tracker is None:
        return {}

    threads: dict[str, list[TicketComment] | None] = {}
    if len(wanted) > _COMMENT_READ_CAP:
        log.warning("%s has %d parked tickets — reading the comments of the first %d; the rest "
                    "will render as UNREADABLE rather than as tickets nobody has commented on",
                    getattr(project, "name", "?"), len(wanted), _COMMENT_READ_CAP)
        # MARKED UNREAD, NOT DROPPED. A parked ticket missing from the digest is a ticket the model
        # reads as quiet, which is the exact confusion the option type exists to prevent — and the
        # cap is our decision, so it is the one kind of "could not read" this module owes an
        # explanation for. `None` is honest for it: nobody looked.
        for ref in wanted[_COMMENT_READ_CAP:]:
            threads[ref] = None
        wanted = wanted[:_COMMENT_READ_CAP]

    def _one(ref: str) -> tuple[str, list[TicketComment] | None]:
        try:
            got = tracker.comments(ref, limit=_COMMENTS_PER_TICKET)
        except Exception as exc:  # noqa: BLE001 — one thread's failure is not the floor's
            log.info("could not read the comments of %s on %s (%s) — they will be shown as "
                     "UNREADABLE, not as absent",
                     ref, getattr(project, "name", "?"), str(exc)[:160])
            return ref, None
        # THE PORT SAYS `None`; ANYTHING ELSE UNRECOGNISED IS ALSO NOT AN EMPTY THREAD. An adapter
        # that has not implemented this method at all raises above; one that answers some other
        # shape lands here, and reading that as "nobody has commented" is the same lie by a
        # different route.
        return ref, (list(got) if isinstance(got, list) else None)

    # Threads for the same reason `ticket_index` uses them: every one of these calls is blocked on
    # IO, and sequentially this is eight round trips in front of an answer somebody is waiting for.
    with ThreadPoolExecutor(max_workers=min(_TICKET_READ_WORKERS, len(wanted))) as pool:
        threads.update(dict(pool.map(_one, wanted)))
    return threads


def render_comments(comments, *, body_chars: int = _COMMENT_BODY_CHARS) -> str:
    """One thread as a CONVERSATION — who said what, when, in the order it was said.

    THE SHAPE IS THE POINT, and it is why `TicketComment` has three fields instead of being a list
    of strings. The tech-lead is being asked to tell a human's instruction (a constraint) from the
    platform's own earlier note (a hypothesis to re-examine), and a wall of undifferentiated text
    throws away the only thing that distinction can be made from. `author` is already the LEGIBLE
    identity per provider — a GitHub login, a Jira displayName, an Azure `uniqueName` — chosen by
    the port precisely so this line does not put a GUID in front of a model.

    BODIES ARE INDENTED, which is not decoration: a comment is markdown that a person or this
    platform wrote, and it can contain a line that looks exactly like the `[when] who:` header
    above it — the park comments this factory posts are full of bracketed prefixes. The indent is
    what stops a quoted note from reading as a fourth commenter.

    Tolerant of a missing field on purpose: this runs on the path that answers a person, outside
    the guard that catches agent trouble, and `answer()` never raises."""
    blocks: list[str] = []
    for c in comments:
        who = str(getattr(c, "author", "") or "").strip() or "(author not given)"
        when = str(getattr(c, "created_at", "") or "").strip() or "(undated)"
        body = str(getattr(c, "body", "") or "").strip()
        if len(body) > body_chars:
            body = body[:body_chars].rstrip() + " …(comment truncated)"
        lines = "\n".join(f"  {line}" for line in body.splitlines()) if body else "  (empty)"
        blocks.append(f"[{when}] {who}:\n{lines}")
    return "\n".join(blocks)


def comment_digest(jobs) -> str:
    """What has already been SAID on each parked ticket — the section of the prompt that replaced
    an apology.

    A PURE FUNCTION OVER WHAT `gather_jobs` ALREADY READ. Every provider call was made and caught
    there; this only renders, because `_answer` calls it outside the try that guards the agent and
    a tech-lead that answers with a traceback has not answered.

    THREE OUTCOMES, THREE SENTENCES, and the third is the whole reason the port returns an option
    type: a thread that could not be read must not render as a ticket nobody has commented on. The
    header says out loud that only parked tickets were asked about, because a reader — human or
    model — resolves a missing section the same way it resolves an empty one.

    ONE BLOCK PER TICKET, NOT PER JOB, and that is not tidiness — it is the same fact `ticket_index`
    deduplicates for: several runs of one ticket are several jobs. Found by driving this against
    the live GitHub board, where a floor with two parked runs of #81 rendered the whole thread
    twice, the second time under `(untitled)` because the older job carried no title. That is a
    doubled prompt bill on the most expensive section here, and worse than the cost: to a model,
    two headers with identical conversations under them read as two tickets somebody is having the
    same argument on."""
    waiting = [j for j in (jobs or []) if parked(j)]
    if not waiting:
        # NOT "no job is parked" — THAT IS A CLAIM ABOUT THE FLOOR, MADE FROM A READ THAT MAY HAVE
        # FAILED. `gather_jobs` answers `[]` both for a project with nothing running and for a
        # Temporal it could not reach, which is why `_answer` appends "(Note: live job state may be
        # incomplete…)" to the snapshot directly above this line. Asserting an idle floor here
        # contradicted that hedge in the very next paragraph, from the same unread read — this
        # card's own rule (an unreadable read is not an empty one) violated one layer up, in the
        # section added to enforce it. The sentence now describes the LIST, which is a thing this
        # function can actually see, and names the case where the list itself is not evidence.
        return ("Ticket comments: nothing in the job list above is parked, so no comment thread "
                "was read. If that list could not be read, this is not evidence that the floor is "
                "quiet. Either way it says NOTHING about whether any ticket has comments — none "
                "were asked.")
    # Merged rather than first-wins: the runs of one ticket do not all carry the same fields, so
    # the title comes from whichever job HAS one and the thread from whichever job was enriched.
    # `gather_jobs` hangs the same list on every job with that ref, so there is no choice to make
    # between two different answers — only between an answer and a hole.
    tickets: dict[str, tuple[str, object]] = {}
    for j in waiting:
        ref = str(j.get("issue") or "").strip() or "?"
        title, thread = tickets.get(ref, ("", None))
        tickets[ref] = ((j.get("title") or "").strip() or title,
                        j.get("comments") if isinstance(j.get("comments"), list) else thread)
    blocks = [
        f"Ticket comments — the last {_COMMENTS_PER_TICKET} on each PARKED ticket, OLDEST FIRST, "
        "with who wrote each one and when. Only parked tickets are read: a ticket absent from this "
        "list was NOT asked about, which is not the same as one that has no comments."
    ]
    for ref, (name, thread) in tickets.items():
        head = f"--- #{ref} {name or '(untitled)'} ---"
        if isinstance(thread, list) and thread:
            blocks.append(f"{head}\n{render_comments(thread)}")
        elif isinstance(thread, list):
            blocks.append(f"{head}\n(The tracker answered: this ticket has NO comments — nobody "
                          "has commented on it.)")
        else:
            blocks.append(f"{head}\n(Comments UNREADABLE — the tracker did not answer, or was not "
                          "asked. This is NOT 'nobody has commented': conclude nothing about "
                          "whether anyone has looked at this ticket, and say you could not see the "
                          "history if it bears on the question.)")
    return "\n\n".join(blocks)


def board_index(project) -> dict[str, str] | None:
    """The BOARD column of every issue, keyed by ref: `{"416": "Needs Action"}`.

    The board is the HUMAN's authoritative view of state and priority — more trustworthy than raw
    Temporal, which goes stale.

    ONE PAGINATED QUERY, not one request per card. This runs on every operator question, and it
    used to shell out to `gh project item-list`, which the CLI implements as a request PER CARD:
    303 GraphQL points on a 256-card board, measured 2026-07-28. Three separate doors read this
    board — the poller, the product role and this one — and this was the third, found by the cost
    guard rather than by looking.

    `None` = COULD NOT READ, `{}` = this project has no board (a supported shape) or the board is
    genuinely empty. `BoardAdapter.columns()` draws that line and its own docstring names the three
    bugs that came from collapsing it; this function then collapsed it again, one layer up, and
    said in a comment that *"the caller renders 'board unknown'"* — which the caller did not do,
    because it was handed `{}` and had nothing left to tell it apart from an empty board."""
    from openfactory.adapters.board import build_board

    # THE BOARD IS A TRACKER OBJECT, so it takes the TRACKER's credential — this read the forge's,
    # which happened to work only while one vendor filled both axes. On an Azure Boards + GitHub
    # Repos deployment (the split ADR-0001 exists to allow) it sends a github.com token to
    # dev.azure.com and reads a 401 that looks like a revoked credential.
    from openfactory.credentials import deployment_tracker_token, tracker_token_for

    try:
        board = build_board(project,
                            token=tracker_token_for(project)
                            or deployment_tracker_token(project) or None)
    except ValueError as exc:
        # A registry row naming a board nobody implements is unreadable, not absent.
        log.warning("board misconfigured for %s: %s", getattr(project, "name", "?"), exc)
        return None
    if board is None:
        return {}  # no board configured — a supported deployment shape, not a failure
    columns = board.columns()
    if columns is None:
        log.warning("could not read the board for %s — every job will say so rather than "
                    "silently losing its column", getattr(project, "name", "?"))
        return None
    return {str(n): col for n, col in columns.items() if col}


#: At most this many jobs are asked what their review and gates found. Each is one query RPC, and
#: a CLOSED workflow answers it by replaying its history on a worker — real cost, per question.
#: Bounded here, and `_verdicts` LOGS when the bound bites, because a cap nobody can see reads as
#: "we looked at everything" (`the-dropped-findings-hide-blockers`).
_VERDICT_READ_CAP = 8


def _worth_a_verdict(job: dict) -> int:
    """How much this job's own verdict changes what somebody does — higher is asked first.

    The ordering IS the cap's policy: a floor with twenty jobs spends its eight reads on the ones
    a person is deciding about, not on the twenty-first thing that merged last week."""
    kind = (job.get("action") or {}).get("kind") if isinstance(job.get("action"), dict) else None
    if kind == _MERGE_WAIT_KIND:
        return 3  # somebody is deciding whether to land this RIGHT NOW
    if parked(job):
        return 2  # it stopped, and the gates are usually why
    if (job.get("state") or "") in ("pr_open", "merged"):
        return 1
    return 0


async def _verdicts(client, jobs: list[dict]) -> dict[str, dict]:
    """`ref → verdict` for the jobs worth asking — `{}` for one that measured nothing, and the
    ref ABSENT when it was not asked at all (#121).

    A FAILED READ IS ITS OWN ANSWER and the caller renders it as UNREADABLE. This module's whole
    posture is that a provider that did not answer must never look like a provider that said "no":
    the ticket read pays for that lesson, the board read pays for it, and a verdict is the one
    somebody will act on hardest — telling a person the review found nothing when the query simply
    failed is how a rejected pull request gets merged on our own advice.
    """
    import asyncio

    from openfactory.runtime.temporal.workflow import JobWorkflow

    ranked = sorted(((_worth_a_verdict(j), i, j) for i, j in enumerate(jobs)),
                    key=lambda t: (-t[0], t[1]))
    wanted = [j for score, _i, j in ranked if score > 0][:_VERDICT_READ_CAP]
    dropped = len([1 for score, _i, _j in ranked if score > 0]) - len(wanted)
    if dropped:
        log.info("%d job(s) past the verdict-read cap of %d were not asked what their review "
                 "found — the answer is thinner for them", dropped, _VERDICT_READ_CAP)

    async def one(job: dict) -> tuple[str, dict | None]:
        ref = str(job.get("issue") or "").strip()
        try:
            handle = client.get_workflow_handle(job["workflow_id"], run_id=job.get("run_id"))
            got = await handle.query(JobWorkflow.verdict)
        except Exception as exc:  # noqa: BLE001 — one unreadable job is not all of them
            # A workflow started before this query existed answers with a "query not registered"
            # error, which is genuinely "could not read" and is rendered as such. It resolves
            # itself the moment that job runs on a worker carrying this code.
            log.info("could not read the verdict for %s (%s)",
                     job.get("workflow_id"), str(exc)[:120])
            return ref, None
        return ref, (got if isinstance(got, dict) else {})

    out: dict[str, dict] = {}
    for ref, got in await asyncio.gather(*(one(j) for j in wanted if j.get("workflow_id"))):
        if not ref:
            continue
        # `None` travels as the UNREADABLE marker; the caller turns it into a job field, because
        # a dict cannot hold both "asked and empty" and "could not ask" under one key.
        out[ref] = got if got is not None else {"__unread__": True}
    return out


def gather_jobs(project) -> list[dict]:
    """This project's live jobs, each ENRICHED with what a human sees: the ticket's real state and
    title from the TRACKER, its BOARD column, and what the factory's own review and gates found.

    Reuses `temporal/view.list_jobs`, the same read the panel does. Returns `[]` when Temporal is
    unreachable; the caller says so rather than presenting an empty floor as a quiet one."""
    import asyncio

    async def _run() -> tuple[list[dict], dict[str, dict]]:
        from openfactory.runtime.temporal.connection import namespace
        from openfactory.runtime.temporal.view import connect, list_jobs

        client = await connect()
        rows = await list_jobs(client, namespace(), limit=50)
        mine = [r for r in rows if r.get("project") == project.name]
        # ONE CONNECTION FOR BOTH READS. The verdict query needs the same client the listing used,
        # so it happens here rather than in a second `asyncio.run` that would re-resolve the
        # engine's address and re-authenticate once per question.
        try:
            return mine, await _verdicts(client, mine)
        except Exception as exc:  # noqa: BLE001 — the listing is worth having without the verdicts
            log.warning("could not read what the reviews found for %s (%s) — the jobs answer "
                        "without them", getattr(project, "name", "?"), exc)
            return mine, {}

    try:
        jobs, verdicts = asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 — a Temporal hiccup must not sink the answer
        log.warning("could not read job state for %s: %s", getattr(project, "name", "?"), exc)
        return []

    # THE TWO READS ARE INSIDE A GUARD AND THE TEMPORAL READ IS ITS OWN. `answer()` calls this
    # OUTSIDE the try that catches agent trouble, so anything escaping here answers a person's
    # question with a traceback. Each read below already degrades on its own; this is the net that
    # keeps the module's headline promise true by construction rather than by the sum of three
    # other functions continuing to behave.
    #
    # AND THE NET ITSELF USED TO OPEN A HOLE, WHICH IS WHY THE MARKING LOOP IS OUTSIDE IT. The loop
    # lived inside this try, so anything escaping either read skipped it — and every job then
    # rendered with no `ticket:` and no `board:` segment at all, which is precisely the absence this
    # module was rewritten to stop producing, restored one layer above the two functions that were
    # carefully taught not to produce it. Reachable rather than theoretical: `board_index` converts
    # only ValueError, deliberately, so a `build_board` that raises anything else (a credential
    # provider, a client constructor) landed exactly there — the tech-lead answering from a hole,
    # confidently, with the only evidence in a log line no model reads.
    #
    # So the two reads are SEEDED with this module's own words for "could not read" — `{}` from
    # `ticket_index`, `None` from `board_index` — and the loop runs unconditionally, which turns
    # both into an UNREADABLE line. It touches no IO and reads only the dicts above, so putting it
    # outside the guard costs nothing it was protecting.
    refs = [str(j.get("issue")).strip() for j in jobs if j.get("issue")]
    index: dict[str, dict] = {}
    board: dict[str, str] | None = None
    threads: dict[str, list[TicketComment] | None] = {}
    try:
        tracker = tracker_for(project)
        # ORDER MATTERS TO THE FAILURE, not just to the reads: `index` is already bound when the
        # board read runs, so a board that explodes costs the COLUMN and not the ticket states that
        # were read successfully a line earlier. The comment read comes last for the same reason
        # and one more: it is the most expensive of the three per line of answer it buys, so it is
        # the one that should be paying for itself rather than costing the other two.
        #
        # THE SAME TRACKER OBJECT, built once above and handed to both reads. Constructing a second
        # one re-resolves the credential and, on a GitHub App deployment, mints a fresh
        # installation token — per answer, for nothing.
        index = ticket_index(project, refs, tracker=tracker)
        board = board_index(project)
        threads = comments_for(project, jobs, tracker=tracker)
    except Exception as exc:  # noqa: BLE001 — un-enriched jobs beat no answer at all
        log.warning("could not enrich %s's jobs with tracker/board state (%s) — answering from "
                    "Temporal alone, with every job marked UNREADABLE rather than rendered as a "
                    "job that has no ticket and no column", getattr(project, "name", "?"), exc)
    for j in jobs:
        num = str(j.get("issue") or "").strip()
        meta = index.get(num)
        if meta and meta["state"]:
            j["ticket_state"] = meta["state"]
        elif num:
            # NOT "open". The snapshot prints this; see `state_snapshot`.
            #
            # A TICKET THAT CAME BACK WITHOUT A STATE LANDS HERE TOO. `Ticket.state` is
            # `str | None` and the contract says None means the provider was not asked — the
            # three trackers that exist all fill it, so `if meta:` alone would have been right
            # today and silently wrong for the fourth. Written this way because the field's own
            # docstring records what the last version of this mistake cost: a `getattr(ticket,
            # "state", "open")` that answered "open" for ever.
            j["ticket_unread"] = True
        if meta and meta["title"]:
            j["title"] = meta["title"]
        if board is None:
            j["board_unread"] = True
        elif num in board:
            j["board"] = board[num]
        # ONLY A LIST IS CARRIED FORWARD. `None` (refused, or past the cap) and a ref that was
        # never asked about are both left ABSENT, and `comment_digest` renders absence on a parked
        # job as UNREADABLE — so the failure mode of this line is "the model is told we did not
        # look", never "the model is shown a quiet ticket". `[]` is a list and does travel: it is
        # the tracker saying nobody has commented, which is a fact worth having.
        thread = threads.get(num)
        if isinstance(thread, list):
            j["comments"] = thread
        # THREE ANSWERS AGAIN — asked and told, asked and could not read, never asked. Only the
        # first two produce a line; a job nobody asked about says nothing, which is honest.
        got = verdicts.get(num)
        if got is not None:
            if got.get("__unread__"):
                j["verdict_unread"] = True
            elif got:
                j["verdict"] = got
    _attach_diffs(project, jobs)
    return jobs


#: How much of a pull request's own changes travels. A large diff dwarfs every other fact in the
#: pack — and this is the one read that is bounded by somebody else's habits, not ours.
_DIFF_CHARS = 60000


def _attach_diffs(project, jobs: list[dict]) -> None:
    """The changes of every job sitting at a HUMAN merge gate (#171).

    AT THE GATE ONLY, because that is the question this is for: "can I merge this?" asked about a
    change the tech-lead has never seen. Fetching for every job would be one provider call per job
    per question, on a credential this deployment has exhausted before.

    THREE ANSWERS AGAIN, like every read in this module. `None` from the port is "I could not
    look"; `""` is "there is nothing there"; a string is the change. They are recorded separately
    because a reader resolves a missing diff and an empty one the same way, and one of those two
    readings is a claim about somebody's pull request made from a read that failed.
    """
    at_the_gate = [j for j in (jobs or [])
                   if (j.get("action") or {}).get("kind") == _MERGE_WAIT_KIND
                   and (j.get("action") or {}).get("pr_url")]
    if not at_the_gate:
        return
    try:
        from openfactory.adapters.forge.registry import build_forge
        from openfactory.credentials import deployment_forge_token, forge_token_for

        # THE FORGE AXIS'S OWN CREDENTIAL, exactly as `tracker_for` does one function up — and
        # this line is here because the first version omitted it and every read on the pilot came
        # back None. The option type was doing its job (it said "could not look" rather than
        # claiming an empty diff), which is the only reason the mistake was visible at all: a
        # collapsed answer would have reported every pull request as changing nothing.
        forge = build_forge(project,
                            token=forge_token_for(project)
                            or deployment_forge_token(project) or None)
    except Exception as exc:  # noqa: BLE001 — no forge is a poorer answer, never a failed one
        log.warning("no forge to read pull requests with for %s (%s)",
                    getattr(project, "name", "?"), str(exc)[:160])
        for job in at_the_gate:
            job["diff_unread"] = True
        return
    for job in at_the_gate:
        pr_url = str((job.get("action") or {}).get("pr_url") or "")
        try:
            got = forge.pr_diff(pr=pr_url, max_chars=_DIFF_CHARS)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not read the diff of %s (%s)", pr_url, str(exc)[:160])
            got = None
        if got is None:
            job["diff_unread"] = True
        else:
            job["diff"] = got


#: The `user:secret@` half of an authenticated HTTPS URL. Same expression the forge adapters and
#: the knowledge pipeline already carry, and it is here for the reason THEY have it: the credential
#: in a clone URL is not always one this module chose. `clone_url_for` lets the ADAPTER's own token
#: win over the caller's — deliberately, because every call site hands the forge axis a GitHub
#: credential and the Azure row refuses it — so the string that comes back may carry a secret this
#: function has never seen and could not pass to `scrubbed()`.
_URL_CREDENTIAL = re.compile(r"(https://)[^@/\s]+@")


def clone_repo(project) -> tuple[Path, bool]:
    """Shallow-clone the project repo into a fresh tmp dir so the agent can Read/Grep/Glob real
    code when the question needs it. Best-effort: returns `(tmp_dir, cloned?)` — on any failure
    `cloned` is False and the agent reasons from the state snapshot alone, never crashing.

    THE URL COMES FROM THE FORGE REGISTRY, not from this file. It used to be an f-string ending in
    `@github.com/<repo>.git`, which on an Azure Repos project is a 404 for a repository that exists
    — and 404 sends whoever reads the log looking for a permissions problem. Azure DevOps also
    nests one level deeper (`/{project}/_git/`), so there is no host swap that would have fixed it:
    the shape of a clone URL is knowledge only the adapter has."""
    from openfactory.adapters.forge.registry import clone_url_for
    from openfactory.credentials import deployment_forge_token, forge_token_for
    from openfactory.util.causes import scrubbed

    tmp = Path(tempfile.mkdtemp(prefix="openfactory-techlead-"))
    repo = repo_of(project)
    if not repo:
        return tmp, False
    # PER PROJECT: one deployment hosts N projects and they no longer share a forge, so the
    # process-wide `forge_token()` handed an Azure project the deployment's GitHub PAT.
    token = forge_token_for(project) or deployment_forge_token(project) or ""
    try:
        # RESOLVING THE URL IS ITSELF FALLIBLE, and inside the guard for that reason: the registry
        # RAISES on a forge kind it does not know, correctly, and a tech-lead that answered a
        # question with that ValueError would have traded a thin answer for no answer.
        url = clone_url_for(project, repo, token=token)
        subprocess.run(["git", "clone", "--depth", "1", url, str(tmp)],
                       check=True, capture_output=True, timeout=120)
        # SCRUB THE CREDENTIAL: the clone URL (with the token) is persisted in .git/config, and
        # the read-only chat agent CAN read that file — a prompt-injected question could exfiltrate
        # a live token into whatever channel asked. The checkout never pushes or fetches again, so
        # rewrite the remote to the tokenless URL. Derived from the URL we actually used rather
        # than rebuilt: asking the registry for a second, token-free URL would not give one — the
        # Azure row mints its credential from a provider, so `token=None` still comes back signed.
        subprocess.run(["git", "-C", str(tmp), "remote", "set-url", "origin",
                        _URL_CREDENTIAL.sub(r"\1", url)],
                       capture_output=True, timeout=15)
        return tmp, True
    except Exception as exc:  # noqa: BLE001 — degrade to reasoning without the checkout
        # REDACT, THEN TRUNCATE. A CalledProcessError embeds the whole tokened clone URL and the
        # secret sits well inside the first 120 characters. The regex goes first because it catches
        # a credential the adapter minted and we never held; `scrubbed` then also covers the one we
        # passed, in case a provider spells its URL in some shape the pattern misses.
        log.warning("could not clone %s for %s: %s", repo, getattr(project, "name", "?"),
                    scrubbed(_URL_CREDENTIAL.sub(r"\1***@", str(exc)), token))
        return tmp, False
