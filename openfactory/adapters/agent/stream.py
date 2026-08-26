"""What a harness stream SAYS, event by event, in ONE vocabulary — readable from a PREFIX.

Every harness this platform drives already narrates itself as JSON lines:

    claude_code   --output-format stream-json --verbose
    codex         --json
    kimi          --output-format stream-json
    opencode      --format json

and every adapter already parses that stream — but only ONCE, at the end, to fill in an
`AgentRunResult`. The information needed to notice that a run went quiet, or started repeating
itself, or kept reaching for a tool it will never be granted, is written the whole time and read
after the process is dead (C-39).

THIS MODULE IS THE READ, SEPARATED FROM THE MOMENT OF READING. It takes text and returns neutral
`Pulse`es, and it is written so that feeding it the first 200 lines of a stream gives exactly the
pulses those 200 lines contain — no terminal event required, no state carried between calls. That
is the property a live watcher needs and the property an end-of-run parser never had to have; it is
also why this is a separate function rather than more branches inside four `_parse_*` families.

IT READS EVENTS, NEVER THE BLOB. Matching text across a raw agent stream is the defect this
codebase has now paid for in three adapters (see `base.prose_only`): generated ids contain `429`,
and the agent's own tool output contains whatever the repository it is working on contains. Nothing
here regex-matches the transcript. Every pulse comes from a named field of a named event type, and
when a harness does not emit a field, the answer is *absence* — never a guess.

WHAT "NOT DISTINGUISHING" MEANS, and why `Pulse` carries `target` separately. A loop detector asks
"is this the same call again?". `bash` eight times in a row is eight different commands on any
healthy run and a loop only if the COMMAND repeats. So a reader that can see the argument puts it
in `target`; a reader that cannot leaves it empty, and `key` then answers `""` — which the caller
must treat as "cannot tell", not as "the same". Guessing in that spot would park healthy jobs, in
precisely the way `_RATE_RE` did.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass

log = logging.getLogger("openfactory.harness.stream")

#: The neutral event kinds. Deliberately few: this is the vocabulary the tech-lead's signals are
#: expressed in, and every kind here has to mean the same thing on all four harnesses or it is
#: worse than not having it.
TURN = "turn"          # the model took another step / began another assistant message
TOOL = "tool"          # it actually used a tool — the only pulse that is evidence of WORK
TEXT = "text"          # it produced prose (a plan, an explanation, its final answer)
REFUSED = "refused"    # it reached for a tool this invocation never granted it
USAGE = "usage"        # the stream reported spend/tokens for the step that just ended
ERROR = "error"        # the harness itself reported a failure
END = "end"            # the terminal event: the run finished and said so


@dataclass(frozen=True)
class Pulse:
    """One thing a harness stream said, stripped of vendor shape."""

    kind: str
    #: the tool / event name (`Bash`, `Edit`, `read`, …). Never a sentence.
    name: str = ""
    #: what makes THIS call different from the next one of the same name — a file path, a shell
    #: command, a search pattern. Empty when the stream did not say, and that emptiness is
    #: load-bearing (see `key`).
    target: str = ""
    #: WALL-CLOCK SECONDS (epoch), when the harness stamps its events; None when it does not.
    #:
    #: Only opencode does today. That is not a detail to paper over: "no event for N minutes" is
    #: arithmetic over arrival times, so on a harness with no clock in its stream the answer
    #: post-mortem is *unknown*, and the reader has to say unknown rather than quiet. A live
    #: watcher stamps arrival itself and the question disappears — which is exactly why the live
    #: watcher is the part that closes C-39 and this is the part that makes it cheap.
    at: float | None = None
    #: dollars the stream attributed to the step this pulse ends. None ≠ 0.0 — a provider that
    #: reports no pricing (the OpenAI-compatible route) must never render as free.
    cost_usd: float | None = None

    @property
    def label(self) -> str:
        """What a human reads. Same shape the job journal already uses ("Bash: pytest -q")."""
        return f"{self.name}: {self.target}" if self.target else self.name

    @property
    def key(self) -> str:
        """What makes two calls THE SAME call — `""` when the stream did not say enough to tell.

        An empty key must never count as a repeat. `bash` recorded without its command line looks
        identical to the next `bash`, and a loop detector that accepted that would report a spin
        on every run that happens to shell out a few times in a row."""
        return f"{self.name}\x00{self.target}" if self.name and self.target else ""


def pulses_of(harness: str, out: str, *, granted: Sequence[str] = ()) -> list[Pulse] | None:
    """Neutral pulses for `harness`'s stream — `None` when this harness cannot be read at all.

    `None` and `[]` are different answers and the difference is the whole point. `[]` means "read
    it, it contained no events"; `None` means "there is no reader for this harness, so nothing can
    be concluded". Collapsing them would make an unknown harness look like a silent one, which is
    this repository's signature failure mode — a failure that reads as an answer.

    `granted` is the tool allow-list THIS invocation was started with. A `tool_use` outside it
    cannot have run: the CLI denies it. Those become `REFUSED` rather than `TOOL`, which is the
    only structural — text-free — way to see a harness spending its pass asking for something it
    is never going to be given. When the caller does not know the grant, pass nothing: every call
    then reads as a real one, which understates rather than invents.
    """
    reader = _READERS.get((harness or "").strip().lower())
    if reader is None:
        return None
    return reader(_objects(out), tuple(granted or ()))


def reading_of(harness: str, out: str, *, granted: Sequence[str] = (),
               now: float | None = None):
    """The tech-lead's reading of `harness`'s stream — the one place the two halves are joined.

    The split is the layering this codebase keeps everywhere else: the adapter knows what a vendor
    event LOOKS like, the tech-lead decides what it MEANS (`techlead/watch.read_harness`, the same
    module that decides what a parked job means). Joined here rather than at each call site so a
    caller that has a stream does not have to know either half.

    NEVER RAISES. Every caller today is on a failure path — a run that hit the wall, a run that
    ended with no result event — and a diagnosis that crashes would convert a park with a bad
    explanation into a crash with none. A reader that cannot read returns a reading that says so.

    The import is function-level deliberately: an adapter module that imported
    `openfactory.techlead` at
    module scope would drag the tech-lead's whole package (and its conversation surface) into every
    harness process, and would couple the two halves at import time for a call that happens once
    per failed pass."""
    from openfactory.techlead.watch import HARNESS_SIGNALS, HarnessReading, read_harness

    try:
        return read_harness(pulses_of(harness, out, granted=granted),
                            now=now, grant_known=bool(granted))
    except Exception as exc:  # noqa: BLE001 — see NEVER RAISES above
        # BEST-EFFORT IS THE REASON TO LOG, NOT THE REASON NOT TO. This returns a reading that
        # honestly says "blind", which is the right ANSWER — but a reader that crashed and a
        # harness that genuinely emitted nothing produce the same one, and only this line tells
        # them apart. Without it, a parser bug here looks exactly like a quiet harness, for ever.
        log.warning("could not read the %s stream (%s) — reporting the reading as BLIND, which is "
                    "indistinguishable from a harness that said nothing; this line is the only "
                    "thing that says which happened", harness, str(exc)[:160])
        return HarnessReading(blind_to=HARNESS_SIGNALS)


def _objects(out: str) -> list[dict]:
    """The JSON objects in a JSON-lines stream, tolerating everything else.

    A harness CLI is a program and programs talk (see `base.json_envelope`): update notices, login
    hints, model-substitution warnings. A non-JSON line is not an error, it is prose — and a
    TRUNCATED last line is normal when the stream is a prefix, which is the case this module is
    built for. Both are skipped in silence, because neither is evidence of anything."""
    found: list[dict] = []
    for line in (out or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            found.append(obj)
    return found


#: Below this a "timestamp" is not a wall clock — it is a sequence number, a relative offset, or a
#: test fixture counting 1, 2, 3. ~2001-09-09 in epoch seconds; the same value in milliseconds is
#: ~1970-01-12, so the two ranges cannot be confused.
_EPOCH_SECONDS = 1_000_000_000
_EPOCH_MILLIS = 1_000_000_000_000


def _clock(value: object) -> float | None:
    """Epoch SECONDS from a stream's own timestamp, or None when the unit cannot be established.

    opencode stamps every event, but nothing in its output declares whether the number is seconds
    or milliseconds, and the two differ by a factor of a thousand — reading ms as s would turn a
    forty-second gap into eleven hours and report a stall on every healthy run. The magnitude
    settles it unambiguously for any real clock, and anything that is neither is refused: a
    silence signal computed from a sequence number is worse than no silence signal."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value >= _EPOCH_MILLIS:
        return float(value) / 1000.0
    if value >= _EPOCH_SECONDS:
        return float(value)
    return None


def _target_of(inp: object) -> str:
    """The argument that makes a tool call distinguishable from the next one.

    Same keys the journal's action trace already reads (`claude_code._action_of`), so a pulse's
    label and the action a human sees in the panel say the same thing about the same call."""
    if not isinstance(inp, dict):
        return ""
    for key in ("file_path", "filePath", "path", "command", "pattern", "query"):
        value = inp.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return ""


# ── claude_code: `--output-format stream-json --verbose` ─────────────────────────────────────────
#
#   {"type":"system","subtype":"init",…}
#   {"type":"assistant","message":{"content":[
#       {"type":"tool_use","name":…,"input":{…}}, {"type":"text",…}]}}
#   {"type":"result","subtype":"success","total_cost_usd":…,"num_turns":…}
#
# No timestamps anywhere, so `at` stays None and the silence signal is unavailable post-mortem.

def _claude(events: list[dict], granted: tuple[str, ...]) -> list[Pulse]:
    out: list[Pulse] = []
    for ev in events:
        kind = ev.get("type")
        if kind == "assistant":
            out.append(Pulse(TURN))
            message = ev.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    name = str(block.get("name") or "tool")
                    out.append(Pulse(
                        REFUSED if granted and name not in granted else TOOL,
                        name=name, target=_target_of(block.get("input"))))
                elif block.get("type") == "text":
                    out.append(Pulse(TEXT))
        elif kind == "result":
            cost = ev.get("total_cost_usd")
            out.append(Pulse(END, name=str(ev.get("subtype") or ""),
                             cost_usd=float(cost) if isinstance(cost, (int, float)) else None))
    return out


# ── codex: `--json` ──────────────────────────────────────────────────────────────────────────────
#
#   {"type":"thread.started","thread_id":…}
#   {"type":"turn.started"} / {"type":"turn.completed","usage":{…}} / {"type":"turn.failed"}
#   {"type":"item.completed","item":{"type":"command_execution","command":…}}
#   {"type":"item.completed","item":{"type":"file_change","changes":[{"path":…,"kind":…}]}}
#   {"type":"item.completed","item":{"type":"agent_message","text":…}}
#
# No per-tool grant list exists for codex (its read-only stage is `-s read-only`, enforced by the
# harness), so `granted` is unused here rather than approximated.

def _codex(events: list[dict], granted: tuple[str, ...]) -> list[Pulse]:
    out: list[Pulse] = []
    for ev in events:
        kind = ev.get("type")
        if kind == "turn.started":
            out.append(Pulse(TURN))
        elif kind == "turn.completed":
            out.append(Pulse(USAGE))
        elif kind in ("turn.failed", "error"):
            out.append(Pulse(ERROR))
        elif kind == "item.completed":
            item = ev.get("item")
            if not isinstance(item, dict):
                continue
            if item.get("type") == "command_execution":
                out.append(Pulse(TOOL, name="Bash",
                                 target=str(item.get("command") or "").strip()[:200]))
            elif item.get("type") == "file_change":
                for change in item.get("changes") or []:
                    if isinstance(change, dict) and change.get("path"):
                        out.append(Pulse(TOOL, name=str(change.get("kind") or "edit").capitalize(),
                                         target=str(change["path"])[:200]))
            elif item.get("type") == "agent_message":
                out.append(Pulse(TEXT))
    return out


# ── opencode: `--format json` ────────────────────────────────────────────────────────────────────
#
# Every event carries `type`, `timestamp`, `sessionID` and `part` — except errors, where `error`
# replaces `part`. The top-level `type` uses underscores, `part.type` uses hyphens; this reads the
# top level, exactly as the adapter does.
#
# THE ONLY HARNESS WITH A CLOCK IN ITS STREAM, which is why it is the only one whose silence can be
# measured after the fact.

def _opencode(events: list[dict], granted: tuple[str, ...]) -> list[Pulse]:
    out: list[Pulse] = []
    for ev in events:
        at = _clock(ev.get("timestamp"))
        part = ev.get("part") if isinstance(ev.get("part"), dict) else {}
        kind = ev.get("type")
        if kind == "step_start":
            out.append(Pulse(TURN, at=at))
        elif kind == "step_finish":
            cost = part.get("cost")
            # cost 0 is reported as UNKNOWN, the adapter's own rule: a deployment-declared
            # OpenAI-compatible provider carries no pricing metadata and returns 0, and showing a
            # client's gateway spend as zero dollars corrupts the one number spend decisions read.
            out.append(Pulse(USAGE, at=at,
                             cost_usd=float(cost) if isinstance(cost, (int, float))
                             and not isinstance(cost, bool) and cost > 0 else None))
        elif kind == "tool_use":
            tool = str(part.get("tool") or "tool")
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            status = state.get("status")
            name = tool if status in (None, "completed") else f"{tool} ({status})"
            out.append(Pulse(TOOL, name=name, target=_target_of(state.get("input")), at=at))
        elif kind == "text":
            out.append(Pulse(TEXT, at=at))
        elif kind == "error":
            out.append(Pulse(ERROR, at=at))
    return out


# ── kimi: `--output-format stream-json` ──────────────────────────────────────────────────────────
#
# THE SCHEMA IS UNVERIFIED — nobody has run this binary (Moonshot access pending), and the adapter
# says so in its own docstring. So this reader mirrors what `kimi._actions` already does: look for
# a tool or command name under any plausible key, and produce NOTHING when it finds none. It never
# invents a turn or a timestamp, because a fabricated pulse would make a stream that cannot be read
# look like one that was read and found healthy.

_KIMI_TOOL_KEYS = ("tool_name", "toolName", "tool", "name")


def _kimi(events: list[dict], granted: tuple[str, ...]) -> list[Pulse]:
    out: list[Pulse] = []
    for ev in events:
        command = _find(ev, "command")
        name = next((v for v in (_find(ev, k) for k in _KIMI_TOOL_KEYS) if v), "")
        if name or command:
            out.append(Pulse(TOOL, name=name or "Bash", target=command))
    return out


def _find(obj: object, key: str, depth: int = 0) -> str:
    """The first string value under `key`, anywhere in a nested object. Bounded depth so a
    pathological event cannot spend the caller's time; local rather than imported from `kimi` to
    keep this module free of any adapter import (kimi imports claude_code, which imports this)."""
    if depth > 6:
        return ""
    if isinstance(obj, dict):
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
        for nested in obj.values():
            found = _find(nested, key, depth + 1)
            if found:
                return found
    elif isinstance(obj, list):
        for nested in obj[:50]:
            found = _find(nested, key, depth + 1)
            if found:
                return found
    return ""


#: harness kind → its reader. The keys are `registry.HARNESSES`'s keys, and a harness that is not
#: here reads as `None` (unknown) rather than as an empty stream — see `pulses_of`.
_READERS = {
    "claude_code": _claude,
    "codex": _codex,
    "kimi": _kimi,
    "opencode": _opencode,
}
