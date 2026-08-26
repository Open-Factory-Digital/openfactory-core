"""A click cannot be misread — ADR-0029.

WHY THIS EXISTS. On 2026-07-30 an owner approved a staged requirement with "Sim — registre." The
word-list gate did not recognise it, nothing was written, and the agent said it had been. A model
now reads the sentence, which fixes recognition — but reading is still INTERPRETATION standing
between a person and an irreversible act taken in their name.

A click is not interpreted. It carries the clicker's identity, it names exactly what was clicked,
and it cannot be a sentence about something else. For the one decision in this platform that spends
money and writes in somebody's name, that is the requirement.

The tests are ordered by what is easiest to get wrong:

  1. DEGRADATION — a provider without buttons must still work, and must not post twice.
  2. THE FINGERPRINT — a proposal replaced between the post and the click must not be approved in
     its place. This is the harm buttons could otherwise INTRODUCE, so it comes before the happy path.
  3. AUTHORISATION — a click carries a real user id, so the same gate applies, and an unauthorised
     click must not consume the proposal.
  4. ONE IMPLEMENTATION — an approved click runs the same handler the typed path runs; a second
     copy of "what a confirmation does" would drift.
  5. REACH — the listener must actually route interactive envelopes, and the staging sites must
     actually offer the buttons.
"""

from __future__ import annotations

import add_ons
import pytest

import openfactory.product.channel as pc
from openfactory.adapters.channel import ChannelAdapter, ConfirmingChannel
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef

ADMIN, OUTSIDER = "U1", "U9"
KEY = "C0PROD"


@pytest.fixture(autouse=True)
def _clean():
    """`pc._PENDING` is module state. A test that stages and never forgets leaks its entry into
    whatever file runs next — this file once broke two of test_acceptance_loop's tests purely by
    alphabetical ordering, the exact defect its own cap test documents fixing."""
    pc._PENDING.clear()
    yield
    pc._PENDING.clear()


def _project():
    return Project(name="books", repo_path="/t", language="pt-BR",
                   tracker=ProviderRef(kind="github", repo="a/b"),
                   forge=ProviderRef(kind="github", repo="a/b"),
                   product=ProductConfig(docs_repo="a/docs", channel_id=KEY,
                                         admins=[ADMIN], agent_name="Nina"))


class _Module:
    """Boundary fake: the writes are recorded, everything between is production code."""

    def __init__(self):
        self.wrote: list[str] = []

    def settle_acceptance(self, text):
        return None

    def close_decisions_answered(self, *, channel=""):
        return 0

    def confirmed(self, reply, *, proposal):
        return "neither"

    def context(self):
        from types import SimpleNamespace
        return SimpleNamespace(available=True, reason="")

    def note_fact(self, *, term, body, said_by, where=""):
        from types import SimpleNamespace
        self.wrote.append(term)
        return SimpleNamespace(ok=True, existed=False, detail="", ref="")


def _stage(term="erp", body="a firma usa Primavera"):
    pc.forget(KEY)
    pc.remember(KEY, {"kind": "fact", "term": term, "body": body, "said_by": ADMIN})
    return pc.proposal_token(KEY, pc.pending_for(KEY))


# ── 1. degradation ─────────────────────────────────────────────────────────────────────────────
def test_a_channel_without_buttons_is_still_a_valid_channel():
    """The capability is a SEPARATE protocol precisely so this holds. Folding it into
    `ChannelAdapter` would make every existing adapter and test double fail an isinstance check for
    something they legitimately cannot do."""
    class _Bare:
        def say(self, **kw):
            return True

        def mention(self, person, **kw):
            return person

        def start_listeners(self):
            return []

    assert isinstance(_Bare(), ChannelAdapter)
    assert not isinstance(_Bare(), ConfirmingChannel)


def test_slack_declares_the_capability():
    SlackChannel = add_ons.module("openfactory.adapters.channel.slack").SlackChannel

    assert isinstance(SlackChannel(), ConfirmingChannel)


def test_with_no_confirm_seam_the_prose_is_returned():
    """Every caller that is not the listener — an activity, the panel, a test — passes nothing and
    must get the text back to post itself."""
    _stage()
    out = pc.offer_with_buttons(_project(), KEY, "confirma?", None)
    assert out == "confirma?"


def test_when_the_buttons_LAND_the_result_is_POSTED_not_None():
    """`None` already means "I could not answer — fall through to the conversational model". A
    successful post returning None therefore read as a FAILED intent: the client got the buttons AND
    an unrelated conversational reply, and paid for a model call to produce it. `Posted` is truthy
    even when empty, and carries the text so the transcript still records what she said."""
    _stage()
    out = pc.offer_with_buttons(_project(), KEY, "confirma?", lambda *a: True)

    assert isinstance(out, pc.Posted), type(out)
    assert bool(out) is True, "a successful post must not read as 'could not answer'"
    assert "confirma?" in str(out), "the transcript would lose the proposal"


def test_when_the_buttons_FAIL_the_prose_comes_back():
    """A provider hiccup must cost the affordance, never the proposal."""
    _stage()
    assert pc.offer_with_buttons(_project(), KEY, "confirma?", lambda *a: False) == "confirma?"

    def _boom(*a):
        raise RuntimeError("slack down")

    assert pc.offer_with_buttons(_project(), KEY, "confirma?", _boom) == "confirma?"


# ── 2. the fingerprint — the harm buttons could introduce ──────────────────────────────────────
def test_a_REPLACED_proposal_is_not_approved_in_the_old_ones_place():
    """THE reason the token carries a fingerprint. A proposal CAN be replaced between being shown
    and being clicked; without this, the click would approve whatever is staged at click time and
    somebody would have confirmed text they never read."""
    token = _stage("erp", "a firma usa Primavera")
    pc.remember(KEY, {"kind": "fact", "term": "erp", "body": "a firma usa SAP", "said_by": ADMIN})
    mod = _Module()

    # `module=mod` is load-bearing: without it production never sees this fake and `wrote == []`
    # could not fail — a stale-fingerprint branch that fell through while wording its reply
    # correctly would write with the test still green
    reply = pc.confirm_by_click(_project(), token=token, approved=True, user=ADMIN, module=mod)

    assert mod.wrote == []
    assert reply and "diferente do que estava neste botão" in reply, reply
    assert pc.pending_for(KEY) is not None, "the replacement was destroyed by a stale click"


def test_the_replacement_that_lands_AFTER_the_check_is_not_approved_either(monkeypatch):
    """THE CHECK ABOVE ONLY TESTED THE CHECK, NEVER THE POP, and the gap between them is two
    network round-trips wide.

    `confirm_by_click` verifies the fingerprint against what is staged NOW, then delegates to
    `handle` — which records the incoming turn (a DynamoDB write), re-reads the staged entry by
    KEY, and pops whatever it finds. Socket Mode dispatches with concurrency=10, so a second
    message in the same conversation runs in parallel and can replace the proposal inside that
    window. Driven at the real seam: the transcript write is where the replacement lands, exactly
    as it would in production. The button posted for "Primavera" closed on "SAP" — a fact recorded
    in somebody's name that they never read, with the fingerprint intact and satisfied.

    Revert the fingerprint carried into `handle` and this writes.
    """
    from openfactory.memory import transcript

    token = _stage("erp", "a firma usa Primavera")
    mod = _Module()
    raced: list[str] = []

    def _record(*a, **kw):
        # the concurrent message, arriving while this click is being written to the transcript
        if not raced:
            raced.append("once")
            pc.remember(KEY, {"kind": "fact", "term": "erp", "body": "a firma usa SAP",
                              "said_by": ADMIN})
        return ""

    monkeypatch.setattr(transcript, "record", _record)

    reply = pc.confirm_by_click(_project(), token=token, approved=True, user=ADMIN, module=mod)

    assert raced, "the seam never ran — the test proves nothing"
    assert mod.wrote == [], "the button performed a proposal it was not posted for"
    assert pc.pending_for(KEY) is not None, "a stale click consumed the proposal that replaced it"
    assert reply, "the click that performed nothing said nothing"


def test_nothing_in_the_channel_pops_a_proposal_by_KEY_ALONE():
    """The structural half, and the reason `consume` takes the verified entry rather than just a
    key. Popping by key is indistinguishable at the call site from popping the thing that was
    judged, and the difference only shows up as a write nobody authorised — so the unconditional
    primitive (`forget`) is barred from the production paths and the next confirmation branch
    inherits the compare-and-swap instead of having to remember it."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path("openfactory/product/channel.py").read_text())
    offenders = [n.lineno for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "forget"]

    assert not offenders, (
        f"forget() is called at line(s) {offenders}: a pop by key alone writes from whatever is "
        "staged at pop time, not from what was verified — use consume(key, verified)")


def test_a_STALE_button_says_so_instead_of_failing_silently():
    """A worker restart drops staged proposals on purpose. The click that arrives afterwards must
    explain itself — three distinct facts (gone, replaced, rejected) get three distinct sentences,
    because one message for all of them leaves the reader unable to tell which happened."""
    token = _stage()
    pc.forget(KEY)

    reply = pc.confirm_by_click(_project(), token=token, approved=True, user=ADMIN)

    # the contract, not the prose: the GONE sentence, and not the other two facts' sentences
    from openfactory.product.voice import proposal_gone, proposal_rejected, proposal_replaced

    # the PROJECT's language, not the platform default: `_project()` declares pt-BR, and
    # comparing a pt-BR reply against the default's sentence measured the default instead of
    # the contract (2026-08-14, when the default became English)
    assert reply == proposal_gone(language="pt-BR"), reply
    assert reply != proposal_replaced(language="pt-BR")
    assert reply != proposal_rejected(language="pt-BR")


def test_the_token_changes_with_the_proposal():
    a = _stage("erp", "usa Primavera")
    b = _stage("erp", "usa SAP")
    assert a != b, "two different proposals share a token — the fingerprint is not fingerprinting"


# ── 3. authorisation ───────────────────────────────────────────────────────────────────────────
def test_an_unauthorised_click_is_refused_AND_does_not_consume_the_proposal():
    """Authz before pop, like every other confirmation path: the real approver's later click has to
    still find something to approve."""
    token = _stage()
    mod = _Module()

    reply = pc.confirm_by_click(_project(), token=token, approved=True, user=OUTSIDER, module=mod)

    assert reply, "an unauthorised click was answered with silence"
    assert mod.wrote == [], "an unauthorised click reached the write path"
    assert pc.pending_for(KEY) is not None, "an unauthorised click consumed the proposal"


def test_rejecting_drops_it_and_says_nothing_was_recorded():
    token = _stage()

    reply = pc.confirm_by_click(_project(), token=token, approved=False, user=ADMIN)

    assert reply and "Nada foi registrado" in reply, reply
    assert pc.pending_for(KEY) is None, "a rejected proposal is still staged"


def test_an_unauthorised_REJECT_cannot_destroy_the_proposal():
    """The asymmetry that matters: refusing is also an act. An outsider must not be able to throw
    away work an admin was about to approve."""
    token = _stage()

    pc.confirm_by_click(_project(), token=token, approved=False, user=OUTSIDER)

    assert pc.pending_for(KEY) is not None, "an outsider destroyed a pending proposal"


# ── 4. one implementation ──────────────────────────────────────────────────────────────────────
def test_an_approved_click_runs_the_SAME_path_as_a_typed_yes(monkeypatch):
    """A second copy of "what a confirmation does" would drift from the first, so both paths must
    end in the same function.

    IT USED TO DELEGATE TO `handle` AND NOW CALLS `confirm` (#105). The promise is unchanged — one
    implementation of what a confirmation does — but the shared thing is the EXECUTOR rather than
    the whole Slack conversation handler, which is why the panel no longer imports this package to
    run a write. Patched on the CORE module, because that is where production resolves it: patching
    the channel's bound alias would leave this passing while the click ran something else.
    """
    from openfactory.product import confirm as confirm_mod

    seen: dict = {}
    real = confirm_mod.confirm

    def _spy(project, **kw):
        seen.update(kw)
        return real(project, **kw)

    monkeypatch.setattr(confirm_mod, "confirm", _spy)
    token = _stage()
    pc.confirm_by_click(_project(), token=token, approved=True, user=ADMIN)

    assert seen, "the click reached no confirmation executor at all"
    assert seen.get("user") == ADMIN, "the click lost the identity of who clicked"
    assert seen.get("key") == KEY, seen
    assert seen.get("fingerprint"), "the click's verified fingerprint did not travel to the pop"


def test_the_typed_yes_runs_that_same_executor(monkeypatch):
    """The other half of "one implementation", and the arm that fails if the typed path grows its
    own copy: `_handle`'s confirmation section must be a call to the SAME function the click uses,
    not a chain of `if` that happens to agree with it today.

    PATCHED ON THE CHANNEL'S ALIAS, because that is the name `_handle` resolves — the house
    convention that lets a test drive `pc.find_waiting`. The identity assertion is what stops the
    alias from quietly becoming a different function: without it, this file could prove both paths
    call "something named confirm" and never that they call the same one.
    """
    from openfactory.product import confirm as confirm_mod

    assert pc.confirm_staged is confirm_mod.confirm, (
        "the channel's alias no longer IS the core executor — the two surfaces have drifted apart")

    seen: dict = {}
    real = pc.confirm_staged

    def _spy(project, **kw):
        seen.update(kw)
        return real(project, **kw)

    monkeypatch.setattr(pc, "confirm_staged", _spy)
    _stage()
    pc.handle(_project(), text="sim", user=ADMIN, thread=KEY, channel=KEY, module=_Module())

    assert seen.get("user") == ADMIN, seen
    assert seen.get("key") == KEY, seen


def test_the_click_actually_writes():
    """End to end through the real path: a staged proposal plus an approving click, and the write
    ran. `module` is injected the way `handle` already allows — without that seam this chain could
    not be proved at all, which is how a click path ships looking correct."""
    mod = _Module()
    token = _stage()

    out = pc.confirm_by_click(_project(), token=token, approved=True, user=ADMIN, module=mod)

    assert mod.wrote == ["erp"], out
    assert pc.pending_for(KEY) is None, "the proposal was written and left staged"


# ── 5. reach ───────────────────────────────────────────────────────────────────────────────────
def test_the_listener_routes_interactive_envelopes():
    """The listener dropped everything that was not `events_api`, so a button could be posted and
    its click would vanish in silence — buttons working in this file while the envelope is discarded
    is this repository's signature defect."""
    import ast

    src = add_ons.source("openfactory/runtime/slack/bot.py").read_text()
    assert '"interactive"' in src, "the listener never looks at interactive envelopes"
    tree = ast.parse(src)
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "_handle_interactive" in names
    assert "confirm_by_click" in src, "the interactive handler routes to nothing"


@pytest.mark.parametrize("site", ["defect_confirmation", "confirmation_request", "queue_proposal",
                                  "fact_confirmation"])
def test_every_staging_site_offers_the_buttons(site):
    """All four, because three of four getting the affordance is how nobody notices the fourth."""
    import re
    from pathlib import Path

    src = Path("openfactory/product/channel.py").read_text()
    where = src.index(site)
    window = src[where:where + 1400]
    assert re.search(r"offer_with_buttons", window), f"{site} never offers an interactive confirm"


def test_the_bot_supplies_the_confirm_seam():
    import ast

    tree = ast.parse(add_ons.source("openfactory/runtime/slack/bot.py").read_text())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "handle"
             and any(k.arg == "confirm" for k in n.keywords)]
    assert calls, "handle() is called without a confirm seam — the buttons never appear"


# ── 6. the dependency this code cannot check ───────────────────────────────────────────────────
def test_the_button_message_ALSO_advertises_the_typed_path():
    """A click only arrives when the Slack app has Interactivity enabled — something this code
    cannot verify. With it off, the button post still SUCCEEDS, so the prose fallback is not sent and
    the proposal waits for a click that can never come. One line removes the dependency; a runbook
    step somebody must remember does not."""
    _stage()
    sent: dict = {}

    def _confirm(text, token, approve, reject):
        sent["text"] = text
        return True

    assert isinstance(pc.offer_with_buttons(_project(), KEY, "confirma?", _confirm), pc.Posted)
    assert "responda confirmando" in sent["text"], sent["text"]
    assert "confirma?" in sent["text"], "the proposal itself was lost"


def test_a_typed_confirmation_still_works_after_buttons_were_offered():
    """The two paths are not exclusive. Whatever the provider supports, "sim" must still land."""
    mod = _Module()
    _stage()
    pc.offer_with_buttons(_project(), KEY, "confirma?", lambda *a: True)

    pc.handle(_project(), text="sim", user=ADMIN, thread=KEY, channel=KEY, module=mod)

    assert mod.wrote == ["erp"], "buttons broke the typed path"


def test_a_posted_proposal_does_NOT_also_get_a_conversational_reply():
    """The bug this sentinel exists for, driven end to end. A queue/fact proposal that posted with
    buttons must not ALSO reach the model — the client would see the buttons plus an unrelated
    answer, and we would pay for it."""
    calls: list = []

    class _Mod(_Module):
        def answer(self, question, *, context="", conversation="", **_):
            calls.append(question)
            from types import SimpleNamespace
            return SimpleNamespace(ok=True, text="uma resposta avulsa", is_defect=False,
                                   is_request=False, decisions=[])

    pc.forget(KEY)
    out = pc.handle(_project(), text="anota que a firma usa Primavera", user=ADMIN, thread=KEY,
                    channel=KEY, module=_Mod(), confirm=lambda *a: True)

    assert not calls, f"the model was consulted after the proposal was already posted: {calls}"
    assert out is None, f"the boundary returned text that is already on the channel: {out!r}"


def test_what_was_posted_interactively_is_STILL_in_her_memory(monkeypatch):
    """A proposal that reached the channel as blocks must be recorded like any other turn, or she
    forgets having proposed it — which is how "did you register it?" became unanswerable."""
    import openfactory.runtime.temporal.activities as activities_mod

    class _Sink:
        def __init__(self):
            self.rows: list = []

        def record(self, rec):
            self.rows.append(rec)

    sink = _Sink()
    monkeypatch.setattr(activities_mod, "_metrics_sink", lambda *a, **k: sink)
    pc.forget(KEY)
    pc.handle(_project(), text="anota que a firma usa Primavera", user=ADMIN, thread=KEY,
              channel=KEY, module=_Module(), confirm=lambda *a: True)

    hers = [r.extra.get("text", "") for r in sink.rows
            if r.kind == "message" and r.role == "agent"]
    assert hers and any("Primavera" in t for t in hers), f"her proposal is not in the record: {hers}"


# ── 7. refusing is an act too ──────────────────────────────────────────────────────────────────
def test_a_THIRD_PARTY_typed_refusal_cannot_destroy_a_proposal():
    """The typed refusal popped the proposal with no check at all, so anybody in the channel could
    throw away work an admin was about to approve by saying "não"."""
    pc.forget(KEY)
    pc.remember(KEY, {"kind": "fact", "term": "erp", "body": "usa Primavera",
                      "said_by": f"<@{ADMIN}>"})

    reply = pc.handle(_project(), text="não", user=OUTSIDER, thread=KEY, channel=KEY,
                      module=_Module())

    assert pc.pending_for(KEY) is not None, "an outsider destroyed a pending proposal by typing"
    assert reply, "the refusal was swallowed in silence"


def test_the_REQUESTER_may_refuse_their_own_proposal_even_without_admin():
    """The case a blanket may_act check gets WRONG. "não, não é isso" from the person whose request
    it is, correcting their own wording, is the entire point of showing a draft back — not vandalism.
    Two different people saying the same word are not the same case."""
    pc.forget(KEY)
    pc.remember(KEY, {"kind": "fact", "term": "erp", "body": "usa Primavera",
                      "said_by": f"<@{OUTSIDER}>"})

    pc.handle(_project(), text="não, não é isso", user=OUTSIDER, thread=KEY, channel=KEY,
              module=_Module())

    assert pc.pending_for(KEY) is None, "the requester could not correct their own request"


def test_an_ADMIN_typed_refusal_still_drops_it():
    _stage()

    pc.handle(_project(), text="não", user=ADMIN, thread=KEY, channel=KEY, module=_Module())

    assert pc.pending_for(KEY) is None, "an admin's refusal left the proposal staged"


# ── 8. an eviction can never be silent again ───────────────────────────────────────────────────
def test_a_NEW_proposal_admits_what_it_displaced():
    """`_PENDING` holds one entry per conversation, last wins — that is the design. Announcing it was
    NOT: only the fact and defect sites did, so a requirement draft or a queue proposal threw away a
    pending defect in silence. The client had been told "vou registrar como problema", nobody took it
    back, and the next "sim" recorded something else."""
    pc.forget(KEY)
    pc.remember(KEY, {"kind": "defect", "restated": "a conciliação duplica"})

    notice = pc.remember(KEY, {"kind": "queue", "numbers": [1, 2]}, lang="pt-BR")

    assert notice and "Deixei de lado" in notice, notice


def test_replacing_a_proposal_with_the_SAME_KIND_says_nothing():
    """Restating a fact is a correction, not a displacement — a notice there is noise."""
    pc.forget(KEY)
    pc.remember(KEY, {"kind": "fact", "term": "erp", "body": "usa Primavera"})

    assert pc.remember(KEY, {"kind": "fact", "term": "erp", "body": "usa SAP"}, lang="pt-BR") == ""


def test_no_caller_may_DISCARD_the_eviction_notice():
    """The structural half. Two of four callers used to forget the notice; a returned value nobody
    is forced to use would let a fifth forget it again. Every `remember()` call must consume the
    result — a bare expression statement fails this."""
    import ast
    from pathlib import Path

    src = Path("openfactory/product/channel.py").read_text()
    tree = ast.parse(src)
    dropped = []
    for node in ast.walk(tree):
        # a call whose value is thrown away appears as a bare Expr statement
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) \
                and getattr(node.value.func, "id", None) == "remember":
            dropped.append(node.lineno)
    assert not dropped, (
        f"remember() called and its eviction notice discarded at line(s) {dropped} — "
        "the client would not be told what was thrown away")


def test_the_cap_no_longer_evicts_on_a_REPLACEMENT():
    """A subtlety found while moving the notice: the cap used to pop the oldest entry even when the
    key was already present, so re-staging in a busy channel could evict an unrelated conversation's
    proposal for nothing.

    The staging dict is module-level, so this test FILLS IT and must put it back — it leaked 200
    entries into every test that ran after it and broke an unrelated one by ordering.
    """
    saved = dict(pc._PENDING)
    try:
        pc._PENDING.clear()
        for i in range(pc._MAX_PENDING):
            pc.remember(f"T{i}", {"kind": "fact", "term": str(i)})
        before = len(pc._PENDING)

        pc.remember("T0", {"kind": "fact", "term": "again"})

        assert len(pc._PENDING) == before, "replacing an existing key evicted somebody else"
    finally:
        pc._PENDING.clear()
        pc._PENDING.update(saved)


def test_an_arriving_click_leaves_a_trace_in_the_log():
    """Interactivity is a Slack app SETTING this code cannot read, so "did the button work?" was
    only answerable by watching somebody try it. The marker makes it checkable from the logs, and
    its ABSENCE after a click is the specific evidence that the setting is still off."""

    src = add_ons.source("openfactory/runtime/slack/bot.py").read_text()
    assert "OPENFACTORY_CLICK_RECEIVED" in src
    where = src.index("OPENFACTORY_CLICK_RECEIVED")
    assert where < src.index("confirm_by_click", where), \
        "the trace is logged after the work, so a crash mid-handler would hide the arrival"


# ── 9. a Posted must never be interpolated ─────────────────────────────────────────────────────
def test_a_posted_proposal_is_returned_WHOLE_not_interpolated():
    """WHAT SHIPPED: `offer_draft` posted the proposal with buttons and returned `Posted(text)`, and
    the caller wrote `f"{answer.text}\\n\\n{offered}"`. An f-string produces a plain `str`, the
    boundary could no longer tell it had been posted, and the WHOLE proposal went out a second time
    — the product owner saw the confirmation block twice, with her reasoning stranded between the
    two.

    A sentinel that survives only until somebody interpolates it is not a sentinel, so this asserts
    over the source: no `Posted`-carrying value may be embedded in a formatted string.
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path("openfactory/product/channel.py").read_text())
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):        # an f-string
            continue
        for part in ast.walk(node):
            if isinstance(part, ast.Name) and part.id in ("offered", "posted"):
                offenders.append((node.lineno, ast.unparse(node)[:70]))
    assert not offenders, (
        "a value that may be `Posted` is interpolated into an f-string, which silently turns it "
        f"back into a plain str: {offenders}")


def test_the_reasoning_travels_WITH_the_proposal():
    """It was returned separately and therefore posted separately — AFTER the block it justifies, so
    the person read "confirm this?" before the argument for it. The preamble goes into the same
    message."""
    import inspect

    src = inspect.getsource(pc.offer_draft)
    assert "preamble" in src, "offer_draft cannot carry her reasoning into the posted message"
    assert "preamble + replaced" in src, "the preamble is accepted and never used"


# ── the router hears BOTH generations of button (#106 item 12) ──────────────────────────────────

def _click_payload(action_id: str) -> dict:
    return {"type": "block_actions",
            "user": {"id": "U1"},
            "channel": {"id": "C1"},
            "container": {"thread_ts": "t1", "message_ts": "t1"},
            "actions": [{"action_id": action_id, "value": "tok-1"}]}


def test_new_buttons_route_and_strangers_do_not(monkeypatch):
    from openfactory.product import channel as product_channel
    bot = add_ons.module("openfactory.runtime.slack.bot")

    seen = {}
    monkeypatch.setattr(product_channel, "confirm_by_click",
                        lambda project, *, token, approved, user, notify=None: (
                            seen.update(approved=approved) or "ok"))
    monkeypatch.setattr(bot, "_client_for_channel", lambda project: None)

    bot._handle_interactive(object(), _click_payload(bot.APPROVE_ACTION))
    assert seen == {"approved": True}

    seen.clear()
    bot._handle_interactive(object(), _click_payload("somebody_elses_button"))
    assert seen == {}, "a foreign action id must never reach the confirmation executor"


def test_posted_buttons_carry_only_the_new_ids():
    """The other half: recognise, never mint."""
    bot = add_ons.module("openfactory.runtime.slack.bot")

    assert bot.APPROVE_ACTION.startswith("openfactory_")
    assert bot.REJECT_ACTION.startswith("openfactory_")
