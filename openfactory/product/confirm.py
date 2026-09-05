"""What a confirmation DOES — the executor behind every "yes", wherever the yes arrives from.

MOVED OUT OF THE SLACK PACKAGE (#105). It was never Slack-specific: it reads a staged entry, asks
`may_act`, pops by compare-and-swap and calls the product module, composing the reply from
`product/voice.py`. Its home in `runtime/slack/product_channel.py` was an accident of what was
written first — and it was the last thing keeping that file an implementation rather than a
mapping, because `answer_staged` (the panel's gate) had to reach into a vendor package to run it.

THE PREAMBLE IS INSIDE, NOT IN THE CALLER, and that is the whole design of this module. Every one
of the eight typed branches used to open with the identical four lines:

    if not may_act(project, user):      → the refusal, said out loud
    entry = _consume()                  → compare-and-swap, not a pop by key
    if entry is None:                   → somebody else answered first
        return _someone_beat_us()

Only the body differed. Leaving those four in the caller would mean re-writing them in every new
transport — and the second line is not boilerplate: `consume` is a COMPARE-AND-SWAP on the staged
object's identity plus the fingerprint the button was posted for, because a proposal staged while
the receipt or the judge was in flight made a "yes" that had been shown approve something else.
That window is closed here, once, for everybody.

THREE CALLERS, ONE IMPLEMENTATION (ADR-0039):

    the typed "sim"   →  `product_channel._handle`, whose confirm section is now one call
    a click / the panel →  `answer_staged`, which no longer routes through the Slack `handle`
    any other surface →  the `product_answer` row, the pair of `product_pending`

`may_act` is asked here even though `answer_staged` asked it one frame up. The duplication is
deliberate: the gate needs the OUTCOME NAME (`unauthorized`, which the panel maps to a 403), and
this needs the client's sentence — and a transport that forgets the first must still be refused.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("openfactory.product.confirm")


# ── the sanitising boundary ──────────────────────────────────────────────────────────────────────

def _client_detail(detail: str, lang, *, project=None) -> str:
    """A failure detail the client may read, with the raw diagnosis sent to the log instead.

    `WriteResult.detail` is written for whoever reads it, and BOTH the team's log and the client's
    channel read it — so git stderr, a branch name or a file path went straight into a business
    conversation. Sanitised at the boundary rather than at every raise site: there are a dozen of
    those and one of this.
    """
    from openfactory.product.voice import client_safe_detail

    safe, raw = client_safe_detail(detail, language=lang)
    if raw:
        log.warning("[%s] a write failed with a detail the client must not read: %s",
                    getattr(project, "name", "?"), raw[:400])
    return safe


#: A success detail that MEASURES what was written — "3 critérios" — rather than reporting what was
#: not. A count and the thing counted, and nothing else: a sentence about a failed second write
#: never has that shape, so what this recognises is safe to leave unsaid. Its holes cost an extra
#: honest fragment at the end of a reply; the opposite rule's holes cost a swallowed truth, and
#: this surface has already told a client "escrevi nos dois" about a note that did not exist.
_A_MEASURE = re.compile(r"\d+\s+\S+")


def _unfinished(result) -> str:
    """What a SUCCESSFUL write did NOT do, in the module's own words — "" when it did all of it.

    ONE READING FOR EVERY SUCCESS BRANCH, because `WriteResult.detail` carries three different
    meanings on `ok` and each branch was left to guess which it had. `close` guessed by testing the
    detail for emptiness (right, for the one method whose happy path leaves it empty), `defect`
    said everything (so "já registrei esse problema antes" was appended to a headline that already
    led with it), and `align` said nothing (so "não consegui deixar escrito nele que o texto
    anterior foi substituído" was computed, logged for us, and never reached the person it was
    written for — under a sentence claiming the note was left).

    The two meanings that are NOT a residue are recognisable without reading Portuguese: `existed`
    is the module saying the thing was already there, and the reply that carries `existed` leads
    with that fact itself; a measure is the module counting what it wrote. Both are ruled out
    here, once, and everything else is something the client has not been told.

    The two never overlap in the module: an `existed` result returns before the second write that
    could fail, so nothing is dropped by ruling it out.
    """
    detail = (getattr(result, "detail", "") or "").strip()
    if not detail or getattr(result, "existed", False) or _A_MEASURE.fullmatch(detail):
        return ""
    return detail


def _still_to_say(text: str, result, lang, *, project=None) -> str:
    """`text`, plus whatever the module still has to say about a write that SUCCEEDED.

    A `WriteResult` that is `ok` can carry a sentence written for the client: the card was closed
    and the pointer on the survivor was not, the problem was filed and the board refused to place
    the card. Every success branch composed its own headline and returned it, so those sentences
    were computed, logged for us, and never said to the person they were written for — the client
    was told "escrevi nos dois" about a note that does not exist.

    Read here, through the same sanitiser the failure branches use, so a detail that turns out to
    carry a path or a git error still cannot reach a business conversation.
    """
    detail = _unfinished(result)
    if not detail:
        return text
    return f"{text}\n\n{_client_detail(detail, lang, project=project)}"


# ── provenance and the receipt ───────────────────────────────────────────────────────────────────

def _where_it_came_from(project, channel: str) -> str:
    """The provenance cell of a decision row: the conversation it was decided in.

    A channel ID is not provenance — `C0BLR9Z4H0Q` tells the person opening the document in three
    months nothing they can act on. So the configured product channel is named by its ROLE, and an
    id that is not the one we know about is reported as the raw reference rather than dressed up
    as something it may not be.
    """
    cfg = getattr(project, "product", None)
    known = str((getattr(cfg, "channel_id", "") or "") or "")
    if channel and known and channel == known:
        return "conversa com o time de produto"
    return f"conversa com o time de produto ({channel})" if channel else \
        "conversa com o time de produto"


def receipt(project, notify, *, seed: str = ""):
    """A callable that says "we are on it" BEFORE the slow part — at most once, ever.

    A FACTORY RATHER THAN A CLOSURE IN THE HANDLER, because a confirmed write is the slow path
    whichever transport it arrives on, and the click path had no way to send one at all: the person
    who used the affordance we built got minutes of nothing while a checkout ran.

    NOT recorded in the transcript on purpose. Layer 0 keeps what was SAID (ADR-0024); this is a
    receipt, carrying no information for either audit or recall. Recording it would inject "deixa
    eu olhar isso" into every later prompt and teach the model to echo it back.
    """
    said = [False]
    lang = getattr(project, "language", None)
    cfg = getattr(project, "product", None)

    def _say() -> None:
        if said[0] or notify is None:
            return
        said[0] = True
        from openfactory.product.voice import on_it

        try:
            # seeded by the MESSAGE, so consecutive questions get different receipts while the
            # same message always gets the same one (deterministic tests, answerable support)
            notify(on_it(language=lang, agent_name=getattr(cfg, "agent_name", "") or "",
                         seed=seed))
        except Exception:  # noqa: BLE001 — a receipt must never cost us the real answer
            log.warning("could not send the acknowledgement", exc_info=True)

    return _say


# ── the eight typed acts, one function each ──────────────────────────────────────────────────────
#
# THE CHAIN OF `if` WAS A DISPATCH TABLE IN DISGUISE — the same shape `_run_intent` had before the
# intent→row map replaced it. Each of these receives an entry that has ALREADY been authorised and
# popped, so none of them may refuse and none of them may pop again: what they do is perform and
# compose. An unknown kind falls to `_confirm_draft`, exactly as the old chain's final `if` did.

def _confirm_queue(project, entry, *, module, user, lang) -> str:
    """the action that spends money."""
    numbers = entry["numbers"]
    results = module.promote(numbers, actor=user)
    from openfactory.contracts.refs import ref_numbers

    landed = ref_numbers(r.ref for r in results if r.ok and r.ref)
    failed = [r for r in results if not r.ok]
    if not landed:
        return (_client_detail(failed[0].detail, lang, project=project) if failed
                else "não consegui colocar na fila.")
    from openfactory.product.voice import queued

    cfg = getattr(project, "product", None)
    out = queued(landed, language=lang, agent_name=getattr(cfg, "agent_name", "") or "")
    if failed:
        # the partial-failure line reads the SAME detail the total-failure branch above already
        # sanitises — one raw and one clean was the sibling divergence, found by the sweep
        out += f"\n\n{len(failed)} não entraram: " \
               f"{_client_detail(failed[0].detail, lang, project=project)}"
    return out


def _confirm_defect(project, entry, *, module, user, lang) -> str:
    """files it, classified, against the promise it breaks."""
    result = module.file_defect(
        restated=entry["restated"], reported_by=entry.get("reported_by", ""),
        violates=entry.get("violates"), severity=entry.get("severity", ""),
        source=entry.get("source", ""))
    if not result.ok:
        return _client_detail(result.detail, lang, project=project)
    from openfactory.product.voice import defect_filed

    # the sibling of the close below: `file_defect` returns ok with a sentence when the card
    # was created and the board refused to place it, and that card is invisible to the queue
    # until a person moves it
    return _still_to_say(
        defect_filed(ref=result.ref, violates=entry.get("violates"),
                     language=lang, existed=result.existed),
        result, lang, project=project)


def _confirm_ticket(project, entry, *, module, user, lang) -> str:
    """opens the card the person asked for, as described, and says where it is."""
    result = module.file_ticket(
        title=entry["title"], described=entry.get("described", ""),
        reported_by=entry.get("reported_by", ""), source=entry.get("source", ""))
    if not result.ok:
        return _client_detail(result.detail, lang, project=project)
    from openfactory.product.voice import ticket_filed
    return _still_to_say(
        ticket_filed(ref=result.ref, url=getattr(result, "url", ""), language=lang,
                     existed=result.existed),
        result, lang, project=project)


def _confirm_accept(project, entry, *, module, user, lang) -> str:
    """the act that creates a promise."""
    # the RAW id, like every other actor this handler passes: `module.accept` re-checks
    # `may_act` against the configured ids, and a decorated `<@U…>` failed that lookup — the
    # gate that had just admitted the admin refused them one call deeper. The module decorates
    # the id itself, only where a human-readable record is written.
    result = module.accept(entry["number"], actor=user)
    if not result.ok:
        return _client_detail(result.detail, lang, project=project)
    from openfactory.product.voice import accepted

    cfg = getattr(project, "product", None)
    head = accepted(number=entry["number"], language=lang,
                    agent_name=getattr(cfg, "agent_name", "") or "")
    if result.existed:
        return head     # nothing was agreed just now, so there is nothing new to break down
    # A PRODUCT OWNER DOES NOT ASK PERMISSION TO DECOMPOSE (the product owner, 2026-07-31).
    # "break requirement N into tasks" is operator vocabulary; a client says "can we start?" —
    # and until this line the agreement produced a sentence and no work, so somebody had to
    # know the magic phrase for anything to exist. Filing costs nothing: Backlog is inert, and
    # the money gate is `promote`, which stays staged and gated (ADR-0019 §5).
    #
    # No receipt call here: `confirm` already fired it for every confirmed write, which is the
    # whole reason it lives there instead of in each branch.
    return _also_broke_it_down(module, entry["number"], user, head, lang, project)


def _confirm_drop(project, entry, *, module, user, lang) -> str:
    """the act that takes something OFF the table."""
    result = module.drop(entry["number"], actor=user, reason=entry.get("reason", ""))
    if not result.ok:
        return _client_detail(result.detail, lang, project=project)
    from openfactory.product.voice import dropped

    cfg = getattr(project, "product", None)
    return dropped(number=entry["number"], was_a_promise=entry.get("was_a_promise", False),
                   language=lang, agent_name=getattr(cfg, "agent_name", "") or "")


def _confirm_decision(project, entry, *, module, user, lang) -> str:
    """the act that puts words in a person's mouth, for keeps."""
    result = module.record_decision(
        entry["number"], decision=entry.get("decision", ""), actor=user,
        # WHERE IT CAME FROM, which is half of what this register answers. A decision whose
        # provenance says only "a person" sends the next reader back to a Slack search.
        where=_where_it_came_from(project, entry.get("channel", "")))
    if not result.ok:
        return _client_detail(result.detail, lang, project=project)
    from openfactory.product.voice import decision_recorded

    cfg = getattr(project, "product", None)
    return decision_recorded(number=entry["number"], existed=result.existed, language=lang,
                             agent_name=getattr(cfg, "agent_name", "") or "")


def _confirm_close(project, entry, *, module, user, lang) -> str:
    """the act that takes a card off the client's board."""
    # the RAW id, like every sibling branch: `may_act` is re-checked against the configured ids
    # one call deeper, and a decorated `<@U…>` fails that lookup. The module decorates it
    # itself, where the human-readable record is written.
    result = module.close_card(entry["number"], actor=user,
                              in_favour_of=entry.get("in_favour_of"),
                              reason=entry.get("reason", ""))
    if not result.ok:
        return _client_detail(result.detail, lang, project=project)
    from openfactory.product.voice import card_closed

    cfg = getattr(project, "product", None)
    # AN OK CLOSE CAN STILL BE HALF DONE. `close_card` closes the card and then writes the
    # pointer on the survivor, and it deliberately reports the second half failing as a
    # SUCCESS with a sentence for the client — the close happened and must not be re-offered.
    # Announcing "escrevi nos dois" over that sentence told somebody a link exists that does
    # not, on the one card the next person will pick up.
    return _still_to_say(
        card_closed(number=entry["number"], in_favour_of=entry.get("in_favour_of"),
                    linked=not _unfinished(result),
                    reasoned=bool((entry.get("reason") or "").strip()),
                    language=lang, agent_name=getattr(cfg, "agent_name", "") or ""),
        result, lang, project=project)


def _confirm_align(project, entry, *, module, user, lang) -> str:
    """the act that changes what gets BUILT."""
    result = module.align_card(entry["number"], requirement=entry["requirement"], actor=user)
    if not result.ok:
        return _client_detail(result.detail, lang, project=project)
    from openfactory.product.voice import card_aligned

    cfg = getattr(project, "product", None)
    # THE SIBLING OF THE CLOSE ABOVE, and it was the branch left behind. `align_card` rewrites
    # the card and then comments to say what happened to it; the comment failing is reported as
    # a SUCCESS with a sentence for the client, because the criteria really were replaced. The
    # headline announced the note anyway — so the card's criteria changed, nothing on the card
    # said so, and the person who authorised it was told the opposite.
    return _still_to_say(
        card_aligned(number=entry["number"], requirement=entry["requirement"],
                     noted=not _unfinished(result), language=lang,
                     agent_name=getattr(cfg, "agent_name", "") or ""),
        result, lang, project=project)


def _confirm_fact(project, entry, *, module, user, lang) -> str:
    """writes it down, attributed, as `aprendido`."""
    result = module.note_fact(term=entry["term"], body=entry["body"],
                              said_by=entry.get("said_by", ""),
                              where=entry.get("source", ""))
    if not result.ok:
        return _client_detail(result.detail, lang, project=project)
    from openfactory.product.voice import fact_noted

    return fact_noted(term=entry["term"], language=lang)


def _confirm_draft(project, entry, *, module, user, lang) -> str:
    """a yes on a pending draft: the requirement itself."""
    from openfactory.product.voice import written_up

    result = module.propose(entry["answer"], actor=user,
                            asked_by=entry.get("asked_by", ""), date=entry.get("date", ""),
                            source=entry.get("source", ""))
    if not result.ok:
        return _client_detail(result.detail, lang, project=project)
    return written_up(title=entry["answer"].draft.title, url=result.url,
                      # "landed in the base" and "still a proposal nobody merged" are different
                      # facts and get different sentences — the second one also warns that she
                      # cannot read it yet, which is true and was previously invisible
                      merged=getattr(result, "merged", True),
                      # WHAT THE WRITE MINTED, not what was predicted before it. The staged
                      # number is derived from the base corpus alone; the mint also consults
                      # the unlanded `req/*` branches, so a pushed-but-unmerged proposal made
                      # the two disagree — and the client was told "o requisito 7 está
                      # registrado" about a file called `0008-…md`. Their very next sentence
                      # is `aceita o requisito 7`, which finds nothing. The staged value stays
                      # as a fallback for a result that carries none, never as a correction of
                      # one that does.
                      number=getattr(result, "number", 0) or entry.get("number") or 0,
                      language=lang)


#: kind → what performing it means. The DEFAULT is the draft, not a refusal: the original chain
#: ended with a bare `if waiting and is_yes(...)`, so an entry whose kind nobody typed is a
#: requirement draft. Changing that here would silently stop writing requirements.
_EXECUTORS = {
    "queue": _confirm_queue,
    "defect": _confirm_defect,
    "ticket": _confirm_ticket,
    "accept": _confirm_accept,
    "drop": _confirm_drop,
    "decision": _confirm_decision,
    "close": _confirm_close,
    "align": _confirm_align,
    "fact": _confirm_fact,
}


def confirm(project, *, key: str, entry: dict, fingerprint: str = "", module, user: str,
            lang=None, on_it=None, via: str = "slack") -> str:
    """A person said yes to what is staged at `key`. Returns what to say back.

    `may_act` → `consume` (compare-and-swap) → perform → compose, in that order and never another.

    `via` is the transport the yes arrived through — provenance for the gate, never permission
    (`may_act` documents why). Defaulted like `may_act` is, so the chat callers keep saying what
    they said; the worker hands down what the panel sent, so an approval typed there is no longer
    recorded as a Slack one.

    AUTHZ BEFORE POP. An unauthorised "yes" must not consume the proposal — the actual approver's
    later yes still has to find it. (The tech-lead's action path learned this the same way.)

    `entry` is what the CALLER read and judged, and it is what gets swapped out: `consume` compares
    identity, so a proposal staged during the receipt or the judge cannot be performed by a yes
    that was shown, and approved, something else. `fingerprint` carries what a CLICK verified two
    round-trips earlier, because a check that does not travel to the act is not a check.

    THE RECEIPT GOES FIRST, before the authorisation and before the write. Every branch below
    reaches a checkout, the client's board or an agent — `align` runs two checkouts and a model
    call — and the person has just approved something irreversible. None of the branches said
    anything first, so a yes bought minutes of silence at the exact moment somebody most needs to
    know they were heard: the platform's standing invariant is that a stall self-heals or speaks,
    never a quiet nothing.
    """
    from openfactory.product.module import may_act, unauthorized_message

    if on_it is not None:
        on_it()
    if not may_act(project, user, via=via):
        return unauthorized_message(project)

    from openfactory.product.staging import consume

    # exactly the entry the caller read and judged, and None when anything replaced it since. The
    # old shape popped by KEY — so a proposal staged during the receipt or the judge was written
    # from by a yes that had been shown, and had approved, something else.
    performed = consume(key, entry, fingerprint=fingerprint, project=project, by=user,
                        approved=True)
    if performed is None:
        from openfactory.product.voice import proposal_already_handled

        return proposal_already_handled(language=lang)

    run = _EXECUTORS.get(str(performed.get("kind") or ""), _confirm_draft)
    said = run(project, performed, module=module, user=user, lang=lang)
    # THE CASE IS FILED with what the executor said — the ref and the URL a person can follow.
    from openfactory.product import case as _case
    _case.hook("filed", project, key, performed, said=said)
    return said


# ── the acceptance's second act ──────────────────────────────────────────────────────────────────

def _also_broke_it_down(module, number: int, user: str, head: str, lang, project) -> str:
    """The acceptance sentence, plus what the automatic breakdown produced.

    THE BREAKDOWN MUST NEVER BE ABLE TO COST THE AGREEMENT. The promise is already written and
    pushed when this runs; everything here is a second act on top of a finished one, so every way
    it can go wrong ends in the client still being told, plainly, that the requirement is agreed.
    That is why the whole thing sits under a catch-all and why the failure line says what still
    holds before it says what did not happen — the opposite order reads as "your acceptance
    failed", about the one thing that certainly did not.

    Two shapes, and they are not the same news:
      - work was filed → the ordinary breakdown sentence, which already ends by saying that
        starting is a person's decision. Nothing about this act spends anything.
      - nothing was filed → say so, say the agreement holds anyway, and offer the retry. Silence
        here would leave a client believing cards exist that do not, which is the exact shape
        `_breakdown_reply` was rebuilt to stop.
    """
    try:
        results = module.break_down(number, actor=user)
    except Exception:  # noqa: BLE001 — the promise is written; this is a courtesy on top of it
        # ERROR, AND UNDER ITS OWN CODE. This catch-all is wide enough to swallow a refactor —
        # rename `break_down` and every acceptance would go on answering politely that it could not
        # break anything down, for ever, with the client believing the platform is merely busy.
        # A test pins the call so a signature drift fails a build; this line is what makes the
        # runtime version of the same failure findable in one grep instead of inferred.
        log.error("OPENFACTORY_PRODUCT_AUTOBREAK_FAILED project=%s req=%s — the acceptance stands "
                  "and no "
                  "work was filed", getattr(project, "name", "?"), number, exc_info=True)
        results = []

    if results and any(r.ok for r in results):
        return head + "\n\n" + _breakdown_reply(results, number, "", lang, project=project)

    detail = ""
    if results:
        failed = [r for r in results if not r.ok]
        detail = _client_detail(failed[0].detail, lang, project=project) if failed else ""
    tail = ("Ainda não consegui transformar isso em frentes de trabalho"
            + (f": {detail}" if detail else " agora")
            + ". O acordo está registrado do mesmo jeito — é só me pedir para quebrar em tarefas "
              "que eu tento de novo.")
    return f"{head}\n\n{tail}"


def _breakdown_reply(results, number: int, name: str, lang=None, project=None) -> str:
    """What the client reads after a requirement was broken into tasks.

    BOTH failure branches pass through `_client_detail`: the guard that found the second one is the
    reason it exists — four sites were sanitised by hand and this fifth, inside a reply builder
    rather than a handler branch, was missed. A per-site fix would have shipped looking complete.

    AND `ok` IS THREE OUTCOMES HERE, NOT ONE — the FIFTH two-write branch, and the last to learn the
    rule `close`, `defect`, `align` and `refine` share. `_file_one` creates the issue and then
    places it on the board, and it reports the placement failing as a SUCCESS carrying a sentence
    written for the client (no Backlog column, no card for the issue, no Status field, a refused
    `item-edit` — all real). It also returns EARLY, having placed nothing, when an issue with that
    title already exists. Both were announced as "estão no Backlog", about cards that have no
    column — invisible to `readiness` and `propose_queue`, which match the column exactly and have
    no else-branch, so the role can never surface that work again.

    So: the residue goes through `_still_to_say`, like every other two-write branch. The card that
    was already there needs the reply ITSELF to say so, because `_unfinished` stays deliberately
    quiet on `existed` — the same split `defect_filed(existed=True)` makes one layer up.
    """
    head = f"{name}: " if name else ""
    failed = [r for r in results if not r.ok]
    if failed and len(failed) == len(results):
        return f"{head}{_client_detail(failed[0].detail, lang, project=project)}"
    if not results:
        # no drafts and no errors: the breakdown ran and produced nothing. Counting that as "virou
        # 0 tarefas" and announcing the Backlog was the shape this whole function is being fixed
        # for — a sentence about cards that do not exist.
        return (f"{head}Não consegui tirar nenhuma tarefa do requisito {number}. Me diga o que ele "
                f"deveria produzir na prática e eu tento de novo.")

    landed = [r for r in results if r.ok]
    already = [r for r in landed if getattr(r, "existed", False)]
    fresh = [r for r in landed if not getattr(r, "existed", False)]
    # a card this call filed AND placed. The board refusing the placement comes back as `ok` with a
    # sentence, and `_unfinished` is the one reading that tells a residue from a measure.
    placed = [r for r in fresh if not _unfinished(r)]

    listed = ", ".join(r.ref for r in landed if r.ref)
    noun = "tarefa" if len(landed) == 1 else "tarefas"
    tail = f": {listed}" if listed else ""
    if fresh:
        out = f"{head}O requisito {number} virou **{len(landed)}** {noun}{tail}."
    else:
        # nothing was created and nothing was moved: "virou" would claim this turn did something
        out = (f"{head}O requisito {number} já estava dividido em **{len(landed)}** {noun}{tail} "
               f"— não criei nada novo e não mudei nada de lugar.")
    if placed:
        one = len(placed) == 1
        where = (("Está" if one else "Estão") if len(placed) == len(landed)
                 else f"{', '.join(r.ref for r in placed if r.ref)} {'está' if one else 'estão'}")
        out += (f"\n\n{where} no Backlog — começar a trabalhar {'nela' if one else 'nelas'} "
                f"continua sendo decisão de uma pessoa.")
    if already and fresh:
        one = len(already) == 1
        out += (f"\n\n{', '.join(r.ref for r in already if r.ref)} já "
                f"{'existia' if one else 'existiam'} de antes — não criei de novo, e "
                f"{'continua' if one else 'continuam'} onde {'estava' if one else 'estavam'}.")
    # the module's own sentence about the cards it could not place, said to the person it was
    # written for. First result only, like the failure line below: one voice per outcome — so when
    # the batch has siblings that DID land, the cards it is about have to be named, or the client
    # reads a caveat with no subject and cannot tell which of them to go and look at.
    unplaced = [r for r in fresh if _unfinished(r)]
    if unplaced:
        if len(landed) > 1:
            out += f"\n\nSobre {', '.join(r.ref for r in unplaced if r.ref)}:"
        out = _still_to_say(out, unplaced[0], lang, project=project)
    if failed:
        out += (f"\n\n{len(failed)} não deu para registrar: "
                f"{_client_detail(failed[0].detail, lang, project=project)}")
    return out


# ── the gate a token arrives at: a click, the panel, the `product_answer` row ────────────────────

def _clicked_but_gone(project) -> str:
    from openfactory.product.voice import proposal_gone

    return proposal_gone(language=getattr(project, "language", None))


def _clicked_but_replaced(project) -> str:
    from openfactory.product.voice import proposal_replaced

    return proposal_replaced(language=getattr(project, "language", None))


def _clicked_reject(project) -> str:
    from openfactory.product.voice import proposal_rejected

    return proposal_rejected(language=getattr(project, "language", None))


def _is_requester(entry: dict, user: str) -> bool:
    """Whether `user` is the person this staged proposal came from.

    Staged entries record who spoke under different keys — a draft has `asked_by`, a dictated fact
    has `said_by`, a defect has `reported_by` — and all three hold a Slack mention (`<@Uxxx>`), so
    the id is matched inside the string rather than compared to it.
    """
    if not user:
        return False
    for key in ("asked_by", "said_by", "reported_by", "actor"):
        if user in str(entry.get(key) or ""):
            return True
    return False


def answer_staged(project, *, token: str, approved: bool, user: str, module=None,
                  notify=None, via: str = "slack") -> tuple[str, str]:
    """`(outcome, sentence)` — a staged proposal resolved by TOKEN, with the outcome NAMED.

    `via` is the transport the click or the call arrived through, handed to each gate below and
    to `confirm` — provenance only. The worker's row passes what the panel sent (2026-08-25); the
    module it builds already carried it, and the gates here did not, so a panel approval was
    recorded as authorised through Slack by the same call that had just built the module right.

    THE SECOND CALLER MADE THIS NECESSARY (C-33, #70). The Slack click renders one sentence and is
    done; the panel's answer route has to map the outcome onto an HTTP status and decide whether
    to record anything — and telling "unauthorized" apart from "done" by comparing prose is how a
    refusal gets recorded as a decision. Outcomes: `done`, `rejected`, `unauthorized`, `gone`,
    `replaced`, `expired`.

    IT NO LONGER ROUTES THROUGH THE SLACK `handle` (#105). That indirection existed for a good
    reason — "exactly one implementation of what a confirmation does, a second one would drift" —
    and the reason survives: `confirm` IS that one implementation, and the typed path calls the
    same function. What the detour cost was the panel reaching into a vendor package to run a
    write, and a second read of the staged entry between the fingerprint check and the pop.
    """
    from openfactory.product.staging import _expired_recently, pending_for, proposal_token

    lang = getattr(project, "language", None)
    key, _, fingerprint = (token or "").partition("|")
    entry = pending_for(key, project=project)
    if entry is None:
        if _expired_recently(key):
            from openfactory.product.voice import proposal_expired

            return "expired", proposal_expired(language=lang)
        return "gone", _clicked_but_gone(project)
    # WHAT THIS CALL VERIFIED, computed rather than taken from the token: a button minted before
    # the fingerprint existed carries none, and "no fingerprint on the button" must not mean "no
    # check at the pop". Below this line the only thing that may be performed is the entry above.
    verified = proposal_token(key, entry).split("|", 1)[1]
    if fingerprint and verified != fingerprint:
        # staged, but not the thing on the button — approving it would confirm unread text
        return "replaced", _clicked_but_replaced(project)

    from openfactory.product.module import may_act, unauthorized_message
    from openfactory.product.staging import consume

    if not approved:
        # REFUSING BY CLICK IS GATED LIKE THE TYPED "NÃO", not like the approval: the person whose
        # request this is may take their own proposal back ("não, não é isso"), and only a third
        # party would be vandalising a draft an admin was about to approve. Requiring an admin here
        # while the typed path allowed the requester was the same act with two different rules.
        if not may_act(project, user, via=via) and not _is_requester(entry, user):
            return "unauthorized", unauthorized_message(project)
        if consume(key, entry, fingerprint=verified, project=project, by=user,
                   approved=False) is None:
            # destroying is an act too, and a race here would throw away a proposal this button
            # was never posted for
            return "replaced", _clicked_but_replaced(project)
        return "rejected", _clicked_reject(project)
    if not may_act(project, user, via=via):
        # AUTHZ BEFORE POP, like every other confirmation path: an unauthorised click must not
        # consume the proposal, or the real approver's later yes finds nothing. `confirm` asks
        # again one frame down — this one exists to NAME the outcome for an HTTP caller.
        return "unauthorized", unauthorized_message(project)

    # Approved. `module` is the same seam the typed path carries: None in production (a real one is
    # built here) and injected by a test, so the click→write chain is provable without a checkout.
    from openfactory.product.module import ProductModule

    name = getattr(project, "name", "?")
    # BUILT WITH THE SAME `via` THE GATES WERE TOLD. The panel's route hands no module, so the
    # one built here is the one whose writes are recorded — and `ProductModule`'s default is
    # `"slack"`: with the two gates above saying `panel`, the write they authorised said
    # `slack`, one line down, for the same click (found driving the route, 2026-08-26).
    module = module or ProductModule(project, via=via)
    # ADR-0024 layer 0: A CLICK IS A TURN. It was recorded when this went through `handle`, and
    # dropping it would leave the conversation's memory showing a proposal nobody ever answered —
    # so the next turn would re-offer, or discuss, something the person has already approved. The
    # word is what the typed path would have carried, because that is the act being recorded.
    try:
        from openfactory.memory import transcript

        transcript.record(name, thread=key, role="person", text="sim", actor=user, channel=key)
    except Exception:  # noqa: BLE001 — the record must never cost the person their answer
        log.warning("[%s] could not record the confirming turn", name, exc_info=True)

    # THE FINGERPRINT TRAVELS WITH IT, to the pop. Between the check above and the swap below sits
    # the transcript write — a DynamoDB round-trip — and Socket Mode dispatches with
    # concurrency=10, so a second message in the same conversation can replace the staged proposal
    # inside that window. Without carrying what was verified, the button posted for #511 closed the
    # #999 that landed meanwhile, and the check above was decoration.
    #
    # SILENCE IS THE WORST ANSWER, and this catch-all came WITH the executor. Routing through the
    # Slack `handle` used to supply it; without it here, a crash in a write branch would reach the
    # listener as an exception and the person who clicked would get nothing — indistinguishable
    # from being ignored, and invisible to us until they complained.
    try:
        sentence = confirm(project, key=key, entry=entry, fingerprint=verified, module=module,
                           user=user, lang=lang, via=via,
                           on_it=receipt(project, notify, seed=token)) or ""
    except Exception:  # noqa: BLE001 — a bad proposal must never kill the socket or the route
        log.exception("[%s] confirming a staged proposal failed", name)
        # a distinct marker so ONE occurrence pages, rather than blending into the generic error
        # burst threshold — a client hearing nothing is not a transient
        log.error("OPENFACTORY_PRODUCT_MUTE project=%s thread=%s — the client got no "
                  "answer", name, key)
        from openfactory.product.voice import broke

        sentence = broke(language=lang)
    try:
        from openfactory.memory import transcript

        if sentence:
            transcript.record(name, thread=key, role="agent", text=str(sentence), channel=key)
    except Exception:  # noqa: BLE001 — the reply is already earned; the record must not eat it
        log.warning("[%s] could not record the answer to the confirmation", name, exc_info=True)
    return "done", sentence
