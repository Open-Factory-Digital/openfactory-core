"""OpenCodeAdapter — OpenCode (opencode.ai) as a coding harness, and the axis's agnostic line.

WHY THIS ONE. `claude_code`, `codex` and `kimi` are each tied to a vendor, so "the harness axis is
agnostic" was true of the seam and unproven in the catalogue. OpenCode is MIT, a single native
binary, and speaks Anthropic, Amazon Bedrock, Azure, OpenAI, Vertex, GitHub Copilot **and any
OpenAI-compatible endpoint you declare** — which is what a client whose IT rejects a vendor-direct
tool, or one reaching Claude through a Foundry deployment, actually needs. Paired with `model:`
(the registry's per-project model), swapping provider becomes configuration rather than a rebuild.

VERIFIED AGAINST THE REAL BINARY (opencode 1.18.13), not against documentation. Every claim below
was observed; where something was not run, it says so.

    opencode run --format json -m <provider/model> -- <prompt>
                 --session <id>          resume; the id is `.sessionID` on every event
                 --agent <name>          the permission profile (see READ-ONLY below)
                 --auto                  auto-approve what is not explicitly denied

FOUR THINGS THAT SHAPE THIS ADAPTER, each found by running it:

1. `--` IS REQUIRED. Without it yargs reads a prompt beginning with `-` as an unknown flag, prints
   its help and never runs — a silent no-op that would look like an agent producing nothing. The
   Codex adapter carries the same guard for the same reason.

2. `--auto` IS REQUIRED, AND IT IS SAFE HERE. A headless run does NOT block waiting for a human:
   an unapproved tool call is AUTO-REJECTED (observed: 4s, `permission requested: bash …;
   auto-rejecting`). So without `--auto` the run does not hang, it silently loses every tool call
   and returns nothing — worse, because it looks like a completed pass. And `--auto` cannot widen
   a `deny`: it only promotes `ask` to `allow` (verified adversarially — see 3).

3. READ-ONLY IS REAL ENFORCEMENT, not a mode. An agent whose `permission` map denies `edit`/`bash`
   has those tools REMOVED from the model's tool list — `opencode debug agent` reports
   `bash: false, edit: false, write: false`, and an agent told to write a file answered that it had
   no tool to do it. That is stronger than Kimi's `--plan` (a mode, i.e. instruction) and on a par
   with Codex's `-s read-only` sandbox policy. It is what makes this harness fit to judge.

4. A CLIENT'S REPOSITORY CAN DEFINE AGENTS, and judging roles run against client checkouts. An
   `opencode.json` at the root of a repo genuinely defines an agent — verified: alone, the hostile
   file granted `bash: true, edit: true, write: true` under the very name this adapter uses for
   its read-only profile. `OPENCODE_CONFIG_CONTENT` wins over it, but precedence is a behaviour of
   one version, so `OPENCODE_DISABLE_PROJECT_CONFIG` is set as well: the repo's file is removed
   from consideration entirely rather than merely out-ranked. A read-only guarantee that a
   reviewed repository can argue with is not a guarantee.

THE PROFILE TRAVELS AS AN ENVIRONMENT VARIABLE, never as a file. Writing `opencode.json` into the
workspace would put framework configuration inside the client's diff, where the executor can commit
it. `OPENCODE_CONFIG_CONTENT` carries the whole config with nothing on disk (verified). It holds
permissions only — no credential ever goes near it.

WHAT IS NOT VERIFIED
- **The Linux/container binary.** Everything above was observed on macOS arm64; the toolbox ships
  a different artefact. `box prove`'s smoke test is what confirms it, per deployment.
- **Bedrock and Azure authentication.** Both providers REGISTER from their env vars (`AWS_PROFILE`
  alone is enough to list 114 Bedrock models), but no call was made through either. Registering is
  not authenticating: presence of a variable proves nothing about the credential behind it.
- **Whether a long answer ever splits into several `text` events within one step.** A 20-line
  answer stayed consolidated; the parser takes the last `text` event either way.
"""

from __future__ import annotations

import json
import os
import re
import shlex

from openfactory.adapters.agent.base import AgentContext, prose_only, ticket_brief, wall_result
from openfactory.adapters.sandbox.base import SandboxAdapter, Workspace
from openfactory.adapters.sandbox.timeouts import AGENT_TIMEOUT, timed_out
from openfactory.contracts import AgentRunResult

_RATE_RE = re.compile(r"rate.?limit|quota|too many requests|429", re.IGNORECASE)
_AUTH_RE = re.compile(r"unauthor|forbidden|invalid api key|invalid x-api-key|401|403",
                      re.IGNORECASE)
_TIMEOUT = AGENT_TIMEOUT

#: The name of the read-only profile this adapter defines and then asks for by name.
JUDGE_AGENT = "openfactory-readonly"

#: The judging profile. `edit: deny` kills BOTH `edit` and `write` (verified). `task` is denied so
#: a judging pass cannot spawn a sub-agent that is not bound by this map, and `question` because a
#: headless run has nobody to ask.
_JUDGE_PERMISSIONS = {
    "edit": "deny", "bash": "deny", "task": "deny", "question": "deny",
    "webfetch": "deny", "websearch": "deny",
    "read": "allow", "grep": "allow", "glob": "allow", "list": "allow",
}


def _checked(model: str | None) -> str | None:
    """Refuse a model string THIS harness cannot resolve, at BUILD time.

    OpenCode addresses a model as `provider/model` — the provider prefix is how the same binary
    reaches Anthropic, Bedrock, Azure or a gateway, and it is the whole reason this harness is on
    the axis. A bare name has no provider, so nothing decides where the call goes.

    WHY IT RAISES RATHER THAN DEGRADING. Measured, not assumed: a job configured with `-m opus`
    (a perfectly good Claude model name, and the value `OPENFACTORY_EXECUTOR_MODEL` holds on this
    deployment) sat for 26 minutes without writing a line. `AGENT_TIMEOUT` is four hours, so the
    ceiling on that mistake is four hours of wall-clock and whatever the harness bills for the
    attempts — for a configuration error visible in one string comparison.

    Same rule as the registry's unknown-kind raise: surface when the runner is built, not hours
    later when a job parks and somebody reads a log to find out why nothing happened.
    """
    name = (model or "").strip()
    if not name:
        return None
    if "/" not in name:
        raise ValueError(
            f"opencode needs `provider/model`, got {name!r} — a bare name has no provider, so the "
            f"run cannot reach any endpoint (e.g. "
            f"`amazon-bedrock/eu.anthropic.claude-haiku-4-5-20251001-v1:0`, "
            f"`anthropic/claude-opus-5`). Check the project's `model:` and any "
            f"OPENFACTORY_*_MODEL variable set on this deployment."
        )
    return name


def judge_config() -> str:
    """The read-only profile, as the JSON `OPENCODE_CONFIG_CONTENT` carries.

    Permissions only. No credential, no endpoint, nothing secret — this string appears in the
    command line the sandbox runs, and everything in it is safe to see there."""
    return json.dumps({"agent": {JUDGE_AGENT: {
        "mode": "primary",
        "description": "read-only judging role (openfactory)",
        "permission": dict(_JUDGE_PERMISSIONS),
    }}}, separators=(",", ":"))


class OpenCodeAdapter:
    """OpenCode, driven non-interactively through the sandbox (never on the host)."""

    name = "opencode"

    def __init__(self, *, model: str | None = None, log_dir=None,
                 language: str | None = None) -> None:
        self.model = _checked(model or os.environ.get("OPENFACTORY_EXECUTOR_MODEL") or None)
        self.planner_model = _checked(os.environ.get("OPENFACTORY_PLANNER_MODEL")) or self.model
        self.log_dir = log_dir
        #: the project's language for anything a human reads (agent/roles.py)
        self.language = language

    # ---- the coding contract -----------------------------------------------------------------

    def plan(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, context: AgentContext
    ) -> AgentRunResult:
        prompt = (
            "Investigate this ticket READ-ONLY and produce a concrete execution plan.\n"
            "Do not modify any file.\n\n" + ticket_brief(context)
        )
        return self._run(sandbox, workspace, prompt, model=self.planner_model,
                         read_only=True, phase="plan")

    def ask(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, prompt: str, phase: str = "ask"
    ) -> AgentRunResult:
        """Run a READ-ONLY prompt against the checkout and return the text (see roles.py).

        Read-only by ENFORCEMENT: the profile removes `edit`, `write`, `bash` and `task` from the
        model's tool list, and `--auto` cannot promote a denied permission."""
        return self._run(sandbox, workspace, prompt, model=self.planner_model,
                         read_only=True, phase=phase)

    def execute(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, context: AgentContext
    ) -> AgentRunResult:
        prompt = ticket_brief(context)
        if context.plan:
            prompt += f"\n\n## The plan to follow\n{context.plan}"
        return self._run(sandbox, workspace, prompt, model=self.model,
                         resume_session=context.resume_handle)

    def repair(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, context: AgentContext,
        failure_log: str,
    ) -> AgentRunResult:
        prompt = (
            "The project's own validation gates FAILED on your change. Fix them, staying strictly "
            "in scope — fix the cause, never silence a gate or delete a test.\n\n"
            f"## Failures\n{failure_log[:12000]}\n\n" + ticket_brief(context)
        )
        return self._run(sandbox, workspace, prompt, model=self.model)

    # ---- command construction (exact, from the observed CLI) ----------------------------------

    def _cli(
        self, prompt: str, *, harness: str, model: str | None, read_only: bool = False,
        resume_session: str = "",
    ) -> str:
        # `harness` is the ABSOLUTE path the box chose — never a bare name, which `PATH` inside
        # the client's image would resolve (ADR-0037 D2).
        env = [f"OPENCODE_CONFIG_CONTENT={shlex.quote(judge_config())}"] if read_only else []
        # ALWAYS, not only for judging: the repo's own `opencode.json` must not reach any run of
        # ours. For a judging pass it is a permission escalation; for a coding pass it would let
        # the repository silently redirect the model or the provider we are billing for.
        env.append("OPENCODE_DISABLE_PROJECT_CONFIG=1")

        cmd = [*env, harness, "run", "--format", "json"]
        if model:
            cmd += ["-m", shlex.quote(model)]
        if read_only:
            cmd += ["--agent", JUDGE_AGENT]
        if resume_session:
            # NEVER `--continue`: it resumes the most recently used session PROCESS-WIDE, so two
            # concurrent jobs on one worker would resume into each other's conversation. Verified:
            # after forking, `--continue` picked up the fork, not the caller's own session.
            cmd += ["--session", shlex.quote(resume_session)]
        # `--auto` approves what is not denied. The read-only profile's denials outrank it, so the
        # judging roles stay read-only WITH it (verified adversarially).
        cmd += ["--auto", "--", shlex.quote(prompt)]
        return " ".join(cmd)

    def _localised(self, prompt: str, phase: str) -> str:
        """The project's language, when a PERSON reads the answer (`roles.needs_language_directive`:
        not the coding path, not a verdict code parses, everything else — an unknown phase too)."""
        from openfactory.adapters.agent.roles import language_directive, needs_language_directive

        if not needs_language_directive(phase):
            return prompt
        return f"{language_directive(self.language)}\n\n{prompt}"

    def _run(
        self, sandbox: SandboxAdapter, workspace: Workspace, prompt: str, *,
        model: str | None, read_only: bool = False, resume_session: str = "",
        phase: str = "execute",
    ) -> AgentRunResult:
        prompt = self._localised(prompt, phase)
        command = self._cli(prompt, harness=sandbox.harness_path("opencode"), model=model,
                            read_only=read_only, resume_session=resume_session)
        code, out = sandbox.run(workspace=workspace, command=command, timeout=_TIMEOUT)
        if timed_out(code, out):
            return wall_result("agent", model, self.name, out)

        events = _parse_jsonl(out)
        text = _final_text(events)
        pause, retry_at = _pause_from(events, out)

        # EXIT 0 WITH NO TEXT IS A FAILURE, not an empty answer. When a tool call is auto-rejected
        # the run aborts with `step_finish(reason: "tool-calls")` and exits 0 having said nothing.
        # Reporting that as a successful pass would let the orchestrator advance a ticket on the
        # strength of an agent that never spoke.
        errored = any(e.get("type") == "error" for e in events)
        res = AgentRunResult(
            ok=code == 0 and pause is None and not errored and bool(text),
            summary=text or _failure_summary(events, out),
            actions=_actions(events),
            model=model or "default",
            harness=self.name,
            pause_reason=pause,
            retry_at=retry_at,
            raw_output=_scrub(out)[-20000:],
        )
        _apply_usage(res, events)
        res.resume_handle = _session_id(events) or None
        return res


# ── the event stream, as observed ────────────────────────────────────────────────────────────────
#
# JSONL — one object per line. Every event carries `type`, `timestamp`, `sessionID` and `part`,
# EXCEPT errors, where `error` replaces `part`. Note the top-level `type` uses underscores while
# `part.type` uses hyphens (`step_finish` / `step-finish`); everything here reads the top level.

def _parse_jsonl(out: str) -> list[dict]:
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


def _part(event: dict) -> dict:
    part = event.get("part")
    return part if isinstance(part, dict) else {}


def _final_text(events: list[dict]) -> str:
    """The assistant's answer: the LAST `text` event. Text arrives consolidated rather than as
    deltas, but a run that interleaves tool calls emits several, and the last one is the answer."""
    texts = [_part(e).get("text") for e in events if e.get("type") == "text"]
    return next((t.strip() for t in reversed(texts) if isinstance(t, str) and t.strip()), "")


def _session_id(events: list[dict]) -> str:
    """`.sessionID`, present on every event including the first — so a run that dies after one
    line is still resumable."""
    for ev in events:
        sid = ev.get("sessionID")
        if isinstance(sid, str) and sid:
            return sid
    return ""


def _actions(events: list[dict]) -> list[str]:
    out: list[str] = []
    for ev in events:
        if ev.get("type") != "tool_use":
            continue
        part = _part(ev)
        tool = part.get("tool")
        if isinstance(tool, str) and tool.strip():
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            status = state.get("status")
            out.append(f"{tool.strip()}{'' if status == 'completed' else f' ({status})'}"[:200])
        if len(out) >= 200:
            break
    return out


def _apply_usage(res: AgentRunResult, events: list[dict]) -> None:
    """Tokens, turns and cost — all of which arrive PER STEP and have to be summed.

    COST 0 IS REPORTED AS UNKNOWN, deliberately. A provider declared by the deployment (the
    OpenAI-compatible route) carries no pricing metadata, so its steps come back `cost: 0` —
    verified. Passing that through would show a client's gateway spend as zero dollars in the one
    instrument every spending decision is read from. A genuinely free model reporting "unknown"
    is the harmless direction of that error."""
    steps = [e for e in events if e.get("type") == "step_finish"]
    starts = sum(1 for e in events if e.get("type") == "step_start")

    inp = out = 0
    cost = 0.0
    for ev in steps:
        tokens = _part(ev).get("tokens")
        if isinstance(tokens, dict):
            inp += tokens.get("input") or 0
            out += tokens.get("output") or 0
        value = _part(ev).get("cost")
        if isinstance(value, (int, float)):
            cost += float(value)

    if inp:
        res.input_tokens = inp
    if out:
        res.output_tokens = out
    if starts:
        res.num_turns = starts
    res.cost_usd = cost if cost > 0 else None


def _pause_from(events: list[dict], out: str) -> tuple[str | None, str | None]:
    """An infra pause rather than a code failure. The status code is authoritative when the stream
    carries one; the text match covers only what the stream could not (see `prose_only`)."""
    for ev in events:
        if ev.get("type") != "error":
            continue
        data = (ev.get("error") or {}).get("data") or {}
        status = data.get("statusCode")
        if status in (429, 529):
            return "rate_limit", None
        if status in (401, 403):
            return "auth", None
        message = str(data.get("message") or "")
        if _RATE_RE.search(message):
            return "rate_limit", None
        if _AUTH_RE.search(message):
            return "auth", None
    tail = prose_only(out)[-4000:]
    if _RATE_RE.search(tail):
        return "rate_limit", None
    if _AUTH_RE.search(tail):
        return "auth", None
    return None, None


def _failure_summary(events: list[dict], out: str) -> str:
    """Why nothing came back — named, because "the agent produced no output" sends a human to read
    a 20,000-line log for a sentence that is already here."""
    for ev in events:
        if ev.get("type") == "error":
            err = ev.get("error") or {}
            data = err.get("data") or {}
            return (f"the harness reported {err.get('name') or 'an error'}: "
                    f"{str(data.get('message') or '')[:400]}")
    rejected = [a for a in _actions(events) if "(error)" in a]
    if rejected:
        return ("the run stopped after a tool call was refused — the harness ran without approval "
                f"for: {', '.join(rejected[:5])}")
    return (_scrub(out) or "").strip()[-4000:]


#: Keys an error event echoes straight from the provider. `responseHeaders` can carry
#: authentication echoes and `responseBody` arbitrary provider detail, and `raw_output` is written
#: to the journal, shown in the panel and quoted into pull requests.
_ECHO_KEYS = ("responseHeaders", "responseBody")


def _scrub(out: str) -> str:
    """Drop the provider echo from error events, keeping every line otherwise byte-identical."""
    lines = []
    for line in (out or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("{") and any(k in stripped for k in _ECHO_KEYS):
            try:
                obj = json.loads(stripped)
            except ValueError:
                lines.append(line)
                continue
            data = ((obj.get("error") or {}).get("data")
                    if isinstance(obj.get("error"), dict) else None)
            if isinstance(data, dict):
                for key in _ECHO_KEYS:
                    data.pop(key, None)
                lines.append(json.dumps(obj, separators=(",", ":")))
                continue
        lines.append(line)
    return "\n".join(lines)
