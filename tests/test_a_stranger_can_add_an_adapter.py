"""A stranger adds the third implementation without editing a file of ours — #106.

`docs/core/07-extensibility.md` states the rule the platform is measured against:

    an axis is agnostic when it is BORN WITH TWO; a platform is extensible when a stranger can
    add the third WITHOUT EDITING OUR FILES.

By the first half the axes passed. By the second the platform failed, and the document said so:
*"`openfactory install <addon>` is impossible today — an add-on would have nowhere to register
itself."* Every registry a dict literal, all inside this repository. Adding a row meant opening a
pull request against us — which for a product sold as agnostic is the differentiator being false
in the one way a buyer can check.

THE TEST IS THE CLAIM. Everything here drives the REAL builders through the REAL registries with a
plugin that exists only for the duration of the test — no file of ours edited, which is the whole
sentence being asserted.

TWO WAYS THE CLAIM WAS FALSE WHILE THIS FILE WAS GREEN (2026-08-26). The file pinned a hand-listed
`AXES` tuple: an axis absent from it was invisible, and a probe with a real `dist-info` measured
six registries refusing an installed add-on by name while the four listed here built it. So the
registries are DERIVED from the tree now — every module with a kind table and an unknown-kind
refusal — and held equal to the published list in `plugins.AXES`. And the fixture patched
`importlib.metadata`, which proves the loader and says nothing about packaging; the second half of
this file installs a REAL distribution (`tests/stranger_addon.py`) and asks every registry for it.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
import stranger_addon

from openfactory import plugins

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Point:
    """One entry point, as `importlib.metadata` hands them over."""

    def __init__(self, name, value):
        self.name, self._value = name, value

    def load(self):
        if isinstance(self._value, Exception):
            raise self._value
        return self._value


@pytest.fixture
def installs(monkeypatch):
    """Install add-ons for the duration of one test, the way a `pip install` would.

    Patched at `importlib.metadata.entry_points` rather than at our own loader, because patching
    the loader would prove that our function returns what we told it to — and the claim is about
    the PACKAGING mechanism, which is the part a stranger actually uses."""
    def _install(*points):
        plugins.reset_cache()
        monkeypatch.setattr("importlib.metadata.entry_points",
                            lambda group=None: list(points) if group == plugins.GROUP else [])
        plugins.reset_cache()
    yield _install
    plugins.reset_cache()


@pytest.fixture
def stranger(tmp_path, monkeypatch):
    """A real distribution on `sys.path` — nothing of ours patched. See `stranger_addon`."""
    return stranger_addon.installed(tmp_path, monkeypatch)


# ── the claim ───────────────────────────────────────────────────────────────────────────────────

def test_a_stranger_s_forge_is_the_one_that_RUNS(installs):
    """The claim, driven through the real builder rather than through the loader.

    THE FIRST VERSION OF THIS TEST WAS DECORATION and a mutation said so: it called
    `plugins.builder(...)` directly, which proves the LOADER works and says nothing about whether
    the registry calls it. Removing the plugin lookup from `build_forge` left it green — the
    "built, tested, reached by nothing" question, asked of my own guard.

    So: install an add-on, ask the registry for it by kind, and assert the add-on's code is what
    came back."""
    from openfactory.adapters.forge.registry import FORGES, build_forge

    sentinel = object()
    installs(_Point("forge.acme_corp", lambda *a, **kw: sentinel))
    assert "acme_corp" not in FORGES, "the fixture collided with a real row"

    project = type("_P", (), {"forge": type("_F", (), {"kind": "acme_corp", "repo": "a/b",
                                                       "options": {}})()})()

    assert build_forge(project) is sentinel, (
        "the forge registry does not consult installed add-ons — a stranger can declare an entry "
        "point and the platform never looks at it")


# ── the registries are DERIVED, not listed ──────────────────────────────────────────────────────

def _string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = "literal"` — a registry may spell its axis once (`AXIS = "box"`)."""
    return {t.id: n.value.value for n in tree.body if isinstance(n, ast.Assign)
            and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
            for t in n.targets if isinstance(t, ast.Name)}


def _refuses_a_kind(tree: ast.Module) -> bool:
    """The house refusal: `raise ValueError(f"unknown <axis> {kind!r} — known: …")` or the board's
    `no board provider … (known: …)`. A message that names what IS known is what makes a module a
    registry rather than a validator: it dispatches on a kind and lists its rows."""
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
                and getattr(node.exc.func, "id", "") == "ValueError" and node.exc.args):
            continue
        message = node.exc.args[0]
        parts = (message.values if isinstance(message, ast.JoinedStr) else [message])
        text = "".join(p.value for p in parts if isinstance(p, ast.Constant)
                       and isinstance(p.value, str))
        # `known:` with the colon — "unknown" contains "known", and the action layer's "unknown
        # outcome code … one of …" is a validator, not a registry
        if "known:" in text and (text.startswith("unknown ") or text.startswith("no ")):
            return True
    return False


def _builds_a_kind(tree: ast.Module) -> bool:
    """A module-level `build_<axis>` — the other registry signature. The notifier registry never
    raises (its callers are scheduled rounds) and would be invisible to the refusal test alone;
    a registry that neither refuses nor builds is not one."""
    return any(isinstance(n, ast.FunctionDef) and n.name.startswith("build_") for n in tree.body)


def _has_a_kind_table(tree: ast.Module) -> bool:
    """A module-level PUBLIC UPPERCASE name bound to a dict literal (possibly wrapped, like the
    box table's `_checked({...})`) — the `kind → builder` shape ADR-0022 gave every axis. A
    private map (`_HEADINGS`) is a lookup inside one module, not a table a kind is dispatched
    through, and the onboarding surveyor carries two of those beside a `build_prompt`."""
    for node in tree.body:
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target] if isinstance(node, ast.AnnAssign) else [])
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if isinstance(value, ast.Call) and value.args:
            value = value.args[0]
        if isinstance(value, ast.Dict) and any(
                isinstance(t, ast.Name) and t.id.isupper() and not t.id.startswith("_")
                for t in targets):
            return True
    return False


def _axes_asked(tree: ast.Module) -> set[str]:
    """Every axis this module passes to `plugins.builder(...)`, literal or module constant."""
    constants = _string_constants(tree)
    asked: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "builder"
                and getattr(node.func.value, "id", "") == "plugins" and node.args):
            first = node.args[0]
            axis = (first.value if isinstance(first, ast.Constant)
                    else constants.get(getattr(first, "id", "")))
            if axis:
                asked.add(axis)
    return asked


def registries(root: pathlib.Path = ROOT) -> dict[str, set[str]]:
    """`relative path → axes asked` for every registry under the package, DERIVED: a module with a
    kind table AND either an unknown-kind refusal or a `build_*` function. A registry that consults
    nothing is in the map with an empty set — which is what makes a closed one visible rather
    than absent."""
    found: dict[str, set[str]] = {}
    for path in sorted(root.joinpath("openfactory").rglob("*.py")):
        tree = ast.parse(path.read_text())
        # A MODULE THAT ASKS THE LOADER IS A REGISTRY WHATEVER ITS DOOR IS CALLED. The credential
        # and board-setup registries (2026-08-26) answer `None` for an unknown kind instead of
        # refusing it, and their doors are `credential_row` / `board_creator`, not `build_*` — so
        # the two shapes above could not see them, and the published list carried two axes that
        # "nobody asked for". The refusal/build shapes stay: they are what makes a CLOSED registry
        # visible, which asking the loader by definition cannot be.
        if _has_a_kind_table(tree) and (
                _refuses_a_kind(tree) or _builds_a_kind(tree) or _axes_asked(tree)):
            found[path.relative_to(root).as_posix()] = _axes_asked(tree)
    return found


REGISTRIES = registries()


def test_the_derivation_finds_the_registries_it_was_written_for():
    """The walk has to see the tree it describes, or every guard below measures nothing."""
    assert len(REGISTRIES) >= 12, sorted(REGISTRIES)
    for rel in ("openfactory/adapters/forge/registry.py", "openfactory/adapters/board/factory.py",
                "openfactory/adapters/notify/registry.py", "openfactory/identity/registry.py",
                "openfactory/adapters/environment/registry.py",
                "openfactory/adapters/agent/session_store.py"):
        assert rel in REGISTRIES, f"{rel} is not recognised as a registry: {sorted(REGISTRIES)}"


@pytest.mark.parametrize("rel", sorted(REGISTRIES))
def test_every_registry_CONSULTS_the_loader(rel):
    """One case per DERIVED registry. "Extensible" that holds for the axes somebody listed and
    not the one they forgot is the shape this repository catalogues most often — and a registry
    added closed must go red here, not stay invisible behind a tuple."""
    asked = REGISTRIES[rel]
    assert asked, (
        f"`{rel}` has a kind table and refuses unknown kinds but never calls `plugins.builder` — "
        f"an add-on for its axis would be declared, loaded, and never asked for")
    unknown = asked - set(plugins.AXES)
    assert not unknown, (
        f"`{rel}` asks the loader for {sorted(unknown)}, which `plugins.AXES` does not publish — "
        f"the axis name is what joins an entry point to a registry, and a stranger reads the list")


def test_the_published_axes_are_EXACTLY_what_the_registries_ask_for():
    """The positive twin of the guard above: every axis in the published list is asked for by a
    registry. An axis listed and asked for by nobody is a door painted on a wall."""
    asked = set().union(*REGISTRIES.values())
    assert asked == set(plugins.AXES), (
        f"published but never asked for: {sorted(set(plugins.AXES) - asked)}; asked for but "
        f"unpublished: {sorted(asked - set(plugins.AXES))}")


def test_the_derivation_can_SEE_a_planted_closed_registry(tmp_path):
    """Verify the verifier: a registry in the exact shape ours have, minus the loader call, must
    be found and reported with an empty set — and a module that merely raises "unknown" without
    a table (a validator) must not be mistaken for one."""
    pkg = tmp_path / "openfactory" / "adapters" / "widget"
    pkg.mkdir(parents=True)
    (pkg / "registry.py").write_text(
        'WIDGETS: dict = {"acme": lambda **kw: None}\n'
        "def build_widget(kind):\n"
        "    builder = WIDGETS.get(kind)\n"
        "    if builder is None:\n"
        '        raise ValueError(f"unknown widget {kind!r} — known: {sorted(WIDGETS)}")\n'
        "    return builder()\n")
    (pkg / "validator.py").write_text(
        'STATES: dict = {"open": 1}\n'
        "def check(kind):\n"
        '    raise ValueError(f"unknown state {kind!r} — one of open, closed")\n')
    (pkg / "composer.py").write_text(
        "def build_runner(project):\n"
        "    return object()\n")
    (pkg / "open.py").write_text(
        "from openfactory import plugins\n"
        'AXIS = "widget"\n'
        'WIDGETS: dict = {"acme": lambda **kw: None}\n'
        "def build_widget(kind):\n"
        "    builder = WIDGETS.get(kind) or plugins.builder(AXIS, kind, builtin=WIDGETS)\n"
        "    if builder is None:\n"
        '        raise ValueError(f"unknown widget {kind!r} — known: {sorted(WIDGETS)}")\n'
        "    return builder()\n")

    found = registries(tmp_path)

    assert found == {"openfactory/adapters/widget/registry.py": set(),
                     "openfactory/adapters/widget/open.py": {"widget"}}, found


# ── a REAL distribution, and every registry builds it ───────────────────────────────────────────

def _project(**overrides):
    from openfactory.contracts.project import Project, ProviderRef

    fields = dict(name="fx-acme", repo_path="/tmp/fx-acme",
                  tracker=ProviderRef(kind="acme", repo="acme/repo"),
                  forge=ProviderRef(kind="acme", repo="acme/repo"),
                  channel="acme", harness="acme")
    fields.update(overrides)
    return Project(**fields)


def _probe_box(project):
    from openfactory.adapters.sandbox.registry import build_sandbox, installed_box_traits

    assert installed_box_traits("acme").name == "acme"
    return build_sandbox("acme")


def _probe_role(project):
    from openfactory.adapters.agent.registry import known_roles

    assert "acme" in known_roles()
    return "acme"


#: Axes whose builder returns a VALUE rather than an adapter (a role spec, the token pool's
#: dict) — proven by `BUILT` alone, since a value carries no module of origin.
VALUE_AXES = {"role", "token_pool"}


#: axis → how its registry is driven for the stranger's kind. THE KEYS ARE HELD EQUAL TO
#: `plugins.AXES` below, so a new axis must say here how a stranger reaches it or the suite is
#: red — the same "absence is visible" rule the derivation above applies to the registries.
PROBES = {
    "forge": lambda p: __import__("openfactory.adapters.forge.registry", fromlist=["x"])
    .build_forge(p),
    "tracker": lambda p: __import__("openfactory.adapters.tracker.registry", fromlist=["x"])
    .build_tracker(p),
    "harness": lambda p: __import__("openfactory.adapters.agent.registry", fromlist=["x"])
    .build_executor(p),
    "channel": lambda p: __import__("openfactory.adapters.channel.registry", fromlist=["x"])
    .build_channel(p),
    "board": lambda p: __import__("openfactory.adapters.board.factory", fromlist=["x"])
    .build_board(p),
    "ci": lambda p: __import__("openfactory.adapters.environment.registry", fromlist=["x"])
    .build_observer(p),
    "box": _probe_box,
    "box_runner": lambda p: __import__("openfactory.adapters.sandbox.registry", fromlist=["x"])
    .remote_box("acme_cloud"),
    "event": lambda p: __import__("openfactory.observability.registry", fromlist=["x"])
    .build_event_sink("acme", path=None),
    "metrics": lambda p: __import__("openfactory.observability.registry", fromlist=["x"])
    .build_metrics_sink("acme"),
    "identity": lambda p: __import__("openfactory.identity.registry", fromlist=["x"])
    .build_identity({"OPENFACTORY_IDENTITY": "acme"}),
    "notifier": lambda p: __import__("openfactory.adapters.notify.registry", fromlist=["x"])
    .build_notifier(p),
    "role": _probe_role,
    "session_store": lambda p: __import__("openfactory.adapters.agent.session_store",
                                          fromlist=["x"]).build_session_store("acme"),
    "token_pool": lambda p: __import__("openfactory.adapters.agent.token_pool", fromlist=["x"])
    .token_pool("acme"),
    # The two the forge cut added (2026-08-26): a vendor declares its credential and its board
    # creator as rows, so a stranger's forge can name its own env var and create its own board.
    "credential": lambda p: __import__("openfactory.adapters.credential.registry", fromlist=["x"])
    .credential_row("acme"),
    "board_setup": lambda p: __import__("openfactory.adapters.board_setup.registry", fromlist=["x"])
    .board_creator("acme"),
}


def test_every_published_axis_has_a_probe():
    assert set(PROBES) == set(plugins.AXES), (
        f"no probe for {sorted(set(plugins.AXES) - set(PROBES))}; probes for axes that do not "
        f"exist: {sorted(set(PROBES) - set(plugins.AXES))}")


def test_the_real_distribution_is_read_by_the_packaging_mechanism(stranger):
    """Nothing patched: `importlib.metadata` scanned `sys.path`, found the dist-info, and the
    loader saw a row on every axis."""
    loaded = plugins._load()
    for axis in plugins.AXES:
        assert stranger_addon.KIND in loaded.get(axis, {}) or (
            axis == "box_runner" and stranger_addon.REMOTE_KIND in loaded.get(axis, {})), (
            f"the `{axis}` entry point of a real distribution was not read: {sorted(loaded)}")


@pytest.mark.parametrize("axis", sorted(PROBES))
def test_a_stranger_s_adapter_is_the_one_EVERY_registry_builds(axis, stranger, monkeypatch):
    """Per axis: ask the registry the way the platform asks it, and assert the object that came
    back was made by the stranger's code — `BUILT` records the builder the platform CALLED, which
    is the difference between "loaded" and "asked for"."""
    stranger.BUILT.clear()
    built = PROBES[axis](_project())

    if axis not in VALUE_AXES:
        assert type(built).__module__ == "acme_addons", (
            f"the `{axis}` registry answered with {type(built).__name__}, not the add-on's object")
    expected = "acme_cloud" if axis == "box_runner" else "acme"
    assert (axis, expected) in stranger.BUILT, (
        f"the `{axis}` registry never CALLED the add-on's builder: {stranger.BUILT}")


def test_the_refusal_NAMES_the_kind_a_stranger_installed(installs):
    """A stranger who installed an add-on and typo'd the kind must see THEIR row in the list, or
    the error tells them the platform does not support what they just installed."""
    from openfactory.adapters.forge.registry import FORGES, build_forge

    installs(_Point("forge.gitlab", lambda *a, **kw: object()))

    assert "gitlab" in plugins.known("forge", FORGES)
    project = type("_P", (), {"forge": type("_F", (), {"kind": "gitlabb", "repo": "a/b",
                                                       "options": {}})()})()
    with pytest.raises(ValueError, match="gitlab"):
        build_forge(project)


def test_an_unknown_kind_still_RAISES(installs):
    """The house rule, unchanged. Falling back to a default would point a deployment at the wrong
    client and surface as a confusing auth error rather than the configuration mistake it is —
    what the plugin group changes is only that the list it names can grow."""
    from openfactory.adapters.forge.registry import build_forge

    installs()
    project = type("_P", (), {"forge": type("_F", (), {"kind": "nope", "repo": "a/b",
                                                       "options": {}})()})()
    with pytest.raises(ValueError, match="unknown forge"):
        build_forge(project)


# ── an add-on is an extension, not a supply chain ───────────────────────────────────────────────

def test_a_built_in_WINS_a_collision(installs):
    """An add-on that could redefine `github` would change what that word means for every project
    on the deployment, silently, from a package somebody installed for something else. That is not
    an extension point.

    Asserted on the BUILDER, not on a flag: the question is which code runs."""
    from openfactory.adapters.forge.registry import FORGES

    installs(_Point("forge.github", lambda *a, **kw: "hijacked"))

    assert plugins.builder("forge", "github", builtin=FORGES) is None, (
        "an add-on shadowed a built-in adapter")
    assert plugins.shadowed("forge", FORGES) == ["github"], (
        "the collision is not even reported, so nobody could find out it was attempted")


# ── one bad add-on may not take anything else down ──────────────────────────────────────────────

def test_an_add_on_that_fails_to_IMPORT_is_ignored_and_the_others_still_work(installs):
    """A stranger's package must never be a reason `openfactory --help` fails. The broken one is
    dropped with a line; every other axis is untouched."""
    from openfactory.adapters.tracker.registry import TRACKERS

    sentinel = object()
    installs(_Point("forge.broken", ImportError("no module named nope")),
             _Point("tracker.acme_corp", lambda *a, **kw: sentinel))

    assert plugins.builder("tracker", "acme_corp", builtin=TRACKERS) is not None
    from openfactory.adapters.forge.registry import FORGES
    assert plugins.builder("forge", "broken", builtin=FORGES) is None


@pytest.mark.parametrize("name", ["nodots", "", ".leading", "trailing."])
def test_a_MALFORMED_entry_point_name_is_refused_rather_than_half_read(name, installs):
    """`<axis>.<kind>` or nothing. Half-reading a name would register a builder under an axis
    nobody meant, and the first sign would be a project resolving an adapter it never declared."""
    installs(_Point(name, lambda *a, **kw: object()))

    assert not any(plugins._load().values()), f"{name!r} was accepted as an axis/kind pair"


def test_a_broken_metadata_store_does_not_take_the_CLI_down(monkeypatch):
    """Import time is where a third-party packaging problem would stop `--help` from running, and
    a stranger's mistake must not be able to do that."""
    plugins.reset_cache()

    def _boom(group=None):
        raise RuntimeError("the metadata store is corrupt")

    monkeypatch.setattr("importlib.metadata.entry_points", _boom)
    plugins.reset_cache()

    assert plugins._load() == {}
    plugins.reset_cache()


# ── the group has to actually be declared ───────────────────────────────────────────────────────

def test_the_group_is_declared_where_a_stranger_would_look():
    """An entry-point group nobody declares is a convention in a docstring. It goes in the
    packaging metadata of the packages that USE it — the platform's own add-ons under `addons/`,
    each of which is the worked example a stranger copies — and the core's own `pyproject.toml`
    declares NO row in it (2026-08-26): a row there would name a module the public wheel does
    not contain. The public tree has no `addons/`; there the group is what the contributor's
    page and the reader's page name (`test_the_public_cut_is_written_down.py`)."""
    import tomllib

    from vendor_addons import packages, require

    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert plugins.GROUP not in data["project"].get("entry-points", {}), (
        f"the core's pyproject declares rows in `{plugins.GROUP}` — the platform's own rows "
        f"belong to the packages under addons/, or the public wheel names modules it lacks")

    require()
    for name, package_dir in packages().items():
        declared = tomllib.loads((package_dir / "pyproject.toml").read_text())
        assert plugins.GROUP in declared["project"].get("entry-points", {}), (
            f"{name} declares no `{plugins.GROUP}` rows — an add-on package with nothing to "
            f"plug in")
