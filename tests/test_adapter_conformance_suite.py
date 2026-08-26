"""The conformance suite is a runnable deliverable, and it can SEE an offender (C-22, #58).

The done-when: a stranger runs it against their own adapter and shows a green run. So the tests
here are two-sided — our own adapters run GREEN through the same functions the CLI exposes (the
suite's first stranger is ourselves), and deliberately broken adapters run RED, because a suite
that cannot fail proves nothing (the house's silent-scanner rule).
"""

from __future__ import annotations

from typer.testing import CliRunner

from openfactory.cli import app
from openfactory.conformance import check_board, check_channel, check_identity, check_notifier

# ── our own providers are the first green run ───────────────────────────────────────────────────

def test_the_panel_channel_is_conformant(monkeypatch):
    from openfactory.adapters.channel.panel import PanelChannel

    # the store write is irrelevant to the contract under test; a False `say` is still a bool
    monkeypatch.setattr("openfactory.memory.messages.say", lambda *a, **k: True)

    assert check_channel(PanelChannel()) == []


def test_the_local_identity_is_conformant():
    from openfactory.identity.local import LocalIdentity

    assert check_identity(LocalIdentity(env={})) == []


def test_the_panel_notifier_is_conformant(monkeypatch):
    from openfactory.adapters.notify.panel import PanelNotifier

    monkeypatch.setattr("openfactory.memory.messages.say", lambda *a, **k: True)

    assert check_notifier(PanelNotifier(project_name="probe")) == []


def test_a_fake_jira_board_is_conformant():
    """The C-05 fake — the second provider the port was proven against — through the published
    suite: the two proofs must agree or one of them is decoration."""
    from openfactory.contracts import JobState

    class FakeJiraBoard:
        def __init__(self):
            self.cards = {"CONT-1": "TO-DO"}

        def url(self) -> str:

            """Where a person looks at this board — `""` for a double that has

            nowhere to send anybody. The port asks it of every board (#162)."""

            return ""


        def columns(self):
            return dict(self.cards)

        def column_names(self):
            return sorted(set(self.cards.values()))

        def pickup_column(self):

            return "TO-DO"


        def items_in_status(self, status):
            return [r for r, c in self.cards.items() if c == status]

        def add_item(self, *, issue_url):
            return None

        def set_column(self, *, issue, issue_url, name):
            if issue not in self.cards:
                return False
            self.cards[issue] = name
            return True

        def set_status(self, *, issue, issue_url, state: JobState):
            return self.set_column(issue=issue, issue_url=issue_url, name=state.value)

    assert check_board(FakeJiraBoard()) == []


# ── and the suite can fail, or it proves nothing ────────────────────────────────────────────────

def test_a_channel_that_raises_is_caught():
    class _Explodes:
        def say(self, *, project, channel, text):
            raise RuntimeError("boom")

        def mention(self, person, **kw):
            return person

        def start_listeners(self):
            return None

    findings = check_channel(_Explodes())

    assert any(f.rule == "channel.say-never-raises" for f in findings)


def test_a_board_with_int_refs_is_caught():
    """THE C-05 rule, as a stranger's adapter would break it: numeric refs work on three of four
    trackers, so the suite is where the fourth stops being a surprise."""
    class _IntBoard:
        def url(self) -> str:
            """Where a person looks at this board — `""` for a double that has
            nowhere to send anybody. The port asks it of every board (#162)."""
            return ""

        def columns(self):
            return None

        def column_names(self):
            return None

        def pickup_column(self):

            return "TO-DO"


        def items_in_status(self, status):
            return [412]  # ints — the collapse

        def add_item(self, *, issue_url):
            return None

        def set_column(self, *, issue, issue_url, name):
            return True  # claims success for a ref it cannot hold

        def set_status(self, *, issue, issue_url, state, needs_person=None):
            return True

    rules = {f.rule for f in check_board(_IntBoard())}

    assert "board.refs-are-strings" in rules
    assert "board.refuses-what-it-cannot-address" in rules


def test_an_identity_that_resolves_nothing_to_somebody_is_caught():
    class _Generous:
        def identify(self, *, credential, via=""):
            from openfactory.identity.base import Subject

            return Subject(id="guest", via="generous")  # even for ""

    findings = check_identity(_Generous())

    assert any(f.rule == "identity.empty-is-nobody" for f in findings)


def test_a_notifier_that_rejects_about_is_caught():
    class _Narrow:
        def notify(self, *, message, level="info"):
            return None  # no `about` — the thread-link rides on it

    findings = check_notifier(_Narrow())

    assert any(f.rule == "notifier.accepts-about" for f in findings)


# ── the published door: the CLI a stranger actually runs ────────────────────────────────────────

def test_the_cli_runs_a_green_adapter_end_to_end():
    result = CliRunner().invoke(app, ["conformance-adapter", "identity",
                                      "openfactory.identity.local:LocalIdentity"])

    assert result.exit_code == 0, result.output
    assert "CONFORMANT" in result.output


def test_the_cli_renders_a_red_run_with_the_lesson():
    """The finding carries the INCIDENT that taught the rule — a stranger fixing their adapter
    should learn why, not just what."""
    result = CliRunner().invoke(app, ["conformance-adapter", "channel",
                                      "tests.test_adapter_conformance_suite:_BrokenChannel"])

    assert result.exit_code == 1
    assert "taught by" in result.output


class _BrokenChannel:
    def say(self, *, project, channel, text):
        raise RuntimeError("boom")

    def mention(self, person, **kw):
        return person

    def start_listeners(self):
        return None


def test_an_unknown_kind_is_refused_with_the_list():
    result = CliRunner().invoke(app, ["conformance-adapter", "tracker9000", "x:y"])

    assert result.exit_code == 2
    assert "channel" in result.output
