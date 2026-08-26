"""The ONE grammar for an operator command the factory can actually execute.

There are exactly two of them — `resume #NN` and `skip #NN` — and this module is the single
place that defines them. It exists because the grammar has two consumers that MUST agree:

- the Slack listener, which parses what a human typed and acts on it;
- the tech-lead's HandOff, which TELLS a human what to type ("reply `skip #447` and I resolve
  it").

When those two drift, the factory promises a resolution it cannot deliver: the operator types
what the bot asked for, nothing happens, and the ticket goes back to rotting — the exact
failure the executable-next-step work set out to kill. So the HandOff's `suggested_command` is
validated against THIS parser before it is ever rendered, and dropped when it doesn't parse.

No verb here ever means prod-release / merge / deploy — those are deliberately absent so a
Slack message can never trigger them, for an admin or anyone else (hard guardrail, ADR-0016).
"""

from __future__ import annotations

import re

#: THE REF SHAPE (C-05). Every regex below used `\d+` — GitHub-only. On a Jira or Azure DevOps
#: deployment, an operator typing exactly what the tech-lead's own HandOff told them to
#: (`normalize_command` renders `resume CONT-412`) could never have it parsed back: the channel
#: that promises "reply this and I resolve it" silently could not honour a reply in the one
#: shape non-numeric trackers actually issue.
#:
#: STILL REQUIRES A DIGIT, deliberately. A ref always carries one — GitHub's `189`, Jira's
#: `CONT-412`, Azure DevOps's `1234` — and no ordinary prose word does (in either language this
#: channel speaks). That is what keeps `test_operator_smalltalk_fuzz_never_acts` passing without
#: widening to a bare `[A-Za-z0-9]+`, which would let "resume the JOB" parse `JOB` as a ref. The
#: optional letter PREFIX is capped at 10 chars and must be hyphenated from the digits — the
#: universal Jira/ADO project-key shape — so a plain word near a verb ("resume ASAP") still
#: cannot match: it has no digits to anchor on.
#:
#: The bare alternation, undecorated — each call site wraps it in the capture shape IT needs
#: (a plain group here, a named `(?P<num>...)` in `_PT_TIGHT`), so this stays reusable rather
#: than forcing one capture-group style on all three regexes.
_REF_BODY = r"[A-Za-z]{1,10}-\d+|\d+"
_REF = rf"#?({_REF_BODY})"

# Action verbs → the normalized action. resume-family = re-run/proceed the parked job;
# skip-family = free the floor.
RESUME_VERBS = frozenset({"resume", "retry", "continue", "go", "unblock", "proceed"})
SKIP_VERBS = frozenset({"skip", "abandon", "drop", "cancel"})

#: `ack #NN` — a person SAW something and is taking it from here. It touches no job: it closes an
#: open loop (ADR-0021), which is why it is a third verb rather than a flavour of skip.
#:
#: It exists because the alternative was worse. A review finding flagged on a merged ticket had
#: nothing that could ever close it — no reply to read, no state change to observe — so the loop
#: would have stayed open for ever, and a list that only grows is a list everybody learns to
#: ignore. Rather than invent an observation, this asks for the one thing that genuinely means
#: "somebody has this": a person saying so.
#: Deliberately WITHOUT a bare "ok": "ok, o #412 está pronto" is ordinary conversation, and
#: reading it as an acknowledgement would silently close a loop that should have stayed open —
#: which is the exact failure this whole mechanism exists to prevent. An ack must be typed on
#: purpose.
ACK_VERBS = frozenset({"ack", "visto", "ciente", "acknowledged", "noted"})

ACTION_OF: dict[str, str] = {
    **{v: "resume" for v in RESUME_VERBS},
    **{v: "skip" for v in SKIP_VERBS},
}

#: The ack pattern is TIGHTER than the action pattern on purpose: verb immediately followed by the
#: ref (optional #, optional colon). The loose gap the action verbs enjoy would make "ciente, o
#: 412 volta amanhã" — ordinary conversation — close #412's finding as acknowledged. Resume/skip
#: act on a PARKED job and are double-checked against its state; an ack's only guard is the parse.
ACK_RE = re.compile(r"\b(" + "|".join(sorted(ACK_VERBS)) + r")\s*[:\s]\s*" + _REF + r"\b", re.I)

#: Portuguese action verbs — the operators' channel speaks pt-BR, and a grammar that only obeys
#: English quietly ignores half the instructions ("pode continuar o 478" parsed as conversation).
#: TIGHT adjacency like the ack pattern, and unlike the English verbs: "continua" is everyday
#: prose ("o cliente continua sem responder há 3 dias" would otherwise resume job 3), so the verb
#: must be followed at most by an article and then the number itself.
_PT_TIGHT = re.compile(
    r"\b(?P<verb>continuar?|continua|retomar?|retoma|liberar?|libera"
    r"|pular?|pula|descartar?|descarta|abandonar?|abandona)"
    r"\s+(?:o|a|the)?\s*#?(?P<num>" + _REF_BODY + r")\b", re.I)
_PT_ACTION = {
    **dict.fromkeys(("continuar", "continua", "retomar", "retoma", "liberar", "libera"),
                    "resume"),
    **dict.fromkeys(("pular", "pula", "descartar", "descarta", "abandonar", "abandona"),
                    "skip"),
}

# One explicit action verb, anywhere, followed later by an issue ref (bare or #-prefixed).
# The verb must be a whole word (\b) so "resuming" or "dropped" don't trip it, and it must come
# BEFORE the ref so a question that merely mentions an issue ("why did #412 fail?") never
# parses — there the only verb ("fail") isn't an action word, so no match.
#
# `[^0-9]*?` (NOT `[^A-Za-z0-9]*?`) is deliberate and still correct with a letter-prefixed ref
# allowed: it is non-greedy, so the engine tries the SHORTEST skip first and stops at the first
# position where the ref pattern matches — "retry CONT-412" skips exactly the one space, then
# `[A-Za-z]{1,10}-\d+` (itself greedy) consumes "CONT-412" whole from there. Requiring the skip
# to stop at letters too (as the old digit-only version did) would make "retry the CONT-412 job"
# stop at "C", which still works the same way — the skip advances one character at a time
# regardless of what class it is, until the REST of the pattern succeeds.
ACTION_RE = re.compile(r"\b(" + "|".join(sorted(ACTION_OF)) + r")\b[^0-9]*?" + _REF + r"\b", re.I)


def parse_command(text: str) -> tuple[str, str] | None:
    """Classify text as an ACT intent → `(action, issue)`, or None if it's a question/unclear.

    `action` is normalized to 'resume', 'skip' or 'ack'; `issue` is the bare ref, `#`-stripped —
    a GitHub number, or a Jira/ADO-shaped `LETTERS-digits` (C-05). Deliberately CONSERVATIVE: it
    requires an explicit action verb as a whole word AND a ref after it, so "resume #412"/
    "skip 99"/"retry the 7 job"/"resume CONT-412" match but "why did #412 fail?"/"status?"/
    "resume" (no ref) do NOT — a question that merely names an issue must fall through to the
    read-only path."""
    m = ACK_RE.search(text or "")
    if m:
        return "ack", m.group(2)
    m = _PT_TIGHT.search(text or "")
    if m:
        return _PT_ACTION[m.group("verb").lower()], m.group("num")
    m = ACTION_RE.search(text or "")
    if not m:
        return None
    return ACTION_OF[m.group(1).lower()], m.group(2)


#: `decisão: <chave>` — the answer to a park that carries a DecisionRequest (#24 item 1).
#:
#: THIS PATTERN EXISTS BECAUSE THE PLATFORM ALREADY PROMISED IT. `machine._hold`'s decision park
#: has told every reader "reply here with `decisão: <key>`" since the day it shipped — and no
#: parser anywhere accepted that reply. The operator typed exactly what the platform asked,
#: nothing happened, and the job waited its ten-year deadline: the unfollowable-instruction
#: failure this module's docstring names, in its most literal form.
#:
#: The COLON (or `=`) is required, not decoration: "a decisão foi difícil" is everyday prose and
#: must never parse. A prose false-positive that DOES carry a colon ("minha decisão: vamos
#: adiar") survives the parse but dies downstream — `view.act_job` validates the key against the
#: park's actual options and answers with the real ones, which is noise that teaches, not an act.
DECISION_RE = re.compile(
    r"\bdecis(?:[ãa]o|ion)\s*[:=]\s*(?P<key>[A-Za-z0-9][A-Za-z0-9_.-]{0,39})", re.I)

#: A ref standing on its own — left-guarded so a digit INSIDE an option key ("opcao_2") can
#: never be read back out of it as a ticket number.
_LONE_REF_RE = re.compile(r"(?<![\w#-])" + _REF + r"\b")


def parse_decision_answer(text: str) -> tuple[str, str] | None:
    """`(option key, ref or "")` when the text answers a decision park — else None.

    The ref is optional because the answer usually arrives in the alert's own thread, where the
    conversation already names the ticket (`bot._asked_for`); an explicit `#NN` anywhere in the
    message wins over the thread when both are present. The KEY is never validated here — only
    the park itself knows its options, and `view.act_job` refuses an unknown key with the real
    list, which is a better answer than this parser silently eating the reply."""
    m = DECISION_RE.search(text or "")
    if not m:
        return None
    rest = (text or "")[: m.start()] + " " + (text or "")[m.end():]
    ref = _LONE_REF_RE.search(rest)
    return m.group("key"), (ref.group(1) if ref else "")


def render_command(action: str, issue: str) -> str:
    """The canonical spelling of a command: `resume #412`. Used when we hand a command TO a
    human, so what they are asked to type is exactly what `parse_command` accepts."""
    return f"{action} #{str(issue).lstrip('#')}"


def normalize_command(text: str, *, issue: str = "") -> str:
    """The canonical, EXECUTABLE form of a suggested command — or "" when there isn't one.

    Returns "" when `text` doesn't parse as a command at all (an LLM writing prose like "wire
    the CI workflow" must not be rendered as a one-word resolution), and also when `issue` is
    given and the command targets a DIFFERENT ticket. That second guard matters: the tech-lead
    diagnoses ticket #447 but is free-generating the command string, and a hallucinated number
    would have us instruct an admin — in the bot's own voice — to act on an unrelated job. A
    command we cannot vouch for is worse than none: with "" the HandOff falls back to spelling
    out the human step in `recommendation`."""
    parsed = parse_command(text)
    if parsed is None:
        return ""
    action, num = parsed
    if issue and num != str(issue).lstrip("#"):
        return ""
    return render_command(action, num)
