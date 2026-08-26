"""`openfactory init` writes an add-on channel's variables by asking the ROW, never by spelling them.

THE LAST VENDOR VARIABLE IN THE CORE (review of the chat cut, 2026-08-26). After the chat rows
left for their package, `onboarding/deployment.py` still rendered `if answers.channel == "slack":`
with the two chat variables written out — reached only when that package's row is installed, and
still the core spelling a vendor's variable. The fix is a contract, not a rename: a row may declare
what it reads (`builder.environment`, derived by the row from its own modules with the core's AST
scan — `environ.names_read` — the way the core derives its own reservations), the renderer asks
the installed row (`plugins.environment`), and the core's text carries no name it does not read.

Held from both sides: the renderer's SOURCE mentions no variable the public core does not read
(the negative, which sees a hard-coded name whatever the installed rows are), and a stranger's
declared variable is rendered as a row with its own comment (the positive twin).
"""

from __future__ import annotations

import ast
import pathlib
import re
import shutil

import add_ons
import pytest
import stranger_addon
from vendor_addons import install, require

from openfactory import environ, plugins
from openfactory.onboarding.deployment import Answers, render

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "openfactory" / "onboarding" / "deployment.py"
COMPOSE = ROOT / "docker-compose.yml"

ENV_TOKEN = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")


@pytest.fixture
def stranger(tmp_path, monkeypatch):
    return stranger_addon.installed(tmp_path, monkeypatch)


def _public_core(tmp_path: pathlib.Path) -> pathlib.Path:
    """The core as the export ships it: `openfactory/` minus the paths STATUS excludes — the
    tree `names_read` is asked about, so a name only a leaving module reads is not 'read by the
    core' here even while the private tree still holds that module."""
    excluded = add_ons.excluded_paths()
    target = tmp_path / "public" / "openfactory"
    for path in sorted((ROOT / "openfactory").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in excluded):
            continue
        dest = target / path.relative_to(ROOT / "openfactory")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, dest)
    return target


def _published_ports() -> set[str]:
    """The names the compose file substitutes in its `ports:` entries — read by no Python, written
    by the renderer as rows. ONLY those: the first version allowed every `${NAME}` the compose
    file substitutes, and the file also forwards the chat package's two variables into the
    worker, so a renderer spelling them again walked through (mutation, 2026-08-26)."""
    import yaml

    services = yaml.safe_load(COMPOSE.read_text())["services"].values()
    names: set[str] = set()
    for service in services:
        for entry in service.get("ports") or []:
            names |= set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", str(entry)))
    return names


def _rows(text: str) -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, re.M))


# ── the negative: the core's text spells no variable the core does not read ─────────────────────

def test_the_renderer_spells_no_variable_the_public_core_does_not_read(tmp_path):
    tree = ast.parse(MODULE.read_text())
    mentioned: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            mentioned |= set(ENV_TOKEN.findall(node.value))
    own = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    # A MODULE-LEVEL NAME EXCUSES ITSELF ONLY WHEN IT DOES NOT HOLD A STRING. The reviewer's cut
    # (2026-08-26) — `SLACK_BOT_TOKEN = "SLACK_BOT_TOKEN"` at module level, rendered through an
    # f-string — walked through the first version, which excused every assigned name. A constant
    # holding a tuple or a dict is the module's own vocabulary; a constant holding a variable's
    # name IS that variable, mentioned.
    own |= {t.id for n in tree.body if isinstance(n, ast.Assign)
            and not (isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))
            for t in n.targets if isinstance(t, ast.Name)}
    allowed = environ.names_read(_public_core(tmp_path)) | _published_ports() | own
    stray = sorted(mentioned - allowed)
    assert not stray, (
        f"openfactory/onboarding/deployment.py spells variables the public core reads nowhere — "
        f"a package's variables belong to its row (`plugins.environment`): {stray}")
    assert len(mentioned & allowed) >= 8, "the sweep found almost no variable — wrong regex"


def test_the_port_allowance_is_the_published_ports_and_nothing_the_worker_forwards():
    ports = _published_ports()
    assert ports and all(name.endswith("_PORT") for name in ports), sorted(ports)
    forwarded = set()
    import yaml

    for service in yaml.safe_load(COMPOSE.read_text())["services"].values():
        forwarded |= set((service.get("environment") or {}).keys()) if isinstance(
            service.get("environment"), dict) else set()
    assert forwarded and not (ports & forwarded), sorted(ports & forwarded)


def test_the_public_core_derivation_drops_what_only_a_leaving_module_reads(tmp_path):
    """Verify the verifier: the scratch core reads the panel token, and a variable that ONLY an
    excluded module reads is not in the set — here or in the export, where the module is gone."""
    read = environ.names_read(_public_core(tmp_path))
    assert "OPENFACTORY_PANEL_TOKEN" in read
    excluded_only = set()
    for rel in add_ons.excluded_paths():
        path = ROOT / rel
        if rel.startswith("openfactory/") and path.exists():
            excluded_only |= environ.names_read(path)
    excluded_only -= read
    if not add_ons.is_public_tree():
        assert excluded_only, "no excluded module reads a name of its own — the twin has no subject"
    assert not (excluded_only & read)


def test_with_only_the_panel_row_the_rendered_file_names_no_add_on_variable(monkeypatch, tmp_path):
    install(monkeypatch, declared_rows=False)
    rows = _rows(render(Answers(channel="panel")).text)
    allowed = environ.names_read(_public_core(tmp_path)) | _published_ports()
    assert rows and rows <= allowed, sorted(rows - allowed)


# ── the positive twin: a row's declared variables are rendered, with its own comment ────────────

def test_a_strangers_declared_variable_is_a_row_and_a_to_do(stranger):
    out = render(Answers(channel="acme"))
    assert "ACME_CHAT_TOKEN" in _rows(out.text)
    # EXACTLY the declaration, not a superset: a renderer spelling one more row beside the
    # declared ones passed `>=` (the reviewer's cut, 2026-08-26).
    assert _rows(out.text) - _rows(render(Answers(channel="panel")).text) == {"ACME_CHAT_TOKEN"}
    assert "Acme workspace's admin console" in out.text, "the row's own how-to is the comment"
    assert "an add-on this generator carries no rows for" not in out.text
    line = next(ln for ln in out.remaining if "ACME_CHAT_TOKEN" in ln)
    assert "`openfactory doctor`" in line and "`acme`" in line


def test_a_row_that_declares_nothing_gets_the_generic_section(stranger, monkeypatch):
    monkeypatch.delattr(stranger.build_channel, "environment")
    out = render(Answers(channel="acme"))
    assert "ACME_CHAT_TOKEN" not in out.text
    assert "an add-on this generator carries no rows for" in out.text


@pytest.mark.parametrize("declared, expected", [
    (("A_B", "C_D"), ("A_B", "C_D")),
    (lambda: ["E_F"], ("E_F",)),
    (None, ()),
])
def test_the_contract_accepts_a_tuple_or_a_callable_and_answers_nothing_for_nothing(declared, expected):
    def builder(**kw):
        return None

    if declared is not None:
        builder.environment = declared
    assert plugins.environment(builder) == expected
    assert plugins.environment(None) == ()
    assert plugins.how_to(builder) == ""


# ── the chat package's row derives its answer from its own modules ──────────────────────────────

def test_the_chat_rows_declaration_is_what_its_modules_read(monkeypatch):
    """Two names, derived — held to the AST scan of the modules that leave with the package, minus
    the platform's own prefix. Skips by name in the export, where the modules are gone."""
    from openfactory.adapters.channel.registry import AXIS, CHANNELS

    require("channel.slack")
    install(monkeypatch, "channel.slack")
    names = plugins.environment(plugins.builder(AXIS, "slack", builtin=CHANNELS))
    derived = (environ.names_read(add_ons.source("openfactory/runtime/slack/"))
               | environ.names_read(add_ons.source("openfactory/adapters/channel/slack.py")))
    assert set(names) == {n for n in derived if not n.startswith(environ.ENV_PREFIX)}
    assert len(names) >= 2
    rendered = (_rows(render(Answers(channel="slack")).text)
                - _rows(render(Answers(channel="panel")).text))
    assert rendered == set(names), "the channel block renders EXACTLY what the row declares"


def test_the_deployment_wide_rows_declare_what_they_read(monkeypatch):
    """The two notifier rows the chat package ships declare their variables the way the channel
    row does — the doctor offers a kind as the deployment-wide fallback only when a project-less
    caller lacks nothing but variables the row declares, so an undeclared row is never offered."""
    from openfactory.adapters.notify.registry import AXIS, NOTIFIERS

    require("notifier.telegram", "notifier.slack")
    install(monkeypatch, "notifier.telegram", "notifier.slack")
    telegram = plugins.builder(AXIS, "telegram", builtin=NOTIFIERS)
    assert set(plugins.environment(telegram)) == set(
        environ.names_read(add_ons.source("openfactory/adapters/notify/telegram.py")))
    slack_row = add_ons.module("openfactory.adapters.notify.slack")
    assert plugins.environment(plugins.builder(AXIS, "slack", builtin=NOTIFIERS)) == (
        slack_row._DEFAULT_TOKEN_ENV,)


def test_names_read_answers_for_one_file_as_well_as_a_tree(tmp_path):
    (tmp_path / "a.py").write_text('import os\nx = os.environ.get("ACME_A")\n')
    (tmp_path / "b.py").write_text('import os\ny = os.environ.get("ACME_B")\n')
    assert environ.names_read(tmp_path / "a.py") == frozenset({"ACME_A"})
    assert environ.names_read(tmp_path) == frozenset({"ACME_A", "ACME_B"})
