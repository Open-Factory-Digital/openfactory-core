"""CodexAdapter — the OpenAI Codex CLI as a coding harness.

Built against the REAL `codex exec --help` surface (verified 2026-07-26), not from memory:

    codex exec [OPTIONS] [PROMPT]        prompt as an argument, or on stdin
    codex exec resume <SESSION_ID> …     continue a previous session
    -m, --model <MODEL>                  model selection
    -C, --cd <DIR>                       working root
    -s, --sandbox <read-only|workspace-write|danger-full-access>
        --dangerously-bypass-approvals-and-sandbox   (for externally-sandboxed environments)
        --json                           JSONL event stream on stdout
    -o, --output-last-message <FILE>     the agent's final message, written to a file
        --skip-git-repo-check            allow running outside a git repo
    -c, --config <key=value>             TOML config override

It implements the MINIMUM contract (`execute` + `repair`) plus `plan`, and deliberately not
`continue_execute` / `recover`: those resume a live session across containers, which for Claude
needs a whole S3 snapshot/restore machinery this adapter has no equivalent of yet. The
orchestrator probes for them with `hasattr` and degrades — a turn-capped Codex run parks for a
human instead of self-healing. That is a real capability gap, stated rather than faked.

WHAT IS AND ISN'T PROVEN HERE
- The command construction is exact — every flag above came from `--help`.
- The final message comes from `--output-last-message`, a file whose contract is "the last
  message", so `summary` does not depend on any event schema.
- The `--json` event schema was OBSERVED from real runs against codex-cli 0.145.0, not guessed:
      {"type":"thread.started","thread_id":"…"}                       ← the id `exec resume` takes
      {"type":"turn.started"} / {"type":"turn.completed","usage":{…}}
      {"type":"item.completed","item":{"type":"command_execution","command":…,"exit_code":…}}
      {"type":"item.completed","item":{"type":"file_change","changes":[{"path":…,"kind":…}]}}
      {"type":"item.completed","item":{"type":"agent_message","text":…}}
  Parsing is still defensive (unknown shapes degrade rather than raise), because one CLI version
  is not a contract.
- There is NO cost and NO turn count in that stream. `cost_usd` therefore stays None and turns are
  DERIVED by counting `turn.completed`. Inventing a cost would poison the very A/B this harness
  exists to be compared in.
- Rate-limit / auth pause detection is TEXT-MATCHED and unverified against a real Codex rate
  limit. Until one is observed, a limit most likely surfaces as a plain failure (the job parks for
  a human) rather than as a resumable PAUSE. Do not read the pause path here as working.
"""

from __future__ import annotations

import json
import os
import re
import shlex

from openfactory.adapters.agent.base import (
    PLANNER_FALLBACK,
    REPAIR_INSTRUCTION,
    AgentContext,
    prose_only,
    ticket_brief,
    wall_result,
)
from openfactory.adapters.agent.roles import role_prompt
from openfactory.adapters.sandbox.base import SandboxAdapter, Workspace
from openfactory.adapters.sandbox.timeouts import AGENT_TIMEOUT, timed_out
from openfactory.contracts import AgentRunResult

# The agent's final message is written here (inside the workspace's container/worktree) and read
# back THROUGH the sandbox — on a container sandbox the host cannot see the file at all.
_LAST_MESSAGE_FILE = ".openfactory-codex-last-message"

# Markers that suggest a usage/auth stop rather than a code failure. Unverified against a real
# Codex limit — see the module docstring.
_RATE_RE = re.compile(r"rate.?limit|quota|too many requests|429", re.IGNORECASE)
_AUTH_RE = re.compile(r"unauthor|forbidden|invalid api key|not logged in|401|403", re.IGNORECASE)


class CodexAdapter:
    """The Codex CLI, driven non-interactively through the sandbox (never on the host)."""

    name = "codex"

    def __init__(
        self, *, model: str | None = None, log_dir=None,
        full_access: bool | None = None, language: str | None = None,
    ) -> None:
        self.model = model or os.environ.get("OPENFACTORY_EXECUTOR_MODEL") or None
        self.planner_model = os.environ.get("OPENFACTORY_PLANNER_MODEL") or self.model
        self.log_dir = log_dir
        #: the project's language for anything a human reads (agent/roles.py)
        self.language = language
        # `workspace-write` is the default, and it is VERIFIED sufficient: a probe run against
        # codex-cli 0.145.0 executed a shell command AND edited a file non-interactively with no
        # approval prompt. That matters because this codebase learned the opposite lesson the hard
        # way with Claude — a headless policy that gates shell commands silently DENIES every
        # `pytest` the agent runs, killing its own TDD loop while it reports that commands are
        # blocked. Codex does not have that failure mode under `workspace-write`.
        #
        # The escape hatch stays only for a case we have not tested: a project whose agent needs
        # to write OUTSIDE its workspace or reach the network. The job box is an ephemeral,
        # credential-less, isolated Fargate task — the "externally sandboxed" case the flag's own
        # help text names — so it is legitimate there. It is never the default.
        self.full_access = (
            full_access if full_access is not None
            else os.environ.get("OPENFACTORY_CODEX_FULL_ACCESS", "").lower() in ("1", "true", "yes")
        )

    # ---- the coding contract -----------------------------------------------------------------

    def plan(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, context: AgentContext
    ) -> AgentRunResult:
        """Read-only investigation → a plan. `-s read-only` IS the permission envelope here:
        Codex has no per-tool allowlist, so the sandbox policy is what makes this stage
        genuinely incapable of editing, rather than merely instructed not to.

        `role_prompt("planner")` is the same primitive `claude_code.py` reads, so
        `org_defaults/roles/planner.md` — a deployment's or project's own house doctrine —
        reaches this harness too, rather than the fixed sentence below (kept only for an
        install that could not read its own role file)."""
        role = role_prompt("planner")
        prompt = f"{role}\n\n{ticket_brief(context)}" if role else (
            f"{PLANNER_FALLBACK}\n\n{ticket_brief(context)}")
        return self._run(sandbox, workspace, prompt, "planner",
                         model=self.planner_model, sandbox_mode="read-only")

    def ask(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, prompt: str, phase: str = "ask"
    ) -> AgentRunResult:
        """Run a READ-ONLY prompt against the checkout and return the text (see roles.py).

        `-s read-only` is a sandbox POLICY, so a judging role here is genuinely incapable of
        editing rather than merely instructed not to — a stronger guarantee than a prompt."""
        return self._run(sandbox, workspace, prompt, phase,
                         model=self.planner_model, sandbox_mode="read-only")

    def execute(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, context: AgentContext
    ) -> AgentRunResult:
        """`role_prompt("executor")` prepended, same as `claude_code.py`'s `_executor_prompt` —
        so `org_defaults/roles/executor.md` (TDD discipline, scope limits) reaches this harness
        rather than a role-neutral ticket brief."""
        role = role_prompt("executor")
        prompt = f"{role}\n\n{ticket_brief(context)}" if role else ticket_brief(context)
        if context.plan:
            prompt += f"\n\n## The plan to follow\n{context.plan}"
        return self._run(sandbox, workspace, prompt, "executor", model=self.model,
                         resume_session=context.resume_handle)

    def repair(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, context: AgentContext,
        failure_log: str,
    ) -> AgentRunResult:
        """Repair is the executor role continuing, same as `claude_code.py`'s `repair()` reusing
        `_executor_prompt` — the role identity leads when available, then the repair instruction
        (always present — it says what THIS pass is, which the role prompt does not), then the
        failures and the ticket."""
        role = role_prompt("executor")
        lead = f"{role}\n\n" if role else ""
        prompt = (
            lead + f"{REPAIR_INSTRUCTION}\n\n"
            f"## Failures\n{failure_log[:12000]}\n\n" + ticket_brief(context)
        )
        return self._run(sandbox, workspace, prompt, "repair", model=self.model)

    # ---- command construction (exact, from `codex exec --help`) --------------------------------

    def _cli(
        self, prompt: str, *, harness: str, model: str | None, sandbox_mode: str,
        resume_session: str = "",
    ) -> str:
        # `harness` is the ABSOLUTE path the box chose — never a bare name,
        # which `PATH` inside the client's image would resolve (ADR-0037 D2).
        cmd = [harness, "exec"]
        if resume_session:
            cmd += ["resume", shlex.quote(resume_session)]
        cmd += [
            "--json",                       # JSONL events on stdout (parsed best-effort)
            "-o", _LAST_MESSAGE_FILE,       # the final message, schema-free
            "--skip-git-repo-check",        # the workspace is a checkout, not always a repo root
        ]
        if self.full_access:
            cmd += ["--dangerously-bypass-approvals-and-sandbox"]
        else:
            cmd += ["-s", sandbox_mode]
        if model:
            cmd += ["-m", shlex.quote(model)]
        cmd += ["--", shlex.quote(prompt)]  # `--` so a prompt starting with '-' is not a flag
        return " ".join(cmd)

    def _localised(self, prompt: str, phase: str) -> str:
        """The project's language, when a PERSON reads the answer (`roles.needs_language_directive`:
        not the coding path, not a verdict code parses, everything else — an unknown phase too)."""
        from openfactory.adapters.agent.roles import language_directive, needs_language_directive

        if not needs_language_directive(phase):
            return prompt
        return f"{language_directive(self.language)}\n\n{prompt}"

    def _run(
        self, sandbox: SandboxAdapter, workspace: Workspace, prompt: str, role: str, *,
        model: str | None, sandbox_mode: str = "workspace-write", resume_session: str = "",
    ) -> AgentRunResult:
        prompt = self._localised(prompt, role)
        command = self._cli(prompt, harness=sandbox.harness_path("codex"),
                            model=model, sandbox_mode=sandbox_mode,
                            resume_session=resume_session)
        code, out = sandbox.run(workspace=workspace, command=command, timeout=_TIMEOUT)
        if timed_out(code, out):
            # Codex has NO turn cap, so this wall is its only effort bound — see the module
            # docstring. Reported as an impediment with the cause named, never a bare failure.
            return wall_result(role, model, self.name, out)

        # The final message comes from the FILE, not the event stream — that contract is
        # documented, the event schema is not. Read it back through the sandbox: on a container
        # sandbox the host cannot see this path.
        _, last = sandbox.run(
            workspace=workspace,
            command=f"cat {_LAST_MESSAGE_FILE} 2>/dev/null; rm -f {_LAST_MESSAGE_FILE}",
            timeout=60,
        )
        summary = (last or "").strip()

        events = _parse_jsonl(out)
        pause, retry_at = _pause_from(out)
        res = AgentRunResult(
            ok=code == 0 and pause is None,
            summary=summary or (out or "")[-2000:],
            actions=_actions(events),
            model=model or "default",
            harness=self.name,
            pause_reason=pause,
            retry_at=retry_at,
            raw_output=(out or "")[-20000:],
        )
        _apply_usage(res, events)
        res.resume_handle = _session_id(events) or None
        return res


# the shared wall-clock wall — see openfactory/adapters/sandbox/timeouts.py
_TIMEOUT = AGENT_TIMEOUT


def _parse_jsonl(out: str) -> list[dict]:
    """Every JSON object on its own line. Non-JSON lines (the CLI also prints human text) are
    skipped rather than fought — this stream is a bonus, not the contract."""
    events: list[dict] = []
    for line in (out or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            events.append(obj)
    return events


def _walk(obj, key: str):
    """First value for `key` anywhere in a nested structure. The event schema is unknown, so we
    look for well-known NAMES rather than assume a shape."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = _walk(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _walk(v, key)
            if found is not None:
                return found
    return None


def _session_id(events: list[dict]) -> str:
    """Codex emits `{"type":"thread.started","thread_id":"…"}` first — that id is what
    `codex exec resume <ID>` takes. The extra key names are tolerated fallbacks in case the
    stream is renamed; the observed one is `thread_id`."""
    for ev in events:
        if ev.get("type") == "thread.started" and isinstance(ev.get("thread_id"), str):
            return ev["thread_id"]
    for ev in events:
        for key in ("thread_id", "session_id", "sessionId", "conversation_id"):
            val = _walk(ev, key)
            if isinstance(val, str) and val:
                return val
    return ""


def _actions(events: list[dict]) -> list[str]:
    """A human-readable trace for the job journal, in the same shape the other harness produces
    ("Bash: pytest", "Edit app/health.py").

    Built from the OBSERVED item schema: `item.completed` carries an `item` whose `type` is
    `command_execution` (with `command`), `file_change` (with `changes[].path`) or `agent_message`
    (prose, which is not an action). Capped so a chatty run cannot flood the journal."""
    out: list[str] = []
    for ev in events:
        if ev.get("type") != "item.completed":
            continue
        item = ev.get("item")
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "command_execution":
            cmd = str(item.get("command") or "").strip()
            if cmd:
                out.append(f"Bash: {cmd[:200]}")
        elif kind == "file_change":
            for change in item.get("changes") or []:
                if isinstance(change, dict) and change.get("path"):
                    verb = str(change.get("kind") or "edit").capitalize()
                    out.append(f"{verb} {change['path']}"[:200])
        if len(out) >= 200:
            break
    return out


def _apply_usage(res: AgentRunResult, events: list[dict]) -> None:
    """Token + turn telemetry from the observed stream.

    `turn.completed` carries `usage.input_tokens` / `usage.output_tokens`; there is NO cost and no
    turn count in the stream, so `cost_usd` stays None (the dashboard renders unknown) and turns
    are DERIVED by counting completed turns — a real number, not an invented one. Reporting a
    fabricated cost would poison the very A/B this harness exists to be compared in."""
    turns = 0
    for ev in events:
        if ev.get("type") != "turn.completed":
            continue
        turns += 1
        usage = ev.get("usage")
        if isinstance(usage, dict):
            for key, field in (("input_tokens", "input_tokens"),
                               ("output_tokens", "output_tokens")):
                val = usage.get(key)
                if isinstance(val, int):
                    setattr(res, field, (getattr(res, field) or 0) + val)
    if turns:
        res.num_turns = turns


def _pause_from(out: str) -> tuple[str | None, str | None]:
    """Classify a usage/auth stop. UNVERIFIED against a real Codex rate limit (see the module
    docstring): the patterns are the generic ones, so treat a `None` here as "we have not seen
    Codex rate-limit yet", not as proof it cannot."""
    tail = prose_only(out)[-4000:]
    if _RATE_RE.search(tail):
        return "rate_limit", None
    if _AUTH_RE.search(tail):
        return "auth", None
    return None, None
