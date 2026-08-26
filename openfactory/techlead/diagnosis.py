"""Why a job parked, and what would move it — the capability, with no publishing in it (C-23/#53).

WHAT MOVED AND WHY THE SPLIT IS THE POINT. This lived inside `activities._do_diagnose`, which both
PRODUCED a diagnosis and PUBLISHED it — a ticket comment plus a channel notice — in one function
reachable from exactly one place: the impediment path a workflow takes on its way to parking.

So the tech-lead could explain a failure the moment it happened and never again. A human looking at
a job that parked yesterday could not ask for the same analysis from anywhere, which is the gap
`openfactory-tech-lead-layer-gap` describes and the reason `diagnose` sat in the action catalog as a
row
that refused.

Producing and publishing are separated here because they have different callers and different
failure rules. The impediment path must publish, because nobody is watching. An operator asking
`diagnose` from the panel must NOT: they are looking at the answer, and posting a duplicate comment
on the ticket every time somebody asks is how a ticket becomes unreadable.

BEST-EFFORT, ALWAYS. Every input is optional — the ticket text, the checkout — and each one missing
makes the answer thinner than it reads, which is worth a log line. `None` is the honest result when
the handoff cannot be read at all; the caller still has the raw note.

AND NO VENDOR IN IT EITHER (#91). Both remaining reads named GitHub: the prior comments came from
`gh issue view` and the checkout was built as `https://…@github.com/<repo>.git`, each carrying the
process-wide FORGE credential. On the Azure deployment that exists as of today the diagnosis
therefore ran with no ticket comments and no code — and it still produced a confident HandOff,
because every input here is optional by design. The checkout now goes through
`forge.registry.clone_url_for`, and the ticket through `TrackerAdapter`, which it already did.

THE COMMENTS CAME BACK THROUGH THE PORT (#97). They were the casualty of that migration: `gh` was
removed, `TrackerAdapter` had no read side, so the four-comment read was DELETED and the prompt
was given a sentence saying the history *"is NOT available to you"* — honest, and the direct cause
of this role's worst failure mode, which is proposing with total confidence the fix the last
person already tried. `TrackerAdapter.comments()` exists now on every vendor, so the sentence is
gone and the thread is here, WITH its authors: the model has to weigh a human's instruction
against this platform's own earlier note, and it cannot do that from a list of bodies. When the
read fails it is told that in those words — `None` is "I could not look", never "nobody spoke".
"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from pathlib import Path

from openfactory.adapters.forge.registry import repo_of
from openfactory.util import scratch

log = logging.getLogger("openfactory.techlead")


def diagnose(project, *, issue: str, state: str = "", note: str = "", tracker=None):
    """The tech-lead's `HandOff` for a parked job, or None when it could not produce a readable one.

    Publishes NOTHING. The caller decides who should see it — see the module docstring."""
    from openfactory.adapters.agent import build_techlead
    from openfactory.adapters.sandbox.base import Workspace
    from openfactory.adapters.sandbox.registry import judging_worktree
    from openfactory.contracts import parse_handoff

    num = str(issue or "").lstrip("#")
    ref = f"#{num}"
    situation = _situation(project, issue=issue, state=state, note=note, tracker=tracker)
    tmp, cloned = _checkout(project, ref)
    situation += (
        "The repository is checked out at the workspace root — OPEN the relevant files and "
        "verify what actually happened before concluding.\n\n" if cloned else
        "(The repo could not be checked out — reason from the failure + ticket.)\n\n"
    ) + "Produce your HandOff json."
    try:
        res = build_techlead(project).diagnose(
            sandbox=judging_worktree(project, root=tmp),
            workspace=Workspace(path=tmp, branch="main", base_branch="main"),
            situation=situation)
        # `issue=num`: any suggested command must target THIS ticket, or it is dropped — an
        # operator is never instructed, in the factory's voice, to act on a hallucinated ref.
        return parse_handoff(_final_text(res), issue=num)
    except Exception as exc:  # noqa: BLE001 — an unreadable handoff is no handoff
        log.warning("the tech-lead's diagnosis of %s could not be read (%s)", ref, str(exc)[:120])
        return None
    finally:
        # The throwaway checkout served its purpose — without this every diagnosis leaks a full
        # clone on the worker's finite disk. `scratch.discard` rather than a bare rmtree, for the
        # reason written at the twin of this line in `conversation.py`: the path arrives from a
        # seam, and this one deletes recursively.
        scratch.discard(tmp)


#: How many of a ticket's comments the diagnosis reads. FOUR, which is what it read before the
#: `gh` removal deleted the capability, and one more than the conversation's three because the
#: budgets are different: `answer()` reads up to eight threads with a person waiting on the reply,
#: while this reads exactly ONE, on the impediment path, where the job has already stopped and
#: nobody is watching a clock. `comments(limit=N)` gives the most recent N, still oldest first —
#: the end of the argument, in the order it was made.
_COMMENTS_READ = 4


def _situation(project, *, issue: str, state: str, note: str, tracker=None) -> str:
    """Everything the tech-lead is told before it opens a file."""
    num = str(issue or "").lstrip("#")
    ref = f"#{num}"
    parts = [f"A job PARKED on an impediment (state={state}) on ticket {ref} and needs a human.\n\n"
             f"Raw failure / note:\n{note}\n\n"]
    # ONE TRACKER FOR BOTH READS. The build resolves a credential and, on a GitHub App deployment,
    # mints an installation token; doing it twice in one diagnosis pays that twice for the same
    # answer. It moved up here out of `_ticket_text` when the second read arrived — a helper that
    # builds its own client is fine until there are two of them.
    if tracker is None:
        tracker = _tracker(project)
    ticket = _ticket_text(issue, ref, tracker=tracker)
    if ticket:
        parts.append(f"{ticket}\n\n")
    parts.append(_comment_history(issue, ref, tracker=tracker))
    return "".join(parts)


def _tracker(project):
    """This project's tracker WITH A CREDENTIAL, or None.

    This was `build_tracker(project)` — no token at all — and the worker has no ambient tracker
    auth, only what the deployment configures, so the read failed every time and the diagnosis ran
    WITHOUT the ticket text on the one path that does not pass a tracker in
    (`actions/catalog.py::_diagnose`, the operator asking for one from the panel). Its own `except`
    then logged the miss at WARNING and produced a HandOff anyway, which is why nothing ever
    surfaced it.

    None rather than a raise: every input to a diagnosis is optional by design, and the caller
    still has the raw failure note."""
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.credentials import deployment_tracker_token, tracker_token_for

    try:
        return build_tracker(
            project, token=tracker_token_for(project) or deployment_tracker_token(project) or None)
    except Exception as exc:  # noqa: BLE001 — a bad provider row makes the diagnosis thinner
        log.warning("no tracker for %s (%s) — diagnosing from the failure note alone",
                    getattr(project, "name", "?"), str(exc)[:160])
        return None


def _ticket_text(issue: str, ref: str, *, tracker=None) -> str:
    try:
        t = tracker.get_ticket(issue)
        body = getattr(t, "body", "") or getattr(t, "objective", "") or ""
        return f"Ticket {ref}: {t.title}\n\n{body[:2000]}"
    except Exception:  # noqa: BLE001 — context is a bonus, never worth failing the diagnosis
        # The diagnosis proceeds WITHOUT the ticket text, which usually makes it vaguer than it
        # looks — worth knowing when the answer reads thin. `tracker=None` (a provider row nobody
        # implements) lands here too, deliberately: there is one branch for "I could not read it",
        # whatever the reason, and it is the branch that says so.
        log.warning("diagnosing %s without its ticket text", ref)
        return ""


def _comment_history(issue: str, ref: str, *, tracker=None) -> str:
    """The prior take on this ticket — the section that used to be an apology.

    WHAT IT IS FOR. This role's failure mode is confidently proposing the fix somebody already
    tried; the comments are the only evidence that they did. It read the last four through `gh
    issue view`, on one provider, and when `gh` came off the path the capability was DELETED rather
    than ported — the port had no read side — and replaced with a sentence saying the history *"is
    NOT available to you"*. That sentence was honest and is now false (#97).

    WHO WROTE WHAT SURVIVES INTO THE PROMPT, because the model is being asked to weigh a human's
    instruction (a constraint) against the platform's own earlier note (a hypothesis, possibly the
    very fix that failed and put this job here). `render_comments` is shared with
    `techlead/conversation.py` deliberately: this is ONE role wearing two hats, and two spellings
    of "who said what" is how one of them quietly loses the author.

    AND `None` IS SAID OUT LOUD. An unreadable thread and an empty one produce the same silence in
    a prompt, and a model resolves both the same way — nobody has looked at this — which is exactly
    the wrong conclusion on a ticket three people have been arguing about."""
    from openfactory.techlead.conversation import render_comments

    try:
        found = tracker.comments(issue, limit=_COMMENTS_READ)
    except Exception as exc:  # noqa: BLE001 — an unread thread is a thinner diagnosis, not a failure
        log.warning("diagnosing %s without its comment history (%s)", ref, str(exc)[:160])
        found = None
    if not isinstance(found, list):
        # `None` from the port, or an adapter that answered a shape this does not recognise. Both
        # mean the same thing to the model, and it is not "no comments".
        return ("(The ticket's comments could NOT be read — the tracker did not answer. That is "
                "NOT the same as nobody having commented: do not conclude that this has or has "
                "not been looked at, and say you could not see the history if it matters.)\n\n")
    if not found:
        return ("(The tracker answered: this ticket has NO comments. Nobody has commented on it, "
                "so no prior fix has been recorded here.)\n\n")
    return (f"The conversation on {ref} so far — the last {_COMMENTS_READ} comments, oldest first, "
            "with who wrote each one. VERIFY these rather than trusting them: a prior fix may be "
            "wrong, and one of these notes may be this platform's own (a bot or app login). A "
            "human's comment is an instruction and a constraint; do not propose again something "
            "the thread shows was already tried and failed.\n"
            f"{render_comments(found)}\n\n")


#: The `user:secret@` half of an authenticated HTTPS URL — see `conversation._URL_CREDENTIAL` for
#: why the token in a clone URL is not always one this module chose and therefore cannot be
#: redacted by value alone.
_URL_CREDENTIAL = re.compile(r"(https://)[^@/\s]+@")


def _checkout(project, ref: str) -> tuple[Path, bool]:
    """A shallow clone so Read/Grep/Glob work against the ACTUAL code — the whole point of this
    role, as opposed to the advisory coordinator that reasons from the text alone.

    THROUGH THE FORGE REGISTRY. The literal this replaced pointed every deployment at github.com,
    where an Azure Repos project is a 404 for a repository that exists — and the failure lands in
    the one branch that still answers, so it reads as a thin diagnosis rather than as a
    misconfiguration."""
    from openfactory.adapters.forge.registry import clone_url_for
    from openfactory.credentials import deployment_forge_token, forge_token_for
    from openfactory.util.causes import scrubbed

    tmp = Path(tempfile.mkdtemp(prefix="openfactory-techlead-"))
    repo = repo_of(project)
    if not repo:
        return tmp, False
    # PER PROJECT: one deployment hosts N projects and they no longer share a forge.
    token = forge_token_for(project) or deployment_forge_token(project) or ""
    try:
        # Inside the guard because the registry RAISES on a forge kind it does not know, and this
        # function's contract is `(tmp, False)` on anything going wrong — never an exception into a
        # diagnosis whose only job is to explain one.
        url = clone_url_for(project, repo, token=token)
        subprocess.run(["git", "clone", "--depth", "1", url, str(tmp)],
                       check=True, capture_output=True, timeout=120)
        # Scrub the tokened URL from .git/config — the read-only agent CAN read that file, and
        # nothing fetches or pushes this throwaway checkout again. Derived from the URL actually
        # used, because asking the registry for a token-free one does not give one: the Azure row
        # mints its credential from a provider and signs the URL regardless of what we passed.
        subprocess.run(["git", "-C", str(tmp), "remote", "set-url", "origin",
                        _URL_CREDENTIAL.sub(r"\1", url)], capture_output=True, timeout=15)
        return tmp, True
    except Exception as exc:  # noqa: BLE001 — degrade to reasoning without the checkout
        # The diagnosis still answers, and the answer is thinner than it reads — which is the
        # failure mode worth knowing about. Redact THEN truncate: the exception text embeds the
        # tokened URL, and truncation is not redaction. The regex first, because it catches a
        # credential the adapter minted and this function never held.
        log.warning("diagnosing %s without a checkout (%s)", ref,
                    scrubbed(_URL_CREDENTIAL.sub(r"\1***@", str(exc)), token))
        return tmp, False


def _final_text(res) -> str:
    """The role's FULL final message. The analysis comes first and the JSON verdict LAST, so a cap
    chops the verdict off — a live bug once (#37's 3509-character response)."""
    from openfactory.adapters.agent.base import final_text

    return final_text(res)
