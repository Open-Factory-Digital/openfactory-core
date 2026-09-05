"""The staged proposal: one draft waiting for a yes, and the rules that make a yes mean it.

MOVED OUT OF THE SLACK PACKAGE (#98 slice 3), unchanged. It was never Slack-specific — its only
imports are `openfactory.memory.messages`, `openfactory.product.voice` and
`openfactory.product.role` — and it was
already reached from a second surface before this move: `api/app.py` calls `answer_staged`, with
the reach-into-Slack documented there as an explicit exception. This is that exception being
retired rather than a new capability.

WHAT IT PROTECTS, and why it is more than a dictionary. A draft is staged per conversation with a
two-hour expiry-on-read, mirrored durably so another PROCESS can resolve it, and confirmed by
compare-and-swap on the object's identity plus a fingerprint — so a "sim" cannot land on a draft
that was replaced while somebody was reading it, and two surfaces cannot both confirm the same
one. Every one of those rules is a defect that already happened.

`product_channel` re-exports every name from here, so the twenty-two test modules that reach
`pc.remember`, `pc._PENDING`, `pc.proposal_token` and the rest keep working against the same
objects — `_PENDING` in particular is re-bound by identity, never copied, because tests mutate it
in place and a copy would silently stop being the dict the code reads.
"""

from __future__ import annotations

import logging
import re
import threading
import time

from openfactory.util.bounded import BoundedDict

log = logging.getLogger("openfactory.product.staging")


_PENDING: dict[str, dict] = {}

#: How long a staged proposal stays confirmable. It never expired, and two things followed. A "sim"
#: days later confirmed something nobody remembered reading — the same harm the click fingerprint
#: prevents, arriving by time instead of by replacement. And while ANY proposal was staged the
#: acceptance path did not run (it is gated on `not waiting`), so a client answering "funcionou"
#: about a delivery was ignored for as long as a forgotten draft sat there.
#:
#: Two hours: long enough for somebody to step away from a conversation and come back to it, short
#: enough that "confirm this" always refers to something the person can still recall reading.
PROPOSAL_TTL_SECONDS = 2 * 60 * 60
_PENDING_LOCK = threading.Lock()

#: How many drafts we keep. A cap, not a policy — an unbounded dict in a long-lived worker is a
#: leak, and the oldest unconfirmed draft is the least likely to be confirmed.
_MAX_PENDING = 200

#: THE APPROVAL VOCABULARY LIVES IN `openfactory/language/assent.py` (#161). What used to be here
#: — `_YES_TOKENS`/`_YES_CORE` — is the CORE/FILLER pair there, with the reason this file learned
#: first: a reply is a yes when the WHOLE message is made of catalogued words and at least one of
#: them asserts, which is how "sim, pode registrar" (the most Brazilian confirmation there is)
#: counts while "ok mas e o prazo?" does not — `mas` is in no row. The first version here was an
#: anchored phrase list, and the owner's natural "sim, pode registrar" fell through to the model:
#: he believed he had confirmed, and nothing was written.
#: The English "no" is NOT in the word-start list: it is also the Portuguese preposition "no"
#: ("No sistema de férias…"), so any pt-BR sentence opening with it read as a rejection — and a
#: rejection DESTROYS the staged proposal before the judge ever sees the sentence. English "no"
#: still counts, but only as the whole message, where it cannot be a preposition.
_NO = re.compile(r"^\s*(n[ãa]o|nao|nope|errado|not quite|not right)\b|^\s*no\s*[.,!…]*\s*$",
                 re.IGNORECASE)

#: Proposals that aged out, so the NEXT yes can be told what happened instead of being silently
#: swallowed. A person who steps away and comes back to type "sim" deserves "that expired, ask me
#: again" — falling through to the conversational model answered them politely as if nothing had
#: ever been staged. A BoundedDict, not a hand-rolled cap: one implementation the caller cannot
#: forget to bound, in a process that never restarts.
_EXPIRED_TOMBSTONES: BoundedDict[str, float] = BoundedDict(64)


def is_yes(text: str) -> bool:
    """The FAST, high-precision path: every word an approval token, at least one a core yes.

    Kept deliberately narrow. It accepts "sim", "sim, pode registrar", "aprovado" — and nothing
    that needs interpretation. Widening it was tried and abandoned: a first-sentence rule accepted
    "Sim — registre." (correct) and also "certo — e quem audita isso?" (a question), because no
    vocabulary list can tell an affirmation from a word that happens to appear in one.

    Anything this does not recognise is not treated as "no". It goes to `judge_confirmation`, where
    a model reads it — which is the only thing that can, and is why this function no longer has to
    grow. See ADR-0028.

    THE VOCABULARY MOVED (#161). This file held one of three hand-rolled yes-lists, and the sweep
    measured them disagreeing: `certo` was CORE here — asserting approval of a proposal that can
    promote tickets and spend money — while the operator channel allowed it without letting it
    assert, and the floor's table had audited it out in as many words. The lists are one table now,
    in `openfactory/language/assent.py`, and this is the mapping onto it.
    """
    from openfactory.language import assent

    return assent.asserts_assent(text)


def is_no(text: str) -> bool:
    return bool(_NO.match(text or ""))


def pending_for(thread: str, *, project=None) -> dict | None:
    """The proposal staged for this conversation, or None — INCLUDING when it aged out.

    Expiry is enforced on READ rather than by a sweeper: there is no clock to hang one on inside a
    Socket Mode listener, and a stale entry is only ever harmful at the moment somebody acts on it.
    """
    with _PENDING_LOCK:
        entry = _PENDING.get(thread)
        if entry is None and project is not None:
            # THE DURABLE FALLBACK (C-33): this process never staged it — it is the panel's
            # process, or a worker that restarted. The store's pending list keeps the latest ask
            # per conversation key; thaw it and let the TTL check below treat it like any local
            # entry. `staged_at` is reconstructed from the row's own timestamp.
            entry = _pending_from_store(thread, project)
            if entry is not None:
                _PENDING[thread] = entry
        if entry is None:
            return None
        staged = entry.get("staged_at")
        if staged is not None and (time.time() - float(staged)) > PROPOSAL_TTL_SECONDS:
            _PENDING.pop(thread, None)
            # the tombstone is what lets a late "sim" (or a late click) hear "that expired"
            # instead of a polite conversational answer to a confirmation of nothing
            _EXPIRED_TOMBSTONES[thread] = time.time()
            log.info("a staged proposal aged out of thread %s before anybody confirmed it", thread)
            return None
        return entry


def _pending_from_store(thread: str, project) -> dict | None:
    """The durable staging row for this conversation, thawed — or None."""
    try:
        from datetime import datetime

        from openfactory.memory import messages as _panel_store

        for q in _panel_store.pending(getattr(project, "name", "") or ""):
            if q.token.partition("|")[0] == thread and q.payload:
                entry = _thaw(q.payload)
                if entry is None:
                    return None
                try:
                    entry["staged_at"] = datetime.fromisoformat(q.ts).timestamp()
                except ValueError:
                    pass  # keep the frozen staged_at; the TTL check handles the rest
                return entry
    except Exception:  # noqa: BLE001 — the fallback is additive; a local miss stays a miss
        log.info("could not read the durable staging for %s", thread, exc_info=True)
    return None


def _expired_recently(*keys: str) -> bool:
    """Whether a proposal aged out under any of these keys — consumed on read: the notice is owed
    to exactly one late confirmation, not to every message for ever after."""
    hit = False
    with _PENDING_LOCK:
        for key in keys:
            if key and _EXPIRED_TOMBSTONES.pop(key, None) is not None:
                hit = True
    return hit


def _freeze(entry: dict) -> str:
    """The staged entry as JSON a DIFFERENT process can reconstruct (C-33).

    Pydantic models (today: the draft's `ProductAnswer`) are tagged and dumped; everything else
    in an entry is JSON-native by construction. The freeze must be FAITHFUL, not merely lossless:
    the proposal token's fingerprint is computed FROM the entry, and the process that answers
    recomputes it — an unfaithful round trip would make every cross-process answer read as
    "replaced"."""
    import json

    from pydantic import BaseModel

    out = {}
    for key, value in entry.items():
        if isinstance(value, BaseModel):
            out[key] = {"__model__": type(value).__name__,
                        "data": value.model_dump(mode="json")}
        else:
            out[key] = value
    return json.dumps(out, ensure_ascii=False, default=str)


#: The models an entry may carry. A NEW model must be registered or `_thaw` refuses the whole
#: entry — half-loading a proposal and running the half is worse than "gone".
_ENTRY_MODELS: dict[str, type] = {}


def _entry_models() -> dict[str, type]:
    if not _ENTRY_MODELS:
        from openfactory.product.role import ProductAnswer

        _ENTRY_MODELS["ProductAnswer"] = ProductAnswer
    return _ENTRY_MODELS


def _thaw(payload: str) -> dict | None:
    """The frozen entry back, or None — never a half-loaded one."""
    import json

    try:
        raw = json.loads(payload)
        out = {}
        for key, value in raw.items():
            if isinstance(value, dict) and "__model__" in value:
                model = _entry_models().get(value["__model__"])
                if model is None:
                    log.warning("a staged proposal carries an unregistered model %r — refusing "
                                "to half-load it", value["__model__"])
                    return None
                out[key] = model(**value["data"])
            else:
                out[key] = value
        return out
    except Exception:  # noqa: BLE001 — an unreadable payload is a gone proposal, not a crash
        log.warning("could not thaw a staged proposal", exc_info=True)
        return None


def remember(thread: str, entry: dict, *, lang=None, project=None) -> str:
    """Stage `entry`, and RETURN the line that admits what it displaced ("" when nothing was).

    THE NOTICE LIVES HERE BECAUSE FOUR CALLERS HAD TO REMEMBER IT AND TWO DID NOT. `_PENDING` holds
    one entry per conversation, last wins — that is the design — but only the fact and defect sites
    announced the eviction. A requirement draft or a queue proposal therefore threw away a pending
    defect in silence: the client had been told "vou registrar como problema", nobody took it back,
    and the next "sim" recorded something else entirely.

    Two callers learning a lesson and two not is the shape this codebase keeps paying for (see
    `final_text` and `BoundedDict`). Returning the notice from the one place that can know about the
    eviction, plus a guard that fails when a caller drops the return value, is what makes it
    structural instead of a habit.
    """
    entry = {**entry, "staged_at": time.time()}
    displaced = None
    with _PENDING_LOCK:
        previous = _PENDING.get(thread)
        if previous is not None and previous.get("kind") != entry.get("kind"):
            displaced = previous
        if thread not in _PENDING and len(_PENDING) >= _MAX_PENDING:
            _PENDING.pop(next(iter(_PENDING)), None)
        _PENDING[thread] = entry
        # a fresh proposal supersedes the memory of an expired one: the next "sim" means THIS
        # text, and must not be answered with "that expired"
        _EXPIRED_TOMBSTONES.pop(thread, None)
    # THE CASE MOVES WITH THE STAGING (#33 hole 7): the intake this draft came from is proposed,
    # and the one it displaced goes back to collecting with its facts kept.
    from openfactory.product import case as _case
    _case.hook("proposed", project, thread, entry, displaced=displaced)
    # THE DURABLE MIRROR (C-33, #70). `_PENDING` is this process's memory, and the panel is a
    # DIFFERENT service: without this row every panel answer found "gone" — the wiring that
    # looked done in one process and was reverted for exactly that. Best-effort, keyed by the
    # same `key|fingerprint` token the click carries; the panel's pending list dedups by key,
    # so a restaged proposal supersedes its predecessor there too.
    if project is not None:
        try:
            from openfactory.memory import messages as _panel_store
            from openfactory.product.voice import confirm_labels

            approve, reject = confirm_labels(language=lang)
            _panel_store.ask(getattr(project, "name", "") or "",
                             _proposal_summary(entry) or "proposta aguardando confirmação",
                             token=proposal_token(thread, entry), approve=approve, reject=reject,
                             channel=thread, payload=_freeze(entry))
        except Exception:  # noqa: BLE001 — the mirror is additive; the staging is not
            log.info("could not mirror the staged proposal onto the panel", exc_info=True)
    if displaced is None:
        return ""
    from openfactory.product.voice import _pick
    return _pick({
        "pt-BR": "(Deixei de lado o que estava aguardando confirmação nesta conversa — se ainda "
                 "quiser aquilo, me peça de novo depois.)\n\n",
        "en": "(I set aside what was awaiting confirmation in this thread — if you still want "
              "it, ask me again afterwards.)\n\n",
    }, lang)


def forget(thread: str) -> dict | None:
    """Throw away whatever is staged here, whatever it is. NOT a confirmation path — `consume` is.

    A pop by key alone cannot be part of performing a yes: between reading a proposal and acting on
    it this handler makes network calls, and by the time the pop runs the key may hold something
    else entirely. This is the primitive for "drop it regardless" (a test cleaning up, a caller that
    has nothing to compare against); a guard in test_confirmation_by_click keeps it out of the
    production paths, because the difference is invisible at the call site and irreversible after.
    """
    with _PENDING_LOCK:
        gone = _PENDING.pop(thread, None)
    if gone is not None:
        from openfactory.product import case as _case
        _case.hook("forgotten", None, thread, gone)
    return gone


def consume(key: str, verified: dict | None, *, fingerprint: str = "",
            project=None, by: str = "", approved: bool = True) -> dict | None:
    """Pop `key` ONLY IF what is staged there is still `verified` — otherwise nothing, and None.

    THE ACT THAT RUNS MUST BE THE ACT THAT WAS CONFIRMED, and until this existed the two were read
    at different moments with the network in between. `_handle` reads the staged entry once, picks
    its branch and judges the sentence against THAT entry; then comes the receipt (a
    chat.postMessage, on every confirmed write) and, for anything but a bare "sim", the judge (a
    model call, seconds). Socket Mode dispatches with concurrency=10, so a second message in the
    same conversation runs in parallel and can replace the staged proposal inside that window. The
    pop then took whatever was under the key: staged "fecha o #511", answered "sim", and #999 —
    which nobody confirmed — was closed on the client's board, in the client's name.

    A compare-and-swap on the way out is what makes the two atomic. Identity, not equality: every
    `remember` stores a fresh dict, so the object under the key IS the proposal's identity, and a
    replacement can never impersonate it.

    THE FINGERPRINT IS FOR THE CLICK PATH, which verifies somewhere this cannot see. A button is
    checked against `pending_for(key)` and then delegates to `handle`, which re-reads — so if the
    replacement landed BEFORE that re-read, identity holds against the wrong entry and only the
    fingerprint the button was posted for still points at the proposal the person actually read.
    A check two round-trips before the act is not a check unless it travels to the act.
    """
    if not key or verified is None:
        return None
    # THE OTHER SURFACE MAY HAVE DECIDED FIRST (C-33). The panel resolves through the durable
    # store and cannot pop THIS process's dict — so before honouring a local hit, ask the store
    # whether this token was already answered. Without it, a panel approve followed by a Slack
    # "sim" runs the act TWICE, each surface convinced it decided.
    if project is not None:
        try:
            from openfactory.memory import messages as _panel_store

            token = proposal_token(key, verified)
            if _panel_store.answer_of(getattr(project, "name", "") or "", token) is not None:
                log.warning("OPENFACTORY_PRODUCT_ALREADY_DECIDED key=%s — this proposal was "
                            "answered on "
                            "another surface; nothing was performed", key)
                with _PENDING_LOCK:
                    if _PENDING.get(key) is verified:
                        _PENDING.pop(key, None)
                return None
        except Exception:  # noqa: BLE001 — an unreadable store must not block a local decision
            log.info("could not check the durable store before consuming", exc_info=True)
    with _PENDING_LOCK:
        current = _PENDING.get(key)
        if current is None and project is not None:
            # THIS process never staged it (the panel's process, or a restarted worker) — OR the
            # other consumer just popped it. Only the durable store can tell the two apart: a
            # cross-process staging still has its PENDING row; a lost race has nothing. Trusting
            # the caller's entry without asking would turn every lost race into the double-write
            # this function exists to prevent.
            token = proposal_token(key, verified)
            try:
                from openfactory.memory import messages as _panel_store

                still_staged = any(
                    p.token == token
                    for p in _panel_store.pending(getattr(project, "name", "") or ""))
            except Exception:  # noqa: BLE001 — an unreadable store cannot vouch for the staging
                log.info("could not check the durable store for the staged row", exc_info=True)
                still_staged = False
            if not still_staged:
                return None
            current = verified
        elif current is None:
            return None
        if current is not verified or (
                fingerprint and proposal_token(key, current).split("|", 1)[1] != fingerprint):
            log.warning("OPENFACTORY_PRODUCT_CONFIRMATION_RACED key=%s — the staged proposal "
                        "changed "
                        "between being read and being written from; nothing was performed", key)
            return None
        _PENDING.pop(key, None)
    # the durable record of the decision — what clears the panel's pending list and what the
    # cross-process guard above reads
    # THE CASE MOVES WITH THE ANSWER (#33 hole 7): confirmed on a yes, dropped on a no.
    from openfactory.product import case as _case
    _case.hook("confirmed" if approved else "rejected", project, key, verified)
    if project is not None:
        try:
            from openfactory.memory import messages as _panel_store

            _panel_store.answer(getattr(project, "name", "") or "",
                                token=proposal_token(key, verified),
                                answer="approve" if approved else "reject", by=by)
        except Exception:  # noqa: BLE001 — the act happened; the record is best-effort and loud
            log.warning("the decision on %s was performed but not recorded durably", key,
                        exc_info=True)
    return verified


def find_waiting(thread: str, channel: str = "", *, project=None) -> tuple[str | None, dict | None]:
    """The staged proposal this confirmation can mean, WITH the key it is staged under.

    A person confirms wherever they happen to be typing: inside the thread the proposal was shown
    in, or back at channel level. The first two lookups cover "staged where I am typing"; the scan
    covers the case they do not — a proposal staged inside a thread, answered with a bare channel
    message. Entries record their channel precisely so this direction is findable; without it the
    bare "sim" fell through to the conversational model, which answered politely and wrote NOTHING.

    Returning the KEY is what lets the caller consume exactly what it read. The old shape
    (`forget(thread) or forget(channel) or waiting`) re-supplied an already-consumed entry from the
    closure — two concurrent confirmations of one proposal became two writes.
    """
    entry = pending_for(thread, project=project)
    if entry is not None:
        return thread, entry
    if channel:
        if channel != thread:
            entry = pending_for(channel, project=project)
            if entry is not None:
                return channel, entry
        # the scan runs for the BARE message too (where thread == channel): that is precisely the
        # person answering "sim" at channel level about a proposal shown inside a thread
        with _PENDING_LOCK:
            candidates = [(k, e) for k, e in _PENDING.items()
                          if e.get("channel") == channel and k not in (thread, channel)]
        # newest first: with several threads waiting in one channel, a bare confirmation means the
        # one most recently put in front of the person
        for key, _ in sorted(candidates, key=lambda kv: kv[1].get("staged_at") or 0, reverse=True):
            entry = pending_for(key, project=project)  # re-read under the TTL check
            if entry is not None:
                return key, entry
    return None, None

def _proposal_summary(entry: dict) -> str:
    """What is on the table, in one blob for the judge. Only what a staged entry actually holds —
    a summary that invents fields would have the model approving something nobody drafted."""
    kind = entry.get("kind", "requisito")
    answer = entry.get("answer")
    draft = getattr(answer, "draft", None) if answer is not None else None
    parts = [f"tipo: {kind}"]
    # `número` is load-bearing for the FINGERPRINT, not just the judge: an accept entry holds
    # nothing but its kind and number, so without it every staged accept hashed identically and a
    # stale button for requirement 3 would have approved whatever accept came to be staged later.
    for label, value in (("título", getattr(draft, "title", "")),
                         ("número", entry.get("number", "") or ""),
                         # WHAT THE NUMBER ALONE DOES NOT DISTINGUISH. Two closes of the same card
                         # in favour of different cards — or two alignments of one card to
                         # different requirements — are different decisions that hash identically
                         # without these, so a button posted for one would perform the other. The
                         # second half of the act is as load-bearing as the first.
                         ("em favor de", entry.get("in_favour_of", "") or ""),
                         ("requisito", entry.get("requirement", "") or ""),
                         # the reason travels onto the client's card in their name, so two closes
                         # (or two drops) of one number with different reasons are different acts
                         # and must not share a button
                         ("motivo", entry.get("reason", "") or ""),
                         ("termo", entry.get("term", "")),
                         # THE SENTENCE ITSELF, and it is load-bearing for exactly the reason the
                         # two lines above are: two decisions recorded against one requirement are
                         # different acts that would hash identically without it, so the button
                         # posted for the first would write the second — into a register whose
                         # entire value is that nobody edits it afterwards.
                         ("decisão", entry.get("decision", "") or ""),
                         ("texto", entry.get("body", "") or entry.get("restated", "")),
                         ("itens", ", ".join(str(n) for n in entry.get("numbers", []) or []))):
        if value:
            parts.append(f"{label}: {value}")
    body = getattr(draft, "body", "") or getattr(draft, "statement", "")
    if body:
        parts.append(f"conteúdo: {str(body)[:800]}")
    # the criteria distinguish two drafts that share a title — a redraft after a correction must
    # not be approvable by the button posted for its predecessor
    criteria = list(getattr(draft, "must_be_true", None) or [])
    if criteria:
        parts.append("critérios: " + "; ".join(str(c) for c in criteria[:8]))
    return "\n".join(parts)


def proposal_token(key: str, entry: dict) -> str:
    """What a confirmation button carries back: WHICH conversation and WHICH proposal.

    The fingerprint is the point. Without it a button posted for one proposal would approve whatever
    is staged under that key at click time — and a proposal CAN be replaced between being shown and
    being clicked (`remember` returns the notice for it). Somebody would then have approved
    which is the exact harm the confirmation gate exists to prevent.
    """
    from hashlib import blake2b

    fingerprint = blake2b(_proposal_summary(entry).encode(), digest_size=6).hexdigest()
    return f"{key}|{fingerprint}"
