"""A decision the platform asked for outlives the tab it was asked in (#123).

Pilot, 2026-08-16: *"ao dar F5 este diálogo some."*

The thread was already fixed — both halves of the conversation land in the panel's own message
store, one clock, one feed. What was still lost on a refresh was the expensive half: the tech-lead
ends an answer proposing ONE concrete action, the panel renders it as a button, and the operator
approves it by pressing that button. The proposal lived in `_chatLocal`, a JavaScript array in
whichever tab produced it. A refresh at that moment discarded a decision the platform had just
asked a human to make.

THAT IS A WAIT ENDING IN NOTHING, which is the one shape this platform is not allowed to have —
and it was invisible, because the operator sees a conversation that simply looks shorter.

WHAT MAKES IT DURABLE without anything new to run: the proposal rides on the row the answer
already writes, as a `token` and a `payload` the store has carried since C-33. Whether it may
still be pressed is a FOLD over the same append-only rows — superseded, answered, expired —
computed server-side, because a second copy of those rules in the browser could only disagree with
the first.

AND A RETIRED SUGGESTION IS SHOWN, NOT REMOVED. A button that silently stops working teaches the
same wrong lesson as one that vanishes: the person concludes the platform forgot, when in fact it
decided. This is why `staged` returns a REASON rather than None.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from openfactory.actions.base import PARAMS
from openfactory.memory import messages as ch

PROJECT = "podbeam"


class Store:
    """A message store in memory, in the shape `read(scan=…)` takes."""

    def __init__(self):
        self.rows: list[dict] = []

    def record(self, rec) -> bool:
        self.rows.append({"kind": rec.kind, "pk": rec.project, "ts": rec.ts,
                          "extra": dict(rec.extra)})
        return True

    def scan(self):
        return list(self.rows)


@pytest.fixture
def store():
    return Store()


def _say_with_suggestion(store, text, verb, ref, *, at=None):
    stamp = at or datetime.now(UTC).isoformat()
    token = ch.suggestion_token(verb, ref, now=stamp)
    assert ch.say(PROJECT, text, channel=PROJECT, token=token,
                  payload=json.dumps({"suggestion": [verb, ref]}), sink=store, now=stamp)
    return token


# ── 1. it survives ──────────────────────────────────────────────────────────────────────────────

def test_a_staged_suggestion_is_still_there_after_the_tab_is_gone():
    """The whole card. Nothing here is a browser: the proposal is written, and read back by
    something that never saw the tab that produced it."""
    store = Store()
    token = _say_with_suggestion(store, "I'd resume #87 — the blocker is gone.", "resume", "87")

    found = ch.staged(PROJECT, scan=store.scan)
    assert found is not None, "the decision vanished with the tab — this is the defect"
    message, reason = found
    assert reason == "", f"a fresh suggestion is already retired ({reason})"
    assert message.token == token
    assert ch.read_suggestion(message) == ("resume", "87", {})


def test_the_answer_text_travels_with_it():
    """The button without the reasoning is an instruction from nowhere. A person coming back to
    this on another screen has to be able to read WHY before pressing it."""
    store = Store()
    _say_with_suggestion(store, "the gates passed and the review did not reject it.", "merge", "9")
    message, _ = ch.staged(PROJECT, scan=store.scan)
    assert "the gates passed" in message.text


def test_a_thread_with_no_proposal_stages_nothing():
    store = Store()
    ch.say(PROJECT, "picked up #91", channel=PROJECT, sink=store)
    ch.told(PROJECT, "obrigado", by="u1", channel=PROJECT, sink=store)
    assert ch.staged(PROJECT, scan=store.scan) is None


# ── 2. it retires, and says why ─────────────────────────────────────────────────────────────────

def test_a_NEWER_proposal_supersedes_the_old_one():
    """Two live buttons in one thread is a person choosing between two pieces of advice, one of
    which was written before the other and is therefore about a floor that has since moved."""
    store = Store()
    old = _say_with_suggestion(store, "resume it", "resume", "87",
                               at="2026-08-16T09:00:00+00:00")
    new = _say_with_suggestion(store, "actually, skip it", "skip", "87",
                               at="2026-08-16T09:05:00+00:00")
    message, reason = ch.staged(PROJECT, scan=store.scan, now="2026-08-16T09:06:00+00:00")
    assert message.token == new and message.token != old
    assert reason == "", "the newest proposal is not the live one"
    assert ch.read_suggestion(message) == ("skip", "87", {})


def test_one_that_was_already_PRESSED_retires_with_that_reason():
    """A second click on a stale page must not read as a second decision — the rule this file's
    sibling route states for the product gate."""
    store = Store()
    token = _say_with_suggestion(store, "resume it", "resume", "87")
    ch.answer(PROJECT, token=token, answer="approve", by="operator-1", sink=store)

    message, reason = ch.staged(PROJECT, scan=store.scan)
    assert reason == "answered"
    assert message.token == token, "the proposal itself is gone — the reader cannot say what was "\
                                   "already done"


def test_one_that_AGED_OUT_retires_with_that_reason():
    """Advice about a floor, and floors move. Slack has always bounded this; the panel — the
    REFERENCE surface — had no bound at all, because its suggestion died with the tab."""
    store = Store()
    old = (datetime.now(UTC) - timedelta(hours=ch.SUGGESTION_TTL_HOURS + 1)).isoformat()
    _say_with_suggestion(store, "resume it", "resume", "87", at=old)
    _message, reason = ch.staged(PROJECT, scan=store.scan)
    assert reason == "expired"


def test_one_INSIDE_the_window_is_still_live():
    """The positive twin. A TTL that retires everything is a feature nobody can use."""
    store = Store()
    recent = (datetime.now(UTC) - timedelta(hours=ch.SUGGESTION_TTL_HOURS - 1)).isoformat()
    _say_with_suggestion(store, "resume it", "resume", "87", at=recent)
    assert ch.staged(PROJECT, scan=store.scan)[1] == ""


def test_a_timestamp_NOBODY_can_parse_retires_rather_than_lives_for_ever():
    """The safe direction: a suggestion that can never age is worse than one that ages early."""
    store = Store()
    _say_with_suggestion(store, "resume it", "resume", "87", at="not-a-time")
    assert ch.staged(PROJECT, scan=store.scan)[1] == "expired"


def test_an_unreadable_payload_costs_its_own_row_and_not_the_thread():
    store = Store()
    ch.say(PROJECT, "half a proposal", channel=PROJECT,
           token=ch.suggestion_token("resume", "87"), payload="{not json", sink=store)
    assert ch.staged(PROJECT, scan=store.scan) is None
    assert len(ch.read(PROJECT, scan=store.scan)) == 1, "the message itself was lost too"


def test_a_plain_narration_is_never_mistaken_for_a_proposal():
    """`say` carries a token and a payload only for something a person may ACT on. Everything the
    factory narrates goes through the same function."""
    store = Store()
    ch.say(PROJECT, "merged #124", channel=PROJECT, sink=store)
    assert ch.staged(PROJECT, scan=store.scan) is None


# ── 2b. the writer, which is where the whole feature can be disconnected ────────────────────────
#
# Everything above proves the FOLD. A mutation that stopped `_remember` attaching the proposal to
# the row left all of it green — the store was correct about a row nobody wrote. That is this
# codebase's most expensive shape and it does not stop being it because the dead half is one
# function further up.

def test_the_answer_that_PROPOSES_something_writes_it_down(monkeypatch):
    from openfactory.actions import catalog

    store = Store()
    monkeypatch.setattr("openfactory.runtime.temporal.activities._metrics_sink", lambda: store)
    catalog._remember(PROJECT, "I'd resume #87.", factory=True, suggestion=("resume", "87"))

    found = ch.staged(PROJECT, scan=store.scan)
    assert found is not None, (
        "the tech-lead proposed something and the row carries no proposal — the store is correct "
        "about a suggestion nobody ever wrote")
    assert ch.read_suggestion(found[0]) == ("resume", "87", {})


def test_an_answer_that_proposes_NOTHING_writes_a_plain_row(monkeypatch):
    from openfactory.actions import catalog

    store = Store()
    monkeypatch.setattr("openfactory.runtime.temporal.activities._metrics_sink", lambda: store)
    catalog._remember(PROJECT, "everything looks fine.", factory=True)
    assert ch.staged(PROJECT, scan=store.scan) is None


def test_the_ASK_row_hands_the_suggestion_to_the_writer():
    """The one seam the two tests above cannot see: `_ask` parses the suggestion out of the
    worker's reply and must pass it on."""
    import ast
    import inspect

    from openfactory.actions import catalog

    tree = ast.parse(inspect.cleandoc("\n" + inspect.getsource(catalog._ask)))
    factory_calls = [n for n in ast.walk(tree)
                     if isinstance(n, ast.Call)
                     and getattr(n.func, "id", "") == "_remember"
                     and any(k.arg == "factory" for k in n.keywords)]
    assert factory_calls, "nothing records the tech-lead's own turn any more"
    assert any(k.arg == "suggestion" for call in factory_calls for k in call.keywords), (
        "the answer is written down without what it proposed — the button never comes back")


# ── 3. the route that approves it ───────────────────────────────────────────────────────────────

def test_the_thread_endpoint_serves_the_suggestion_and_whether_it_is_LIVE(monkeypatch):
    """Decided server-side. The browser must not re-derive superseded/answered/expired; the rules
    are a fold over rows it does not have."""
    import inspect

    from openfactory.api import app as api

    src = inspect.getsource(api._staged_suggestion)
    assert "channel.staged" in src and '"live"' in src and '"reason"' in src


def test_approving_goes_through_the_ACTION_LAYER_with_the_presser_credential():
    """Not the credential that composed the suggestion. Somebody who cannot resume a job must not
    be able to approve a proposal to resume it — even one addressed to a colleague."""
    import inspect

    from openfactory.api import app as api

    src = inspect.getsource(api.approve_suggestion)
    assert "actions.perform" in src, "the approval executes outside the layer that gates it"
    assert "_actor(request)" in src, (
        "the action runs as somebody other than the person who pressed the button")


def test_approving_records_the_decision_whatever_the_outcome():
    """It retires the button either way. A refusal is an answer, and a proposal a person has
    already pressed and been refused must not sit there inviting the same click."""
    import ast
    import inspect

    from openfactory.actions import catalog

    # THE SEQUENCE MOVED (#156) and the claim did not: it lives in `run_staged` now, which the
    # route and the chat's plain "yes" both call. Asserting it on the route would have passed for
    # the wrong reason the day the route became a mapping.
    tree = ast.parse(inspect.cleandoc("\n" + inspect.getsource(catalog.run_staged)))
    # The recording must not sit under an `if outcome.ok` — that is the branch that leaves a
    # refused proposal live for ever.
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "outcome.ok" in ast.unparse(node.test):
            assert "channel.answer" not in ast.unparse(node), (
                "the decision is only recorded when the action worked — a refused suggestion "
                "stays pressable for ever")
    assert "channel.answer" in ast.unparse(tree)


def test_a_stale_token_is_REFUSED_rather_than_applied_to_the_replacement():
    import inspect

    from openfactory.actions import catalog

    src = inspect.getsource(catalog.run_staged)
    assert "found[0].token != token" in src, (
        "an approval of an older proposal is applied to whatever is staged now — the difference "
        "between approving a decision and approving its replacement")


# ── 3b. …and it is genuinely REACHABLE, not just correct ────────────────────────────────────────
#
# Everything above this line reads code. This platform's most expensive recurring defect is a
# feature that is built, tested and reached by nothing — sixteen of them and counting — so the
# route is driven end to end here, through the real app, with a real credential.

@pytest.fixture
def live(tmp_path, monkeypatch):
    """The app, with one in-memory store behind BOTH the write and the read paths."""
    from starlette.testclient import TestClient

    from openfactory.api.app import app

    class Sink:
        rows: list = []

        def record(self, rec) -> bool:
            Sink.rows.append({"kind": rec.kind, "pk": rec.project, "ts": rec.ts,
                              "extra": dict(rec.extra)})
            return True

    Sink.rows = []
    monkeypatch.setattr("openfactory.runtime.temporal.activities._metrics_sink", lambda: Sink())
    monkeypatch.setattr(
        "openfactory.observability.query.records_of_kind",
        lambda project, kind, limit=500, **kw: sorted(
            [r for r in Sink.rows if r["kind"] == kind and r["pk"] == project],
            key=lambda r: str(r["ts"]))[-limit:])
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", "mine:alice:Alice Ferreira")
    monkeypatch.delenv("OPENFACTORY_IDENTITY", raising=False)
    return TestClient(app)


AUTH = {"Authorization": "Bearer mine"}


def test_the_thread_endpoint_really_serves_a_staged_suggestion(live):
    token = ch.suggestion_token("resume", "87")
    ch.say(PROJECT, "I'd resume #87.", channel=PROJECT, token=token,
           payload=json.dumps({"suggestion": ["resume", "87"]}))

    body = live.get(f"/api/messages/{PROJECT}", headers=AUTH).json()

    assert body["suggestion"] == {
        "token": token, "ts": body["suggestion"]["ts"],
        "action": "resume", "issue": "87", "params": {}, "live": True, "reason": "",
        # WHAT EACH PARAMETER IS, from the catalogue row (#172) — served so a front end never
        # invents a label from the key. `resume` stages with none, and the labels are still sent:
        # they describe the ACTION, not this proposal's values.
        "labels": {"project": PARAMS["project"], "issue": PARAMS["issue"],
                   "choice": PARAMS["choice"]},
        "act": {"method": "POST", "url": f"/api/messages/{PROJECT}/suggestion",
                "body": {"token": token}},
    }
    assert [m["token"] for m in body["messages"]] == [token], (
        "the panel cannot match the suggestion to the message it was made in")


def test_a_proposal_with_an_INSTRUCTION_serves_it_to_the_button(live):
    """Approving `adjust #87` without seeing the instruction is approving a blank cheque, and the
    instruction is composed inside a loop that has read the client's own ticket comments (#170).
    The panel cannot render what the endpoint does not send."""
    token = ch.suggestion_token("adjust", "87")
    ch.say(PROJECT, "I'd send #87 back for one pass.", channel=PROJECT, token=token,
           payload=json.dumps({"suggestion": ["adjust", "87"],
                               "params": {"instruction": "tie finish_reason to the episode"}}))

    served = live.get(f"/api/messages/{PROJECT}", headers=AUTH).json()["suggestion"]

    assert served["action"] == "adjust"
    assert served["params"] == {"instruction": "tie finish_reason to the episode"}


def test_a_payload_carrying_something_other_than_STRINGS_is_dropped(live):
    """Whatever comes back is spread into `perform(**params)`. A nested structure arriving from a
    store is a shape nobody wrote a reader for, and this is the one place it could enter."""
    token = ch.suggestion_token("adjust", "87")
    ch.say(PROJECT, "proposal", channel=PROJECT, token=token,
           payload=json.dumps({"suggestion": ["adjust", "87"],
                               "params": {"instruction": {"nested": "object"}, "ok": "text"}}))

    served = live.get(f"/api/messages/{PROJECT}", headers=AUTH).json()["suggestion"]

    assert served["params"] == {"ok": "text"}, served["params"]


def test_pressing_it_runs_the_action_and_retires_the_button(live, monkeypatch):
    """The whole gesture, driven the way a browser drives it."""
    ran: dict = {}

    async def perform(name, *, by, **params):
        from openfactory.actions.base import done

        ran.update({"name": name, "by": by, **params})
        return done(f"#{params['issue']} resumed")

    monkeypatch.setattr("openfactory.actions.perform", perform)
    token = ch.suggestion_token("resume", "87")
    ch.say(PROJECT, "I'd resume #87.", channel=PROJECT, token=token,
           payload=json.dumps({"suggestion": ["resume", "87"]}))

    r = live.post(f"/api/messages/{PROJECT}/suggestion", json={"token": token}, headers=AUTH)

    assert r.status_code == 200, r.text
    assert ran["name"] == "resume" and ran["issue"] == "87" and ran["project"] == PROJECT
    assert ran["by"].id == "alice", "the action ran as somebody other than whoever pressed it"

    after = live.get(f"/api/messages/{PROJECT}", headers=AUTH).json()
    assert after["suggestion"]["live"] is False and after["suggestion"]["reason"] == "answered"
    assert "#87 resumed" in [m["text"] for m in after["messages"]], (
        "what happened is not in the thread — a refresh loses the outcome too")


def test_pressing_a_REFUSED_one_still_retires_it(live, monkeypatch):
    async def perform(name, *, by, **params):
        from openfactory.actions.base import CONFLICT, refused

        return refused(CONFLICT, "that job is not parked")

    monkeypatch.setattr("openfactory.actions.perform", perform)
    token = ch.suggestion_token("resume", "87")
    ch.say(PROJECT, "I'd resume #87.", channel=PROJECT, token=token,
           payload=json.dumps({"suggestion": ["resume", "87"]}))

    r = live.post(f"/api/messages/{PROJECT}/suggestion", json={"token": token}, headers=AUTH)

    assert r.status_code == 409
    body = live.get(f"/api/messages/{PROJECT}", headers=AUTH).json()
    assert body["suggestion"]["reason"] == "answered", (
        "a proposal a person pressed and was refused sits there inviting the same click")
    assert "that job is not parked" in [m["text"] for m in body["messages"]]


def test_pressing_a_SUPERSEDED_one_does_nothing(live, monkeypatch):
    called: list = []

    async def perform(name, *, by, **params):
        from openfactory.actions.base import done

        called.append(name)
        return done("ok")

    monkeypatch.setattr("openfactory.actions.perform", perform)
    old = ch.suggestion_token("resume", "87", now="2026-08-16T09:00:00+00:00")
    ch.say(PROJECT, "resume it", channel=PROJECT, token=old,
           payload=json.dumps({"suggestion": ["resume", "87"]}), now="2026-08-16T09:00:00+00:00")
    ch.say(PROJECT, "actually, skip it", channel=PROJECT,
           token=ch.suggestion_token("skip", "87", now="2026-08-16T09:05:00+00:00"),
           payload=json.dumps({"suggestion": ["skip", "87"]}), now="2026-08-16T09:05:00+00:00")

    r = live.post(f"/api/messages/{PROJECT}/suggestion", json={"token": old}, headers=AUTH)

    assert r.status_code == 409
    assert called == [], "an approval of an older proposal ran against the newer one"


@pytest.mark.parametrize("retire", ["answered", "expired"])
def test_pressing_a_RETIRED_one_runs_nothing(live, monkeypatch, retire):
    """The token check catches a SUPERSEDED proposal, because a newer one exists to compare
    against. These two have no replacement — the same token is still the latest — so only the
    reason stops them, and a mutation that dropped that check survived every other test here."""
    called: list = []

    async def perform(name, *, by, **params):
        from openfactory.actions.base import done

        called.append(name)
        return done("ok")

    monkeypatch.setattr("openfactory.actions.perform", perform)
    when = (datetime.now(UTC) - timedelta(hours=ch.SUGGESTION_TTL_HOURS + 1)).isoformat() \
        if retire == "expired" else datetime.now(UTC).isoformat()
    token = ch.suggestion_token("resume", "87", now=when)
    ch.say(PROJECT, "I'd resume #87.", channel=PROJECT, token=token,
           payload=json.dumps({"suggestion": ["resume", "87"]}), now=when)
    if retire == "answered":
        ch.answer(PROJECT, token=token, answer="approve", by="someone")

    r = live.post(f"/api/messages/{PROJECT}/suggestion", json={"token": token}, headers=AUTH)

    assert r.status_code == 409, r.text
    assert called == [], f"a {retire} suggestion was executed anyway"


def test_the_route_is_behind_the_same_credential_as_every_other_door(live):
    assert live.post(f"/api/messages/{PROJECT}/suggestion",
                     json={"token": "tl:resume:87:x"}).status_code in (401, 403)


# ── 4. the browser holds no second copy of any of it ────────────────────────────────────────────

def _panel() -> str:
    import inspect
    from pathlib import Path

    from openfactory.api import app as api

    return (Path(inspect.getfile(api)).parent / "panel.html").read_text()


def test_the_panel_reads_the_suggestion_from_the_SERVER():
    code = "\n".join(ln for ln in _panel().splitlines() if not ln.lstrip().startswith("//"))
    assert "d.suggestion" in code, "the panel is back to remembering the proposal itself"
    assert "sugg:(d.data" not in code, (
        "the answer's suggestion is stashed in the tab again — one refresh and it is gone")


def test_the_panel_does_not_re_decide_whether_a_SUGGESTION_is_still_valid():
    """superseded / answered / expired are folds over rows the browser does not have. A copy of
    those rules here would be a second answer to a question with one.

    ASSERTED AS "IT DOES NOT BRANCH ON THE REASON", not as "the word does not appear" — the first
    cut banned the words and fired on `m.kind=="answered"`, which is the message KIND the thread
    filters on and has nothing to do with a suggestion retiring. A false alarm on correct code is
    how a guard gets deleted. Looking it up to render a sentence (`_RETIRED[...]`) is fine; the
    line this draws is between rendering a decision and making one."""
    code = "\n".join(ln for ln in _panel().splitlines() if not ln.lstrip().startswith("//"))
    assert "_staged.live" in code, "the server's answer about validity is fetched and ignored"
    for deciding in ("_staged.reason==", "_staged.reason ==", "_staged.reason===",
                     "_staged.reason!=", "SUGGESTION_TTL"):
        assert deciding not in code, (
            f"the panel decides for itself whether a suggestion is still valid ({deciding}) — the "
            f"rules are a fold over rows the browser does not have")


def test_a_RETIRED_suggestion_is_shown_with_its_reason_rather_than_removed():
    """ASSERTED ON THE BRANCH THAT RENDERS IT, not on the table it reads. The first cut checked
    that `_RETIRED` and "expirou" appeared anywhere in the file — so gutting the rendering to `""`
    left the lookup table sitting there unused and the guard green.

    AND ON THE COMMENT-STRIPPED PAGE, like its siblings — the 2026-08-17 guard audit caught this
    one reading the RAW file while the two tests beside it strip `//` comments, so a JS comment
    mentioning the word would have kept it green after the same gutting, again.

    AND ON THE PROPERTY, NOT ON A WORD (#136). This asserted the literal string "expirou", using a
    Portuguese word as the proxy for "this is a sentence, not a machine key". Translating the panel
    to English broke it, correctly — but a guard that a translation can break was never testing the
    thing it named. What must be true is that each machine key maps to an EXPLANATION: something
    longer than the key, that is not the key. That survives any language."""
    import re

    # COMMENTS STRIPPED WHEREVER THEY START, not only at the beginning of a line. Dropping only
    # line-leading `//` leaves `""//_RETIRED[_staged.reason]` — the rendering commented out
    # mid-line — reading exactly like live code to a substring check, which is how the mutation
    # for this very guard survived. `:` guards the one false positive that matters: `https://`.
    code = "\n".join(re.sub(r"(?<!:)//.*$", "", ln) for ln in _panel().splitlines())
    assert "_RETIRED[_staged.reason]" in code, (
        "a suggestion that stops working now disappears — which is the defect this card is "
        "about, one step later in the story")
    table = re.search(r"const _RETIRED=\{(.+?)\};", code, re.S)
    assert table, "the reasons table is gone — the rendering above reads nothing"
    entries = re.findall(r'(\w+)\s*:\s*"([^"]+)"', table.group(1))
    assert len(entries) >= 2, f"only {len(entries)} reason(s) explained: {entries}"
    for key, sentence in entries:
        assert sentence.strip() != key, f"{key!r} is rendered as the bare machine word"
        assert len(sentence.split()) >= 3, (
            f"{key!r} maps to {sentence!r} — a label, not an explanation a human can act on")


# ── 5. nothing new to run, and the retention is written down ────────────────────────────────────

def test_it_needs_no_database_no_account_and_no_cloud():
    """§12's promise. The thread uses the store every other message already uses; a second one
    would be a thing to provision, secure and forget — and forgetting it means a silent factory."""
    import inspect

    src = inspect.getsource(ch)
    assert "MESSAGE_KIND" in src
    for infra in ("boto3", "psycopg", "redis", "requests.post"):
        assert infra not in src, f"the conversation now depends on {infra}"


def test_the_retention_is_stated_where_the_other_retentions_are():
    from pathlib import Path

    doc = Path(__file__).resolve().parents[1] / "docs" / "rotation-and-retention.md"
    lines = doc.read_text().splitlines()

    # THE CONSTANT AND ITS VALUE ON ONE LINE. Checked separately, the guard passed while the
    # actual number had been replaced by "a while" — `SUGGESTION_TTL_HOURS` still appeared in the
    # "where it lives" list and `12` appeared somewhere else on the page. A retention a reader
    # cannot look up is not stated.
    for name, value in (("SUGGESTION_TTL_HOURS", ch.SUGGESTION_TTL_HOURS),
                        ("READ_LAST", ch.READ_LAST)):
        assert any(name in ln and str(value) in ln for ln in lines), (
            f"{name} is documented without its value ({value}) — a person reading this page "
            f"cannot find out how long it actually is")
    page = "\n".join(lines)
    for reason in ("superseded", "answered", "expired"):
        assert reason in page, f"a person cannot find out what {reason!r} means"
