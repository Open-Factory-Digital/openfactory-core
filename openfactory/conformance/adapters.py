"""The adapter conformance suite — every provider rule an incident taught, runnable (C-22).

WHY THIS IS A DELIVERABLE AND NOT A TEST FOLDER. The platform's promise is that a provider is a
ROW — a module plus a registry entry — and a promise like that is only worth what a stranger can
verify: hand your adapter to this suite and show a green run. Every rule here was learned from a
live incident on this deployment, which is what makes the suite compound with adoption: each new
provider that fails a check is failing where WE already paid.

THE RULES ARE FUNCTIONS, NOT PYTEST. A stranger's adapter lives in their repo with their runner;
importing pytest into their process to check ours would make the suite unusable exactly where it
matters. Each check returns findings; `openfactory conformance-adapter` renders them; our own test
suite
drives the same functions over our own adapters — one implementation, two callers.

WHAT A CHECK MAY DO: construct nothing, mutate nothing remote. Every check exercises the
adapter's LOCAL contract — signatures, degradation rules, refusal shapes. A suite that needed a
live Jira to run would never be run.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# THE PORTS, at module level: they are the second element of every `CHECKS` row and the CLI's
# instance-versus-factory decision. Each is a `base.py` — a Protocol over pydantic models — so
# importing them costs no vendor package (the ledger guard holds that line).
from openfactory.adapters.agent.base import CodingAgentAdapter
from openfactory.adapters.board.base import BoardAdapter
from openfactory.adapters.channel.base import ChannelAdapter
from openfactory.adapters.environment.base import EnvironmentObserver
from openfactory.adapters.forge.base import ForgeAdapter
from openfactory.adapters.notify.base import Notifier
from openfactory.adapters.sandbox.base import SandboxAdapter
from openfactory.adapters.tracker.base import TrackerAdapter
from openfactory.identity.base import IdentityProvider


@dataclass(frozen=True)
class Finding:
    """One broken rule: the rule, what happened, and the incident that taught it."""

    rule: str
    detail: str
    taught_by: str = ""


def _finding(rule: str, detail: str, taught_by: str) -> Finding:
    return Finding(rule=rule, detail=detail, taught_by=taught_by)


# ── the channel contract ────────────────────────────────────────────────────────────────────────

def check_channel(channel, *, project=None) -> list[Finding]:
    """The three-method contract plus the degradation rules its docstrings state."""
    findings: list[Finding] = []
    from openfactory.adapters.channel.base import ChannelAdapter

    if not isinstance(channel, ChannelAdapter):
        missing = [m for m in ("say", "mention", "start_listeners") if not hasattr(channel, m)]
        findings.append(_finding(
            "channel.protocol", f"does not satisfy ChannelAdapter (missing: {missing})",
            "the port exists so the core can be handed a channel without naming Slack"))
        return findings  # nothing else is checkable

    project = project or type("_P", (), {"name": "conformance-probe", "channel_options": {}})()

    # `say` returns a bool and NEVER raises — its callers are scheduled rounds; an exception
    # there turns one undelivered message into a retry storm.
    try:
        out = channel.say(project=project, channel="", text="conformance probe — ignore")
        if not isinstance(out, bool):
            findings.append(_finding(
                "channel.say-returns-bool",
                f"say() returned {type(out).__name__}, not bool",
                "a caller that cannot tell delivered from dropped retries what landed"))
    except Exception as exc:  # noqa: BLE001 — the raise IS the finding
        findings.append(_finding(
            "channel.say-never-raises", f"say() raised {type(exc).__name__}: {exc}",
            "an exception in a scheduled round turns one missed post into a retry storm"))

    # `mention` degrades to the plain name — a wrong mention makes somebody read an irrelevant
    # message AND leaves the right person never asked, while the thread looks answered.
    try:
        got = channel.mention("nobody-of-this-name-exists")
        if not isinstance(got, str):
            findings.append(_finding(
                "channel.mention-returns-str",
                f"mention() returned {type(got).__name__}",
                "the caller embeds it in a sentence"))
    except Exception as exc:  # noqa: BLE001
        findings.append(_finding(
            "channel.mention-never-raises", f"mention() raised {type(exc).__name__}: {exc}",
            "an unresolvable person must cost the mention, never the message"))
    return findings


# ── the notifier contract ───────────────────────────────────────────────────────────────────────

def check_notifier(notifier) -> list[Finding]:
    findings: list[Finding] = []
    if not isinstance(notifier, Notifier):
        # NAMED, like every other port: without this gate an object with no `notify` was
        # reported as `notifier.never-raises` ("raised AttributeError") — a verdict about the
        # wrong rule, and the CLI hands a failing INSTANCE here to be told what it lacks.
        missing = [m for m in ("notify",) if not hasattr(notifier, m)]
        findings.append(_finding(
            "notifier.protocol", f"does not satisfy Notifier (missing: {missing})",
            "every unprompted sentence the tech-lead speaks goes through `notify`"))
        return findings
    try:
        notifier.notify(message="conformance probe — ignore", level="info", about="")
    except TypeError as exc:
        findings.append(_finding(
            "notifier.accepts-about", f"notify() rejected the `about` kwarg: {exc}",
            "the thread-link rides on `about`; a provider that rejects it loses "
            "every shorthand reply"))
    except Exception as exc:  # noqa: BLE001
        findings.append(_finding(
            "notifier.never-raises", f"notify() raised {type(exc).__name__}: {exc}",
            "a notifier that has been failing for a week looks exactly like a quiet week — "
            "and one that raises fails the job it decorates"))
    return findings


# ── the identity contract ───────────────────────────────────────────────────────────────────────

def check_identity(provider) -> list[Finding]:
    findings: list[Finding] = []
    from openfactory.identity.base import IdentityProvider

    if not isinstance(provider, IdentityProvider):
        missing = [m for m in ("identify",) if not hasattr(provider, m)]
        findings.append(_finding(
            "identity.protocol", f"does not satisfy IdentityProvider (missing: {missing})",
            "the panel gate and require_auth both dispatch through it"))
        return findings

    for credential, label in (("", "an empty credential"),
                              ("   ", "whitespace"),
                              ("definitely-not-a-known-token", "an unknown token")):
        try:
            got = provider.identify(credential=credential, via="conformance")
            if got is not None and credential.strip() == "":
                findings.append(_finding(
                    "identity.empty-is-nobody", f"{label} resolved to {got!r}",
                    "an unknown caller who gets a plausible identity is written into the audit "
                    "record as fact"))
        except Exception as exc:  # noqa: BLE001
            findings.append(_finding(
                "identity.never-raises",
                f"identify() raised on {label}: {type(exc).__name__}: {exc}",
                "a provider that throws takes down the door rather than closing it"))
    return findings


# ── the board contract ──────────────────────────────────────────────────────────────────────────

def check_board(board) -> list[Finding]:
    """The rules C-05 and the state map taught. Needs a board the CALLER constructed — pointed at
    a sandbox project of THEIRS, never at anything live."""
    findings: list[Finding] = []
    from openfactory.adapters.board.base import BoardAdapter

    if not isinstance(board, BoardAdapter):
        # NAMED, AS `check_tracker` ALREADY DOES. "does not satisfy BoardAdapter" tells an
        # integrator nothing they can act on, and the day the port gains a method — `url()`, which
        # is the day this comment was written — every board written before it fails this gate with
        # no hint of which one. The sentence has to be the repair.
        missing = [m for m in dir(BoardAdapter)
                   if not m.startswith("_") and not hasattr(board, m)]
        findings.append(_finding(
            "board.protocol", f"does not satisfy BoardAdapter (missing: {missing})",
            "the vendor-agnostic claim rests on this seam"))
        return findings

    # REFS ARE THE PROVIDER'S OPAQUE STRINGS (C-05). Three of four trackers are numeric, so an
    # int-shaped port looks fine until the first Jira deployment collapses CONT-412 into 412.
    try:
        items = board.items_in_status("conformance-probe-no-such-column")
        if not isinstance(items, list) or any(not isinstance(i, str) for i in items):
            findings.append(_finding(
                "board.refs-are-strings",
                f"items_in_status returned {type(items).__name__} with non-string members",
                "int refs collapse CONT-412 and PROJ-412 into one ticket (a bug found live)"))
    except Exception as exc:  # noqa: BLE001
        findings.append(_finding(
            "board.reads-degrade",
            f"items_in_status raised {type(exc).__name__}: {exc}",
            "a read that raises takes the poller tick down with it"))

    # UNREADABLE IS ITS OWN ANSWER (`None`), NEVER "no columns" AND NEVER A RAISE. Three
    # meanings, two shapes, is how `doctor` once reported a permissions failure as "no board
    # configured — tickets are named directly", cheerfully, as a PASS.
    #
    # WHY IT IS A VENDOR-NEUTRAL RULE and not a GitHub test: the same defect surfaced twice on
    # GitHub inside four days (a personal-account board this platform had CREATED, unreadable by
    # it), and both times the fix landed in the GitHub adapter while nothing asked Azure DevOps
    # or Jira the same question. The operator named the pattern (2026-08-14): *"é importante que
    # any change be aimed at the PRODUCT and not at my specific case"*. A
    # contract every board must satisfy is what turns one vendor's incident into a property.
    try:
        columns = board.column_names()
        if columns is not None and (not isinstance(columns, list)
                                    or any(not isinstance(c, str) for c in columns)):
            findings.append(_finding(
                "board.columns-are-names-or-None",
                f"column_names returned {type(columns).__name__} with non-string members",
                "the caller renders these to a human and compares them to the pickup column"))
        elif columns == []:
            findings.append(_finding(
                "board.columns-unreadable-is-None",
                "column_names returned [] — a board with no columns and a board this credential "
                "cannot read are different answers and must not share a shape",
                "an empty list reads as 'configured and empty', so doctor passes a setup that "
                "will never pick anything up"))
    except Exception as exc:  # noqa: BLE001
        findings.append(_finding(
            "board.columns-unreadable-is-None",
            f"column_names raised {type(exc).__name__}: {exc}",
            "doctor asks this on a machine that may have no credential at all; a raise there is "
            "a traceback instead of a finding with a remedy"))

    # AN UNADDRESSABLE REF IS REFUSED, NEVER GUESSED. A GitHub board handed CONT-412 must return
    # False — reducing it to 412 moves somebody else's card.
    try:
        moved = board.set_column(issue="CONFORMANCE-999999", issue_url="", name="Done")
        if moved is True:
            findings.append(_finding(
                "board.refuses-what-it-cannot-address",
                "set_column claimed success for a ref this provider cannot hold",
                "a guessed ref moves the wrong card, silently, in the client's name"))
    except Exception as exc:  # noqa: BLE001
        findings.append(_finding(
            "board.writes-return-false",
            f"set_column raised {type(exc).__name__}: {exc}",
            "the caller's bool is what makes every False leave a trace; a raise loses the job"))
    return findings


# ── the tracker contract ────────────────────────────────────────────────────────────────────────

#: A ref no tracker on earth holds. Deliberately shaped like nothing: not a number GitHub or Azure
#: DevOps could resolve, not a `KEY-123` Jira could. Every check below is a READ against it, so a
#: caller may point this at their real project — the worst it can do is ask about a ticket that is
#: not there.
_NO_SUCH_TICKET = "CONFORMANCE-PROBE-000000"


def check_tracker(tracker) -> list[Finding]:
    """The rule #97 was opened for: **`None` = I could not read; `[]` = I read, and there is
    nothing.**

    THIS IS THE ONE THAT COSTS MOST WHEN IT IS BROKEN, because the read side of a tracker feeds a
    MODEL and a triage rule, neither of which can tell an absent answer from a negative one. The
    three times this codebase has collapsed the two, the symptom was never an error: an unreadable
    board read as an empty queue and the factory reported itself idle, an unparsed review read as a
    rejection, an unread ticket read as still open. Nobody files a bug against a poorer answer.

    The probes are reads against a ref that cannot exist, which is the cheapest way to reach an
    adapter's failure path without asking it to break anything."""
    findings: list[Finding] = []
    from openfactory.adapters.tracker.base import TicketComment, TicketSummary, TrackerAdapter

    if not isinstance(tracker, TrackerAdapter):
        missing = [m for m in dir(TrackerAdapter)
                   if not m.startswith("_") and not hasattr(tracker, m)]
        findings.append(_finding(
            "tracker.protocol", f"does not satisfy TrackerAdapter (missing: {missing})",
            "the platform's claim is that a provider is a row in a registry; a half-implemented "
            "adapter fails at the first job instead of at build time"))
        return findings  # nothing else is checkable

    # A ticket that does not exist cannot be READ, so the answer is None. `[]` here is the
    # collapse: it tells the tech-lead nobody has commented on a ticket it never managed to open.
    try:
        got = tracker.comments(_NO_SUCH_TICKET, limit=3)
        if got == []:
            findings.append(_finding(
                "tracker.unreadable-is-not-empty",
                "comments() answered [] for a ticket it cannot have read",
                "an empty comment history and an unreadable one are the same silence in a prompt, "
                "and a model resolves both as 'nobody has looked at this'"))
        elif got is not None and not all(isinstance(c, TicketComment) for c in got):
            findings.append(_finding(
                "tracker.comments-are-typed",
                f"comments() returned {[type(c).__name__ for c in got]}",
                "a bare list of bodies cannot tell a human's instruction from the platform's own "
                "earlier note, which is the only question the caller is asking"))
    except Exception as exc:  # noqa: BLE001 — the raise IS the finding
        findings.append(_finding(
            "tracker.reads-degrade", f"comments() raised {type(exc).__name__}: {exc}",
            "the read side gates no write; its callers are a chat answer and a board sweep, and "
            "both must degrade to a thinner answer rather than a traceback"))

    # REFS ARE THE PROVIDER'S OPAQUE STRINGS (C-05) — three of four trackers are numeric, so an
    # int-shaped summary looks fine until the first Jira deployment collapses CONT-412 into 412.
    #
    # THIS ONE READS THE CALLER'S REAL BOARD, unlike every probe above it, because there is no
    # unreal board to read: `list_tickets` takes no ref. `limit=1` is the smallest answer that can
    # still be judged, and it is not free — on GitHub any limit routes the read through
    # `--search sort:updated-desc` (measured: this call issues `gh issue list --search
    # sort:updated-desc`), which is the SEARCH quota rather than the ordinary one, shared with the
    # poller and every job. One request per suite run, said out loud here so a deployment that has
    # exhausted that quota knows why the check is the thing that failed.
    try:
        listed = tracker.list_tickets(state="open", limit=1)
        if listed is not None:
            if not all(isinstance(t, TicketSummary) for t in listed):
                findings.append(_finding(
                    "tracker.tickets-are-typed",
                    f"list_tickets() returned {[type(t).__name__ for t in listed]}",
                    "the board reader judges on why a card was closed and when it last moved; a "
                    "shape without those fields is a promise no adapter can keep"))
            elif any(not isinstance(t.ref, str) or not t.ref for t in listed):
                findings.append(_finding(
                    "tracker.refs-are-strings",
                    "list_tickets() answered with a ref that is not a non-empty string",
                    "int refs collapse CONT-412 and PROJ-412 into one ticket (a bug found live)"))
    except Exception as exc:  # noqa: BLE001
        findings.append(_finding(
            "tracker.reads-degrade", f"list_tickets() raised {type(exc).__name__}: {exc}",
            "an unreadable board must arrive as None and a sentence, never as a traceback in a "
            "scheduled round"))

    # AND THE CALLER'S OWN BUG IS THE EXCEPTION THAT PROVES THE RULE: a filter the port does not
    # know is not a provider failure, and widening it to "all" is how somebody asking for the open
    # queue is handed the closed cards without ever learning they asked wrong.
    try:
        tracker.list_tickets(state="opne", limit=1)
        findings.append(_finding(
            "tracker.refuses-an-unknown-filter",
            "list_tickets(state='opne') was accepted instead of raising ValueError",
            "a silently widened filter answers a question nobody asked, and the caller cannot see "
            "that it happened"))
    except ValueError:
        pass  # the contract
    except Exception as exc:  # noqa: BLE001
        findings.append(_finding(
            "tracker.refuses-an-unknown-filter",
            f"list_tickets(state='opne') raised {type(exc).__name__} rather than ValueError: {exc}",
            "the caller distinguishes its own bug from the provider's by the exception type"))
    return findings


# ── the forge contract ──────────────────────────────────────────────────────────────────────────

#: A host no forge on earth answers for. Every credential rule below is asked against it.
_FOREIGN_URL = "https://forge.conformance-probe.invalid/owner/repo.git"


def check_forge(forge) -> list[Finding]:
    """The rules #162 taught: a credential only goes to the host that issued it.

    LOCAL CHECKS ONLY. A forge's reads (`pr_for_head`, `list_branches`) are network calls to the
    caller's real forge, and the checks above reach their adapters' failure paths without asking;
    a forge's failure path is an HTTP error, so the probes here are the two methods that build a
    URL without sending one. They are also where the live incident was: a clone URL with somebody
    else's token spliced in, measured verbatim on 2026-08-16."""
    findings: list[Finding] = []
    from openfactory.adapters.forge.base import ForgeAdapter, carries_credentials

    if not isinstance(forge, ForgeAdapter):
        missing = [m for m in dir(ForgeAdapter)
                   if not m.startswith("_") and not hasattr(forge, m)]
        findings.append(_finding(
            "forge.protocol", f"does not satisfy ForgeAdapter (missing: {missing})",
            "the box clones, pushes and opens pull requests through this port and nothing else; "
            "a half-implemented forge fails at the first push instead of at build time"))
        return findings

    # A TOKENLESS CLONE URL CARRIES NO SECRET. The registry's `clone_url_for` hands the adapter
    # its own token, and an adapter that finds one elsewhere (the process environment, a
    # neighbour's variable) has re-created the leak the registry exists to close.
    try:
        url = forge.clone_url("owner/repo", token=None)
        if not isinstance(url, str) or not url:
            findings.append(_finding(
                "forge.clone-url-is-a-string", f"clone_url() returned {type(url).__name__}",
                "the box hands it to git as an argument"))
        elif carries_credentials(url):
            findings.append(_finding(
                "forge.tokenless-clone-carries-no-credential",
                "clone_url(token=None) produced a URL with credentials in it",
                "a credential the caller did not pass came from somewhere it was not meant for "
                "this repository — the cross-vendor leak of 2026-08-16"))
    except Exception as exc:  # noqa: BLE001 — the raise IS the finding
        findings.append(_finding(
            "forge.clone-url-never-raises", f"clone_url() raised {type(exc).__name__}: {exc}",
            "a forge that cannot name its own clone URL fails every job at the first step"))

    # A CREDENTIAL STAYS ON ITS OWN HOST. `authenticated_url` is asked to authenticate a URL on
    # a host this forge does not own; the only right answer is the URL back, untouched.
    try:
        got = forge.authenticated_url(_FOREIGN_URL)
        if got != _FOREIGN_URL or carries_credentials(got):
            findings.append(_finding(
                "forge.credential-stays-on-its-own-host",
                f"authenticated_url() rewrote a URL on a host it does not own: {got!r}",
                "a token for one system spliced into another's URL — measured live as a "
                "github.com token sent to dev.azure.com, and reported as a permissions problem"))
    except Exception as exc:  # noqa: BLE001
        findings.append(_finding(
            "forge.authenticated-url-never-raises",
            f"authenticated_url() raised {type(exc).__name__}: {exc}",
            "the box authenticates the clone in a scheduled activity; a raise there is a job "
            "that dies before it starts, with no sentence about the URL"))
    return findings


# ── the harness contract ────────────────────────────────────────────────────────────────────────

class _RecordingSandbox:
    """A `SandboxAdapter` that records what the harness asks of it and answers nothing.

    NOT A MOCK OF THE HARNESS — a stand-in for the box, which is the one collaborator `execute`
    needs and the one this suite may not start (a real box is a container or a remote task). It
    exists so the check can CALL `execute` rather than inspect its signature: a mock cannot fail
    an arity check, and a harness whose `execute` raises on the first `sandbox.run` would pass a
    shape-only check and fail the first ticket."""

    def __init__(self) -> None:
        self.commands: list[str] = []

    def prepare(self, *, repo_path, base_branch, branch, checkout_existing=False, remote_url=None):
        from openfactory.adapters.sandbox.base import Workspace

        return Workspace(path=repo_path, branch=branch, base_branch=base_branch,
                         host_path=repo_path)

    def harness_path(self, name: str) -> str:
        return name

    def run(self, *, workspace, command: str, timeout: int) -> tuple[int, str]:
        self.commands.append(command)
        return 0, ""

    def tail(self):
        return None

    def export_home_dir(self, *, workspace, relative, dest) -> bool:
        return False

    def import_home_dir(self, *, workspace, src, relative) -> bool:
        return False

    def diff_paths(self, *, workspace) -> list[str]:
        return []

    def publish_branch(self, *, workspace, remote_url=None) -> None:
        return None

    def rebase_onto_base(self, *, workspace, remote_url=None) -> bool:
        return True

    def cleanup(self, *, workspace) -> None:
        return None


def check_harness(harness) -> list[Finding]:
    """The two-method contract, and the one thing a shape cannot prove: that `execute` EMITS a
    result. Every terminal outcome the lifecycle decides on is read off `AgentRunResult`; a
    harness that raises instead, or returns a dict, leaves the job with no verdict to act on."""
    findings: list[Finding] = []
    from openfactory.adapters.agent.base import AgentContext, CodingAgentAdapter
    from openfactory.contracts import AgentRunResult, Ticket

    if not isinstance(harness, CodingAgentAdapter):
        missing = [m for m in ("execute", "repair") if not hasattr(harness, m)]
        findings.append(_finding(
            "harness.protocol", f"does not satisfy CodingAgentAdapter (missing: {missing})",
            "the orchestrator calls exactly these two; everything else is an optional capability "
            "it probes for and degrades without"))
        return findings

    import tempfile
    from pathlib import Path

    sandbox = _RecordingSandbox()
    with tempfile.TemporaryDirectory(prefix="openfactory-conformance-") as tmp:
        workspace = sandbox.prepare(repo_path=Path(tmp), base_branch="main",
                                    branch="openfactory/conformance-probe")
        context = AgentContext(ticket=Ticket(id="CONFORMANCE-PROBE-000000",
                                             title="conformance probe — ignore",
                                             objective="answer with a result and change nothing",
                                             repo="conformance/probe"))
        try:
            result = harness.execute(sandbox=sandbox, workspace=workspace, context=context)
        except Exception as exc:  # noqa: BLE001 — the raise IS the finding
            findings.append(_finding(
                "harness.execute-emits-a-result",
                f"execute() raised {type(exc).__name__}: {exc}",
                "a harness that raises leaves the job with no verdict — the platform's "
                "professional baseline is 'always emit a result', even a failed one"))
            return findings
    if not isinstance(result, AgentRunResult):
        findings.append(_finding(
            "harness.execute-emits-a-result",
            f"execute() returned {type(result).__name__}, not AgentRunResult",
            "the lifecycle reads its verdict, its changed paths and its resume handle off the "
            "result; a bare dict has none of the contract's meaning"))
    return findings


# ── the CI observer contract ────────────────────────────────────────────────────────────────────

#: A URL nothing answers at — the loopback discard port, so `health` sees a refused connection
#: rather than a DNS wait. Local by construction: no packet leaves the machine.
_DEAD_URL = "http://127.0.0.1:9/"


def check_observer(observer) -> list[Finding]:
    """The three-method contract, and the degradation rule its callers rely on: `health` answers
    a bool and never raises. `ci_status` and `deploy_status` read the caller's real CI and are
    not probed — a suite that needed a live pipeline would never be run."""
    findings: list[Finding] = []
    from openfactory.adapters.environment.base import EnvironmentObserver

    if not isinstance(observer, EnvironmentObserver):
        missing = [m for m in ("ci_status", "deploy_status", "health") if not hasattr(observer, m)]
        findings.append(_finding(
            "ci.protocol", f"does not satisfy EnvironmentObserver (missing: {missing})",
            "the promotion runner asks exactly these three of a CI, and nothing a vendor offers"))
        return findings

    try:
        alive = observer.health(url=_DEAD_URL, timeout=1)
        if not isinstance(alive, bool):
            findings.append(_finding(
                "ci.health-returns-bool", f"health() returned {type(alive).__name__}",
                "the promotion runner decides staging on it; a truthy object reads as healthy"))
        elif alive:
            findings.append(_finding(
                "ci.health-is-not-optimistic", "health() answered True for a URL nothing serves",
                "a health check that cannot fail promotes to production on a dead deployment"))
    except Exception as exc:  # noqa: BLE001
        findings.append(_finding(
            "ci.health-never-raises", f"health() raised {type(exc).__name__}: {exc}",
            "an unreachable environment is an answer (False) the runner retries on; a raise is "
            "a promotion that dies instead of waiting"))
    return findings


# ── the box contract ────────────────────────────────────────────────────────────────────────────

def check_box(box) -> list[Finding]:
    """The port's shape and the one answer it gives before anything runs — `tail()` is `None`
    (cannot stream) or a list (streams; nothing yet), never a raise.

    NEVER CALLS `run()`, `prepare()` OR `cleanup()`. Those start a container, a worktree or a
    remote task, and the CLI promises that nothing remote is created; a box is proven by running
    something inside it with `openfactory box prove`, which is the door for that. What is
    checkable here is the contract the lifecycle reads before it starts believing a stream."""
    findings: list[Finding] = []
    from openfactory.adapters.sandbox.base import SandboxAdapter

    if not isinstance(box, SandboxAdapter):
        missing = [m for m in dir(SandboxAdapter)
                   if not m.startswith("_") and not hasattr(box, m)]
        findings.append(_finding(
            "box.protocol", f"does not satisfy SandboxAdapter (missing: {missing})",
            "the job runs every command through this port; a box missing one fails mid-job"))
        return findings

    try:
        lines = box.tail()
        if lines is not None and (not isinstance(lines, list)
                                  or any(not isinstance(ln, str) for ln in lines)):
            findings.append(_finding(
                "box.tail-is-None-or-lines",
                f"tail() returned {type(lines).__name__} with non-string members",
                "None means 'cannot read my own output', a list means 'read it'; a third shape "
                "is a watcher that cannot tell a calm agent from a blind box"))
    except Exception as exc:  # noqa: BLE001
        findings.append(_finding(
            "box.tail-never-raises", f"tail() raised {type(exc).__name__}: {exc}",
            "tail() is read from another thread while run() blocks; a raise there kills the "
            "watcher and the job reports a calm agent for four hours"))
    return findings


#: kind → (the check that judges it, the port it must satisfy). `openfactory conformance-adapter`
#: dispatches here, and the table is the published surface: a new port earns a row, and a row is
#: a set of incidents not re-paid. EVERY port has one (2026-08-26): forge, harness, CI and box
#: joined, so the four axes a stranger could register on but never validate are validated.
#:
#: ONE TABLE, TWO FACTS PER ROW, and the second is what decides instance-versus-factory in the
#: CLI: `isinstance(target, Protocol)`. It used to be a second hand-kept map there with a
#: `"__call__"` default, and a kind absent from that map (tracker, measured 2026-08-26) made a
#: zero-arg factory FUNCTION pass as the instance and report every method missing — absence read
#: as a verdict. A row here without a Protocol cannot exist; the guard reads the pairs.
CHECKS: dict[str, tuple[Callable[..., list[Finding]], type]] = {
    "channel": (check_channel, ChannelAdapter),
    "notifier": (check_notifier, Notifier),
    "identity": (check_identity, IdentityProvider),
    "board": (check_board, BoardAdapter),
    "tracker": (check_tracker, TrackerAdapter),
    "forge": (check_forge, ForgeAdapter),
    "harness": (check_harness, CodingAgentAdapter),
    "ci": (check_observer, EnvironmentObserver),
    "box": (check_box, SandboxAdapter),
}
