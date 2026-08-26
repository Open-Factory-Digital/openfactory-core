"""The tech-lead's brain works with no Slack anywhere near it (C-24, #52).

WHY THIS FILE IS THE POINT OF THE CARD. Answering a question about a project — reading Temporal,
cross-referencing the forge and the board, cloning the repository, running the read-only chat
agent — was written inside `runtime/slack/bot.py` and never had a line of Slack in it. An
application living inside one provider is the layer model upside down, and this one *acts*:
resume and skip are reachable from that answer.

The practical consequence was not tidiness. A deployment that does not buy Slack had **no
tech-lead**, not a quieter one — and "never a silent hang" is a promise the platform makes to
every deployment.

So the tests below import `openfactory.techlead.conversation` and nothing else. If that ever stops being
possible, this file stops collecting, which is the loudest failure available.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from openfactory.techlead import conversation


class _Proj:
    name = "books"
    forge = None
    tracker = None
    language = "pt-BR"


class _Res:
    """What a harness hands back. `raw_output` is the stream; `summary` the fallback."""

    def __init__(self, summary: str = "", raw_output: str = "") -> None:
        self.summary = summary
        self.raw_output = raw_output


class _Harness:
    """A fake HARNESS — one read-only primitive serves chat/diagnose/advise/size alike."""

    def __init__(self, res: _Res) -> None:
        self._res = res

    def ask(self, **_kw):
        return self._res


@pytest.fixture
def offline(monkeypatch):
    """No Temporal, no clone, no network — the capability under a stubbed harness."""
    monkeypatch.setattr(conversation, "gather_jobs", lambda project: [])
    monkeypatch.setattr(conversation, "clone_repo",
                        lambda project: (pathlib.Path("/tmp/does-not-matter"), False))

    def _use(res: _Res):
        from openfactory.adapters.agent import registry as harnesses
        monkeypatch.setitem(harnesses.HARNESSES, "claude_code", lambda **kw: _Harness(res))

    return _use


# ── the capability, with no channel ──────────────────────────────────────────────────────────────

def test_a_deployment_with_no_slack_still_gets_an_answer(offline):
    """THE CARD'S OWN SENTENCE. Nothing in this test knows what a channel is."""
    offline(_Res(summary="o #69 está travado há dois dias."))

    answer = conversation.answer(_Proj(), "como está o quadro?")

    assert answer.text == "o #69 está travado há dois dias."
    assert answer.suggestion is None


def test_the_suggestion_comes_back_as_a_FIELD_not_hidden_in_the_prose(offline):
    """The tag is a wire format between this module and the model. A caller that caps or reformats
    the prose must not be able to lose the action, and must never post the marker."""
    offline(_Res(summary="o #69 não anda.\n[[SUGGEST resume #69]]"))

    answer = conversation.answer(_Proj(), "e o 69?")

    assert answer.suggestion == ("resume", "69")
    assert "[[" not in answer.text and "SUGGEST" not in answer.text


def test_the_cap_bounds_the_PROSE_and_cannot_amputate_the_action(offline):
    """THE REGRESSION THIS SHAPE EXISTS TO PREVENT. The guidance puts the tag on the LAST line and
    the cap used to run over the whole string: a long answer either cut the approvable action off
    the end — the prose still said "responda ok" and the ok found nothing staged — or sliced a tag
    in half and posted the remainder."""
    offline(_Res(summary="A" * 5000 + "\n[[SUGGEST resume #69]]"))

    answer = conversation.answer(_Proj(), "resumo?", cap=2500)

    assert answer.text.endswith("…(truncated)")
    assert len(answer.text) <= 2520
    assert answer.suggestion == ("resume", "69"), "the cap amputated the approvable action"


def test_no_cap_is_the_default_because_only_a_renderer_has_one(offline):
    """2500 characters is Slack's problem. The capability must not impose one channel's limit on
    a panel, a CLI, or an email that has a different one or none."""
    offline(_Res(summary="B" * 5000))

    assert len(conversation.answer(_Proj(), "?").text) == 5000


def test_agent_trouble_becomes_a_sentence_never_a_traceback(offline, monkeypatch):
    """A tech-lead that answers a question with a stack trace has not answered it."""
    def _boom(project):
        raise RuntimeError("the harness is not installed")

    monkeypatch.setattr("openfactory.adapters.agent.build_techlead", _boom)

    answer = conversation.answer(_Proj(), "e aí?")

    assert answer.text.startswith("Sorry")
    assert "the harness is not installed" in answer.text
    assert answer.suggestion is None


def test_an_empty_answer_is_said_rather_than_posted_as_nothing(offline):
    offline(_Res(summary="   "))

    assert conversation.answer(_Proj(), "?").text == "Sorry — I couldn't produce an answer for that one."


# ── the suggestion tag ───────────────────────────────────────────────────────────────────────────

def test_extract_suggestion_reads_the_action_and_strips_the_tag():
    text, sug = conversation.extract_suggestion("Olha o #69, tá travado.\n[[SUGGEST resume #69]]")
    assert text == "Olha o #69, tá travado."
    assert sug == ("resume", "69")
    assert conversation.extract_suggestion("skip it → [[SUGGEST skip #386]]")[1] == ("skip", "386")
    assert conversation.extract_suggestion("nada a fazer")[1] is None


def test_a_NON_NUMERIC_ref_can_be_suggested(caplog):
    """C-05 reached into this regex too. `#?(\\d+)` meant that on a tracker which does not number
    its tickets the tag never matched, the suggestion was swept as malformed, and the one feature
    that turns an answer into an act was missing — with nothing logged about a ticket."""
    with caplog.at_level("WARNING"):
        text, sug = conversation.extract_suggestion("trava.\n[[SUGGEST skip #CONT-412]]")

    assert sug == ("skip", "CONT-412")
    assert "[[" not in text
    assert "LOST_TAG" not in caplog.text, "a valid Jira suggestion was swept as malformed"


def test_a_malformed_tag_is_stripped_never_posted(caplog):
    """Parse narrowly, strip broadly. A tag off-grammar parses as no suggestion, but the raw
    plumbing must still not reach whoever asked — role.py's net exists because a marker escaped
    both parse and strip and reached a client three times."""
    with caplog.at_level("WARNING"):
        text, sug = conversation.extract_suggestion("Os dois travados.\n[[SUGGEST resume #69 e #70]]")

    assert sug is None
    assert "[[" not in text and "SUGGEST" not in text
    assert "LOST_TAG" in caplog.text, "a lost suggestion vanished with nothing said"

    text2, sug2 = conversation.extract_suggestion("feito → [[SUGGEST merge #12]]")
    assert sug2 is None, "merge is never an action offered from a conversation"
    assert "[[" not in text2


# ── the evidence it composes ─────────────────────────────────────────────────────────────────────

def test_an_empty_floor_is_said_out_loud():
    assert "No jobs" in conversation.state_snapshot([])


def test_each_job_becomes_a_line_carrying_only_the_first_line_of_its_note():
    """THE NOTE COMES OUT OF `action`, WHICH IS THE ONLY PLACE IT HAS EVER BEEN (#121).

    This test used to hand `state_snapshot` a dict with a top-level `note`, and the renderer read
    one — so both sides agreed on a shape `view.list_jobs` has never produced. `_row` sets no
    `note`; neither does `list_jobs`; the park reason lives inside the `action` payload. The
    assertion passed, the feature was dead, and the guidance went on telling the tech-lead to
    "use its park note to explain WHY" about a field that was empty on every job of every answer.
    """
    out = conversation.state_snapshot([
        {"issue": "189", "state": "running", "title": "add health route"},
        {"issue": "42", "state": "on_hold", "attention": True,
         "action": {"kind": "impediment", "state": "on_hold",
                    "note": "gates unfixable\nsecond line ignored"}},
    ])

    assert "#189" in out and "running" in out and "add health route" in out
    assert "#42" in out and "on_hold" in out and "needs-attention" in out
    assert "gates unfixable" in out
    assert "second line ignored" not in out


def test_a_sparse_row_still_produces_a_line():
    """This renders whatever Temporal returned. A missing field is a smaller line, never a crash
    on the path that answers a person."""
    assert conversation.state_snapshot([{}])


def test_the_three_realities_are_told_apart():
    snap = conversation.state_snapshot([
        # (a) closed ticket + still-parked workflow → ORPHANED, skip to clean up
        {"issue": "69", "state": "failed", "title": "Plan 88.1 — Spreadsheet import",
         "ticket_state": "closed", "board": "Done"},
        # (b) closed + terminal → truly resolved, no flag
        {"issue": "393", "state": "merged", "title": "Plan 92a", "ticket_state": "closed"},
        # (c) open + parked → genuine attention, and the board column shows
        {"issue": "416", "state": "needs_refinement", "title": "tech-lead test",
         "ticket_state": "open", "board": "Needs Action", "attention": True},
    ])

    assert "ORPHANED" in snap.splitlines()[0]
    assert "ORPHANED" not in snap.splitlines()[1]
    assert "board: Needs Action" in snap.splitlines()[2]
    assert "Plan 88.1" in snap, "a task named only by its number is unreadable on a phone"


def test_the_agent_result_is_read_through_the_one_shared_reader():
    assert conversation.answer_text(_Res(
        summary="capped",
        raw_output='{"type":"assistant","message":{"content":[]}}\n'
                   '{"type":"result","result":"the full answer","session_id":"s1"}\n',
    )) == "the full answer"
    assert conversation.answer_text(_Res(summary="fallback summary",
                                         raw_output="not json\n")) == "fallback summary"


# ── and the capability does not grow back inside the channel ─────────────────────────────────────

#: Things only a capability does. A transport that constructs any of these has stopped being a
#: transport — which is exactly the state this card found, and the reason a guard is worth more
#: here than a review.
_CAPABILITY_NAMES = frozenset({
    "build_techlead",      # constructing the role's agent
    "build_board",         # reading the tracker's board
    "WorktreeSandbox",     # cloning into a sandbox to reason over code
    "list_jobs",           # reading the factory floor
})

_SLACK = pathlib.Path(__file__).resolve().parents[1] / "openfactory" / "runtime" / "slack"


def _capability_uses(root: pathlib.Path) -> list[str]:
    """Where any capability name is IMPORTED or CALLED. Read from the AST rather than the text, so
    the prose in a docstring naming one of them is not mistaken for using it."""
    hits: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                names = [node.func.id]
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                names = [node.func.attr]
            for n in names:
                if n in _CAPABILITY_NAMES:
                    hits.append(f"{path.name}:{node.lineno} {n}")
    return hits


def test_the_slack_package_builds_no_agent_no_board_and_no_sandbox():
    """The card's "done when", asserted rather than believed."""
    offenders = _capability_uses(_SLACK)

    assert not offenders, ("the Slack package is doing the work again instead of delivering it:\n"
                           + "\n".join(f"  {o}" for o in offenders))


def test_the_guard_can_actually_SEE_an_offender(tmp_path):
    """A scan that matched nothing — a broken walk, a renamed symbol, a wrong root — would pass
    the test above for ever while proving nothing."""
    (tmp_path / "bot.py").write_text(
        "from openfactory.adapters.agent import build_techlead\n", encoding="utf-8")

    assert [h.split()[-1] for h in _capability_uses(tmp_path)] == ["build_techlead"]


def test_the_channel_asks_the_product_role_what_it_is_waiting_on():
    """The other half of the same move. Opening the memory store, filtering loop kinds and writing
    the Portuguese used to happen inside the Slack channel; a channel asks, it does not work it
    out. Called with a project that has no ledger at all — the answer is "", never an exception,
    because this line is appended to a status somebody is waiting on."""
    from openfactory.product.followup import waiting_line

    assert waiting_line("a-project-with-no-ledger-at-all") == ""


def test_the_waiting_line_actually_carries_the_open_loops(monkeypatch):
    """THE POSITIVE TWIN, added after the adversarial review: the test above asserts "" — the
    same value the function's own blanket except returns on ANY internal breakage, so it proved
    nothing about the line ever being produced. This one seeds a real ledger and demands the
    sentence."""
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import DELIVERY, QUESTION, open_loop
    from openfactory.product.followup import OWNER, waiting_line

    loops = [open_loop(QUESTION, "412", owner=OWNER, ts="2026-08-01T10:00:00"),
             open_loop(DELIVERY, "7", owner=OWNER, ts="2026-08-01T11:00:00")]
    monkeypatch.setattr(loop_store, "read", lambda name: list(loops))

    line = waiting_line("demo")

    assert "#412" in line, "an open question never reached the sentence"
    assert "entrega" in line or "delivery" in line


def test_the_waiting_sentence_speaks_the_deployment_s_language():
    """It was Portuguese-only while it lived in the channel. Moving it into `voice` is what makes
    the language configurable at all — the same gap the language setting closed for every other
    sentence this role says."""
    from openfactory.product.voice import still_waiting

    pt = still_waiting(questions=["412"], deliveries=2, language="pt-BR")
    en = still_waiting(questions=["412"], deliveries=2, language="en")

    assert "aguardo" in pt and "entrega" in pt
    assert "waiting" in en and "delivery" in en
    assert still_waiting(questions=[], deliveries=0) == ""


def test_the_waiting_line_names_at_most_five_and_counts_the_rest():
    """A status line listing twenty refs is a wall nobody reads, and the count already says how
    many there are."""
    from openfactory.product.voice import still_waiting

    line = still_waiting(questions=[str(n) for n in range(1, 9)], deliveries=0)

    assert line.count("#") == 5
    assert "(+3)" in line


def test_a_non_numeric_ref_is_printed_as_the_tracker_wrote_it():
    from openfactory.product.voice import still_waiting

    assert "#CONT-412" in still_waiting(questions=["CONT-412"], deliveries=0)


# ── a failed clone must not publish the credential it carried ───────────────────────────────────

def test_a_clone_failure_never_logs_the_live_token(monkeypatch, caplog):
    """A failed `git clone` raises CalledProcessError, whose text embeds the full command —
    including `https://x-access-token:<live token>@github.com/...` — and the token sits well
    inside the first 120 characters. `str(exc)[:120]` therefore published a live GitHub App
    credential into the worker's own log stream on every clone failure. Truncation is not
    redaction; the scrub replaces FIRST."""
    import subprocess as sp

    token = "ghs_LIVE1234567890abcdefghijklmnop"
    monkeypatch.setattr("openfactory.credentials.forge_token", lambda: token)
    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: "")

    def _fail(cmd, **kw):
        raise sp.CalledProcessError(128, cmd)

    monkeypatch.setattr(conversation.subprocess, "run", _fail)

    class _WithRepo:
        name = "demo"
        forge = None
        # `kind` because the URL is resolved through the forge REGISTRY now (#91), and the registry
        # refuses to guess a vendor. A row that declares only `tracker:` inherits its kind, which is
        # the shape `contracts/project.py` documents and this fixture is written in.
        tracker = type("T", (), {"repo": "o/r", "kind": "github"})()

    with caplog.at_level("WARNING"):
        _tmp, cloned = conversation.clone_repo(_WithRepo())

    assert cloned is False
    assert token not in caplog.text, "a live credential reached the log stream"
    assert "***" in caplog.text, "the failure lost its trace along with the token"


def test_the_diagnosis_checkout_is_scrubbed_the_same_way(monkeypatch, caplog):
    import subprocess as sp

    from openfactory.techlead import diagnosis

    token = "ghs_LIVE1234567890abcdefghijklmnop"
    monkeypatch.setattr("openfactory.credentials.forge_token", lambda: token)
    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: "")

    def _fail(cmd, **kw):
        raise sp.CalledProcessError(128, cmd)

    monkeypatch.setattr(diagnosis.subprocess, "run", _fail)

    class _WithRepo:
        name = "demo"
        forge = None
        tracker = type("T", (), {"repo": "o/r", "kind": "github"})()

    with caplog.at_level("WARNING"):
        _tmp, cloned = diagnosis._checkout(_WithRepo(), "#412")

    assert cloned is False
    assert token not in caplog.text
    assert "***" in caplog.text


def test_scrubbed_replaces_before_it_truncates():
    """The order IS the fix: truncate-then-replace would keep the token whenever it straddles the
    cut, which is exactly where a clone command puts it."""
    from openfactory.util.causes import scrubbed

    secret = "S" * 100
    exc = RuntimeError("Command 'git clone https://x:" + secret + "@host/r.git' failed")

    out = scrubbed(exc, secret, limit=60)

    assert secret[:10] not in out
    assert "***" in out
    assert len(out) <= 60
