"""What the first hour on one machine still got wrong, found by walking it (ADR-0049 D9).

Three things, each measured end to end rather than read:

  · **`poll` walked past the gate it had just been given.** `scan_todo` consults `gate_reason`
    before it starts anything; the command whose own docstring says to put it on a cron — the only
    scheduler a one-machine deployment has — did not. A card ran all the way to Done with
    `openfactory doctor` reporting the last box proof FAILED.
  · **The proof demanded a token variable the harness does not read here.** `claude --version`
    answered from inside the box, the endpoint answered, and `box prove` failed anyway on
    `ANTHROPIC_API_KEY` — the same reading the doctor was taught in slice 4d, one command over.
  · **Everything the factory said was dropped.** The message store writes through the metrics
    sink, which is Null unless a deployment names one, so "PR ready for review", the parks and the
    tech-lead's voice were produced and discarded, with the panel's Conversation empty by
    construction.
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, "tests")
import one_machine as om  # noqa: E402

# ── the scheduler asks the same gate ────────────────────────────────────────────────────────────

@pytest.fixture
def queued(tmp_path, monkeypatch):
    """A project with a card in TO-DO, on a machine that declares the work is its own."""
    from openfactory import own_work

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(own_work.VARIABLE, "1")
    repo = om.a_repository(tmp_path)
    om.a_deployment(tmp_path, monkeypatch=monkeypatch)
    om.register_the_harness()
    assert om.cli("project", "init", "myapp", str(repo))[0] == 0
    om.plug_the_project_in(repo, merge_policy="auto")
    om.cli("act", "card_create", "-p", "myapp", "-P", "title=Add the feature",
           "-P", f"body={om.CARD_BODY}")
    om.cli("act", "card_move", "-p", "myapp", "-i", "1", "-P", "column=TO-DO")
    return repo


def test_poll_HOLDS_when_the_gate_holds_and_says_the_gates_own_reason(queued, monkeypatch):
    monkeypatch.setattr("openfactory.box_prove.gate_reason",
                        lambda *a, **k: "the box has never been proven — run `openfactory box "
                                        "prove myapp`")

    code, out = om.cli("poll", "myapp")

    assert code == 0
    assert "pickup is held" in out and "never been proven" in out
    assert "→ #1" not in out, "a card was picked up behind a held gate"
    assert not (queued / om.FEATURE).exists(), "the agent ran anyway"


def test_poll_RUNS_when_the_gate_is_clear(queued, monkeypatch):
    monkeypatch.setattr("openfactory.box_prove.gate_reason", lambda *a, **k: None)

    code, out = om.cli("poll", "myapp")

    assert "→ #1" in out and "done" in out
    assert (queued / om.FEATURE).read_text().strip() == om.VALUE


# ── the proof accepts the login where there is one ──────────────────────────────────────────────

def _probes(**over):
    from openfactory.box_prove import Probes

    base = dict(
        resolve_digest=lambda img: "sha256:" + "a" * 64,
        image_platform=lambda img: ("linux", "amd64", "glibc"),
        toolbox_stamp=lambda: {"variant": "linux-amd64-glibc", "harnesses": ["claude"]},
        contract=lambda img: {},
        run_in_box=lambda cmd: (0, "ok"),
        harness_reachable=lambda: (True, "200"),
        setup_commands=list,
        validate_commands=dict,
        harness_name=lambda: "claude",
        env_in_box=lambda names: {},          # no token variable inside the box
    )
    base.update(over)
    return Probes(**base)


def test_a_box_with_no_image_is_proven_on_the_LOGIN():
    """It was measured failing with everything else green: the harness answered its version from
    inside the box and the endpoint answered, and the proof refused for a variable nothing here
    would have read."""
    from openfactory.box_prove import prove

    proof = prove("myapp", "", _probes(honours_image=False, machine_stamp=lambda: "claude 2.1"))

    auth = next(f for f in proof.findings if f.check == "harness auth")
    assert auth.ok and "login on this machine" in auth.message
    assert proof.ok, [f.message for f in proof.findings if not f.ok]


def test_a_box_that_ISOLATES_still_demands_the_variable():
    """There the CLI authenticates with no human at a browser and no login to inherit."""
    from openfactory.box_prove import prove

    proof = prove("myapp", "an-image", _probes(honours_image=True))

    auth = next(f for f in proof.findings if f.check == "harness auth")
    assert not auth.ok and "INSIDE the box" in auth.message


# ── the factory's own voice lands somewhere ─────────────────────────────────────────────────────

def test_the_host_file_NAMES_the_store_the_panel_reads(tmp_path):
    from openfactory.onboarding.deployment import Answers, Probes, render

    text = render(Answers(), Probes(home=lambda: str(tmp_path))).text

    assert "OPENFACTORY_METRICS_SINK=sqlite" in text
    assert f"OPENFACTORY_METRICS_DB={tmp_path}/.openfactory/metrics.db" in text


def test_what_the_factory_SAYS_is_there_to_be_read(tmp_path, monkeypatch):
    """End to end through the notifier the panel channel ships: produced, written, read back."""
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    from openfactory.adapters.notify.panel import PanelNotifier
    from openfactory.memory import messages

    PanelNotifier(project_name="myapp").notify(message="#1 PR ready for review", level="info")

    said = [m.text for m in messages.read("myapp")]
    assert any("PR ready for review" in line for line in said), said


def test_a_deployment_that_names_NO_store_still_loses_it(tmp_path, monkeypatch):
    """The inference is deliberately unchanged: the compose file says `sqlite` in as many words,
    and a default that overrode what a file says is how a deployment stops being readable. What
    changed is that `init` NAMES one for the runtime it writes."""
    monkeypatch.delenv("OPENFACTORY_METRICS_SINK", raising=False)
    monkeypatch.delenv("OPENFACTORY_METRICS_TABLE", raising=False)
    from openfactory.observability.registry import metrics_sink_kind

    assert metrics_sink_kind() == "null"
