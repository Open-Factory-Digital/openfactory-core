"""Every door an operator or a stranger walks through reads the registries — none keeps a copy.

The registries were opened (`test_a_stranger_can_add_an_adapter.py`) and four doors in front of
them still refused an installed add-on, each from its own hand copy of the vocabulary — measured
2026-08-26 with a real distribution on the path:

  `openfactory init`            four literal tuples: "forge: 'acme' is not one of github, azure_devops"
  `openfactory project init`    a host list: "git.acme.example is not a forge this build implements"
  `conformance-adapter`         five kinds of nine, and a factory FUNCTION judged as the instance
  the worker                    `build_channel()` with no project — the panel, so no add-on (nor
                                Slack) ever listened

And two registries that opened still needed an ordering fixed: the board consulted its rows only
AFTER a GitHub-only coordinates gate, and the notifier had no registry at all. Each guard here
drives the real door with the stranger's package installed, and each has the twin that keeps the
refusal for a kind nobody implements.
"""

from __future__ import annotations

import ast
import inspect
import logging
import re

import add_ons
import pytest
import stranger_addon
from typer.testing import CliRunner

from openfactory import plugins
from openfactory.contracts.project import Project, ProviderRef


@pytest.fixture
def stranger(tmp_path, monkeypatch):
    return stranger_addon.installed(tmp_path, monkeypatch)


def _project(**overrides):
    fields = dict(name="fx-acme", repo_path="/tmp/fx-acme",
                  tracker=ProviderRef(kind="acme", repo="acme/repo"),
                  forge=ProviderRef(kind="acme", repo="acme/repo"), channel="acme")
    fields.update(overrides)
    return Project(**fields)


# ── 1. `openfactory init` reads the registries ──────────────────────────────────────────────────

def test_init_ACCEPTS_the_kinds_a_stranger_installed(stranger):
    from openfactory.onboarding.deployment import Answers, choices

    for axis in ("forge", "tracker", "harness", "channel"):
        assert "acme" in choices(axis), f"{axis}: {choices(axis)}"
    Answers(forge="acme", tracker="acme", harness="acme", channel="acme").validate()


@pytest.mark.parametrize("axis", ["forge", "tracker", "harness", "channel"])
def test_and_still_REFUSES_a_kind_nobody_implements_listing_the_registry(axis):
    """The twin: the vocabulary grew from outside, it did not become "anything"."""
    from openfactory.onboarding.deployment import Answers, UnknownAnswer, choices

    with pytest.raises(UnknownAnswer) as e:
        Answers(**{axis: "nosuch"}).validate()
    assert "nosuch" in str(e.value)
    for kind in choices(axis):
        assert kind in str(e.value), f"the refusal does not list {kind!r}: {e.value}"


def test_the_prompt_offers_the_installed_kind_when_it_is_READ_not_when_the_module_loaded(stranger):
    """`QUESTIONS` is a module constant; its options must not be — a tuple frozen at import would
    show the interactive prompt and the non-tty refusal a list the registry had outgrown."""
    from openfactory.onboarding.deployment import QUESTIONS

    by_flag = {q.flag: q for q in QUESTIONS}
    for flag in ("forge", "tracker", "harness", "channel"):
        assert "acme" in by_flag[flag].options, f"--{flag} offers {by_flag[flag].options}"
        assert by_flag[flag].default in by_flag[flag].options


def test_render_NAMES_an_add_on_kind_and_who_owns_its_credential(stranger):
    """The worse defect the first fix would have shipped: widening the vocabulary alone wrote a
    file with no forge row and a to-do list with no line for its credential — a file that looks
    configured and authenticates nothing. Every add-on answer gets a named section AND a line."""
    from openfactory.onboarding.deployment import Answers, render

    out = render(Answers(forge="acme", tracker="acme", harness="acme", channel="acme"))

    for axis in ("forge", "tracker", "harness"):
        assert f"{axis}: acme — an add-on this generator carries no rows for" in out.text, (
            f"the file never names the {axis} add-on:\n{out.text}")
    # the channel row DECLARES what it reads (`plugins.environment`, 2026-08-26), so its section
    # carries the rows themselves rather than the placeholder — still named, still a to-do line
    assert "`acme` is an add-on channel" in out.text and "ACME_CHAT_TOKEN=" in out.text, out.text
    lines = [ln for ln in out.remaining if "`acme`" in ln]
    assert len(lines) == 4, out.remaining
    for ln in lines:
        assert "add-on" in ln and "doctor" in ln, ln
    # and no built-in vendor's credential was invented for it
    assert "OPENFACTORY_BOT_TOKEN" not in out.text and "AZURE_DEVOPS_PAT" not in out.text


def test_render_writes_NO_add_on_section_for_shipped_kinds():
    """The twin: the shipped vocabulary renders its own blocks, never the add-on placeholder."""
    from openfactory.onboarding.deployment import Answers, render

    out = render(Answers(forge="github", tracker="jira", harness="codex", channel="panel"))

    assert "an add-on this generator carries no rows for" not in out.text
    assert not any("add-on" in ln for ln in out.remaining), out.remaining


def test_render_writes_the_chat_how_to_when_its_package_is_installed(monkeypatch):
    """`slack` is an add-on kind since 2026-08-26 — the generator refuses it unless the
    `channel.slack` row is installed — and once it is, the init still writes the chat package's
    own how-to (the two tokens, by name) rather than the generic add-on placeholder: the block
    is the maintainers' own package's instructions, reached only when that package is there."""
    from vendor_addons import install, require

    from openfactory.onboarding.deployment import Answers, UnknownAnswer, render

    require("channel.slack")
    with pytest.raises(UnknownAnswer, match="slack"):
        render(Answers(channel="slack"))

    install(monkeypatch, "channel.slack")
    out = render(Answers(channel="slack"))

    assert "SLACK_BOT_TOKEN" in out.text and "SLACK_APP_TOKEN" in out.text
    assert "an add-on this generator carries no rows for" not in out.text
    for line in out.remaining:
        assert re.search(r"`[^`]+`|\b[a-z-]+\.(com|dev|io)\b|docs/[\w/.-]+\.md", line), (
            f"this to-do names no command, page or document: {line!r}")


def test_the_shipped_set_is_the_registry_s_own_rows_and_never_an_add_on(stranger):
    """`shipped(axis)` is read off the registries' tables when asked — no list kept beside
    them. The literal it replaced equalled the four tables by luck and was read by no test
    (measured 2026-08-26); a row added to a registry without a name in it would have been
    rendered as an add-on — a false sentence in the operator's own `.env`."""
    from openfactory.adapters.agent.registry import HARNESSES
    from openfactory.adapters.channel.registry import CHANNELS
    from openfactory.adapters.forge.registry import FORGES
    from openfactory.adapters.tracker.registry import TRACKERS
    from openfactory.onboarding.deployment import choices, shipped

    for axis, table in (("forge", FORGES), ("tracker", TRACKERS), ("harness", HARNESSES),
                        ("channel", CHANNELS)):
        assert set(shipped(axis)) == set(table), axis
        assert "acme" in choices(axis) and "acme" not in shipped(axis), axis


def _every_shipped_kind():
    from openfactory.onboarding.deployment import shipped

    return [(axis, kind) for axis in ("forge", "tracker", "harness", "channel")
            for kind in shipped(axis)]


@pytest.mark.parametrize("axis,kind", _every_shipped_kind())
def test_every_shipped_kind_NAMES_itself_in_the_file_rendered_for_it(axis, kind):
    """The positive twin of the add-on placeholder. A shipped row this generator forgot to
    write a block for would render NOTHING for its kind — no rows, no placeholder, no to-do
    line — and nothing looks configured. So every row of every table must appear, by name, in
    what is rendered when it is the answer."""
    from openfactory.onboarding.deployment import Answers, render

    out = render(Answers(**{axis: kind}))

    said = (out.text + "\n".join(out.remaining)).lower()
    assert kind in said or kind.replace("_", " ") in said, (
        f"{axis}={kind} is shipped and renders nothing that names it")
    assert "an add-on this generator carries no rows for" not in out.text


def test_the_init_COMMAND_writes_a_file_for_an_add_on_deployment(stranger, tmp_path):
    """The published door, end to end: the exact invocation that exited 2 on 2026-08-26."""
    from openfactory.cli import app

    dest = tmp_path / ".env.compose"
    result = CliRunner().invoke(app, [
        "init", "--forge", "acme", "--tracker", "acme", "--harness", "acme",
        "--channel", "acme", "--panel-local", "--out", str(dest)])

    assert result.exit_code == 0, result.output
    assert dest.exists()
    assert "forge: acme" in dest.read_text()
    assert "`acme` forge add-on" in result.output, result.output


def test_the_init_help_carries_no_hand_copy_of_the_vocabulary():
    """`--help` listed `github | azure_devops` beside a generator that reads the registry — a
    third copy, and the one a stranger reads first. Read off the command's own option help."""
    from openfactory.cli import init_deployment

    for param in inspect.signature(init_deployment).parameters.values():
        text = str(getattr(param.default, "help", "") or "")
        if param.name in ("forge", "tracker", "harness", "channel"):
            assert "github" not in text and "azure_devops" not in text and "slack" not in text, (
                f"--{param.name} help still lists vendors by hand: {text!r}")


# ── 2. `project init` lets an installed add-on claim its host ───────────────────────────────────

def test_a_known_forge_list_includes_the_installed_add_on(stranger):
    from openfactory.cli import _installed_forges, _known_forges

    assert "acme" in _known_forges()
    assert _installed_forges() == ["acme"]


def test_an_installed_add_on_CLAIMS_its_host_by_name(stranger):
    from openfactory.cli import _foreign_host

    url = "https://git.acme.example/team/repo.git"
    assert _foreign_host(url) == "git.acme.example", "the host is not ours; unnamed, it is foreign"
    assert _foreign_host(url, provider="acme") == ""


def test_a_provider_nobody_implements_is_refused_listing_what_is(stranger):
    """The twin: `--provider` is not a bypass, it is a name the registry must know."""
    from openfactory.cli import _foreign_host

    with pytest.raises(ValueError, match="nosuch") as e:
        _foreign_host("https://git.acme.example/team/repo.git", provider="nosuch")
    assert "acme" in str(e.value) and "github" in str(e.value)


def _init(tmp_path, monkeypatch, url, provider=None):
    import typer

    from openfactory import cli

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    said: list[str] = []
    monkeypatch.setattr(cli.typer, "echo", lambda text="", **k: said.append(str(text)))
    try:
        cli.project_init(name="acme-proj", repo_path=url, repo=None, board_owner=None,
                         language=None, provider=provider)
    except typer.Exit as exit_:
        return said, exit_.exit_code
    return said, 0


def test_project_init_REGISTERS_an_add_on_forge_under_its_own_kind(stranger, tmp_path,
                                                                    monkeypatch):
    from openfactory.registry import ProjectRegistry

    said, code = _init(tmp_path, monkeypatch, "https://git.acme.example/team/repo.git",
                       provider="acme")

    assert code == 0, said
    got = ProjectRegistry().get("acme-proj")
    assert got.tracker.kind == "acme" and got.forge.kind == "acme", got
    assert got.tracker.repo == "team/repo"


def test_the_refusal_OFFERS_the_installed_add_on_as_the_remedy(stranger, tmp_path, monkeypatch):
    """Without `--provider` the host is still refused — and the sentence now names the flag and
    the kind that would claim it, so the operator is not sent to docs for a vendor they have."""
    from openfactory.registry import ProjectRegistry

    said, code = _init(tmp_path, monkeypatch, "https://git.acme.example/team/repo.git")

    assert code == 2
    joined = "\n".join(said)
    assert "--provider" in joined and "acme" in joined, joined
    with pytest.raises(KeyError):
        ProjectRegistry().get("acme-proj")


def test_the_remedy_is_not_offered_when_nothing_is_installed(tmp_path, monkeypatch):
    """The twin: a `--provider` line with nothing to name would be a dead end dressed as help."""
    said, code = _init(tmp_path, monkeypatch, "https://gitlab.com/o/r.git")

    assert code == 2
    assert "--provider" not in "\n".join(said)


def test_a_SHIPPED_kind_cannot_claim_a_foreign_host(stranger):
    """The other direction of the claim. This build knows GitHub's hosts, so `--provider
    github` on a GitLab URL is the label-that-does-not-stay-put reopened by flag — measured
    2026-08-26: the first version let any KNOWN kind claim, and the URL was written as a GitHub
    row. Only a kind an add-on brought claims a host, because only its host is unknowable."""
    from openfactory.cli import _foreign_host

    url = "https://gitlab.com/acme/widgets.git"
    assert _foreign_host(url, provider="github") == "gitlab.com"
    assert _foreign_host(url, provider="azure_devops") == "gitlab.com"
    assert _foreign_host(url, provider="acme") == ""


def test_a_shipped_kind_on_ITS_OWN_host_is_not_foreign():
    from openfactory.cli import _foreign_host

    assert _foreign_host("https://github.com/acme/widgets.git", provider="github") == ""
    assert _foreign_host("https://dev.azure.com/org/proj/_git/repo",
                         provider="azure_devops") == ""


def test_a_shipped_kind_named_over_ANOTHER_shipped_kind_s_host_is_refused_by_name():
    """`--provider azure_devops` on a github.com URL wrote an Azure row with `owner/name` for a
    repository and no organisation — refused at pickup, hours later. Refused here, naming both
    kinds."""
    from openfactory.cli import _foreign_host

    with pytest.raises(ValueError) as e:
        _foreign_host("https://github.com/acme/widgets.git", provider="azure_devops")
    said = str(e.value)
    assert "github.com" in said and "'github'" in said and "'azure_devops'" in said, said
    with pytest.raises(ValueError, match="dev.azure.com"):
        _foreign_host("https://dev.azure.com/org/proj/_git/repo", provider="github")


def test_the_shipped_host_table_has_a_row_per_shipped_forge():
    """A shipped kind with no hosts here would be refused as foreign on its own host."""
    from openfactory.adapters.forge.registry import FORGES
    from openfactory.cli import _shipped_hosts

    assert set(_shipped_hosts()) == set(FORGES)


def test_project_init_with_a_shipped_provider_on_a_foreign_host_REGISTERS_NOTHING(
        stranger, tmp_path, monkeypatch):
    from openfactory.registry import ProjectRegistry

    said, code = _init(tmp_path, monkeypatch, "https://gitlab.com/o/r.git", provider="github")

    assert code == 2
    joined = "\n".join(said)
    assert "claims nothing" in joined and "github" in joined, joined
    with pytest.raises(KeyError):
        ProjectRegistry().get("acme-proj")

    said, code = _init(tmp_path, monkeypatch, "https://github.com/o/r.git",
                       provider="azure_devops")

    assert code == 2 and "azure_devops" in "\n".join(said), said
    with pytest.raises(KeyError):
        ProjectRegistry().get("acme-proj")


# ── 3. conformance: every port, both forms ──────────────────────────────────────────────────────

def test_every_check_row_carries_a_runtime_checkable_port():
    """The instance-versus-factory decision rests on `isinstance(target, Protocol)`; a row whose
    second element is not a runtime-checkable Protocol would make every target a factory."""
    from typing import runtime_checkable

    from openfactory.conformance import CHECKS

    for kind, (check, protocol) in CHECKS.items():
        assert callable(check), kind
        assert getattr(protocol, "_is_runtime_protocol", False), (
            f"CHECKS[{kind!r}] carries {protocol!r}, which is not a @runtime_checkable Protocol")
        assert runtime_checkable(protocol) is protocol


def test_the_check_table_covers_every_port_that_has_a_conformance_kind():
    from openfactory.conformance import CHECKS

    assert set(CHECKS) == {"channel", "notifier", "identity", "board", "tracker", "forge",
                           "harness", "ci", "box"}
    assert set(stranger_addon.CONFORMANCE_FORMS) == set(CHECKS), (
        "the stranger's package has no adapter for a conformance kind")


@pytest.mark.parametrize("kind", sorted(stranger_addon.CONFORMANCE_FORMS))
def test_the_cli_accepts_the_CLASS_form_for_every_kind(kind, stranger):
    from openfactory.cli import app

    cls, _ = stranger_addon.CONFORMANCE_FORMS[kind]
    result = CliRunner().invoke(app, ["conformance-adapter", kind, f"acme_addons:{cls}"])

    assert result.exit_code == 0, result.output
    assert "CONFORMANT" in result.output


@pytest.mark.parametrize("kind", sorted(stranger_addon.CONFORMANCE_FORMS))
def test_the_cli_accepts_a_zero_arg_FACTORY_FUNCTION_for_every_kind(kind, stranger):
    """The form the help text documented and nothing tested: today (2026-08-26) a tracker
    factory was judged the instance and reported seventeen methods missing."""
    from openfactory.cli import app

    _, factory = stranger_addon.CONFORMANCE_FORMS[kind]
    result = CliRunner().invoke(app, ["conformance-adapter", kind, f"acme_addons:{factory}"])

    assert result.exit_code == 0, result.output
    assert "CONFORMANT" in result.output


@pytest.mark.parametrize("kind", sorted(stranger_addon.HALF_FORMS))
def test_a_half_implemented_INSTANCE_is_refused_by_name_and_never_called(kind, stranger):
    """The form the help text lists first. The door once called any target that failed the
    port — `TypeError: 'HalfChannel' object is not callable`, measured 2026-08-26 — so for the
    exact input this command exists to judge no `<kind>.protocol` finding was reachable."""
    from openfactory.cli import app

    attr, lacks = stranger_addon.HALF_FORMS[kind]
    result = CliRunner().invoke(app, ["conformance-adapter", kind, f"acme_addons:{attr}"])

    assert result.exit_code == 1, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit), (
        repr(result.exception))
    assert "does not satisfy" in result.output and lacks in result.output, result.output
    assert "NOT CONFORMANT" in result.output


def test_an_instance_with_a_call_of_its_own_is_STILL_an_instance(stranger):
    """`callable(target)` is not the test — an object may define `__call__` and still be the
    adapter under judgement. The fixture's `__call__` raises, so a door that calls it is caught
    in the act rather than by a missing finding."""
    from openfactory.cli import app

    result = CliRunner().invoke(
        app, ["conformance-adapter", "channel", "acme_addons:half_callable_channel"])

    assert result.exit_code == 1, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit), (
        repr(result.exception))
    assert "does not satisfy" in result.output and "CALLED" not in result.output, result.output


def test_the_cli_help_lists_the_kinds_off_the_table():
    from openfactory.cli import app
    from openfactory.conformance import CHECKS

    result = CliRunner().invoke(app, ["conformance-adapter", "--help"])
    for kind in CHECKS:
        assert kind in result.output, f"{kind} missing from: {result.output}"


def test_a_forge_that_splices_its_token_into_a_foreign_host_is_caught():
    from openfactory.conformance import check_forge

    class _Leaky(stranger_addon_forge_base()):
        token = "secret"

        def authenticated_url(self, url):
            return url.replace("https://", "https://x:secret@", 1)

    rules = {f.rule for f in check_forge(_Leaky())}
    assert "forge.credential-stays-on-its-own-host" in rules


def stranger_addon_forge_base():
    """The stranger's forge class, loaded from source without the packaging machinery — a
    conformant base to break one rule on."""
    import types

    module = types.ModuleType("acme_addons_for_checks")
    exec(stranger_addon.SOURCE, module.__dict__)
    return module.AcmeForge


def test_a_harness_that_RAISES_instead_of_emitting_a_result_is_caught():
    """A shape-only check cannot fail this — lesson 3, a mock cannot fail an arity check. The
    check hands `execute` a recording box and asks for the result."""
    from openfactory.conformance import check_harness

    class _Raises:
        def execute(self, *, sandbox, workspace, context):
            raise RuntimeError("no CLI here")

        def repair(self, *, sandbox, workspace, context, failure_log):
            raise RuntimeError("no CLI here")

    class _Dict(_Raises):
        def execute(self, *, sandbox, workspace, context):
            return {"ok": True}

    assert {f.rule for f in check_harness(_Raises())} == {"harness.execute-emits-a-result"}
    assert {f.rule for f in check_harness(_Dict())} == {"harness.execute-emits-a-result"}


def test_an_observer_whose_health_check_cannot_fail_is_caught():
    from openfactory.conformance import check_observer

    class _Optimist:
        def ci_status(self, *, repo, ref):
            return []

        def deploy_status(self, *, env, ref):
            return "unknown"

        def health(self, *, url, timeout=10):
            return True

    assert {f.rule for f in check_observer(_Optimist())} == {"ci.health-is-not-optimistic"}


def test_the_box_check_starts_NOTHING():
    """The CLI promises nothing remote is created; a check that called `run()` or `prepare()`
    would start a container. Asserted on a box that records every call."""
    from openfactory.conformance import check_box

    box = stranger_addon_box()
    findings = check_box(box)

    assert findings == []
    assert box.ran == [] and box.prepared == []


def stranger_addon_box():
    import types

    module = types.ModuleType("acme_addons_for_checks")
    exec(stranger_addon.SOURCE, module.__dict__)

    class _Recording(module.AcmeBox):
        def __init__(self):
            super().__init__()
            self.prepared = []

        def prepare(self, **kw):
            self.prepared.append(kw)
            return super().prepare(**kw)

    return _Recording()


# ── 4. the worker starts one listener per DISTINCT channel kind ─────────────────────────────────

def test_the_worker_starts_the_listeners_of_EVERY_kind_the_registry_speaks(stranger,
                                                                            monkeypatch):
    """A Slack-coordinated project and an add-on project: both kinds' listeners start, once
    each. `build_channel()` with no project resolved to the panel, so neither ever did."""
    from vendor_addons import install, require

    from openfactory.runtime.temporal import worker

    require("channel.slack")
    add_ons.module("openfactory.runtime.slack.bot")
    started: list[str] = []
    monkeypatch.setattr("openfactory.runtime.slack.bot.start_listeners",
                        lambda: started.append("slack") or [])
    # the chat row is the add-on's now; the stranger's is served beside it, not instead of it
    install(monkeypatch, "channel.slack", extra=tuple(stranger_addon.points()))
    slack_a = Project(name="a", repo_path="/tmp/a", channel_id="C1")
    slack_b = Project(name="b", repo_path="/tmp/b", channel_id="C2")

    held = worker.start_channel_listeners([slack_a, _project(), slack_b])

    assert started == ["slack"], "Slack's listeners start once per deployment, not per project"
    assert stranger.STARTED == ["acme"]
    assert {type(h).__name__ for h in held} == {"SlackChannel", "AcmeChannel"}


def test_no_projects_at_all_still_gives_the_panel():
    """The surface that always exists — an empty registry is a panel-only deployment."""
    from openfactory.runtime.temporal import worker

    held = worker.start_channel_listeners([])

    assert [type(h).__name__ for h in held] == ["PanelChannel"]


def test_one_channel_that_cannot_start_is_a_LINE_not_a_dead_worker(caplog, monkeypatch):
    from vendor_addons import install, require

    from openfactory.runtime.temporal import worker

    require("channel.slack")
    add_ons.module("openfactory.runtime.slack.bot")
    install(monkeypatch, "channel.slack")
    monkeypatch.setattr("openfactory.runtime.slack.bot.start_listeners",
                        lambda: (_ for _ in ()).throw(RuntimeError("socket refused")))
    projects = [Project(name="a", repo_path="/tmp/a", channel_id="C1"),
                Project(name="p", repo_path="/tmp/p", channel="panel")]

    with caplog.at_level(logging.ERROR, logger="openfactory.worker"):
        held = worker.start_channel_listeners(projects)

    assert [type(h).__name__ for h in held] == ["PanelChannel"]
    assert any("'slack'" in r.getMessage() and "socket refused" in r.getMessage()
               for r in caplog.records), caplog.text


def test_the_worker_REACHES_the_registry_driven_start():
    """Reachability, read off `main`: the per-kind start is called, and the project-less
    `build_channel()` that silenced every listener for twenty days is gone."""
    from openfactory.runtime.temporal import worker

    tree = ast.parse(inspect.getsource(worker.main))
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "start_channel_listeners" in called
    assert "build_channel" not in called, "the deployment-wide build is back — it resolves to " \
                                          "the panel and no add-on (nor Slack) ever listens"


# ── 5. the notifier registry: an add-on speaks, a channel-only add-on is not a failure ──────────

def test_an_add_on_NOTIFIER_is_the_one_the_project_speaks_through(stranger):
    from openfactory.factory import notifier_for_project

    got = notifier_for_project(_project())

    assert type(got).__name__ == "AcmeNotifier"
    assert ("notifier", "acme") in stranger.BUILT


def test_a_channel_only_add_on_falls_back_to_the_PANEL_and_SAYS_SO(monkeypatch, caplog):
    """`ChannelAdapter.say` is a legitimate way to build a channel and stop; refusing would fail
    job start. The fallback is the panel — and a WARNING naming the kind, never silence."""
    from openfactory.adapters.notify.registry import build_notifier

    monkeypatch.delenv("OPENFACTORY_TELEGRAM_BOT_TOKEN", raising=False)
    plugins.reset_cache()
    monkeypatch.setattr("importlib.metadata.entry_points",
                        lambda group=None: [_point("channel.matrix", lambda **kw: object())]
                        if group == plugins.GROUP else [])
    monkeypatch.setattr(plugins, "_cache", None)

    with caplog.at_level(logging.WARNING, logger="openfactory.notify"):
        got = build_notifier(_project(channel="matrix"))

    assert type(got).__name__ == "PanelNotifier"
    record = next((r for r in caplog.records if "'matrix'" in r.getMessage()), None)
    assert record is not None, caplog.text
    assert "no notifier of its own" in record.getMessage()
    assert "PanelNotifier" in record.getMessage()


def test_a_kind_neither_axis_knows_NEVER_RAISES_here_and_is_named(monkeypatch, caplog):
    """`build_channel` refuses it by name at its own door; the notifier is called from scheduled
    rounds and activities with no try/except, so a raise here is a retry storm."""
    from openfactory.adapters.notify.registry import build_notifier

    monkeypatch.delenv("OPENFACTORY_TELEGRAM_BOT_TOKEN", raising=False)
    with caplog.at_level(logging.WARNING, logger="openfactory.notify"):
        got = build_notifier(_project(channel="carrier-pigeon"))

    assert type(got).__name__ == "PanelNotifier"
    record = next((r for r in caplog.records if "'carrier-pigeon'" in r.getMessage()), None)
    assert record is not None, caplog.text
    assert "neither the channel nor the notifier registry" in record.getMessage()


def test_an_add_on_that_hands_back_a_non_notifier_is_refused_and_named(monkeypatch, caplog):
    from openfactory.adapters.notify.registry import build_notifier

    monkeypatch.delenv("OPENFACTORY_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr("importlib.metadata.entry_points",
                        lambda group=None: [_point("notifier.matrix", lambda project: object())]
                        if group == plugins.GROUP else [])
    monkeypatch.setattr(plugins, "_cache", None)

    with caplog.at_level(logging.WARNING, logger="openfactory.notify"):
        got = build_notifier(_project(channel="matrix"))

    assert type(got).__name__ == "PanelNotifier"
    assert any("does not satisfy Notifier" in r.getMessage() for r in caplog.records), caplog.text


def test_a_shipped_row_that_cannot_post_SAYS_what_was_missing_and_where_speech_goes(
        monkeypatch, caplog):
    """Slack with no bot token became the panel with no line at all (measured 2026-08-26) —
    the silence the module docstring promised was gone. Now: the project, the kind, the
    variable that was missing, and the fallback taken."""
    from vendor_addons import install, require

    from openfactory.adapters.notify.registry import build_notifier

    require("notifier.slack")
    install(monkeypatch, "notifier.slack")
    monkeypatch.delenv("OPENFACTORY_NOTIFIER_FALLBACK", raising=False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    slack = Project(name="s", repo_path="/tmp/s", channel_id="C1")

    with caplog.at_level(logging.WARNING, logger="openfactory.notify"):
        got = build_notifier(slack)

    assert type(got).__name__ == "PanelNotifier"
    line = next((r.getMessage() for r in caplog.records if "'slack'" in r.getMessage()), None)
    assert line is not None, caplog.text
    assert "SLACK_BOT_TOKEN" in line and "PanelNotifier" in line and "project s" in line, line


def test_the_missing_piece_named_is_the_one_actually_missing(monkeypatch, caplog):
    """Token present and channel id absent names the channel id, not the token; a project that
    names its own token variable is told about THAT variable."""
    from vendor_addons import install, require

    from openfactory.adapters.notify.registry import build_notifier

    require("notifier.slack")
    install(monkeypatch, "notifier.slack")
    monkeypatch.delenv("OPENFACTORY_NOTIFIER_FALLBACK", raising=False)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-1")
    monkeypatch.delenv("ACME_SLACK", raising=False)

    with caplog.at_level(logging.WARNING, logger="openfactory.notify"):
        build_notifier(Project(name="no-channel", repo_path="/tmp/n", channel="slack"))
    line = next(r.getMessage() for r in caplog.records if "no-channel" in r.getMessage())
    assert "channel_id" in line and "SLACK_BOT_TOKEN" not in line, line

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="openfactory.notify"):
        build_notifier(Project(name="custom", repo_path="/tmp/c", channel_id="C1",
                               channel_options={"bot_token_env": "ACME_SLACK"}))
    line = next(r.getMessage() for r in caplog.records if "custom" in r.getMessage())
    assert "ACME_SLACK" in line and "channel_id" not in line, line


def test_a_row_that_CAN_post_takes_no_fallback_and_warns_of_nothing(monkeypatch, caplog):
    """The positive twin: a warning on every build would be the silence's mirror image."""
    from vendor_addons import install, require

    from openfactory.adapters.notify.registry import build_notifier

    require("notifier.slack")
    install(monkeypatch, "notifier.slack")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-1")
    with caplog.at_level(logging.WARNING, logger="openfactory.notify"):
        got = build_notifier(Project(name="s", repo_path="/tmp/s", channel_id="C1"))

    assert type(got).__name__ == "SlackNotifier"
    assert not [r for r in caplog.records if r.name == "openfactory.notify"], caplog.text


def test_the_fallback_NAMED_is_the_one_TAKEN(monkeypatch, caplog):
    """With the deployment-wide fallback DECLARED as Telegram and Telegram configured, the speech
    goes to Telegram, and the line says Telegram — a line that always said 'panel' would send the
    operator to the wrong screen."""
    from vendor_addons import install, require

    from openfactory.adapters.notify.registry import build_notifier

    require("notifier.slack", "notifier.telegram")
    install(monkeypatch, "notifier.slack", "notifier.telegram")
    monkeypatch.setenv("OPENFACTORY_NOTIFIER_FALLBACK", "telegram")
    monkeypatch.setenv("OPENFACTORY_TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("OPENFACTORY_TELEGRAM_CHAT_ID", "c")
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    with caplog.at_level(logging.WARNING, logger="openfactory.notify"):
        got = build_notifier(Project(name="s", repo_path="/tmp/s", channel_id="C1"))

    assert type(got).__name__ == "TelegramNotifier"
    line = next(r.getMessage() for r in caplog.records if "'slack'" in r.getMessage())
    assert "TelegramNotifier" in line and "PanelNotifier" not in line, line


def test_an_add_on_row_answering_None_is_named_too(monkeypatch, caplog):
    """The shorter contract — a bare `None` — still takes a fallback out loud, admitting that the
    row did not say what it lacked."""
    from openfactory.adapters.notify.registry import build_notifier

    monkeypatch.delenv("OPENFACTORY_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr("importlib.metadata.entry_points",
                        lambda group=None: [_point("notifier.matrix", lambda project: None)]
                        if group == plugins.GROUP else [])
    monkeypatch.setattr(plugins, "_cache", None)

    with caplog.at_level(logging.WARNING, logger="openfactory.notify"):
        got = build_notifier(_project(channel="matrix"))

    assert type(got).__name__ == "PanelNotifier"
    line = next((r.getMessage() for r in caplog.records if "'matrix'" in r.getMessage()), None)
    assert line is not None, caplog.text
    assert "did not name" in line and "PanelNotifier" in line, line


def test_the_shipped_rows_are_the_shipped_notifiers(monkeypatch):
    """The core's table is the panel alone (the chat rows are `openfactory-slack`'s since
    2026-08-26); with the package's rows installed the answers are the if-chain's: explicit
    panel → panel; Slack with a token and a channel id → Slack; Slack without a token → the
    fallback, never a raise."""
    from vendor_addons import install, require

    from openfactory.adapters.notify.registry import NOTIFIERS, build_notifier

    assert set(NOTIFIERS) == {"panel"}
    require("notifier.slack")
    install(monkeypatch, "notifier.slack")
    monkeypatch.delenv("OPENFACTORY_NOTIFIER_FALLBACK", raising=False)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-1")
    slack = Project(name="s", repo_path="/tmp/s", channel_id="C1")
    assert type(build_notifier(slack)).__name__ == "SlackNotifier"
    monkeypatch.delenv("SLACK_BOT_TOKEN")
    assert type(build_notifier(slack)).__name__ == "PanelNotifier"
    assert type(build_notifier(None)).__name__ == "NullNotifier"


def _point(name, value):
    class _P:
        def __init__(self):
            self.name = name

        def load(self):
            return value

    return _P()


# ── 6. the board: the lookup comes BEFORE the coordinates gate ──────────────────────────────────

def test_a_jira_shaped_add_on_board_is_built_WITHOUT_coordinates(stranger):
    """The absence-read-as-compliance the first draft kept: a stranger's board for a tracker with
    no board_owner/board_number answered None — tickets only — before its builder was asked."""
    from openfactory.adapters.board import build_board

    board = build_board(_project())

    assert type(board).__name__ == "AcmeBoard"
    assert ("board", "acme") in stranger.BUILT


def test_an_add_on_board_is_asked_WITH_coordinates_too(stranger):
    from openfactory.adapters.board import build_board

    p = _project(tracker=ProviderRef(kind="acme", repo="acme/repo",
                                     options={"board_owner": "o", "board_number": "3"}))
    board = build_board(p)

    assert type(board).__name__ == "AcmeBoard" and board.options["board_number"] == "3"


def test_a_kind_nobody_implements_is_tickets_only_WITHOUT_coordinates_and_refused_WITH(stranger):
    """The twin, both halves: an unknown kind with no board pointer is a legitimate tickets-only
    project; one that points at a board is refused, and the refusal lists the installed kind."""
    from openfactory.adapters.board import build_board

    assert build_board(_project(tracker=ProviderRef(kind="nosuch", repo="x"))) is None
    p = _project(tracker=ProviderRef(kind="nosuch", repo="x",
                                     options={"board_owner": "o", "board_number": "3"}))
    with pytest.raises(ValueError, match="no board provider") as e:
        build_board(p)
    assert "acme" in str(e.value) and "github" in str(e.value)


def test_BOARD_KINDS_is_the_table_s_projection():
    from openfactory.adapters.board import BOARD_KINDS, BOARDS

    assert BOARD_KINDS == tuple(BOARDS)
    assert set(BOARDS) == {"github", "jira", "azure_devops"}


def test_a_github_project_without_coordinates_is_still_tickets_only():
    """The gate moved into the GitHub row; it did not disappear."""
    from openfactory.adapters.board import build_board

    assert build_board(Project(name="g", repo_path="/tmp/g",
                               tracker=ProviderRef(kind="github", repo="o/r"))) is None


# ── 7. the CI observer: the loader, the remedy, and no borrowed credential ──────────────────────

def test_an_add_on_observer_is_built_WITHOUT_the_caller_s_credential(stranger):
    """Both call sites hand this axis the deployment's FORGE credential — a GitHub token on a
    GitHub deployment. The built-in Azure rows refuse it; an add-on gets None for the same reason:
    a credential only goes to the host that issued it, and this host is nobody's we know."""
    from openfactory.adapters.environment.registry import build_observer

    built = build_observer(_project(), token="ghs_the_deployments_github_token")

    assert type(built).__name__ == "AcmeObserver"
    assert built.token is None


def test_a_built_in_observer_still_receives_the_credential_it_takes():
    """The twin: GitHub Actions IS the system the deployment's token is for."""
    from openfactory.adapters.environment.registry import build_observer

    p = Project(name="g", repo_path="/tmp/g", forge=ProviderRef(kind="github", repo="o/r"))
    assert build_observer(p, token="ghs_x").token == "ghs_x"


def test_a_forge_add_on_with_no_CI_of_its_own_is_refused_NAMING_the_option(monkeypatch):
    """The kind was inherited from the forge; the operator's two ways out are named — install
    the `ci.<kind>` add-on, or set `forge.options.ci`. "unknown CI 'gitea'" alone sent them to
    the forge registry, where everything was fine."""
    from openfactory.adapters.environment.registry import build_observer

    monkeypatch.setattr("importlib.metadata.entry_points",
                        lambda group=None: [_point("forge.gitea", lambda *a, **kw: object())]
                        if group == plugins.GROUP else [])
    monkeypatch.setattr(plugins, "_cache", None)
    p = Project(name="g", repo_path="/tmp/g", forge=ProviderRef(kind="gitea", repo="o/r"))

    with pytest.raises(ValueError, match="unknown CI 'gitea'") as e:
        build_observer(p)
    text = str(e.value)
    assert "inherited from the forge kind" in text
    assert "`forge.options.ci`" in text and "`ci.gitea`" in text


def test_an_explicit_ci_that_nobody_implements_says_it_was_NAMED():
    from openfactory.adapters.environment.registry import build_observer

    p = Project(name="g", repo_path="/tmp/g",
                forge=ProviderRef(kind="github", repo="o/r", options={"ci": "jenkins"}))
    with pytest.raises(ValueError, match="named by `forge.options.ci`"):
        build_observer(p)


# ── 8. identity: the loader, and fail-closed on what an add-on hands back ───────────────────────

def test_an_add_on_identity_is_the_deployment_s_provider(stranger):
    from openfactory.identity.registry import build_identity

    provider = build_identity({"OPENFACTORY_IDENTITY": "acme"})

    assert type(provider).__name__ == "AcmeIdentity"
    assert provider.identify(credential="", via="test") is None
    assert provider.identify(credential="acme-token", via="test").id == "acme-user"


def test_an_add_on_that_is_not_an_identity_provider_is_REFUSED_not_used(monkeypatch):
    """Fail closed: the panel gate dispatches through `identify`; a provider without one would
    fail at the door, hours later, as an AttributeError."""
    from openfactory.identity.registry import build_identity

    # `saml`, not `oidc`: since #33 `oidc` is a built-in row, and a built-in wins a collision —
    # an add-on under that name would never be the object built here.
    monkeypatch.setattr("importlib.metadata.entry_points",
                        lambda group=None: [_point("identity.saml", lambda: object())]
                        if group == plugins.GROUP else [])
    monkeypatch.setattr(plugins, "_cache", None)

    with pytest.raises(TypeError, match="does not satisfy IdentityProvider"):
        build_identity({"OPENFACTORY_IDENTITY": "saml"})


def test_an_unknown_identity_still_RAISES_listing_the_installed_kind(stranger):
    from openfactory.identity.registry import build_identity

    with pytest.raises(ValueError, match="unknown identity provider 'entraid'") as e:
        build_identity({"OPENFACTORY_IDENTITY": "entraid"})
    assert "acme" in str(e.value) and "local" in str(e.value)


def test_a_row_whose_builder_RAISES_is_a_line_and_a_fallback_never_an_exception(monkeypatch, caplog):
    """The module's contract is "never raises", and a row is code we did not write. The
    reviewer's cut (2026-08-26): a builder that raised propagated straight out of build_notifier
    — one add-on's bug, and every scheduled round that speaks would retry it for ever."""
    from openfactory.adapters.notify.registry import build_notifier

    def broken(project):
        raise RuntimeError("the vendor SDK is not installed")

    monkeypatch.delenv("OPENFACTORY_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr("importlib.metadata.entry_points",
                        lambda group=None: [_point("notifier.matrix", broken)]
                        if group == plugins.GROUP else [])
    monkeypatch.setattr(plugins, "_cache", None)

    with caplog.at_level(logging.WARNING, logger="openfactory.notify"):
        got = build_notifier(_project(channel="matrix"))

    assert type(got).__name__ == "PanelNotifier"
    line = next((r.getMessage() for r in caplog.records if "'matrix'" in r.getMessage()), "")
    assert "RuntimeError" in line and "not installed" in line, caplog.text
