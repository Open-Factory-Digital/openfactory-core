"""Every provider axis must be pluggable: one row in a registry, never a sweep through the code.

The product owner, 2026-07-28: *"we can leave Telegram for later since Slack is more professional…
and we leave GitLab for later too, but we have to leave it PREPARED to plug all of that in."*

So this file guards the preparation, not the implementations. GitLab and Telegram deliberately do
not exist yet — a stub adapter nothing exercises would be the thirteenth instance of this
codebase's signature defect (built, tested, reached by nothing). What must exist is the seam:

    a registry that dispatches on the configured kind
    an unknown kind that RAISES instead of quietly using GitHub
    zero call sites naming a concrete class
    a Protocol checked at runtime, so a future adapter cannot ship half-implemented

With those, adding GitLab is one module plus one row — and this suite already knows how to hold it
to the same contract.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from openfactory.adapters.environment.registry import OBSERVERS, build_observer, observer_kind
from openfactory.adapters.forge.base import ForgeAdapter
from openfactory.adapters.forge.registry import FORGES, build_forge
from openfactory.adapters.tracker.registry import TRACKERS
from openfactory.contracts.project import Project, ProviderRef


def _project(forge_kind="github", tracker_kind="github", **forge_options):
    return Project(name="x", repo_path="/t",
                   tracker=ProviderRef(kind=tracker_kind, repo="a/b"),
                   forge=ProviderRef(kind=forge_kind, repo="a/b", options=forge_options))


# ── the seams exist and dispatch ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("registry,name", [(TRACKERS, "tracker"), (FORGES, "forge"),
                                           (OBSERVERS, "observer")])
def test_every_axis_dispatches_through_a_registry(registry, name):
    assert isinstance(registry, dict) and registry, f"the {name} axis has no dispatch table"


def test_the_forge_satisfies_its_contract_at_runtime():
    """A Protocol nobody checks is documentation. This is what caught BoardAdapter's own
    implementation missing `columns()` earlier today."""
    assert isinstance(build_forge(_project()), ForgeAdapter)


@pytest.mark.parametrize("kind", ["gitlab", "bitbucket", "typo"])
def test_an_unknown_forge_RAISES_rather_than_reaching_for_github(kind):
    """Today `gitlab` is an honest error at startup. Falling back would authenticate against the
    wrong host with the wrong token and surface as a permissions problem — the most expensive shape
    a configuration mistake can take, because it looks like something else."""
    with pytest.raises(ValueError, match="unknown forge"):
        build_forge(_project(forge_kind=kind))


def test_the_error_names_what_IS_supported():
    """An error a person can act on: it says what to configure instead.

    DERIVED FROM THE REGISTRY, not spelled out. This asserted `known: github` and broke the day a
    second forge landed — over-specified onto the vendor instead of onto the property, so it read
    as a regression when it was the registry growing exactly as intended. Worse, the literal was
    the weaker guard: it could not notice a NEW kind missing from the sentence, which is the only
    way this promise actually fails. A person reading `known: azure_devops` and not finding their
    own provider needs the list to be complete, not to be the one it was on the day it was written.
    """
    from openfactory.adapters.forge.registry import FORGES

    with pytest.raises(ValueError) as raised:
        build_forge(_project(forge_kind="gitlab"))

    message = str(raised.value)
    assert "known:" in message
    missing = [kind for kind in FORGES if kind not in message]
    assert not missing, (
        f"the error offers no way to reach {missing} — every registered forge must appear, or a "
        f"person configures around a provider that already exists"
    )


# ── the CI follows the forge ────────────────────────────────────────────────────────────────────

def test_the_CI_kind_defaults_to_the_forge_so_one_value_configures_both():
    """Nobody is on GitLab for code and GitHub Actions for CI. When GitLab CI lands, a project that
    moved its forge gets the right observer automatically instead of silently watching the wrong
    system — where the symptom is a release stuck in 'verifying' for ever."""
    assert observer_kind(_project(forge_kind="github")) == "github"


def test_a_deployment_can_still_split_them_explicitly():
    assert observer_kind(_project(forge_kind="github", ci="github_actions")) == "github_actions"


def test_an_unknown_CI_RAISES():
    with pytest.raises(ValueError, match="unknown CI"):
        build_observer(_project(forge_kind="github", ci="jenkins"))


# ── nothing names a vendor ──────────────────────────────────────────────────────────────────────

_VENDOR_CLASSES = {"GitHubForge", "GitHubActionsObserver", "GitHubIssuesTracker", "JiraTracker",
                   "GitHubProjectBoard"}

#: The provider modules themselves, their registries, and their packages' own __init__ re-exports
#: (a package re-exporting its own class is inside the provider, not a seam violation — the teeth
#: that catch aliased imports flagged these on their first run, correctly but uselessly).
_MAY_NAME_A_VENDOR = {
    "openfactory/adapters/forge/registry.py", "openfactory/adapters/forge/github.py",
    "openfactory/adapters/forge/__init__.py",
    "openfactory/adapters/environment/registry.py", "openfactory/adapters/environment/github_actions.py",
    "openfactory/adapters/environment/__init__.py",
    "openfactory/adapters/tracker/registry.py", "openfactory/adapters/tracker/github.py",
    "openfactory/adapters/tracker/jira.py", "openfactory/adapters/tracker/github_project.py",
    "openfactory/adapters/tracker/__init__.py",
    "openfactory/adapters/board/factory.py",
}


def test_no_module_outside_its_provider_constructs_a_vendor_class():
    """The seam's entire claim, asserted. Before today, eleven forge constructions and a dozen
    tracker constructions lived across the CLI, the panel, the worker and the box — so a client on
    another provider meant editing every one of them.

    THREE TEETH an audit found missing from the first version, each a sabotage that passed:
    - `from …github import GitHubForge as GF; GF(...)` — the alias hid the name from Call.func.id,
      so IMPORTS of vendor classes are flagged too (the alias cannot hide the import).
    - `import …github as g; g.GitHubForge(...)` — Attribute calls are now checked by attr name.
    - `pytest` run from another directory made `rglob` return NOTHING and the guard pass green
      over an empty scan — the scan now proves it scanned."""
    stray = {}
    scanned = 0
    for path in Path("openfactory").rglob("*.py"):
        scanned += 1
        if str(path) in _MAY_NAME_A_VENDOR:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        named: set[str] = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                named.add(getattr(n.func, "id", "") or getattr(n.func, "attr", ""))
            elif isinstance(n, ast.ImportFrom):
                named.update(a.name for a in n.names)
        hit = named & _VENDOR_CLASSES
        if hit:
            stray[str(path)] = sorted(hit)
    assert scanned > 80, f"scanned only {scanned} files — run from the repo root, or fix the scan"
    assert not stray, (
        f"these construct or import a provider by name: {stray}. Use the registry — a client on "
        f"GitLab or Jira must not need any of them changed."
    )


def test_adding_a_provider_is_one_row_plus_one_module():
    """The shape of the extension point, so a future reader knows where to add GitLab."""
    src = Path("openfactory/adapters/forge/registry.py").read_text()
    assert "FORGES" in src and "gitlab" in src.lower(), (
        "the registry no longer documents where GitLab plugs in")


# ── the conversation channel ────────────────────────────────────────────────────────────────────

def test_the_core_never_imports_slack_directly():
    """The axis with the biggest coupling and no protocol at all: 1,500 lines of Socket Mode,
    threads and mrkdwn, imported by the worker and the activities by name. Telegram is deferred
    (Slack is what a professional client expects) — but "later" must not mean rewriting the worker,
    so the seam ships now."""
    offenders = []
    scanned = 0
    for path in Path("openfactory").rglob("*.py"):
        scanned += 1
        # THE VENDOR SIDE OF THE SEAM, and it is defined by the file's own NAME rather than by a
        # list of directories somebody keeps in step. `adapters/notify/slack.py` was outside the
        # old prefix list purely because nobody had written it yet when the list was made — and the
        # first time a Slack adapter needed Slack machinery, the guard read it as the core leaking.
        # A module called `slack.py` inside `adapters/` IS the Slack implementation; forbidding it
        # from importing Slack is forbidding it from existing.
        if str(path).startswith("openfactory/runtime/slack/") or (
                str(path).startswith("openfactory/adapters/") and path.name == "slack.py"):
            continue
        # the plain dotted path, not just the `from` form: `import openfactory.runtime.slack.bot`,
        # `importlib.import_module("openfactory.runtime.slack.bot")` and `from openfactory.runtime import
        # slack` all sailed past the first version's `from openfactory.runtime.slack` substring
        if "openfactory.runtime.slack" in path.read_text() or "openfactory.runtime import slack" in path.read_text():
            offenders.append(str(path))
    assert scanned > 80, f"scanned only {scanned} files — run from the repo root, or fix the scan"
    # DOCUMENTED EXCEPTIONS, each carrying the debt it represents — the house pattern for a guard
    # that must keep blocking NEW accretion while one known crossing is being paid down. An entry
    # here is a promise with a ticket, not a pass.
    # EMPTY, AND THAT IS THE POINT. It held `openfactory/api/app.py` for as long as the EXECUTOR of a
    # confirmation lived in the Slack package: the panel's answer route had to import
    # `product_channel` to run a write. #105 moved that executor to `openfactory/product/confirm.py`, the
    # route now calls the core gate, and the entry was deleted — which is exactly what the
    # staleness check below forces. A new crossing has to be argued for in this dict, with its
    # ticket, or it fails.
    allowed: set[str] = set()
    undocumented = [o for o in offenders if o not in allowed]
    assert not undocumented, f"these reach into Slack directly: {undocumented}"
    stale = [a for a in allowed if a not in offenders]
    assert not stale, (f"allowlist entries no longer needed: {stale} — the crossing was paid "
                      f"down; delete the entry so the guard tightens back")


#: A module is transport when it MENTIONS the transport. Crude on purpose: anything subtler would
#: need to know what each helper is for, and the failure being caught is not subtle — it is a file
#: of pure product logic that happens to sit in a vendor's folder.
_SLACK_MARKERS = ("slack", "Slack", "SLACK", "WebClient", "chat_post", "mrkdwn", "Socket Mode")


def _indifferent_to_slack(package: Path) -> list[str]:
    """Modules under `package` that never mention Slack — core hiding in a vendor package.

    Takes the directory rather than hardcoding it so the positive twin below can run the SAME
    function over a tree it planted. A scanner only ever exercised on a clean tree is a scanner
    nobody has seen find anything."""
    found = []
    for path in sorted(package.rglob("*.py")):
        if path.name == "__init__.py":      # a package marker names the package, not its contents
            continue
        if not any(m in path.read_text() for m in _SLACK_MARKERS):
            found.append(str(path))
    return found


def test_nothing_in_the_slack_package_is_INDIFFERENT_TO_slack():
    """ADR-0038 rule 3 — *"no capability may live in `runtime/<channel>/`; that package renders
    and parses"* — asserted rather than believed.

    THE GUARD ABOVE CANNOT SEE THIS ONE, and that is why both exist. It scans for the core
    reaching INTO Slack and skips `openfactory/runtime/slack/` wholesale, so the opposite leak —
    transport-neutral logic parked inside the vendor's folder — was invisible to it by
    construction. `product_intents.py` sat there for months: 587 lines, `import re` and nothing
    else, matching a client's Portuguese sentence to an intent. Nothing about it was Slack, and no
    deployment without Slack could reach it.

    That is the commercial constraint, not a tidiness one: core behaviour inside `runtime/slack/`
    is core the company cannot sell separately and an add-on it cannot remove."""
    stowaways = _indifferent_to_slack(Path("openfactory/runtime/slack"))
    assert not stowaways, (
        f"these modules never mention Slack, so they are not transport — they are capability in a "
        f"vendor package, and a deployment without Slack cannot reach them: {stowaways}")


def test_the_stowaway_scan_can_SEE_one(tmp_path):
    """The positive twin. `assert not found` passes just as happily when the scan is broken, and
    this repository has shipped three guards that were green over live defects for exactly that
    reason."""
    pkg = tmp_path / "slack"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""marker."""\n')
    (pkg / "bot.py").write_text("from slack_sdk import WebClient\n")
    (pkg / "intents.py").write_text("import re\n\ndef match(t):\n    return re.match('x', t)\n")

    found = _indifferent_to_slack(pkg)
    assert found == [str(pkg / "intents.py")], found
    # …and the transport module is not accused, or the guard would cry wolf on every real one
    assert str(pkg / "bot.py") not in found


def test_the_channel_contract_is_what_the_CORE_needs_not_what_slack_offers():
    """Three methods, because that is all five call sites ever asked for. A protocol built from
    what a provider CAN do would be a Slack API in disguise and Telegram would have to fake half
    of it."""
    from openfactory.adapters.channel import ChannelAdapter, build_channel

    surface = {n for n in dir(ChannelAdapter) if not n.startswith("_")}
    assert surface == {"say", "mention", "start_listeners"}, surface
    assert isinstance(build_channel(), ChannelAdapter)


def test_an_unknown_channel_RAISES_rather_than_posting_nowhere():
    """Silence is this axis's failure mode, and it is indistinguishable from a quiet factory —
    the exact confusion the whole tech-lead layer exists to remove."""
    from openfactory.adapters.channel import build_channel

    class _P:
        channel = "carrier-pigeon"

    with pytest.raises(ValueError, match="unknown channel"):
        build_channel(_P())


def test_the_core_runners_escalate_to_the_PROJECT_channel():
    """`notifier_from_env`'s own docstring is the specification: "Project-less callers: Telegram
    global fallback or Null. Slack routing needs a project's channel — use
    notifier_for_project(project)."

    Both builders called the project-less one with `project` right there in scope, so everything
    `JobRunner` and `PromotionRunner` escalate — "staging deploy/health failed", "prod verification
    failed — rolling back", "awaiting a human's approval to promote to prod" — went to a
    NullNotifier and was dropped in silence unless a global Telegram happened to be configured.

    The instruction was written down, in the same file, and not followed."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path("openfactory/factory.py").read_text())
    for builder in ("build_runner", "build_promotion_runner"):
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == builder), None)
        assert fn is not None, f"{builder} vanished — this guard is now watching nothing"
        body = ast.unparse(fn)
        assert "notifier_for_project(project)" in body, (
            f"{builder} escalates to the project-less fallback; its messages are dropped")
        assert "notifier=notifier_from_env()" not in body, builder
