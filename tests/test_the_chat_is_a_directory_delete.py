"""The chat is a directory delete: the chat connectors are an add-on the core never imports.

THE DOCTRINE (owner, 2026-08-24/26): the public repository is the core; the chat connectors leave
with `openfactory-slack`, the cloud with `openfactory-aws`, and both are installed from outside
through the `openfactory.adapters` entry-point group. The doctrine agent measured the gap on
2026-08-26: the cloud side was a directory delete and the chat side was not — `slack` was a
built-in row of `adapters/channel/registry.py` and `slack`/`telegram` of
`adapters/notify/registry.py`, each importing its module lazily inside the row, so with the
modules absent `channel: slack` raised a `ModuleNotFoundError` out of the row instead of being
refused by name.

THE PROOF IS THE DELETE, again: with the four chat paths removed from a scratch export of this
tree, ruff and the gate are green and `build_channel(project(channel="slack"))` refuses by name —
the experiment is recorded in the commit that added this file. What this file pins is what made
that true, each piece by behaviour and with a positive twin:

  · no module that stays imports a chat module, however the import is spelled;
  · the two tables hold `panel` and nothing else;
  · a project declaring `channel: slack` — or carrying a `channel_id` — on a deployment without
    the package is refused BY NAME, and the sentence names the package to install; a kind
    nobody publishes is refused without a package; with the row installed the adapter is built;
  · the notifier degrades to the panel with one WARNING naming the package;
  · the deployment-wide fallback is DECLARED (`OPENFACTORY_NOTIFIER_FALLBACK`), built as a row,
    and never inferred from a vendor's variables — which the core no longer reads at all;
  · the hint table names a package for exactly the rows the platform's own packages declare,
    and the packages' overlays carry exactly the paths `docs/STATUS.md` assigns to them.
"""

from __future__ import annotations

import ast
import logging
import pathlib

import add_ons
import pytest
from vendor_addons import Point, declared, declared_by, install, packages, require

from openfactory import plugins
from openfactory.adapters.channel.registry import CHANNELS, build_channel, refusal
from openfactory.adapters.notify.registry import FALLBACK_ENV, NOTIFIERS, build_notifier
from openfactory.contracts.project import Project

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The paths that ARE the chat connector. Everything else under `openfactory/` is the core.
CHAT_PATHS = (
    "openfactory/runtime/slack/",
    "openfactory/adapters/channel/slack.py",
    "openfactory/adapters/notify/slack.py",
    "openfactory/adapters/notify/telegram.py",
)
CHAT_MODULES = (
    "openfactory.runtime.slack",
    "openfactory.adapters.channel.slack",
    "openfactory.adapters.notify.slack",
    "openfactory.adapters.notify.telegram",
)
#: The two variables only the Telegram row may read.
TELEGRAM_VARIABLES = ("OPENFACTORY_TELEGRAM_BOT_TOKEN", "OPENFACTORY_TELEGRAM_CHAT_ID")


def _names_chat(module: str) -> bool:
    return any(module == m or module.startswith(m + ".") for m in CHAT_MODULES)


def _static_text(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(_static_text(v) for v in node.values if isinstance(v, ast.Constant))
    return ""


def imports_of_chat(tree: ast.AST) -> list[str]:
    """Every way a module can reach a chat module: `import a.b`, `from a.b import c`, and
    `importlib.import_module("a.b")` / `__import__("a.b")` with a literal — at any depth,
    lazily inside a function included."""
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            hits += [a.name for a in node.names if _names_chat(a.name)]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            if _names_chat(node.module):
                hits.append(node.module)
            hits += [f"{node.module}.{a.name}" for a in node.names
                     if _names_chat(f"{node.module}.{a.name}")]
        elif isinstance(node, ast.Call):
            callee = node.func
            name = (callee.attr if isinstance(callee, ast.Attribute)
                    else callee.id if isinstance(callee, ast.Name) else "")
            if name in ("import_module", "__import__") and node.args:
                target = _static_text(node.args[0])
                if _names_chat(target):
                    hits.append(target)
    return hits


def _core_sources() -> list[pathlib.Path]:
    return [p for p in sorted(ROOT.joinpath("openfactory").rglob("*.py"))
            if not any(p.relative_to(ROOT).as_posix().startswith(c) for c in CHAT_PATHS)]


# ── 1. the import graph: the core never names the chat connector ────────────────────────────────

def test_the_sweep_walks_the_core():
    assert len(_core_sources()) > 100, "the sweep found almost nothing — it is walking the wrong tree"


def test_no_core_module_imports_the_chat_connector():
    """The registries held the rows until 2026-08-26 — lazily, inside the builders — and this
    sweep sees a lazy import as well as a module-level one."""
    offenders = {}
    for path in _core_sources():
        hits = imports_of_chat(ast.parse(path.read_text()))
        if hits:
            offenders[path.relative_to(ROOT).as_posix()] = sorted(set(hits))
    assert not offenders, (
        "modules that stay in the public tree import the chat connector by name — the export "
        f"would break them or, in a registry row, raise instead of refusing: {offenders}")


@pytest.mark.parametrize("spelling", [
    "import openfactory.runtime.slack.bot",
    "from openfactory.runtime.slack import bot",
    "from openfactory.adapters.channel.slack import SlackChannel",
    "from openfactory.adapters.notify import telegram",
    "def f():\n    from openfactory.adapters.notify.slack import SlackNotifier",
    "import importlib\nimportlib.import_module('openfactory.runtime.slack.people')",
    "__import__('openfactory.adapters.notify.telegram')",
])
def test_the_sweep_sees_the_connector_however_it_is_spelled(spelling):
    assert imports_of_chat(ast.parse(spelling)), spelling


@pytest.mark.parametrize("spelling", [
    "from openfactory.adapters.notify.registry import build_notifier",
    "from openfactory.adapters.channel import panel",
    "import openfactory.runtime.temporal.worker",
    "importlib.import_module(name)",
])
def test_the_sweep_ignores_the_core_importing_itself(spelling):
    assert not imports_of_chat(ast.parse(spelling)), spelling


# ── 2. the tables ───────────────────────────────────────────────────────────────────────────────

def test_the_two_tables_hold_the_panel_and_nothing_else():
    assert set(CHANNELS) == {"panel"}
    assert set(NOTIFIERS) == {"panel"}


# ── 3. refused by name, naming the package ──────────────────────────────────────────────────────

@pytest.fixture
def nothing_installed(monkeypatch):
    install(monkeypatch, declared_rows=False)


@pytest.mark.parametrize("project", [
    Project(name="declared", repo_path="/tmp/d", channel="slack"),
    Project(name="coordinates", repo_path="/tmp/c", channel_id="C0"),
], ids=["channel: slack", "channel_id only"])
def test_a_chat_project_on_a_core_without_the_package_is_refused_naming_the_package(
        nothing_installed, project):
    with pytest.raises(ValueError) as err:
        build_channel(project)
    message = str(err.value)
    assert "'slack'" in message and "panel" in message, message
    assert plugins.install_hint("channel", "slack") in message, message
    assert "openfactory-slack" in message, message
    assert "ModuleNotFoundError" not in message


def test_a_kind_nobody_publishes_is_refused_without_a_package(nothing_installed):
    """The negative twin of the hint: a stranger's typo is not sent to install our package."""
    with pytest.raises(ValueError) as err:
        build_channel(Project(name="m", repo_path="/tmp/m", channel="matrix"))
    message = str(err.value)
    assert "'matrix'" in message and "panel" in message
    assert not [p for p in set(plugins.SHIPS_IN.values()) if p in message], message


def test_with_the_row_installed_the_chat_channel_is_built(monkeypatch):
    """The positive twin: the same project, the package's row served, the adapter arrives."""
    require("channel.slack")
    add_ons.module("openfactory.adapters.channel.slack")
    install(monkeypatch, "channel.slack")
    assert type(build_channel(Project(name="d", repo_path="/tmp/d", channel="slack"))).__name__ == "SlackChannel"
    assert type(build_channel(Project(name="c", repo_path="/tmp/c", channel_id="C0"))).__name__ == "SlackChannel"


def test_the_refusal_sentence_is_one_function_and_the_worker_uses_it(nothing_installed, caplog):
    """The worker's listener start refuses with the same words as `build_channel`: a project
    with chat coordinates on a core without the package is one ERROR line naming the package,
    and the panel is still held.

    AND THE REMEDY SURVIVES THE LOG LINE. The worker bounds the reason it prints; the remedy is
    the tail of that sentence, so a fixed slice kept the complaint and dropped the fix — which is
    the whole message being useless in the one place an operator reads it (found 2026-08-26, when
    the hint grew past the cut). `worker._readable` cuts at a sentence end for that reason."""
    from openfactory.runtime.temporal import worker

    with caplog.at_level(logging.ERROR, logger="openfactory.worker"):
        held = worker.start_channel_listeners([
            Project(name="a", repo_path="/tmp/a", channel_id="C1"),
            Project(name="p", repo_path="/tmp/p", channel="panel")])
    assert [type(h).__name__ for h in held] == ["PanelChannel"]
    line = next((r.getMessage() for r in caplog.records if "'slack'" in r.getMessage()), None)
    assert line is not None, caplog.text
    assert "openfactory-slack" in line, line
    assert refusal("slack").split(". ")[0] in line, line
    assert plugins.install_hint("channel", "slack") in line, (
        "the operator's log line names the kind and not what to do about it", line)


def test_a_reason_that_is_not_a_sentence_is_still_bounded():
    """The negative twin of that cut: `_readable` may not become "print anything, at any length".
    A stranger's adapter can raise a page of text, and a log line is not a place for it."""
    from openfactory.runtime.temporal import worker

    assert worker._readable(ValueError("short")) == "short"
    assert len(worker._readable(ValueError("x" * 5000))) == 200
    assert worker._readable(ValueError("y" * 2000 + ". tail")) == "y" * 200, (
        "a first 'sentence' longer than any human message is not kept whole")
    kept = worker._readable(ValueError("the refusal names the kind and its remedy at length, "
                                       + "w" * 300 + ". And then the boilerplate tail."))
    assert kept.endswith(".") and "w" * 300 in kept, kept


# ── 4. the hint table ───────────────────────────────────────────────────────────────────────────

def test_the_hint_names_the_package_for_the_platforms_own_rows_and_nothing_for_a_strangers():
    assert "openfactory-slack" in plugins.install_hint("channel", "slack")
    telegram = plugins.install_hint("notifier", "telegram")
    assert "openfactory-slack" in telegram and "notifier.telegram" in telegram, telegram
    assert "openfactory-aws" in plugins.install_hint("box_runner", "fargate")
    assert plugins.install_hint("channel", "matrix") == ""
    assert plugins.install_hint("forge", "slack") == "", "the hint is by axis AND kind"


def test_every_hint_key_is_an_axis_the_loader_publishes_and_a_kind():
    for key in plugins.SHIPS_IN:
        axis, _, kind = key.partition(".")
        assert axis in plugins.AXES, f"{key}: {axis!r} is not a published axis"
        assert kind and "." not in kind, f"{key}: not `<axis>.<kind>`"


def test_the_hint_table_is_exactly_the_rows_the_packages_declare_each_under_its_own_package():
    """Both directions, and the owner too: a hint for a row nobody declares sends the operator
    to install a package that will not help; a declared row with no hint is refused without a
    remedy; a hint naming the wrong package is the worse of the two."""
    require()
    owners = {point: name for name, package_dir in packages().items()
              for point in declared_by(package_dir)}
    assert set(plugins.SHIPS_IN) == set(owners), (
        f"hinted but undeclared: {sorted(set(plugins.SHIPS_IN) - set(owners))}; declared but "
        f"unhinted: {sorted(set(owners) - set(plugins.SHIPS_IN))}")
    wrong = {k: (v, owners[k]) for k, v in plugins.SHIPS_IN.items() if v != owners[k]}
    assert not wrong, f"hint names the wrong package (hinted, declared): {wrong}"


def test_the_packages_named_are_the_ones_STATUS_names():
    require()
    from_status = {p for p in add_ons.excluded_paths().values() if p}
    assert set(plugins.SHIPS_IN.values()) == from_status == set(packages()), (
        f"plugins.SHIPS_IN names {sorted(set(plugins.SHIPS_IN.values()))}, docs/STATUS.md names "
        f"{sorted(from_status)}, addons/ holds {sorted(packages())}")


def test_every_declared_row_of_the_chat_package_resolves_to_a_callable():
    require("channel.slack", "notifier.slack", "notifier.telegram")
    for name in ("channel.slack", "notifier.slack", "notifier.telegram"):
        assert callable(Point(name, declared()[name]).load()), name


# ── 5. the overlays carry what STATUS says leaves ───────────────────────────────────────────────

def test_each_packages_overlay_is_exactly_the_python_paths_STATUS_assigns_to_it():
    """The packages' `[tool.openfactory-addon] overlay` lists are what the wheel carries; STATUS's
    table is the one place the excluded paths are written. Held equal per package, restricted to
    paths under `openfactory/` (the terraform and the two documents leave with `openfactory-aws`
    and are not Python)."""
    import tomllib

    require()
    by_package: dict[str, set[str]] = {}
    for path, package in add_ons.excluded_paths().items():
        if package and path.startswith("openfactory/"):
            by_package.setdefault(package, set()).add(path)
    for name, package_dir in packages().items():
        data = tomllib.loads((package_dir / "pyproject.toml").read_text())
        overlay = set(data["tool"]["openfactory-addon"]["overlay"])
        assert overlay == by_package.get(name, set()), (
            f"{name} carries {sorted(overlay)}; docs/STATUS.md assigns it "
            f"{sorted(by_package.get(name, set()))}")
        for rel in overlay:
            assert (ROOT / rel).exists(), f"{name} carries {rel}, which is not in this tree"


# ── 6. the notifier degrades out loud, naming the package ───────────────────────────────────────

def test_a_chat_project_without_the_package_speaks_through_the_panel_and_the_warning_names_it(
        nothing_installed, caplog, monkeypatch):
    monkeypatch.delenv(FALLBACK_ENV, raising=False)
    with caplog.at_level(logging.WARNING, logger="openfactory.notify"):
        got = build_notifier(Project(name="coords", repo_path="/tmp/c", channel_id="C0"))
    assert type(got).__name__ == "PanelNotifier"
    line = next((r.getMessage() for r in caplog.records if "'slack'" in r.getMessage()), None)
    assert line is not None, caplog.text
    assert "openfactory-slack" in line and "PanelNotifier" in line and "coords" in line, line


# ── 7. the deployment-wide fallback is declared, and built as a row ─────────────────────────────

class _Speaks:
    """A stranger's notifier row, so the fallback is proven on the AXIS and not on one vendor."""

    def notify(self, *, message, level="info", about=""):
        return None


def _point(name, builder):
    class _P:
        def __init__(self):
            self.name = name

        def load(self):
            return builder

    return _P()


def test_a_declared_fallback_is_the_row_it_names_for_an_inferred_panel_project(monkeypatch):
    install(monkeypatch, declared_rows=False, extra=(_point("notifier.pager", lambda p: _Speaks()),))
    monkeypatch.setenv(FALLBACK_ENV, "pager")
    inferred = Project(name="x", repo_path="/tmp/x")  # no channel, no coordinates
    assert isinstance(build_notifier(inferred), _Speaks)
    assert isinstance(build_notifier(None), _Speaks), "the project-less caller gets it too"


def test_an_explicit_panel_is_not_overruled_by_the_declared_fallback(monkeypatch):
    install(monkeypatch, declared_rows=False, extra=(_point("notifier.pager", lambda p: _Speaks()),))
    monkeypatch.setenv(FALLBACK_ENV, "pager")
    assert type(build_notifier(Project(name="p", repo_path="/tmp/p", channel="panel"))).__name__ == "PanelNotifier"


def test_no_declared_fallback_means_the_panel_with_no_warning(nothing_installed, monkeypatch, caplog):
    """The positive twin of every warning below: the default deployment is not nagged."""
    monkeypatch.delenv(FALLBACK_ENV, raising=False)
    with caplog.at_level(logging.WARNING, logger="openfactory.notify"):
        got = build_notifier(Project(name="x", repo_path="/tmp/x"))
    assert type(got).__name__ == "PanelNotifier"
    assert not [r for r in caplog.records if r.name == "openfactory.notify"], caplog.text


def test_a_declared_fallback_nobody_installed_is_a_warning_naming_the_package(
        nothing_installed, monkeypatch, caplog):
    monkeypatch.setenv(FALLBACK_ENV, "telegram")
    with caplog.at_level(logging.WARNING, logger="openfactory.notify"):
        got = build_notifier(Project(name="x", repo_path="/tmp/x"))
    assert type(got).__name__ == "PanelNotifier"
    line = next((r.getMessage() for r in caplog.records if FALLBACK_ENV in r.getMessage()), None)
    assert line is not None, caplog.text
    assert "'telegram'" in line and "openfactory-slack" in line, line


def test_a_declared_fallback_whose_row_cannot_post_says_what_it_lacked(monkeypatch, caplog):
    from openfactory.adapters.notify.registry import CannotPost

    install(monkeypatch, declared_rows=False,
            extra=(_point("notifier.pager", lambda p: CannotPost(("the PAGER_KEY variable",))),))
    monkeypatch.setenv(FALLBACK_ENV, "pager")
    with caplog.at_level(logging.WARNING, logger="openfactory.notify"):
        got = build_notifier(Project(name="x", repo_path="/tmp/x"))
    assert type(got).__name__ == "PanelNotifier"
    line = next((r.getMessage() for r in caplog.records if FALLBACK_ENV in r.getMessage()), None)
    assert line is not None, caplog.text
    assert "PAGER_KEY" in line and "'pager'" in line, line


def test_the_fallback_is_taken_when_a_projects_own_row_cannot_post(monkeypatch):
    """A project whose row lacks its coordinates falls to the DECLARED fallback, not the panel."""
    from openfactory.adapters.notify.registry import CannotPost

    install(monkeypatch, declared_rows=False,
            extra=(_point("notifier.pager", lambda p: _Speaks()),
                   _point("notifier.chat", lambda p: CannotPost(("the CHAT_TOKEN variable",))),
                   _point("channel.chat", lambda **kw: object())))
    monkeypatch.setenv(FALLBACK_ENV, "pager")
    assert isinstance(build_notifier(Project(name="c", repo_path="/tmp/c", channel="chat")), _Speaks)


# ── 8. the core reads no Telegram variable ──────────────────────────────────────────────────────

def _string_constants(path: pathlib.Path) -> set[str]:
    return {n.value for n in ast.walk(ast.parse(path.read_text()))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def test_no_core_module_names_a_telegram_variable():
    """The Telegram row switched itself on from two variables the CORE read — the inference the
    cloud cut removed from the box axis, on the notifier axis. The variables are the row's now."""
    offenders = [p.relative_to(ROOT).as_posix() for p in _core_sources()
                 if _string_constants(p) & set(TELEGRAM_VARIABLES)]
    assert not offenders, f"core modules still name a Telegram variable: {offenders}"


def test_the_telegram_row_is_the_one_that_reads_them():
    """The positive twin: the variables are read, by the row, or the scan above is watching a
    vocabulary that left with nothing reading it."""
    path = add_ons.source("openfactory/adapters/notify/telegram.py")
    assert set(TELEGRAM_VARIABLES) <= _string_constants(path)


# ── 9. the cloud's refusals name their package too ──────────────────────────────────────────────

def test_the_cloud_rows_are_refused_naming_their_package(nothing_installed, monkeypatch):
    """The same hint at the four cloud doors: the box runner, the metrics sink, the session
    store and the token-pool source each refuse the kind by name AND carry the platform's own
    remedy for it — the cloud cut refused naming the entry point alone. The expected clause is
    `install_hint`'s own answer, so the wording lives in one place and this guard follows it."""
    from openfactory.adapters.agent.session_store import build_session_store
    from openfactory.adapters.agent.token_pool import token_pool
    from openfactory.adapters.sandbox.registry import remote_box
    from openfactory.observability.registry import build_metrics_sink

    monkeypatch.delenv("OPENFACTORY_TOKEN_POOL_SOURCE", raising=False)
    for door, axis, kind in ((remote_box, "box_runner", "fargate"),
                             (build_metrics_sink, "metrics", "dynamodb"),
                             (build_session_store, "session_store", "s3"),
                             (token_pool, "token_pool", "ssm")):
        with pytest.raises((ValueError, RuntimeError)) as err:
            door(kind)
        assert plugins.install_hint(axis, kind) in str(err.value), (door.__name__, str(err.value))
        assert "openfactory-aws" in str(err.value) and "openfactory-slack" not in str(err.value)
    with pytest.raises(ValueError) as err:
        build_session_store("minio")
    assert not [p for p in set(plugins.SHIPS_IN.values()) if p in str(err.value)], (
        "a stranger's kind is sent to one of our packages")
