"""KimiAdapter — Kimi Code (Moonshot) as a coding harness.

Built against the REAL `kimi --help` surface (kimi-code 0.29.1, verified 2026-07-26):

    kimi -p, --prompt <prompt>        run ONE prompt non-interactively and print the response
         --output-format text|stream-json
    -m, --model <model>               model alias (else `default_model` in config.toml)
    -S, --session [id]                resume a session by id
    -c, --continue                    continue the previous session for this working directory
    -y, --yolo                        auto-approve regular tool calls; MAY STILL ASK QUESTIONS
        --auto                        fully autonomous: the agent will NOT ask questions
        --plan                        start in plan mode
        --add-dir <dir>               extra workspace directory (repeatable)
    kimi login                        device-code authentication

TWO DIFFERENCES FROM CODEX THAT SHAPE THIS ADAPTER

1. `--auto`, not `-y`. In a headless job there is nobody to answer a question, and `-y/--yolo`'s
   own help says the agent "may still ask questions" — a run that stops to ask is a run that
   burns its budget and returns nothing. `--auto` is the only flag whose contract is "will not
   ask". This codebase already paid for that lesson once with Claude, where an approval-gated
   headless run silently denied every `pytest` the agent tried and killed its own TDD loop.

2. There is NO sandbox-policy flag. Codex has `-s read-only`, which makes its planner genuinely
   INCAPABLE of editing. Kimi has only `--plan` (a mode). So the plan stage here is read-only by
   MODE AND INSTRUCTION, not by enforcement — a weaker guarantee, stated rather than papered over.
   The isolation that does hold is the sandbox the platform already puts around it: an ephemeral,
   credential-less Fargate box (ADR-0001 D-4). It cannot escape the box; it could in principle
   edit inside it during a plan.

   There is also no `--cd`: the working directory is the process's, which is exactly what the
   platform's sandbox already sets (`sandbox.run(workspace=…)` runs in the workspace). Nothing to
   pass, nothing to get wrong.

WHAT IS NOT VERIFIED — read this before trusting a number from here
- **The `stream-json` schema is unknown.** Nobody has run this binary yet (Moonshot access is
  pending), so actions/usage/session-id parsing is a defensive best-effort over plausible shapes.
  Unknown shapes degrade to None/[] and NEVER raise. Cost is left None rather than invented.
- **Session resume is untested.** `-S <id>` is documented, but which id and where it appears in
  the stream is not; if the id cannot be recovered, a resumed run starts cold — which the
  orchestrator already handles.
- **Rate-limit/auth detection is text-matched** and unverified, exactly as for Codex.

The first real run is the acceptance test. Until then treat this as wired, not proven — the
harness seam makes it one table entry, so correcting it costs a small diff, not a redesign.
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
_AUTH_RE = re.compile(r"unauthor|forbidden|invalid api key|not logged in|401|403", re.IGNORECASE)
# the shared wall-clock wall — see openfactory/adapters/sandbox/timeouts.py
_TIMEOUT = AGENT_TIMEOUT


class KimiAdapter:
    """Kimi Code, driven non-interactively through the sandbox (never on the host)."""

    name = "kimi"

    def __init__(self, *, model: str | None = None, log_dir=None,
                 language: str | None = None) -> None:
        self.model = model or os.environ.get("OPENFACTORY_EXECUTOR_MODEL") or None
        self.planner_model = os.environ.get("OPENFACTORY_PLANNER_MODEL") or self.model
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
                         plan_mode=True, phase="plan")

    def ask(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, prompt: str, phase: str = "ask"
    ) -> AgentRunResult:
        """Run a READ-ONLY prompt against the checkout and return the text (see roles.py).

        WEAKER than the other harnesses: Kimi exposes no sandbox-policy flag, so this is plan
        MODE plus instruction, not enforcement. It cannot escape the platform's own ephemeral box,
        but it could in principle edit inside it while judging."""
        return self._run(sandbox, workspace,
                         "Answer READ-ONLY. Do not modify any file.\n\n" + prompt,
                         model=self.planner_model, plan_mode=True, phase=phase)

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

    # ---- command construction (exact, from `kimi --help`) -------------------------------------

    def _cli(
        self, prompt: str, *, harness: str, model: str | None, plan_mode: bool = False,
        resume_session: str = ""
    ) -> str:
        # `harness` is the ABSOLUTE path the box chose — never a bare name,
        # which `PATH` inside the client's image would resolve (ADR-0037 D2).
        cmd = [harness, "--auto", "--output-format", "stream-json"]
        if plan_mode:
            cmd += ["--plan"]
        if model:
            cmd += ["-m", shlex.quote(model)]
        if resume_session:
            cmd += ["-S", shlex.quote(resume_session)]
        cmd += ["-p", shlex.quote(prompt)]
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
        model: str | None, plan_mode: bool = False, resume_session: str = "",
        phase: str = "execute",
    ) -> AgentRunResult:
        prompt = self._localised(prompt, phase)
        command = self._cli(prompt, harness=sandbox.harness_path("kimi"),
                            model=model, plan_mode=plan_mode,
                            resume_session=resume_session)
        code, out = sandbox.run(workspace=workspace, command=command, timeout=_TIMEOUT)
        if timed_out(code, out):
            return wall_result("agent", model, self.name, out)

        events = _parse_jsonl(out)
        pause, retry_at = _pause_from(out)
        # Kimi has no --output-last-message equivalent, so the summary has to come from the
        # stream (or, failing that, the raw tail). That is a WEAKER contract than Codex's file:
        # if the stream schema differs from what we guess, the summary degrades to raw output
        # rather than being wrong — the orchestrator only journals it and shows it in the PR.
        res = AgentRunResult(
            ok=code == 0 and pause is None,
            summary=_final_text(events) or _plain_tail(out),
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


def _plain_tail(out: str) -> str:
    """When nothing parses, keep the tail of the raw output. `--output-format text` would land
    here wholesale, which is a survivable degradation rather than an empty result."""
    return (out or "").strip()[-4000:]


def _walk(obj, key: str):
    """First value for `key` anywhere in a nested structure — used only because the schema is
    UNKNOWN. Replace these with exact paths the moment a real stream is captured."""
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


def _final_text(events: list[dict]) -> str:
    """The assistant's last textual message, under whichever key the stream uses."""
    texts: list[str] = []
    for ev in events:
        for key in ("text", "content", "message", "response"):
            val = ev.get(key) if isinstance(ev, dict) else None
            if isinstance(val, str) and val.strip():
                texts.append(val.strip())
                break
    return texts[-1] if texts else ""


def _actions(events: list[dict]) -> list[str]:
    out: list[str] = []
    for ev in events:
        for key in ("command", "tool_name", "tool", "name"):
            val = _walk(ev, key)
            if isinstance(val, str) and val.strip():
                out.append(val.strip()[:200])
                break
        if len(out) >= 200:
            break
    return out


def _session_id(events: list[dict]) -> str:
    for ev in events:
        for key in ("session_id", "sessionId", "session", "thread_id", "conversation_id"):
            val = _walk(ev, key)
            if isinstance(val, str) and val:
                return val
    return ""


def _apply_usage(res: AgentRunResult, events: list[dict]) -> None:
    """Tokens if the stream carries them; cost is NEVER guessed. An invented cost would corrupt
    the cross-harness comparison this adapter exists to take part in."""
    for keys, field in ((("input_tokens", "prompt_tokens"), "input_tokens"),
                        (("output_tokens", "completion_tokens"), "output_tokens")):
        for key in keys:
            val = _walk(events, key)
            if isinstance(val, int):
                setattr(res, field, val)
                break


def _pause_from(out: str) -> tuple[str | None, str | None]:
    tail = prose_only(out)[-4000:]
    if _RATE_RE.search(tail):
        return "rate_limit", None
    if _AUTH_RE.search(tail):
        return "auth", None
    return None, None
