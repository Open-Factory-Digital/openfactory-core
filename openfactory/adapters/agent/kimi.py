"""KimiAdapter — Kimi Code (Moonshot) as a coding harness.

Built against kimi-code 0.31.1 — the version `docker/worker.Dockerfile` pins — read in its
bundle (`dist/main.mjs`) and measured against the binary on 2026-10-17 (#362):

    kimi -p, --prompt <prompt>        run ONE prompt non-interactively and print the response
         --output-format text|stream-json   (only with -p)
    -m, --model <model>               model alias (else `default_model` in config.toml)
    -S, --session [id]                resume a session by id      (hidden aliases: -r, --resume)
    -c, --continue                    continue the previous session (not with -S; hidden: -C)
    -y, --yolo                        auto-approve regular tool calls     (NOT with -p)
                                      (hidden aliases: --yes, --auto-approve)
        --auto                        fully autonomous                    (NOT with -p, not with -y)
        --plan                        start in plan mode                  (NOT with -p)
        --agent <name>                a built-in agent, e.g. `explore`    (not with -S/-c)
        --agent-file <path>           an agent file; its `tools:` list is the model's tool list
                                      (not with --agent, not with -S/-c)
        --add-dir <dir>               extra workspace directory (repeatable)
    kimi login                        device-code authentication

The "NOT with -p" column is `validateOptions`, which exits 1 with `Cannot combine --prompt with
--auto.` (or `--yolo`, `--plan`) before any model is called. The hidden aliases are mapped by
`createProgram` before it, so `--yes -p` is refused as `--yolo`. A pin bump reads both again
first: `tests/test_kimi_flags_are_a_combination_the_cli_accepts.py` holds that table as data.

TWO DIFFERENCES FROM CODEX THAT SHAPE THIS ADAPTER

1. No permission flag at all, because prompt mode IS auto. In a headless job there is nobody to
   answer a question, and a run that stops to ask burns its budget and returns nothing — this
   codebase paid for that once with Claude, where an approval-gated headless run silently denied
   every `pytest` the agent tried. Up to 0.29.1 `--auto` bought "will not ask"; 0.31.1 refuses it
   beside `-p` and gives it by construction instead: a new session is put in `setMode("auto")`,
   a resumed one (`-S`) gets `forceAuto`. So the command carries neither `--auto` nor `-y`, and
   the full-access and resumed runs keep the mode they need from prompt mode itself (#362) —
   observed in the review of #783: a tool call ran unattended on a new session and on a resume.

2. There is NO sandbox-policy flag, and in prompt mode no plan mode either. Codex has
   `-s read-only`, which makes its planner genuinely INCAPABLE of editing. Kimi had only `--plan`
   (a mode), and 0.31.1 refuses it beside `-p`; the only other way in, `defaultPlanMode` in
   `config.toml`, is account-wide rather than per run. So the plan stage and `ask` here are
   read-only by INSTRUCTION ONLY, not by mode and not by enforcement — the weakest guarantee of
   the shipped rows, stated rather than papered over. `--agent-file` with a `tools:` list is
   reachable per run and not used yet (#785): measured, it removes `Write` from the model's tools,
   but its body replaces Kimi's whole system prompt and it cannot be used with `-S`. Nothing
   confines what a disobedient run writes; where it lands depends on the role (#788, located on
   620bb577, 2026-10-20). The planner runs in the job's box on the job's own workspace, the one
   the executor continues from and `_commit` sweeps with `git add -A`, so an edit it left reached
   the pull request; with `--sandbox worktree` that workspace is a directory on the host. So the
   orchestrator measures that workspace before and after a Kimi plan pass
   (`orchestrator/read_only_pass.py`; this harness is named in
   `base.py::PLANNERS_READ_ONLY_BY_INSTRUCTION`) and holds the job when the pass wrote, naming
   the paths, before the pause, the commit or the push: the job stops before pushing anything.
   A workspace git cannot answer holds it too, in git's words. It detects the write; nothing here
   prevents it, and it sees only what is there at the second reading: a process the planner
   leaves running that writes after it is not seen (measured in the review of dc0efac4,
   2026-10-20: a background `late.txt` written a second later reached the pushed branch). A pass
   the box walled is now held before the executor runs (#980): the wall kills only the shell, so
   a walled planner may still be running; what remains of the limit is a process left behind by a
   pass that ended on its own.
   Where an `ask()` runs is its caller's choice. A judging role's caller builds
   `sandbox/registry.py::judging_worktree`, a `WorktreeSandbox` whose `run` is a host
   subprocess, so the question runs on the host whatever the project's box, in a room nothing
   commits from (a temporary directory, the repo cache's master clone, a module's cached view),
   and its edit reaches no pull request but stays where it was written, except `env context
   --ask`, which asks in the checkout it is pointed at (the person's own repository on a local
   deployment), where a write is left in that working tree, and the independent review, which
   runs in the job's box on the job's workspace before the push (`JobRunner._review` hands
   `HarnessReviewer.review` both), where a write it commits, or one a review-repair pass then
   sweeps in, can reach the pull request (measured in the review of dc0efac4, 2026-10-20).
   Review is on by default and that pass is not measured. The onboarding first run's review asks
   in its own rehearsal workspace, from which nothing is pushed.

   There is also no `--cd`: the working directory is the process's, which is exactly what the
   platform's sandbox already sets (`sandbox.run(workspace=…)` runs in the workspace). Nothing to
   pass, nothing to get wrong.

WHAT IS NOT VERIFIED — read this before trusting a number from here
- **The `stream-json` schema is captured, usage is not.** 0.31.1 was run against a local stub in
  the review of #783: one JSON object per line, `role` `assistant` (the reply in `content`, tool
  calls in `tool_calls[].function.name`), `tool` (a result), and a closing `meta` line of type
  `session.resume_hint` carrying `session_id` — whose own `content` is NOT the answer. Prompt mode
  was observed running a tool unattended on a new session and on a `-S` resume. No token usage
  appeared in that capture, so usage parsing stays a best-effort walk; unknown shapes degrade to
  None/[] and NEVER raise. Cost is left None rather than invented.
- **Session resume works from the hint's `session_id`**, against the stub. 0.31.1 refuses `-S`
  when the session was created under another directory, so a resume must run in the workspace
  path that created it; if the id cannot be recovered, a resumed run starts cold — which the
  orchestrator already handles.
- **Rate-limit/auth detection is text-matched** and unverified, exactly as for Codex.

A real Moonshot answer is still the acceptance test. Until then treat this as wired, not proven —
the harness seam makes it one table entry, so correcting it costs a small diff, not a redesign.
"""

from __future__ import annotations

import json
import os
import re
import shlex

from openfactory.adapters.agent.base import (
    HARNESSES_WITHOUT_STAGED_PROMPT,
    PLANNER_FALLBACK,
    REPAIR_INSTRUCTION,
    AgentContext,
    PromptTooLarge,
    prompt_too_large_result,
    prose_only,
    stage_prompt,
    ticket_brief,
    wall_result,
)
from openfactory.adapters.agent.roles import role_prompt
from openfactory.adapters.sandbox.base import SandboxAdapter, Workspace
from openfactory.adapters.sandbox.timeouts import AGENT_TIMEOUT, timed_out
from openfactory.contracts import AgentRunResult

_RATE_RE = re.compile(r"rate.?limit|quota|too many requests|429", re.IGNORECASE)
_AUTH_RE = re.compile(r"unauthor|forbidden|invalid api key|not logged in|401|403", re.IGNORECASE)
# the shared wall-clock wall — see openfactory/adapters/sandbox/timeouts.py
_TIMEOUT = AGENT_TIMEOUT

#: NO MCP SERVER OF THE ACCOUNT, AND KIMI CODE CANNOT BE STARTED WITHOUT THEM. It has no flag and no
#: variable for it (0.31.1, pinned, read in its bundle): `loadMcpServers` reads
#: `$KIMI_CODE_HOME/mcp.json`, every enabled plugin under `$KIMI_CODE_HOME/plugins/` adds its own,
#: and the login lives in the same directory, so the directory cannot be moved away. So no role
#: starts while the account declares either, and the person reads which file and what to do.
NOT_WHILE_DECLARED = (
    'k="${KIMI_CODE_HOME:-$HOME/.kimi-code}"; '
    'for f in "$k/mcp.json" "$k/plugins/installed.json"; do '
    'if [ -e "$f" ]; then echo "Kimi Code starts every MCP server declared in $f and cannot be '
    'started without them, so they would reach this role. Nothing was started: remove the file '
    'from the account that runs the harness, or give this role another harness."; '
    'exit 3; fi; done;')

#: What the shell runs before Kimi Code: the refusal. `plugins/installed.json` refuses even when it
#: enables nothing: its format is readable in the bundle (`{"version": 1, "plugins": [{"enabled":
#: …}]}`, a plugin's servers starting only when `enabled` is truthy), but this check runs in the
#: box's own POSIX shell, which has no JSON reader, and deciding truthiness by matching text would
#: be a guess. On the safe side, and the person reads the file to remove.
BEFORE_THE_HARNESS = NOT_WHILE_DECLARED


class KimiAdapter:
    """Kimi Code, driven non-interactively through whatever box the caller hands it.

    That is the job's box for `plan`, `execute` and `repair`, a directory on the host under
    `--sandbox worktree`; for a judging role's `ask()` it is `judging_worktree`, on the host
    whatever the project's box, in a room nothing commits from, except `env context --ask`,
    which asks in the checkout it is pointed at, and the independent review, which runs in the
    job's box on the job's workspace before the push, where its write can reach the pull request
    (see the module docstring, difference 2)."""

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
        """`role_prompt("planner")` is the same primitive `claude_code.py` reads, so
        `org_defaults/roles/planner.md` reaches this harness too, rather than the fixed sentence
        below (kept only for an install that could not read its own role file)."""
        role = role_prompt("planner")
        prompt = f"{role}\n\n{ticket_brief(context)}" if role else (
            f"{PLANNER_FALLBACK}\n\n{ticket_brief(context)}")
        return self._run(sandbox, workspace, prompt, model=self.planner_model,
                         phase="plan", project=context.ticket.repo)

    def ask(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, prompt: str, phase: str = "ask"
    ) -> AgentRunResult:
        """Run a READ-ONLY prompt against the checkout and return the text (see roles.py).

        WEAKER than the other harnesses: Kimi exposes no sandbox-policy flag, and 0.31.1 refuses
        `--plan` beside `-p`, so this is instruction only — no mode, no enforcement (#362);
        `--agent-file` with a `tools:` list is reachable per run and not used yet (#785), so
        there is no enforcement until a per-run agent file is wired. A judging role's caller hands
        it `judging_worktree`, which runs it on the host whatever the project's box, in a room
        nothing commits from, except `env context --ask`, which asks in the checkout it is pointed
        at, where a write is left in that working tree, and the independent review, which runs in
        the job's box on the job's workspace before the push (`HarnessReviewer.review`), where a
        write it commits, or one a review-repair pass then sweeps in, can reach the pull request.
        An edit made while judging elsewhere reaches no pull request, and nothing confines it to
        its room either."""
        return self._run(sandbox, workspace,
                         "Answer READ-ONLY. Do not modify any file.\n\n" + prompt,
                         model=self.planner_model, phase=phase)

    def execute(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, context: AgentContext
    ) -> AgentRunResult:
        """`role_prompt("executor")` prepended, same as `claude_code.py`'s `_executor_prompt` —
        so `org_defaults/roles/executor.md` reaches this harness too."""
        role = role_prompt("executor")
        prompt = f"{role}\n\n{ticket_brief(context)}" if role else ticket_brief(context)
        if context.plan:
            prompt += f"\n\n## The plan to follow\n{context.plan}"
        return self._run(sandbox, workspace, prompt, model=self.model,
                         resume_session=context.resume_handle, project=context.ticket.repo)

    def repair(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, context: AgentContext,
        failure_log: str, instruction: str = "",
    ) -> AgentRunResult:
        """Repair is the executor role continuing — role identity leads when available, then the
        repair instruction (always present), then the failures and the ticket."""
        role = role_prompt("executor")
        lead = f"{role}\n\n" if role else ""
        # WHAT THIS PASS IS, IN THE CALLER'S WORDS (`instruction`): the orchestrator knows
        # whether it holds a gate's output or a person's comment, and this row does not —
        # so it renders that sentence where its own used to stand and adds none.
        # THE FAILURE LOG IS THE CLIENT'S SUITE TALKING, so it goes where every other value
        # nobody here wrote goes: inside the brief, under a DATA heading, below the rule. It used
        # to sit ABOVE `ticket_brief`, which put a stranger's text before the only sentence that
        # says how to read a stranger's text (review of #108).
        prompt = (
            lead + f"{instruction or REPAIR_INSTRUCTION}\n\n"
            + ticket_brief(context, failures=failure_log[:12000])
        )
        return self._run(sandbox, workspace, prompt, model=self.model,
                         project=context.ticket.repo)

    # ---- command construction (exact, from kimi-code 0.31.1's option table) -------------------

    def smoke_command(self, *, harness: str, prompt: str) -> str:
        """The smallest real call this harness can be asked to make (#129).

        BUILT BY THE SAME `_cli` A TICKET GOES THROUGH, so what it exercises is the invocation
        that actually runs — the harness binary at the path the box chose, its own flags, its own
        credential. A probe assembled by hand here would prove a command nothing issues, which is
        how #122 survived every check: `curl` reached the endpoint while the harness could not."""
        return self._cli(prompt, harness=harness, model=self.planner_model)

    def smoke_reply(self, out: str) -> str:
        """What the model said to `smoke_command`, read by `_final_text` — the reading this
        adapter's ticket summary uses: the last assistant message, never the resume hint the CLI
        prints after it (see the module docstring). `""` when there is none."""
        return _final_text(_parse_jsonl(out))

    def _cli(
        self, prompt: str, *, harness: str, model: str | None,
        resume_session: str = "", prompt_path: str | None = None
    ) -> str:
        # `harness` is the ABSOLUTE path the box chose — never a bare name,
        # which `PATH` inside the client's image would resolve (ADR-0037 D2).
        #
        # THIS ROW KEEPS THE PROMPT ON ARGV, alone among the shipped four (#5, review of #360).
        # `-p -` was assumed to be a stdin sentinel and is not one: `kimi-code` 0.31.1 — the pinned
        # version — declares `-p, --prompt <prompt>` as an option that takes a value, and enqueues
        # that value verbatim, so `-` reached the model as the whole task on every staged run.
        # Read in the bundle, 0.31.1 and 0.32.0: no path reads stdin into the prompt. `prompt_path`
        # is therefore always None here (the caller asks with `channel=False`), and the branch stays
        # so the day that CLI grows a stdin or file form is a one-line change rather than a rewrite.
        head = ([BEFORE_THE_HARNESS, f"cat {shlex.quote(prompt_path)} |", harness] if prompt_path
                else [BEFORE_THE_HARNESS, harness])
        # NO `--auto`, `-y` OR `--plan` (#362): 0.31.1 refuses each beside `-p` before it calls a
        # model, and prompt mode is auto already — see the module docstring, difference 1.
        cmd = [*head, "--output-format", "stream-json"]
        if model:
            cmd += ["-m", shlex.quote(model)]
        if resume_session:
            cmd += ["-S", shlex.quote(resume_session)]
        cmd += ["-p", "-" if prompt_path else shlex.quote(prompt)]
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
        model: str | None, resume_session: str = "",
        phase: str = "execute", project: str = "",
    ) -> AgentRunResult:
        prompt = self._localised(prompt, phase)
        # OFF THE COMMAND LINE (#5): stage the prompt so a corpus past the argv ceiling reaches the
        # CLI over stdin rather than raising `OSError: Argument list too long`, and a box that
        # cannot stage refuses BY NAME instead of crashing.
        try:
            # NO CHANNEL FOR THIS ROW, AND IT IS NOT A PREFERENCE (review of #360). `kimi-code`'s
            # `-p, --prompt <prompt>` is a Commander option that TAKES a value, `validateOptions`
            # only checks it is not blank, and `runNativeTurn` enqueues it verbatim — so `-p -`
            # sends the model the one-character task `-`, on EVERY staged run, small ones included.
            # Verified by reading 0.31.1 (the version `docker/worker.Dockerfile` pins) and 0.32.0:
            # no code path reads stdin into the prompt. So the prompt stays the argument that was
            # verified, and the ceiling is still asked — a corpus past it parks with a sentence
            # instead of dying with `Errno 7`. When `kimi-code` grows a stdin or file form, drop
            # `channel=False` and this row joins the others — dropping this kind from
            # `HARNESSES_WITHOUT_STAGED_PROMPT`, the one place that fact lives.
            prompt_path = stage_prompt(sandbox, workspace, prompt, phase=phase, project=project,
                                       channel=self.name not in HARNESSES_WITHOUT_STAGED_PROMPT)
        except PromptTooLarge as exc:
            return prompt_too_large_result(exc, model=model, harness=self.name)
        command = self._cli(prompt, harness=sandbox.harness_path("kimi"),
                            model=model, resume_session=resume_session,
                            prompt_path=prompt_path)
        code, out = sandbox.run(workspace=workspace, command=command, timeout=_TIMEOUT)
        if timed_out(code, out):
            return wall_result("agent", model, self.name, out)

        events = _parse_jsonl(out)
        pause, retry_at = _pause_from(out)
        # Kimi has no --output-last-message equivalent, so the summary has to come from the
        # stream (or, failing that, the raw tail). That is a WEAKER contract than Codex's file.
        # It reads the captured shape — the last `role: assistant` message, never the `meta`
        # resume hint after it (review of #783) — and when no assistant line is there, it degrades
        # to raw output; the orchestrator only journals it and shows it in the PR.
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
    """The assistant's last non-blank message — and ONLY the assistant's (review of #783): 0.31.1
    ends every prompt-mode turn with a `role: meta` `session.resume_hint` line whose `content` is
    "To resume this session: kimi -r …", and reading the last `content` of any role handed that
    hint to `box prove`, to every plan and to every `ask` as the model's answer."""
    for ev in reversed(events):
        val = ev.get("content") if ev.get("role") == "assistant" else None
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _actions(events: list[dict]) -> list[str]:
    """Each tool the model called, from `tool_calls[].function.name` — every call of a message,
    not only its first. A `meta` line is the CLI talking, never the model: the resume hint's
    `command` (`kimi -r …`) is not an action. Any other shape keeps the defensive walk."""
    out: list[str] = []
    for ev in events:
        if ev.get("role") == "meta":
            continue
        calls = ev.get("tool_calls")
        if isinstance(calls, list):
            for call in calls:
                fn = call.get("function") if isinstance(call, dict) else None
                name = fn.get("name") if isinstance(fn, dict) else None
                if isinstance(name, str) and name.strip():
                    out.append(name.strip()[:200])
            continue
        for key in ("command", "tool_name", "tool", "name"):
            val = _walk(ev, key)
            if isinstance(val, str) and val.strip():
                out.append(val.strip()[:200])
                break
        if len(out) >= 200:
            break
    return out[:200]


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
