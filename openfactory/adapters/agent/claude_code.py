"""ClaudeCodeAdapter — v1 executor, built over the `claude -p` CLI (not the SDK).

Why the CLI and not the Agent SDK: the CLI accepts both subscription auth
(CLAUDE_CODE_OAUTH_TOKEN) and API-key auth (ANTHROPIC_API_KEY) with the same code
path — swap an env var. The Agent SDK forbids subscription auth for third-party
agents. The command runs *through the sandbox*, so it executes inside the container
(or the worktree) — never on the host directly.

Anti-black-box / anti-silent-hang measures (operator visibility):
- `--output-format stream-json --verbose`: every action (edit, command) is a JSON
  event. The full transcript is captured, and written per-job when `log_dir` is set.
- `--max-turns`: a hard cap on the agent loop — it cannot run forever.
- The sandbox enforces a timeout: a hang is killed and surfaces as a failed job,
  never a silent stall.
- `--permission-mode acceptEdits` + explicit `--allowedTools`: anything outside the
  grant is denied, not left waiting on an approval that will never come.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import time
from pathlib import Path

from openfactory.adapters.agent.base import (
    AgentContext,
    CodingAgentAdapter,
    ticket_brief,
    wall_result,
)
from openfactory.adapters.agent.roles import role_prompt
from openfactory.adapters.agent.stream import reading_of
from openfactory.adapters.sandbox.base import SandboxAdapter, Workspace
from openfactory.adapters.sandbox.timeouts import AGENT_TIMEOUT, timed_out
from openfactory.contracts import AgentRunResult

log = logging.getLogger("openfactory.agent.claude")

# The wall-clock wall lives with the sandbox (one concept, one number, every harness). Claude
# also has `--max-turns`, so it normally stops on TURNS long before this — the wall is the
# backstop for a run that is stuck rather than merely long.
_EXECUTE_TIMEOUT = AGENT_TIMEOUT

#: THE CHAT'S OWN FENCES, and the ORDER is the whole point (#167). A chat inherited the executor's
#: four-hour wall and its 200-turn cap while `AskWorkflow` gives the activity six minutes with
#: `maximum_attempts=1` — so the OUTER fence was the tightest one. A question that thought for
#: seven minutes died at the Temporal wall, the operator read "I could not work that out just now",
#: and the agent kept running and kept billing with nobody to hand the answer to.
#:
#: Innermost first: turns stop it before the wall, the wall stops it before the activity budget.
#: Both env-tunable, because the honest number is the one a deployment measures — and step (a) of
#: this card is what finally records the distribution to measure it from.
_CHAT_TIMEOUT = int(os.environ.get("OPENFACTORY_CHAT_TIMEOUT", "300"))
_CHAT_MAX_TURNS = int(os.environ.get("OPENFACTORY_CHAT_MAX_TURNS", "12"))


def _load_agent_token_pool() -> list[dict]:
    """The agent's credential pool for rate-limit / auth FAILOVER.

    A JSON array in `OPENFACTORY_AGENT_TOKENS` — `[{"id","token","type"?}]` — lets one exhausted
    or revoked token fail over to the next instead of halting the job. Falls back to the
    single `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_API_KEY` so a single-token deploy behaves
    exactly as before. A malformed pool degrades to that fallback, never a crash (#2)."""
    raw = os.environ.get("OPENFACTORY_AGENT_TOKENS", "").strip()
    if raw:
        try:
            data = json.loads(raw)
            pool = [
                {"id": str(t.get("id", i)), "token": t["token"],
                 "type": t.get("type", "subscription")}
                for i, t in enumerate(data)
                if isinstance(t, dict) and t.get("token")
            ]
            if pool:
                return pool
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            # A TYPO IN THE POOL LEAVES YOU WITH ONE TOKEN AND NO FAILOVER, which looks identical
            # to a deployment that never configured a pool — right up until the day one credential
            # fails and there is nothing to rotate to. Said out loud, because it is unfixable by
            # anything but a person editing that value.
            log.warning("OPENFACTORY_AGENT_TOKENS could not be read (%s) — falling back to a "
                        "SINGLE "
                        "credential, so there is no failover", str(exc)[:120])
    if tok := os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return [{"id": "single", "token": tok, "type": "subscription"}]
    if tok := os.environ.get("ANTHROPIC_API_KEY"):
        return [{"id": "single", "token": tok, "type": "api"}]
    return []


# -- C2 (perfect resume), Claude-specific. The core round-trips an OPAQUE resume_handle; here is
# where it gets its meaning. On a rate-limit pause we snapshot the CLI's session state (the
# `.claude` directory where `claude` keeps the transcript that `--resume <id>` replays) and encode
# {phase, session, state_key} into the handle. On resume we restore that state and pass --resume,
# so the agent CONTINUES its session instead of starting cold. Every step degrades to a no-op
# (→ today's fresh restart) when unconfigured — the resume is a bonus, never a new failure mode.
#
# THE SESSION IS TAKEN FROM THE BOX THAT WROTE IT, and that is what makes this work on a free
# deployment (#118). It used to be read from the ORCHESTRATOR's own `~/.claude`, which is the same
# filesystem only when the box is a worktree — the shape of the cloud path, where the whole job
# runs inside one task. On the default local box the CLI runs through `docker exec`, so its session
# lives in the CONTAINER's HOME and dies with it: a compose deployment could not resume at all, and
# one that set a bucket anyway would have uploaded the WORKER's transcripts (the tech-lead's, the
# sizer's — client repository content) while STILL resuming cold. Both halves are gone: the bytes
# come out of the box through the sandbox port, and where they are kept is an axis with a free row.
#: What the harness writes, relative to the HOME of the box it ran in.
_SESSION_RELATIVE = ".claude/projects"

#: A session id from the CLI, before it is interpolated into a shell glob that runs in the box.
#: It arrives from a JSON stream the harness produced; this is where it stops being trusted.
_SESSION_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")


# `_resume_bucket()` lived here and answered "is durable resume switched on?". The question is
# gone with the answer: WHERE a session is kept is `session_store.session_store_kind()`, which
# prefers what the deployment declares and falls back to the free store, and WHETHER one can be
# kept is the box's `transfers_state`. A bucket is now a coordinate, never a switch.


def _encode_handle(phase: str, session: str, state_key: str) -> str:
    return json.dumps({"v": 1, "phase": phase, "session": session, "state_key": state_key})


def _decode_handle(handle: str) -> dict | None:
    """Parse an opaque handle this adapter emitted. Foreign/empty/garbage → None (resume cold)."""
    if not handle:
        return None
    try:
        d = json.loads(handle)
        return d if isinstance(d, dict) and d.get("v") == 1 and d.get("session") else None
    except (json.JSONDecodeError, TypeError):
        return None


#: The phases whose session can ever be REPLAYED. `machine.py` sets `resume_handle` on the job's
#: primary context only, so a handle minted anywhere else is write-only: the judging roles (the
#: tech-lead's chat, diagnose, advise, the sizer) build a fresh context every call and a repair
#: context never carries one. Snapshotting them cost a full copy + gzip of the worker's own
#: `~/.claude` on every rate-limited judging pass, all of it addressed by a ticket id those roles
#: share ("chat", "techlead") so every project overwrote every other — and nothing ever read one
#: back. Proved with a live probe during the review of #118, not reasoned about.
_RESUMABLE_PHASES = ("plan", "execute")

#: What a kept session may weigh. A harness home is written by the agent's own code, in a box it
#: has root in, and the blob is built in memory and stored on the volume that also carries the
#: registry — so "however big it happens to be" is a disk-full surfacing as "every job raises".
#: Past this the run resumes cold, which costs one agent pass; the alternative costs the factory.
_MAX_SNAPSHOT_BYTES = 256 * 1024 * 1024


#: What this harness says when it will not run the model it was given. MEASURED against the real
#: CLI (2026-08-15): it prints this, emits no stream event at all, and exits ZERO — so neither the
#: exit code nor the event stream can be keyed on, and the text is the only signal there is.
#: STOPS AT THE QUOTE, not at the newline. The sentence reaches us inside a JSON event, so
#: "everything to the end of the line" dragged the rest of the envelope into an operator-facing
#: message — `…pick a different model."}],"context_management":null,"parent_tool_use_id":null,…`
#: (pilot, 2026-08-15). The string it lives in ends where the quote does, and on a plain stderr
#: line there is no quote, so the newline still bounds it.
_MODEL_REJECTED = re.compile(
    r"There's an issue with the selected model[^\"\n]*", re.I)


def _model_rejection(out: str) -> str:
    """The harness's own sentence about a model it will not run, or ""."""
    m = _MODEL_REJECTED.search(out or "")
    return m.group(0).strip() if m else ""


#: The harness's own `init` event — proof it has read its arguments, and the only positive signal
#: that the question was asked at all.
_INIT_EVENT = re.compile(r'"subtype"\s*:\s*"init"')

#: How the CLI answers a model it will not run: a message from `<synthetic>`, produced locally,
#: with `duration_api_ms: 0`. Measured 2026-08-15.
_SYNTHETIC = re.compile(r'"model"\s*:\s*"<synthetic>"')

#: How long to wait for `init`. GENEROUS, because the alternative failed on the pilot's worker: a
#: node CLI booting in a cold container takes seconds, and a short wall turned "still starting"
#: into "approved".
_START_TIMEOUT = 25.0

#: How long a rejection may take once the name has been read. It is produced locally and arrives
#: at once; this is a margin, not an expectation.
_VERDICT_GRACE = 4.0


def recognises_model(model: str, *, harness: str = "claude") -> tuple[str, str]:
    """OPTIONAL CAPABILITY (see the port): `(verdict, detail)` about a model name.

        ("known",     "")            the harness read the name and did not reject it
        ("unknown",   "<sentence>")  it answered that the model does not exist or is unreachable
        ("unchecked", "<why>")       it could not be asked — NOT a verdict about the model

    THREE ANSWERS, BECAUSE TWO WOULD LIE. Returning "" for both "fine" and "could not ask" means
    an operator on a machine where the probe cannot run reads silence as confirmation — the
    distinction `tail()` documents on the sandbox port, for the same reason.

    THE SIGNAL IS THE HARNESS'S OWN `init` EVENT, and getting this wrong is what made the second
    cut worse than the first. That one inferred "known" from the process still being ALIVE after
    a three-second wall — true of a healthy run and equally true of a cold container that had not
    finished booting, so on the pilot's worker a typo came back approved, in silence. `init` is
    emitted only once the CLI has read its arguments (it echoes the model back), so it is the
    proof that the question was actually asked. A rejection then arrives immediately after it,
    from `<synthetic>` with `duration_api_ms: 0` — the CLI answers locally, without contacting
    anything. All of it measured against the real CLI on 2026-08-15.
    """
    import subprocess

    try:
        proc = subprocess.Popen(
            # THE FLAGS THE REAL RUN USES, plus the stream the real run parses. Without
            # `--permission-mode` the CLI can refuse in an environment where the job itself works
            # — measured on the pilot's worker, where the probe exited 1 before reading the model
            # name while every job's own invocation was fine. A probe that behaves differently
            # from the thing it is probing answers a different question.
            [harness, "--model", model, "--permission-mode", "acceptEdits",
             "--output-format", "stream-json", "--verbose", "-p", "ok"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace",
        )
    except (OSError, ValueError) as exc:
        return "unchecked", f"there is no {harness!r} on this machine to ask ({str(exc)[:80]})"
    said: list[str] = []
    try:
        import select

        started = False
        deadline = time.monotonic() + _START_TIMEOUT
        while (remaining := deadline - time.monotonic()) > 0:
            # WAITED ON, NEVER BLOCKED ON: `readline()` blocks until the harness speaks, and the
            # wall a caller was given has to mean something on a machine where it never does.
            if not select.select([proc.stdout], [], [], remaining)[0]:
                break
            line = proc.stdout.readline()
            if not line:
                break
            if line.strip():
                said.append(line.strip())
            if _MODEL_REJECTED.search(line):
                return "unknown", _MODEL_REJECTED.search(line).group(0).strip()
            if _SYNTHETIC.search(line):
                return "unknown", (f"the harness answered about {model!r} without contacting a "
                                   "model at all")
            if not started and _INIT_EVENT.search(line):
                # The name has been READ. Only a rejection can still arrive, and it arrives at
                # once — so the window shrinks from "has it started?" to "did it object?".
                started, deadline = True, time.monotonic() + _VERDICT_GRACE
        if started:
            return "known", ""
        why = f"status {proc.returncode}" if proc.poll() is not None else (
            f"it said nothing in {_START_TIMEOUT:.0f}s")
        # WITH WHAT IT SAID. "status 1" is a fact an operator cannot act on; the CLI's own last
        # line usually names the reason, and that is the difference between a note and a dead end.
        if said:
            why += f": {said[-1][:160]}"
        return "unchecked", f"{harness!r} never got as far as the model name ({why})"
    except (OSError, ValueError) as exc:
        return "unchecked", str(exc)[:80]
    finally:
        # KILLED, ALWAYS. Left running it would go on working through the prompt for a model that
        # IS recognised — a configuration command quietly buying an agent turn.
        proc.kill()
        try:
            proc.stdout.close()
        except OSError:
            pass


def _only_this_session(member, session: str):
    """Keep the paused session's own transcript and nothing else.

    THE SCOPE USED TO BE THE WHOLE `projects/` TREE, which is every session of every job that ever
    ran in that home. On a container box that is one job's worth. On the `worktree` box — the one
    the judging roles run IN THE WORKER'S OWN PROCESS — it is the operator's entire history, and
    on the cloud path it would have crossed a machine boundary. A snapshot exists to continue ONE
    session; taking the rest was never the feature, only the implementation.

    Directories are kept so the layout survives; REGULAR FILES ONLY, so a symlink or a device node
    the agent left behind cannot ride out of the box. This is the line that enforces it for every
    box: the worktree box also drops links while copying, but `docker cp` carries them, so a claim
    that "the box handles it" would be true of one box and false of the reference one."""
    if member.isdir():
        return member
    name = member.name.rsplit("/", 1)[-1]
    return member if member.isreg() and name.startswith(f"{session}.") else None


def _snapshot_session(
    session: str, project: str, issue: str, *,
    sandbox: SandboxAdapter | None = None, workspace: Workspace | None = None,
) -> str:
    """Take the session out of the box that wrote it, keep it, and return its key ("" = not kept).

    Scoped to `projects/` so credentials and settings are never archived and the blob stays small
    (audit); symlinks are dropped — the agent can write into a shared HOME, and restoring its
    symlinks or hooks into the NEXT box would be a persistence channel. Enforced HERE
    (`_only_this_session`) rather than left to the box, because the two boxes carry links
    differently and the property must not depend on which one ran.

    Best-effort at every step: a pause that cannot be snapshotted resumes cold, and never crashes.
    """
    if not (session and sandbox is not None and workspace is not None):
        return ""
    if not _SESSION_ID.fullmatch(session):
        return ""  # the id becomes a store key; it is checked here, not where it is written
    try:
        import io
        import tarfile
        import tempfile

        from openfactory.adapters.agent.session_store import build_session_store, session_key

        with tempfile.TemporaryDirectory(prefix="openfactory-session-") as tmp:
            staged = Path(tmp) / "projects"
            if not sandbox.export_home_dir(workspace=workspace, relative=_SESSION_RELATIVE,
                                           dest=staged):
                return ""  # nothing was written (a cold pass), or this box cannot hand it over
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                tar.add(str(staged), arcname=_SESSION_RELATIVE,
                        filter=lambda m: _only_this_session(m, session))
        blob = buf.getvalue()
        if len(blob) > _MAX_SNAPSHOT_BYTES:
            print(f"OPENFACTORY_RESUME: the session snapshot is {len(blob) // (1 << 20)}MB — over "
                  f"the {_MAX_SNAPSHOT_BYTES // (1 << 20)}MB this deployment keeps; the resumed "
                  "run will start cold rather than fill the disk", flush=True)
            return ""
        key = session_key(project, issue, session)
        return key if build_session_store().put(key=key, blob=blob) else ""
    except ValueError as exc:  # a store kind this deployment does not have — say so, loudly
        print(f"OPENFACTORY_RESUME: {exc} — resume is OFF until that is corrected", flush=True)
        return ""
    except Exception as exc:  # noqa: BLE001 — snapshotting is opportunistic
        print(f"OPENFACTORY_RESUME: session snapshot failed ({str(exc)[:120]})", flush=True)
        return ""


def _restore_session(
    state_key: str, *,
    sandbox: SandboxAdapter | None = None, workspace: Workspace | None = None,
) -> bool:
    """Put a prior snapshot back into THIS box so `--resume` can replay it.

    True only means the bytes landed; the caller still proves the session is actually there before
    passing `--resume`, because passing it for a session the CLI cannot find errors the whole
    invocation and turns a resumable pause into a bogus hold."""
    if not (state_key and sandbox is not None and workspace is not None):
        return False
    try:
        import io
        import tarfile
        import tempfile

        from openfactory.adapters.agent.session_store import build_session_store

        blob = build_session_store().get(key=state_key)
        if not blob:
            return False
        with tempfile.TemporaryDirectory(prefix="openfactory-session-") as tmp:
            with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
                try:
                    tar.extractall(tmp, filter="data")  # 3.12+ (and 3.11.4+): safe extraction
                except TypeError:
                    tar.extractall(tmp)  # noqa: S202 — older Python; our own trusted snapshot
            staged = Path(tmp) / _SESSION_RELATIVE
            if not staged.is_dir():
                return False
            return sandbox.import_home_dir(workspace=workspace, src=staged,
                                           relative=_SESSION_RELATIVE)
    except Exception as exc:  # noqa: BLE001 — a failed restore just means resume cold
        print(f"OPENFACTORY_RESUME: session restore failed ({str(exc)[:120]})", flush=True)
        return False


def _session_is_in_the_box(
    sandbox: SandboxAdapter, workspace: Workspace, session: str,
) -> bool:
    """Does the box hold the transcript `--resume <session>` will look for?

    ASKED IN THE BOX, because that is where the CLI reads it. The orchestrator's own filesystem
    answered this question until #118, which on the default local box is a different machine's
    worth of state: it said "no" for a session that was there and "yes" for one that was not."""
    if not _SESSION_ID.fullmatch(session or ""):
        return False  # never interpolate an unvalidated id into a command that runs in the box
    rc, _ = sandbox.run(
        workspace=workspace,
        command=f'ls "$HOME"/{_SESSION_RELATIVE}/*/{session}.jsonl >/dev/null 2>&1',
        timeout=60,
    )
    return rc == 0


_READONLY_TOOLS = ["Read", "Grep", "Glob"]  # the planner investigates, never edits
# Mutating tools an investigate-only role must never wield. We DENY these explicitly
# (--disallowedTools) on top of restricting the available set (--tools), because the two
# flags are honoured differently across `claude` CLI versions — a pinned-but-older image
# once ignored --tools and let the planner edit. The deny list is the belt to --tools'
# braces: whatever a version does with the available-set, an explicit deny holds.
_MUTATING_TOOLS = ["Edit", "Write", "Bash", "NotebookEdit", "Task"]


class ClaudeCodeAdapter(CodingAgentAdapter):
    def __init__(
        self, *, model: str | None = None, planner_model: str | None = None,
        executor_model: str | None = None, max_turns: int | None = None,
        log_dir: Path | None = None, language: str | None = None,
    ) -> None:
        self.model = model
        #: the project's language for anything a human reads (see agent/roles.py)
        self.language = language
        # a model PER ROLE (plan cheap/fast, execute strong) — param > env > legacy `model`.
        self.planner_model = planner_model or os.environ.get("OPENFACTORY_PLANNER_MODEL") or model
        self.executor_model = (executor_model
                               or os.environ.get("OPENFACTORY_EXECUTOR_MODEL") or model)
        # Turn cap (the runaway guard). With the two-stage split the EXECUTOR now does the
        # whole implementation (the planner only reads + plans), so a full feature — backend
        # route + widget + TDD test runs — can exceed the old cap of 60 and get cut off
        # mid-work (#232 hit 60 with the plan half-applied). Default 120; tune via env
        # without a rebuild. The read-only planner never approaches it.
        self.max_turns = (
            max_turns if max_turns is not None
            else int(os.environ.get("OPENFACTORY_MAX_TURNS", "200"))
        )
        self.log_dir = log_dir  # if set, the per-job transcript is written here
        self._pool = _load_agent_token_pool()  # credential failover pool (may be 1)
        self._ti = 0  # index of the token currently in use (sticky across roles)

    @staticmethod
    def recognises_model(model: str) -> tuple[str, str]:
        """OPTIONAL CAPABILITY (see the port's list): `(verdict, detail)` — see the module
        function. `known` | `unknown` | `unchecked`, and the third is never read as the first.

        On the ADAPTER because that is where a caller can find it — the port's contract is that
        optional capabilities are probed on the object with `hasattr`, so a harness that cannot
        answer this question simply does not have the method, and `set-model` says so rather than
        guessing on its behalf."""
        return recognises_model(model)

    def plan(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, context: AgentContext
    ) -> AgentRunResult:
        """The PLANNER: investigate (read-only) and produce an execution plan — no edits.
        Its final message is the plan, handed to the executor via context.plan."""
        role = role_prompt("planner")
        prompt = (f"{role}\n\n{self._ticket_context(context)}" if role
                  else self._build_prompt(context))
        return self._invoke(sandbox, workspace, prompt, "plan",
                            tools=_READONLY_TOOLS, model=self.planner_model, context=context)

    def ask(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, prompt: str, phase: str = "ask"
    ) -> AgentRunResult:
        """Run a READ-ONLY prompt against the checkout and return the text (see roles.py).

        Read-only here is enforced twice: `--tools` restricts the available set AND the mutating
        tools are explicitly denied, because the two flags have been honoured differently across
        CLI versions and a pinned-but-older image once ignored `--tools` and let a read-only role
        edit."""
        from openfactory.contracts import Ticket

        ctx = AgentContext(ticket=Ticket(id=phase, title=phase, objective=phase, repo=""))
        return self._invoke(sandbox, workspace, prompt, phase,
                            tools=_READONLY_TOOLS, model=self.planner_model, context=ctx)

    def size(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, context: AgentContext
    ) -> AgentRunResult:
        """The SIZER (ADR-0013 D2): read-only pre-flight judgment — INVEST on the ticket text,
        blast-radius estimate over the checkout. Emits a structured verdict the preflight
        activity parses. Cheap model (planner tier), read-only tools, never edits."""
        role = role_prompt("sizer")
        prompt = (f"{role}\n\n{self._ticket_context(context)}" if role
                  else f"Judge whether this ticket is one small, testable change; output a "
                       f"fenced json verdict (fit|split|unclear).\n\n"
                       f"{self._ticket_context(context)}")
        return self._invoke(sandbox, workspace, prompt, "size",
                            tools=_READONLY_TOOLS, model=self.planner_model, context=context)

    def advise(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, situation: str
    ) -> AgentRunResult:
        """The COORDINATOR / tech lead: read a parked decision + the project situation and produce
        a humanized briefing + a recommended option (v0 is advisory). Read-only tools (it may
        inspect the repo for context), planner-tier model, never edits."""
        from openfactory.adapters.agent.base import AgentContext
        from openfactory.contracts import Ticket

        role = role_prompt("coordinator")
        prompt = (f"{role}\n\n## Situation\n{situation}" if role
                  else f"You are a tech lead. Briefly advise (json: summary/recommend/rationale) "
                       f"on this parked decision:\n\n{situation}")
        ctx = AgentContext(ticket=Ticket(id="coordinator", title="decision",
                                         objective="advise", repo=""))
        return self._invoke(sandbox, workspace, prompt, "advise",
                            tools=_READONLY_TOOLS, model=self.planner_model, context=ctx)

    def diagnose(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, situation: str
    ) -> AgentRunResult:
        """The TECH LEAD on an IMPEDIMENT: read the failure + ticket + the actual repo and produce
        a humanized HandOff (what happened / why / recommendation) — VERIFYING claims against the
        code, and CORRECTING a prior human comment if it's wrong. The workspace is a real checkout
        so Read/Grep/Glob can inspect the repo. Read-only tools, planner-tier model, never edits."""
        from openfactory.adapters.agent.base import AgentContext
        from openfactory.contracts import Ticket

        role = role_prompt("techlead")
        fallback = (
            "You are the project's tech lead. A job PARKED on an impediment and needs a human. "
            "Investigate against the repo, verify every claim (including any prior human comment — "
            "say so if it's wrong), and output your diagnosis as a fenced json block with keys: "
            "headline, what_happened, why, correction (optional), recommendation, alternatives "
            "(optional)."
        )
        prompt = (f"{role}\n\n## Situation\n{situation}" if role
                  else f"{fallback}\n\n## Situation\n{situation}")
        ctx = AgentContext(ticket=Ticket(id="techlead", title="impediment",
                                         objective="diagnose", repo=""))
        return self._invoke(sandbox, workspace, prompt, "diagnose",
                            tools=_READONLY_TOOLS, model=self.planner_model, context=ctx)

    def chat(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, question: str, context: str = ""
    ) -> AgentRunResult:
        """The TECH LEAD answering a teammate's free-text question (ADR-0015 v2, read-only). Unlike
        advise()/diagnose() — which force a fenced-JSON HandOff/verdict a caller parses — a chat
        reply is plain prose posted straight back to Slack, so this renders a free-text prompt (no
        forced JSON, no coordinator role). The workspace is a real checkout so Read/Grep/Glob can
        VERIFY the answer against the code. Read-only tools, planner-tier model, never edits."""
        from openfactory.adapters.agent.base import AgentContext
        from openfactory.contracts import Ticket

        prompt = (
            "You are the project's tech lead, answering a teammate's question in a chat. Be "
            "concise, concrete, plain-language — no preamble, no fenced JSON, no markdown headers "
            "(this renders as a chat message). The repository is checked out at the workspace "
            "root: use "
            "Read/Grep/Glob to VERIFY before you answer. If you don't know or can't tell from "
            "what's available, say so plainly rather than guessing.\n\n"
            f"## Question\n{question}"
            + (f"\n\n## Current factory state\n{context}" if context else "")
        )
        ctx = AgentContext(ticket=Ticket(id="chat", title="question",
                                         objective="answer", repo=""))
        return self._invoke(sandbox, workspace, prompt, "chat",
                            tools=_READONLY_TOOLS, model=self.planner_model, context=ctx)

    def execute(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, context: AgentContext
    ) -> AgentRunResult:
        """The EXECUTOR: implement the plan with TDD."""
        return self._invoke(sandbox, workspace, self._executor_prompt(context), "execute",
                            tools=context.allowed_tools, model=self.executor_model, context=context)

    def repair(
        self,
        *,
        sandbox: SandboxAdapter,
        workspace: Workspace,
        context: AgentContext,
        failure_log: str,
    ) -> AgentRunResult:
        prompt = (
            f"{self._executor_prompt(context)}\n\n"
            f"The following validations FAILED. Fix the code so they pass — do not "
            f"change the tests to make them pass:\n\n{failure_log}"
        )
        return self._invoke(sandbox, workspace, prompt, "repair",
                            tools=context.allowed_tools, model=self.executor_model, context=context)

    def continue_execute(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, context: AgentContext,
        handle: str, brief: str,
    ) -> AgentRunResult:
        """Recovery rung 1 (ADR-0013 D5): CONTINUE the executor session that just stopped
        (turn cap) — same container, transcript on local disk, so no S3 restore is needed.
        `handle` is the opaque token the stop emitted; a foreign/garbled one runs cold."""
        h = _decode_handle(handle)
        session = h["session"] if h else ""
        return self._invoke(sandbox, workspace, brief, "execute",
                            tools=context.allowed_tools, model=self.executor_model,
                            context=context, resume_session=session)

    def recover(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, context: AgentContext,
        brief: str,
    ) -> AgentRunResult:
        """Recovery rung 2 (ADR-0013 D5): a FRESH recovery pass — clean context, the diff so
        far, instructed to assess then finish or simplify. Never widens scope."""
        role = role_prompt("recovery")
        prompt = (f"{role}\n\n{brief}\n\n{self._ticket_context(context)}" if role
                  else f"{self._executor_prompt(context)}\n\n{brief}")
        return self._invoke(sandbox, workspace, prompt, "execute",
                            tools=context.allowed_tools, model=self.executor_model,
                            context=context)

    # -- internals --

    def _executor_prompt(self, context: AgentContext) -> str:
        role = role_prompt("executor")
        if not role:
            return self._build_prompt(context)  # degrade to the generic single-agent prompt
        plan = f"\n\n## Plan\n{context.plan}" if context.plan else ""
        return f"{role}{plan}\n\n{self._ticket_context(context)}"

    def _ticket_context(self, context: AgentContext) -> str:
        """The ticket + its knowledge cascade — `base.ticket_brief`, the ONE builder every
        harness renders. This adapter kept a fourth copy of it (with the card's Context, without
        its In-scope list) beside three others that disagreed; the fields are decided once now.
        The 'who you are' comes from the role prompt, so this is role-neutral."""
        return ticket_brief(context)

    def _build_prompt(self, context: AgentContext) -> str:
        """The generic single-agent prompt — fallback when the role files are absent."""
        return (
            "You are an autonomous coding agent implementing one ticket. Work only within "
            "the granted permissions. Implement the change and ensure it is complete against "
            "the acceptance criteria.\n\n" + self._ticket_context(context)
        )

    def _cli(
        self, prompt: str, *, harness: str, tools: list[str], model: str | None,
        resume_session: str = "", phase: str = ""
    ) -> str:
        # `harness` is the ABSOLUTE path the box chose — never a bare name,
        # which `PATH` inside the client's image would resolve (ADR-0037 D2).
        cmd = [
            harness, "-p", shlex.quote(prompt),
            "--output-format", "stream-json", "--verbose",
            "--permission-mode", "acceptEdits",
            "--max-turns", str(_CHAT_MAX_TURNS if phase == "chat" else self.max_turns),
        ]
        if resume_session:  # C2: continue the paused session instead of a cold start
            cmd += ["--resume", shlex.quote(resume_session)]
        if tools:
            # --tools RESTRICTS the available set (the planner gets only Read/Grep/Glob).
            # Belt-and-braces: also DENY every mutating tool not explicitly granted, so a
            # read-only role stays read-only even on a CLI version that mishandles --tools.
            cmd += ["--tools", shlex.quote(",".join(tools))]
            denied = [t for t in _MUTATING_TOOLS if t not in tools]
            if denied:
                cmd += ["--disallowedTools", shlex.quote(",".join(denied))]
            # AUTO-APPROVE exactly the granted set. Without this, `acceptEdits` auto-accepts
            # file edits but Bash still needs per-command approval — and in headless `-p` mode
            # there is no human, so EVERY `pytest`/`python`/lint call is DENIED. That silently
            # killed the executor's TDD self-verify loop (it literally can't run its tests) and
            # made agents confabulate "commands are blocked behind an approval." The sandbox is
            # an isolated, credential-less, ephemeral Fargate box, so auto-approving the tools
            # already granted (and only those — the envelope above still holds) is safe and is
            # exactly the OpenFactory intent: the coder runs its own gates.
            cmd += ["--allowedTools", shlex.quote(",".join(tools))]
        if model:
            cmd += ["--model", shlex.quote(model)]
        return " ".join(cmd)

    def _apply_token(self) -> None:
        """Point the CLI at the token currently in use. A subscription token goes in
        CLAUDE_CODE_OAUTH_TOKEN, an API key in ANTHROPIC_API_KEY; the other is cleared so
        a stale value can't shadow the active one. The sandbox inherits os.environ."""
        if not self._pool:
            return
        tok = self._pool[self._ti]
        if tok.get("type") == "api":
            os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
            os.environ["ANTHROPIC_API_KEY"] = tok["token"]
        else:
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = tok["token"]

    def _localised(self, prompt: str, phase: str) -> str:
        """The project's language, prepended when a PERSON reads the answer.

        One place per adapter rather than one per role: the four judging methods, the product
        role's, and every future one all funnel through here, so a new conversational role
        cannot silently ship speaking the wrong language — including a phase this package has
        never heard of. The rule is `roles.needs_language_directive`, one for all four harnesses:
        not the coding path, not a verdict code parses, everything else yes."""
        from openfactory.adapters.agent.roles import language_directive, needs_language_directive

        if not needs_language_directive(phase):
            return prompt
        return f"{language_directive(self.language)}\n\n{prompt}"

    def _invoke(
        self,
        sandbox: SandboxAdapter,
        workspace: Workspace,
        prompt: str,
        phase: str,
        *,
        tools: list[str],
        model: str | None,
        context: AgentContext,
        resume_session: str | None = None,
    ) -> AgentRunResult:
        """Run the agent, failing over CYCLICALLY through the credential pool. On a rate-limit /
        auth stop we rotate to the next token — wrapping around, so a job that starts on token 2
        still comes back to token 1 — and we CONTINUE the same session on it (--resume) instead of
        restarting, so most-done work isn't redone. One lap = each token tried once; when a full
        lap finds them ALL exhausted the pause survives → PAUSED (rate) / ON_HOLD (auth), and the
        durable resume tries another lap LATER (after the backoff, when a token's window may have
        reset — retrying an as-yet-unreset token in the same lap would be pointless). With a single
        token this is the old behaviour (at most one try). Bounded: at most `len(pool)` attempts."""
        started_at = self._ti  # to report whether we rotated during this invocation
        n = len(self._pool) or 1  # laps are bounded by pool size; guard the single/empty case
        # C2 resume: if THIS phase is the one that paused before, restore its session state and
        # continue it with --resume. Only when the restore actually succeeds — else run cold.
        # A caller-supplied session (recovery's in-container continue) skips the S3 machinery —
        # the transcript is already on local disk.
        if resume_session is None:
            resume_session = self._resume_session_for(phase, context, sandbox, workspace)
        prompt = self._localised(prompt, phase)
        attempts = 0
        saw_rate, first_retry = False, None  # lap-wide: any rate-limited token → resumable
        while True:
            self._apply_token()
            res = self._invoke_once(sandbox, workspace, prompt, phase, tools=tools,
                                    model=model, context=context, resume_session=resume_session)
            attempts += 1
            if res.pause_reason == "rate_limit":
                saw_rate, first_retry = True, (first_retry or res.retry_at)
            # AGNOSTIC telemetry: which credential produced this + whether we rotated. The core
            # only surfaces it (panel visibility + proof failover ran); it never sees the token.
            # The `id` (an operator-chosen label, e.g. "primary"/"secondary") is the human
            # identifier — a sha256 fingerprint was noise (unrecognisable next to a real token).
            if self._pool:
                tok = self._pool[self._ti]
                res.credential = {
                    "index": self._ti + 1, "total": len(self._pool),
                    "id": tok.get("id", "?"), "rotated": self._ti != started_at,
                }
            paused = res.pause_reason in ("rate_limit", "auth")
            if not (paused and attempts < n):
                # A full lap found every token exhausted (or a non-pause result). MIXED lap
                # (audit HIGH): if ANY token was merely rate-limited, the pause must survive as
                # rate_limit — PAUSED auto-resumes when that token's window resets — instead of
                # letting a revoked token seen LAST turn the whole job into a human-only
                # ON_HOLD and discard the resumable session.
                if paused and saw_rate and res.pause_reason != "rate_limit":
                    res.pause_reason, res.retry_at = "rate_limit", first_retry
                # On any RESUMABLE stop, snapshot the session so a later run can continue it,
                # and upgrade the raw session id into the full opaque handle. Resumable =
                # a rate-limit pause OR an unfinished non-pause stop (turn-cap, error result) —
                # ADR-0013 D1: work is preserved on ANY stop, so a hold can be continued instead
                # of redone. Use the freshest KNOWN session — the last attempt's, or the one
                # accumulated during the lap (a final attempt that died before emitting any JSON
                # must not throw away a session captured one attempt earlier — audit HIGH).
                sess = res.resume_handle or resume_session
                t = getattr(context, "ticket", None)
                resumable = res.pause_reason == "rate_limit" or (
                    not res.ok and res.pause_reason is None)
                if resumable and sess and t is not None:
                    # Keep the session only for a phase something can replay it into — see
                    # `_RESUMABLE_PHASES`. The handle is still minted either way: it is what the
                    # core round-trips, and an empty `state_key` is exactly how a resume knows to
                    # run cold.
                    key = (_snapshot_session(sess, self._safe(t.repo), self._safe(t.id),
                                             sandbox=sandbox, workspace=workspace)
                           if phase in _RESUMABLE_PHASES else "")
                    res.resume_handle = _encode_handle(phase, sess, key)
                return res
            # Rotate to the next credential (wrapping around), CONTINUING the same session rather
            # than restarting it. The just-failed invocation may have done most of the work (e.g.
            # 80% before a rate limit); we hand its session id to the next token via --resume so it
            # picks up where we stopped instead of replanning/redoing (which also re-burned the
            # fresh token). The transcript is on local disk in THIS container → no S3 for same-run
            # rotation; S3 only backs the cross-container DURABLE resume (C2).
            resume_session = res.resume_handle or resume_session
            prev, self._ti = self._pool[self._ti]["id"], (self._ti + 1) % n
            print(
                f"OPENFACTORY_TOKEN: token '{prev}' hit {res.pause_reason} — failing over to "
                f"'{self._pool[self._ti]['id']}' ({self._ti + 1}/{len(self._pool)}), "
                f"continuing session {resume_session or '(none)'}",
                flush=True,
            )

    @staticmethod
    def _safe(s: str) -> str:
        """A path-safe token for the snapshot key (repo/issue may carry '/' or '#')."""
        return re.sub(r"[^A-Za-z0-9._-]", "-", s or "x")

    def _resume_session_for(
        self, phase: str, context: AgentContext,
        sandbox: SandboxAdapter | None = None, workspace: Workspace | None = None,
    ) -> str:
        """If the job is resuming and the paused phase == this phase, restore the CLI session
        state INTO THIS BOX and return the session id to `--resume`. Otherwise "" (run cold). Two
        gates keep a bad restore from BREAKING the run instead of degrading it: the restore must
        succeed, AND the session's transcript must actually be in the box afterwards — passing
        --resume for a session the CLI can't find errors the whole invocation (audit HIGH), which
        would turn a resumable pause into a bogus hold. Missing/failed anything → run cold."""
        h = _decode_handle(getattr(context, "resume_handle", "") or "")
        if not h or h.get("phase") != phase:
            return ""
        if sandbox is None or workspace is None:
            return ""  # no box to restore into: the session belongs to a box, not to this process
        if not _restore_session(h.get("state_key", ""), sandbox=sandbox, workspace=workspace):
            return ""
        # the transcript must be present at <box HOME>/.claude/projects/<dir>/<session>.jsonl
        if not _session_is_in_the_box(sandbox, workspace, h["session"]):
            print(f"OPENFACTORY_RESUME: restored state lacks session {h['session']} — running cold",
                  flush=True)
            return ""
        print(f"OPENFACTORY_RESUME: continuing {phase} session {h['session']}", flush=True)
        return h["session"]

    def _invoke_once(
        self,
        sandbox: SandboxAdapter,
        workspace: Workspace,
        prompt: str,
        phase: str,
        *,
        tools: list[str],
        model: str | None,
        context: AgentContext,
        resume_session: str = "",
    ) -> AgentRunResult:
        rc, out = sandbox.run(
            workspace=workspace,
            command=self._cli(prompt, harness=sandbox.harness_path("claude"), tools=tools,
                              phase=phase,
                              model=model, resume_session=resume_session),
            timeout=_CHAT_TIMEOUT if phase == "chat" else _EXECUTE_TIMEOUT,
        )
        self._write_transcript(context, phase, out)
        if timed_out(rc, out):
            # `tools` is what this invocation actually granted, and it is the ONLY structural way
            # to see a harness spending its pass on a tool it will never be allowed to use — the
            # read-only planner probing `Edit` is denied silently, and four hours of that looks
            # identical to four hours of work from outside. The other three harnesses have no
            # per-tool allow-list to pass, so their readings say they cannot answer that question.
            return wall_result(phase, model, "claude_code", out, granted=tools)
        res = _parse_stream(rc, out, allowed_tools=tools)
        # stamp the cost-telemetry dimensions this layer knows: the model tier the CLI was told
        # to use, and the harness identity. Tokens/cost/turns are filled from the stream by
        # _parse_stream. (observability.metrics reads these off the RunResult.)
        res.model = model or "default"
        res.harness = "claude_code"
        return res

    def _write_transcript(self, context: AgentContext, phase: str, out: str) -> None:
        if not self.log_dir:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        safe = context.ticket.id.lstrip("#").replace("/", "-")
        (self.log_dir / f"{safe}-{phase}.jsonl").write_text(out)


def _action_of(block: dict) -> str | None:
    """Turn a tool_use content block into a readable action line."""
    if block.get("type") != "tool_use":
        return None
    name = block.get("name", "tool")
    inp = block.get("input", {}) if isinstance(block.get("input"), dict) else {}
    target = inp.get("file_path") or inp.get("path") or inp.get("command") or inp.get("pattern")
    return f"{name}: {target}" if target else name


# Claude-specific signals (each agent adapter detects its own — this never leaks
# into the core). Rate/usage limits resume after a reset; auth problems need a fix.
# Usage/rate/session limits all RESUME after a reset (→ rotate the token pool, then PAUSED),
# unlike auth problems which need a human fix. Claude's subscription cap message is
# "You've hit your session limit · resets 10:30pm (UTC)" — the `(reached|hit) your … limit`
# and `session limit` branches catch it (a missing `session limit` once sent a limited job
# straight to on_hold with no failover/pause — partner-reported).
_RATE_LIMIT = re.compile(
    r"(rate.?limit|usage limit|session limit|quota|429|"
    r"(?:reached|hit) your .{0,24}limit|limit reached)",
    re.I,
)
_AUTH = re.compile(
    r"(authentication|unauthorized|401|invalid.{0,12}(api key|token)|expired.{0,12}token|"
    r"please (run )?/?login|credit balance|"
    # An org that turns off subscription access for Claude Code fails EVERY call with this, and it
    # says nothing a rate-limit or a generic error pattern matches. Observed in production
    # 2026-07-27: the run stopped, nothing classified it, and the ticket parked saying only "agent
    # stopped" — which sends whoever reads it looking at the ticket instead of at the credential.
    r"disabled claude subscription|subscription access|use an anthropic api key|"
    r"ask your admin to enable)", re.I
)
_RESET_AT = re.compile(
    r"(?:reset|resume|available|try again|retry)[^0-9]{0,24}"
    r"(\d{4}-\d\d-\d\dT[\d:+.Z-]+|\d{1,2}:\d{2}\s*(?:am|pm)?|\d{1,2}\s*(?:am|pm))",
    re.I,
)


def _detect_pause(text: str) -> tuple[str | None, str | None]:
    """Return (pause_reason, retry_at). reason ∈ {'rate_limit','auth'} or None."""
    if _RATE_LIMIT.search(text):
        m = _RESET_AT.search(text)
        return "rate_limit", (m.group(1) if m else None)
    if _AUTH.search(text):
        return "auth", None
    return None, None


def _parse_stream(
    rc: int, out: str, allowed_tools: list[str] | None = None
) -> AgentRunResult:
    """Parse `--output-format stream-json`: many JSON-lines events. The terminal
    `type == "result"` event carries the outcome and cost; assistant events carry
    tool_use blocks we surface as a readable action trace (for the job journal).

    `allowed_tools` (the set granted to this invocation) filters the trace: a tool that
    was NOT granted cannot actually have run, so a tool_use block for it is a blocked or
    hallucinated *attempt* — e.g. the read-only planner probing `Edit`/`Write`. We drop
    those, so the trace shows real actions only (they once read as "the planner edited")."""
    granted = set(allowed_tools or [])
    final: dict | None = None
    actions: list[str] = []
    session_id = ""  # C2: the Claude session to `--resume` if this invocation pauses
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(evt, dict):
            continue
        if isinstance(evt.get("session_id"), str) and evt["session_id"]:
            session_id = evt["session_id"]  # present on init/result/assistant events; last wins
        if evt.get("type") == "result":
            final = evt
        elif evt.get("type") == "assistant":
            content = evt.get("message", {}).get("content", [])
            if isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if granted and b.get("type") == "tool_use" and b.get("name") not in granted:
                        continue  # a tool the invocation didn't grant → blocked attempt
                    a = _action_of(b)
                    if a:
                        actions.append(a)
    if final is None:
        # Only classify a pause when the run actually FAILED (rc != 0). A clean exit with no
        # result event is odd but not a limit; scanning its full transcript would false-match
        # any "429"/"quota" the agent merely read or wrote (audit: bogus pause on healthy runs).
        reason, retry = _detect_pause(out) if rc != 0 else (None, None)
        # "no result event in agent output" is true and tells nobody anything: it is the shape a
        # harness takes when it died mid-thought, and the events it DID emit before that are the
        # only account of why. Same reading as the wall (C-39), same reason — a failure must not
        # read as an answer, and an unexplained one reads as "the agent just didn't work".
        stream = reading_of("claude_code", out, granted=allowed_tools or ())
        # A MODEL THIS HARNESS WILL NOT RUN IS A CONFIGURATION FACT, NOT A MYSTERY. The CLI
        # prints one sentence, emits no events and exits ZERO, so without this the job reads as
        # "the agent produced nothing" — an operator who typed one wrong character into
        # `set-model` gets a failed ticket and no way back to the cause. Measured against the
        # real CLI on 2026-08-15, which is also why it is matched on the text: there is no exit
        # code and no event to key on.
        return AgentRunResult(
            ok=False,
            summary=f"no result event in agent output. What the stream shows: {stream.note}",
            actions=actions,
            pause_reason=reason, retry_at=retry, raw_output=out, resume_handle=session_id,
        )
    # Pause detection ONLY on error envelopes. The result text of a SUCCESSFUL run is the
    # agent's own summary/plan — a ticket about rate limiting legitimately says "429" or
    # "rate limit" there, and classifying that as a pause would lap the whole token pool and
    # park a healthy job (audit CRITICAL). Real limit stops arrive with is_error/rc set.
    is_err = bool(final.get("is_error", False)) or rc != 0
    result_text = f"{final.get('result', '')} {final.get('subtype', '')}"
    # A MODEL THIS HARNESS WILL NOT RUN IS A CONFIGURATION FACT, NOT A MYSTERY, and it arrives
    # looking like a successful run: MEASURED on 2026-08-15, the CLI answers `subtype: "success"`
    # with `is_error: true`, `total_cost_usd: 0`, an assistant message from `<synthetic>`, and
    # EXITS ZERO. Its sentence names the model and stops there; what an operator needs is where
    # that name came from and how to change it, before the job burns its repair attempts on a
    # ticket that was never the problem.
    # ON AN ERROR ENVELOPE ONLY, exactly like the pause detection two lines down and for the same
    # audit-CRITICAL reason: the result text of a SUCCESSFUL run is the agent's own prose, and a
    # ticket about model selection legitimately quotes this sentence. Reading that as a
    # configuration failure would fail a healthy job on its own summary.
    if is_err and (rejected := _model_rejection(result_text)):
        return AgentRunResult(
            ok=False,
            summary=(f"{rejected} It is this project's configured model — change it with "
                     "`openfactory project set-model <project> <model>` (`--role` for one role); "
                     "the panel's MODELS gauge shows what is set now."),
            actions=actions, raw_output=out, resume_handle=session_id,
        )
    reason, retry = _detect_pause(result_text) if is_err else (None, None)
    ok = rc == 0 and not final.get("is_error", False) and reason is None
    usage = final.get("usage") or {}
    return AgentRunResult(
        ok=ok,
        summary=_summarize(final, ok, reason),
        cost_usd=final.get("total_cost_usd"),
        actions=actions,
        pause_reason=reason,
        retry_at=retry,
        num_turns=final.get("num_turns"),  # the effort currency (ADR-0013 D4)
        # token usage for the cost dashboard — input includes cache reads/writes when the CLI
        # reports them; absent on older CLIs → None (the dashboard just shows cost then).
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        raw_output=out,
        resume_handle=session_id,  # C2: raw session id; _invoke wraps it into the full handle
    )


def _summarize(final: dict, ok: bool, reason: str | None) -> str:
    """The agent's final message — but when it FAILED with an empty result (the CLI hit the
    turn cap, was interrupted, or errored), surface the SUBTYPE so the operator sees WHY the job
    is on hold instead of a blank "agent stopped:" (it once read as an empty on_hold — no way to
    know it was max-turns). A pause has its own reason, so leave its summary as-is."""
    result = str(final.get("result", "")).strip()
    if ok or reason or result:
        return result[:1000]
    sub = str(final.get("subtype", "") or "")
    turns = final.get("num_turns")
    if "max_turns" in sub:
        n = f" after {turns} turns" if turns else ""
        return (f"reached the {turns or ''}-turn safety cap{n} without finishing — the ticket is "
                "likely too big; split it or raise OPENFACTORY_MAX_TURNS for it").replace("  ", " ")
    return f"agent ended with no result ({sub or 'unknown error'})"
