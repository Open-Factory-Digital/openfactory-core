"""#207 — what a provider is CALLED comes from its own row, never from a table in generic code.

THE SIBLING. `test_the_lifecycle_names_no_provider.py` refuses a provider's KIND (`"github"`) in
the three files the lifecycle lives in: no decision is taken by the name of the row on the other
side of a port. This file asks the question beside it, about the word a PERSON reads: is a
provider's display name — "GitHub Actions", "Azure Pipelines" — spelled anywhere outside the
adapters?

It was, in the panel's view. `runtime/temporal/view.py` kept `_FORGE_LABELS`, a table from CI
kind to heading, under a comment that said what was wrong with it: *"a new provider must not need
this table to be displayed HONESTLY, only to be displayed prettily"*. So a CI add-on registered
through the `openfactory.adapters` entry-point group was shown by its registry key, the only way
to show it properly was to edit the core, and the table carried a row for a provider the core
does not ship.

TWO HALVES, as in the sibling: a parsed rule over the whole package with its planted twin, and
the behaviour — a stranger's row, with a name it declared, read back through the heading and
through the payload the panel draws.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openfactory import plugins
from openfactory.adapters.environment import registry as ci
from openfactory.contracts.project import Project, ProviderRef
from openfactory.registry import ProjectRegistry
from openfactory.runtime.temporal import view as tv
from tests import vendor_addons
from tests.test_the_card_says_what_the_floor_says import GATE, _async, _Client, _Handle
from tests.test_the_lifecycle_names_no_provider import _docstrings

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "openfactory"

#: Where a provider's own words live, and the only place they may: its adapter and its registry.
ADAPTERS = "openfactory/adapters/"

#: Providers this core does not ship a row for, whose names a table in generic code would carry —
#: the defect's own table had one. The names of the rows it DOES ship are not listed here: they
#: are read off the rows (`_shipped_names`), so a row added tomorrow is covered by being added.
STRANGERS = frozenset({"GitLab", "GitLab CI", "Bitbucket", "Bitbucket Pipelines", "Jenkins",
                       "CircleCI", "Travis CI", "Gitea", "Azure Repos", "Azure Boards", "Jira"})

#: ONE TABLE IS LEFT ALONE, BY NAME, and the reason is that it is not this seam. `onboarding/
#: infer.py::_RANK_WHY` labels the CI FILE FORMATS that module parses itself (`_read_gitlab` is
#: thirty lines above it) when it explains where an inferred gate command came from. There is no
#: axis behind it and no row an add-on could register: a format this module cannot parse cannot
#: be a source. Exempt by the NAME of the assignment, never by the file.
EXEMPT = {("openfactory/onboarding/infer.py", "_RANK_WHY")}


def _shipped_names() -> frozenset[str]:
    """Every name a shipped row declares — read off the rows, not copied from them.

    Read with a bare `getattr`, not through `plugins.display_name`: the vocabulary of the rule
    must not depend on the helper the rule is about, or a tree without the helper is red for a
    missing name instead of for the table it still carries."""
    from openfactory.adapters.forge.azure_devops import AzureReposForge
    from openfactory.adapters.forge.github import GitHubForge

    rows = [*ci.OBSERVERS.values(), GitHubForge, AzureReposForge]
    declared = (getattr(row, "display_name", "") for row in rows)
    return frozenset(name for name in declared if isinstance(name, str) and name.strip())


def provider_names(tree: ast.Module, names: frozenset[str],
                   exempt: frozenset[str] = frozenset()) -> list[tuple[int, str]]:
    """Every string constant that IS a provider's display name, outside prose — THE RULE ITSELF.

    A function for the sibling's reason: the planted twin below has to call the real walk, or it
    proves its own copy. THE WHOLE STRING, exactly as cased: a sentence that mentions a vendor is
    documentation, and `"github"` is a registry key (the sibling's business) — what is refused is
    the label itself, which only exists in generic code to be looked up by kind."""
    prose = _docstrings(tree)
    skipped: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id in exempt for t in targets):
                skipped.update(id(inner) for inner in ast.walk(node))
    return sorted((node.lineno, node.value) for node in ast.walk(tree)
                  if isinstance(node, ast.Constant) and isinstance(node.value, str)
                  and node.lineno not in prose and id(node) not in skipped
                  and node.value.strip() in names)


def _generic_modules() -> list[str]:
    return sorted(path.relative_to(ROOT).as_posix() for path in PACKAGE.rglob("*.py")
                  if not path.relative_to(ROOT).as_posix().startswith(ADAPTERS))


# ═══ the rule, over the whole package ═══════════════════════════════════════════════════════════

def test_the_rule_reads_the_package_and_knows_the_shipped_names() -> None:
    """A negative guard needs its positive twin: an empty list of files, or of names, passes."""
    assert len(_generic_modules()) > 100 and "openfactory/runtime/temporal/view.py" in \
        _generic_modules()
    assert {"GitHub Actions", "Azure Pipelines", "GitHub", "Azure DevOps"} <= _shipped_names()


def test_no_generic_module_spells_a_providers_display_name() -> None:
    names = _shipped_names() | STRANGERS
    offenders = []
    for rel in _generic_modules():
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        exempt = frozenset(name for path, name in EXEMPT if path == rel)
        offenders += [f"{rel}:{n}: {word!r}" for n, word in provider_names(tree, names, exempt)]

    assert not offenders, (
        "generic code spells what a provider is called — so a row it has never heard of is shown "
        "by its registry key, and showing it properly means editing the core. Declare "
        "`display_name` on the row and ask it (`plugins.display_name`):\n  "
        + "\n  ".join(offenders))


def test_the_guard_can_see_the_offence_and_only_the_offence() -> None:
    planted = ast.parse(
        'def heading(kind):\n'
        '    """A docstring naming GitHub Actions, which is prose and must not count."""\n'
        '    labels = {"github": "GitHub Actions", "gitlab": "GitLab"}\n'
        '    why = "GitHub Actions answers 404 for a private repository"\n'
        '    return labels.get(kind, kind)\n'
        '_RANK_WHY = {"gitlab_ci": "GitLab CI"}\n')
    names = frozenset({"GitHub Actions", "GitLab", "GitLab CI"})

    assert [w for _, w in provider_names(planted, names)] == [
        "GitHub Actions", "GitLab", "GitLab CI"], "the key, the sentence and the prose are not names"
    assert [w for _, w in provider_names(planted, names, frozenset({"_RANK_WHY"}))] == [
        "GitHub Actions", "GitLab"], "the exemption is by the name of the assignment, and only it"


def test_the_one_exemption_is_still_there_to_be_exempt() -> None:
    """An exemption for a table that has gone is a hole with a comment on it."""
    for rel, name in EXEMPT:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        assert provider_names(tree, _shipped_names() | STRANGERS), f"{rel} spells no name now"
        assert not provider_names(tree, _shipped_names() | STRANGERS, frozenset({name})), (
            f"{rel} spells a provider's name outside `{name}`")


# ═══ the rows say what they are called ══════════════════════════════════════════════════════════

def test_only_a_non_empty_string_is_a_declaration() -> None:
    assert plugins.display_name(SimpleNamespace(display_name=" Acme CI "), "acme") == "Acme CI"
    assert plugins.display_name(object(), "acme") == "acme"
    assert plugins.display_name(None, "acme") == "acme", "no row at all is shown by its kind"
    assert plugins.display_name(SimpleNamespace(display_name="  "), "acme") == "acme"
    assert plugins.display_name(MagicMock(), "acme") == "acme", "a test double is not a declaration"


@pytest.mark.parametrize(("kind", "called"), [
    ("github", "GitHub Actions"), ("github_actions", "GitHub Actions"),
    ("azure_devops", "Azure Pipelines"), ("azure_pipelines", "Azure Pipelines"),
    # NOTHING IS WATCHED, and the panel says that rather than a dash: a dash is a value that could
    # not be read, and this one was read (ADR-0049 D1). The sentence is the `none` row's own.
    ("none", "nothing is watched"), ("local", "nothing is watched"),
])
def test_each_shipped_observer_row_says_what_it_is_called(kind: str, called: str) -> None:
    assert plugins.display_name(ci.OBSERVERS[kind], kind) == called


def test_no_shipped_observer_row_is_left_to_be_shown_by_its_key() -> None:
    nameless = [kind for kind, row in ci.OBSERVERS.items() if not plugins.display_name(row, "")]
    assert not nameless, f"shipped rows with no `display_name`: {nameless}"


# ═══ a stranger's row, read back through the heading and the panel's payload ════════════════════

def _acme_observer(project, *, token=None):
    return SimpleNamespace(ci_status=lambda **kw: [], deploy_status=lambda **kw: "none",
                           health=lambda **kw: False)


def _nameless_observer(project, *, token=None):
    return _acme_observer(project, token=token)


_acme_observer.display_name = "Acme CI"


@pytest.fixture
def a_project_watched_by(tmp_path, monkeypatch):
    """A registered project whose `forge.options.ci` names an ADD-ON's kind, with that add-on's
    row served through the real entry-point mechanism."""
    def register(builder) -> str:
        monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
        vendor_addons.install(monkeypatch, declared_rows=False, extra=(
            SimpleNamespace(name="ci.acme", value="acme:observer", load=lambda: builder),))
        ProjectRegistry().add(Project(
            name="podbeam", repo_path=str(tmp_path),
            tracker=ProviderRef(kind="github", repo="o/r"),
            forge=ProviderRef(kind="github", repo="o/r", options={"ci": "acme"})))
        return "podbeam"
    return register


def test_an_addons_declared_name_reaches_the_heading(a_project_watched_by) -> None:
    assert tv._ci_provider(a_project_watched_by(_acme_observer)) == "Acme CI"  # noqa: SLF001


def test_an_addon_that_declares_nothing_is_shown_by_its_own_kind(a_project_watched_by) -> None:
    """Honest, as before: no name is invented for a row that gave none."""
    assert tv._ci_provider(a_project_watched_by(_nameless_observer)) == "acme"  # noqa: SLF001


async def test_and_it_reaches_the_payload_the_panel_draws(a_project_watched_by, monkeypatch):
    """`panel.html` writes `"CI checks (" + d.ci_provider + ")"` from this field and nothing else."""
    project = a_project_watched_by(_acme_observer)
    monkeypatch.setattr(tv, "_memo_title", lambda desc: _async("t"))
    monkeypatch.setattr(tv, "_true_status",
                        lambda c, wf: _async(tv.WorkflowExecutionStatus.RUNNING))
    monkeypatch.setattr(tv, "_pr_checks", lambda project, url: _async([]))

    got = await tv.job_detail(_Client(_Handle(merge=GATE)), project, "107", "default")

    assert got["ci_provider"] == "Acme CI"
