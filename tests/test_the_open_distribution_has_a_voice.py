"""A deployment that declares no Slack still has a channel (C-44, #87).

`DEFAULT_KIND` was `"slack"` and `Project.channel` defaults to `""`, so a deployment that declared
nothing resolved to Slack. Verified by loading the SHIPPED `registry.yaml.example` through the real
code: `channel='' → 'slack' → SlackChannel`. Meanwhile `.env.compose.example` tells the reader the
opposite — *"leave it empty and the factory still works: it reports on the ticket, and you drive it
from the panel"* — and `PanelChannel`, the second implementation that turned this registry from a
hypothesis into a real seam, sat registered, tested and unreachable in the default configuration of
the artefact being open-sourced.

Flipping the constant alone would have been the opposite failure: the live client declares no
`channel:` either — it carries `channel_id` — so a bare default of `panel` would have silenced a
working Slack deployment. That is why these tests load the two real files rather than synthetic
projects: the fix has to be right for BOTH shapes that exist, and only the files say what those are.

#266 SLICE 6 TOOK THE INFERENCE OUT (ADR-0051 D16): a coordinate no longer names a vendor, only
`channel:` does, and the registry names the old coordinate, once, with the line that keeps such a
deployment on its add-on. The test that pinned the inference is flipped, and says so.
"""

from __future__ import annotations

import pathlib

import yaml

from openfactory.adapters.channel.registry import build_channel, channel_kind
from openfactory.contracts.project import Project

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _first_project(path: pathlib.Path) -> Project:
    data = yaml.safe_load(path.read_text())["projects"]
    return Project(**data[next(iter(data))])


def test_a_stranger_copying_the_example_gets_the_panel():
    """The shape being open-sourced. This is the assertion that was false."""
    stranger = _first_project(ROOT / "deploy/registry.yaml.example")
    assert channel_kind(stranger) == "panel"
    assert type(build_channel(stranger)).__name__ == "PanelChannel"


def test_a_project_with_chat_COORDINATES_and_no_declaration_gets_the_panel_and_is_TOLD(
        tmp_path, caplog):
    """FLIPPED ON PURPOSE BY #266 SLICE 6 (ADR-0051 D16). This pinned the inference that kept the
    live client on its vendor: no `channel:`, a `channel_id`, therefore that vendor. The inference
    was the core answering "which vendor?" from the shape of a field, and it is gone — only
    `channel:` names the add-on. What keeps the live client from going quiet unnoticed is the
    registry naming the old coordinate, once, with the one line that keeps it on its add-on."""
    import logging

    from openfactory.registry import ProjectRegistry

    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump({"projects": {"c": {
        "name": "c", "repo_path": "/tmp/c", "channel_id": "C0BK72VQDHA"}}}))
    with caplog.at_level(logging.WARNING, logger="openfactory.registry"):
        live = ProjectRegistry(path).get("c")
    assert channel_kind(live) == "panel"
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "'channel_id'" in said and "`channel: <kind>`" in said, said


def test_an_explicit_declaration_always_wins():
    for kind in ("slack", "panel"):
        p = Project(name="x", repo_path="/tmp/x", channel=kind,
                    channel_options={"channel": "C123"})
        assert channel_kind(p) == kind


def test_no_project_at_all_is_the_panel():
    """The deployment-wide question — asked by callers with nothing in hand."""
    assert channel_kind(None) == "panel"


def test_the_compose_example_promise_is_now_TRUE():
    """`.env.compose.example` says leaving Slack empty still gives a working factory driven from
    the panel. That sentence was false against the shipped default; a doc and a default that
    disagree is how a stranger's first hour is spent."""
    text = (ROOT / ".env.compose.example").read_text()
    assert "panel" in text.lower()
    stranger = _first_project(ROOT / "deploy/registry.yaml.example")
    assert type(build_channel(stranger)).__name__ == "PanelChannel"


def test_the_notifier_and_the_channel_agree(monkeypatch):
    """Two answers to "where does this project speak" that disagree is how a message lands in a
    store nobody reads while the listener runs somewhere else."""
    from openfactory.factory import notifier_for_project

    monkeypatch.delenv("OPENFACTORY_NOTIFIER_FALLBACK", raising=False)
    stranger = _first_project(ROOT / "deploy/registry.yaml.example")
    assert channel_kind(stranger) == "panel"
    assert type(notifier_for_project(stranger)).__name__ == "PanelNotifier"


def test_an_INFERRED_panel_does_not_step_in_front_of_the_declared_fallback(monkeypatch):
    """The ordering this fix nearly broke. `channel_kind` now infers `panel` for a project with no
    chat coordinates, and short-circuiting the NOTIFIER on that inferred answer would silence a
    deployment that DECLARED a deployment-wide fallback on purpose. The panel is the LAST resort
    in the notifier and the FIRST in the channel registry — both correct, because only one of
    them has somewhere else to go. The fallback is a declared kind on the notifier axis
    (`OPENFACTORY_NOTIFIER_FALLBACK`), served here by the chat package's Telegram row."""
    from vendor_addons import install, require

    from openfactory.factory import notifier_for_project

    require("notifier.telegram")
    install(monkeypatch, "notifier.telegram")
    monkeypatch.setenv("OPENFACTORY_NOTIFIER_FALLBACK", "telegram")
    monkeypatch.setenv("OPENFACTORY_TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("OPENFACTORY_TELEGRAM_CHAT_ID", "c")
    p = Project(name="x", repo_path="/tmp/x")  # no channel, no channel_id
    assert channel_kind(p) == "panel"                      # the CHANNEL says panel
    assert type(notifier_for_project(p)).__name__ == "TelegramNotifier"   # the NOTIFIER routes


def test_an_EXPLICIT_panel_does_step_in_front_of_the_declared_fallback(monkeypatch):
    """The positive twin: a deployment that chose the panel is not overruled by the fallback."""
    from vendor_addons import install, require

    from openfactory.adapters.notify.panel import PanelNotifier
    from openfactory.factory import notifier_for_project

    require("notifier.telegram")
    install(monkeypatch, "notifier.telegram")
    monkeypatch.setenv("OPENFACTORY_NOTIFIER_FALLBACK", "telegram")
    monkeypatch.setenv("OPENFACTORY_TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("OPENFACTORY_TELEGRAM_CHAT_ID", "c")
    p = Project(name="x", repo_path="/tmp/x", channel="panel")
    assert isinstance(notifier_for_project(p), PanelNotifier)
