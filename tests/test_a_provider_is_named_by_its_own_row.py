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

AND THE SENTENCES, 2026-09-19. The names moved and the words a vendor needs SAID stayed behind:
the doctor chose a forge-credential remedy by finding `azure_devops` inside its own probe's
message and gave GitHub's to everybody else, chose a board's coordinates and its remedy by
`if kind == …`, `product declare` had a likely cause per vendor, and the panel's how-to spelled
the three boards that ship. So the same rule asks two more questions — is a vendor NAMED in a
string a person reads, and are words CHOSEN by a vendor's kind — and the second half drives a
stranger's credential, board and forge rows, each with words it declared, through the doctor's
real findings, the real command and the payload the panel draws. What is left is written down
in `LEDGER`, by the name of the thing that holds it, and every entry fails the day it is cured.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import vendor_addons

from openfactory import doctor, plugins
from openfactory.adapters.board import factory as boards
from openfactory.adapters.credential import registry as cred
from openfactory.adapters.environment import registry as ci
from openfactory.adapters.forge import registry as forges
from openfactory.contracts.project import Project, ProviderRef
from openfactory.registry import ProjectRegistry
from openfactory.runtime.temporal import view as tv
from tests.pinned_probes import a_fully_pinned_probe_set
from tests.test_the_card_says_what_the_floor_says import GATE, _async, _Client, _Handle
from tests.test_the_lifecycle_names_no_provider import _docstrings

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "openfactory"

#: Where a provider's own words live, and the only place they may: its adapter and its registry.
ADAPTERS = "openfactory/adapters/"

#: Providers this core does not ship a row for, whose names a table in generic code would carry —
#: the defect's own table had one. The names of the rows it DOES ship are not listed here: they
#: are read off the rows (`_shipped_names`), so a row added tomorrow is covered by being added.
#: ("Jira" and "Azure Boards" are rows' own names since 2026-09-19 and stay here as well: the
#: vocabulary must not shrink on a tree whose rows do not say them yet, or that tree reads clean.)
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

    rows = [*ci.OBSERVERS.values(), *boards.BOARDS.values(), GitHubForge, AzureReposForge]
    declared = (getattr(row, "display_name", "") for row in rows)
    return frozenset(name for name in declared if isinstance(name, str) and name.strip())


def _scopes(tree: ast.Module) -> dict[int, str]:
    """`id(node)` → the name of the TOP-LEVEL statement the node sits in — a function, the target
    of an assignment, or a class's MEMBER (a whole class is too wide a thing to excuse); `""` for
    anything else. What an exemption is keyed by — never a line, which moves, and never a file,
    which would exempt the next offence written into it."""
    out: dict[int, str] = {}
    members = [m for stmt in tree.body if isinstance(stmt, ast.ClassDef) for m in stmt.body]
    for stmt in [*tree.body, *members]:  # a class first, then its members over it
        name = getattr(stmt, "name", "")
        if isinstance(stmt, ast.Assign | ast.AnnAssign):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            name = next((t.id for t in targets if isinstance(t, ast.Name)), "")
        for inner in ast.walk(stmt):
            out[id(inner)] = name
    return out


def _skipped(tree: ast.Module, exempt: frozenset[str]) -> set[int]:
    """Every node under an assignment, a function or a class NAMED in `exempt`, at any depth."""
    skipped: set[int] = set()
    for node in ast.walk(tree):
        names: list[str] = [getattr(node, "name", "")]
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
        if any(name and name in exempt for name in names):
            skipped.update(id(inner) for inner in ast.walk(node))
    return skipped


def provider_names(tree: ast.Module, names: frozenset[str],
                   exempt: frozenset[str] = frozenset()) -> list[tuple[int, str]]:
    """Every string constant that IS a provider's display name, outside prose — THE RULE ITSELF.

    A function for the sibling's reason: the planted twin below has to call the real walk, or it
    proves its own copy. THE WHOLE STRING, exactly as cased: `"github"` is a registry key (the
    sibling's business) — what is refused here is the label itself, which only exists in generic
    code to be looked up by kind. A SENTENCE that names the vendor is the rule below this one."""
    prose = _docstrings(tree)
    skipped = _skipped(tree, exempt)
    return sorted((node.lineno, node.value) for node in ast.walk(tree)
                  if isinstance(node, ast.Constant) and isinstance(node.value, str)
                  and node.lineno not in prose and id(node) not in skipped
                  and node.value.strip() in names)


# ── the second question: a SENTENCE that is a vendor's, said by generic code ────────────────────

#: Registry kinds of vendors this core ships no row for — what a branch in generic code would
#: test for them. The kinds it DOES ship are read off the rows (`_vendor_kinds`).
STRANGER_KINDS = frozenset({"gitlab", "bitbucket", "gitea"})

#: A sentence, for counting: three words of two letters or more — the threshold
#: `test_nothing_speaks_before_it_asks_the_language.py` separates a sentence from a token by.
_WORD = re.compile(r"[^\W\d_]{2,}", re.UNICODE)


def _vendor_kinds() -> frozenset[str]:
    """The registry kinds that are a VENDOR's: every shipped credential row that NEEDS a
    credential. Read off the rows — `local` declares `needs=False`, and it is this machine, not
    somebody's service; a vendor shipped tomorrow is covered by declaring its row."""
    from openfactory.adapters.credential import registry as cred

    return frozenset(kind for kind in cred.CREDENTIALS
                     if getattr(cred.credential_row(kind), "needs", True))


def _shipped_variables() -> frozenset[str]:
    """The variable each shipped vendor's credential lives in (`CredentialRow.env`) — a vendor's
    word as surely as its name: "set AZURE_DEVOPS_PAT" is a sentence only one vendor's row owns."""
    from openfactory.adapters.credential import registry as cred

    rows = (cred.credential_row(kind) for kind in cred.CREDENTIALS)
    return frozenset(row.env for row in rows if row is not None and row.env)


def _is_prose(text: str) -> bool:
    """Three words with a space between them: `OPENFACTORY_BOT_TOKEN` is one word, not three."""
    return len([word for word in text.split() if _WORD.search(word)]) >= 3


def vendor_sentences(tree: ast.Module, words: frozenset[str], kinds: frozenset[str],
                     exempt: frozenset[str] = frozenset()) -> list[tuple[int, str, str]]:
    """`(line, scope, text)` of every string a person reads that NAMES a vendor — THE RULE.

    HOW A KEY IS TOLD FROM PROSE: BY THE SHAPE OF THE STRING, never by a list of allowed sites.
    A string that IS the kind (`"github"`) is a key — a lookup, a comparison, a registry default —
    and a string that IS the name is the rule above. What is refused here is a string with OTHER
    words in it where a vendor's name, or its credential's variable, stands as a word of its own;
    or prose where a registry kind does. A kind inside a host, a path or an identifier
    (`github.com`, `docs/setup/github.md`, `.github/workflows`) is none of those: it is an
    address, and whether generic code may hold a vendor's address is another question."""
    prose = _docstrings(tree)
    skipped = _skipped(tree, exempt)
    scopes = _scopes(tree)
    named = re.compile(r"(?<!\w)(?:" + "|".join(
        re.escape(w) for w in sorted(words, key=len, reverse=True)) + r")(?!\w)")
    keyed = re.compile(r"(?<![\w./-])(?:" + "|".join(
        re.escape(k) for k in sorted(kinds, key=len, reverse=True)) + r")(?![\w/-]|\.\w)")
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        text = node.value.strip()
        if node.lineno in prose or id(node) in skipped or text in words or text in kinds:
            continue
        if named.search(text) or (_is_prose(text) and keyed.search(text)):
            found.append((node.lineno, scopes.get(id(node), ""), " ".join(text.split())))
    return sorted(found)


def _kinds_tested(test: ast.expr, kinds: frozenset[str]) -> list[str]:
    """The vendor kinds a condition compares against — `kind == "github"`, `"jira" in kinds`,
    `kind in ("github", "jira")` — on either side of the comparison."""
    tested: list[str] = []
    for node in ast.walk(test):
        if isinstance(node, ast.Compare):
            for side in (node.left, *node.comparators):
                tested += [c.value for c in ast.walk(side)
                           if isinstance(c, ast.Constant) and c.value in kinds]
    return tested


def _are_words(value: ast.expr | None) -> bool:
    """An expression that is words for somebody: a sentence, or an f-string (a FORMAT — the
    doctor's board coordinates were `f"{owner}/{number}"` for one kind and another for the next)."""
    if isinstance(value, ast.JoinedStr):
        return True
    return isinstance(value, ast.Constant) and isinstance(value.value, str) \
        and _is_prose(value.value)


def _says(statements: list[ast.stmt], *, deep: bool) -> bool:
    """Whether these statements hand words to somebody: return them, keep them, or call something
    with them. `deep` reads the whole branch; an `else` is read shallow, because an `elif` is an
    `If` of its own and is judged on its own test."""
    nodes = [n for s in statements for n in (ast.walk(s) if deep else [s])]
    for node in nodes:
        if isinstance(node, ast.Return | ast.Assign) and _are_words(node.value):
            return True
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and any(
                _are_words(arg) for arg in [*node.value.args,
                                            *(k.value for k in node.value.keywords)]):
            return True
    return False


def vendor_branches(tree: ast.Module, kinds: frozenset[str],
                    exempt: frozenset[str] = frozenset()) -> list[tuple[int, str, str]]:
    """`(line, scope, kinds)` of every place generic code CHOOSES WORDS BY A VENDOR'S KIND.

    The rule above reads the words; this one reads the choice, and it is the one that sees a
    vendor's sentence that never says the vendor's name (`if kind == "jira": return "check that
    the account can browse the project"`). Three shapes: an `if` on a vendor's kind whose branch
    says something, the same as a conditional expression, and a table keyed by kind whose values
    are sentences. A branch that only DOES something — builds a row, picks a client — is the
    sibling guard's business (`test_the_lifecycle_names_no_provider.py`), not this one's."""
    skipped = _skipped(tree, exempt)
    scopes = _scopes(tree)
    found = []
    for node in ast.walk(tree):
        if id(node) in skipped:
            continue
        tested: list[str] = []
        if isinstance(node, ast.If) and (_says(node.body, deep=True)
                                         or _says(node.orelse, deep=False)):
            tested = _kinds_tested(node.test, kinds)
        elif isinstance(node, ast.IfExp) and (_are_words(node.body) or _are_words(node.orelse)):
            tested = _kinds_tested(node.test, kinds)
        elif isinstance(node, ast.Dict) and any(_are_words(v) for v in node.values):
            tested = [k.value for k in node.keys
                      if isinstance(k, ast.Constant) and k.value in kinds]
        if tested:
            found.append((node.lineno, scopes.get(id(node), ""), ", ".join(sorted(set(tested)))))
    return sorted(found)


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


# ═══ the second question, over the whole package ════════════════════════════════════════════════

#: WHAT IS LEFT, BY THE NAME OF THE THING THAT HOLDS IT — never by file, never by line. Every entry
#: is a place where generic code still names a vendor to a person, and none of them is a sentence
#: a row could simply be asked for: each sits inside vendor BEHAVIOUR that generic code also
#: carries, and the words go when the behaviour does. `test_every_ledger_entry_…` fails the day an
#: entry stops being needed, so this list can only shrink.
LEDGER: dict[tuple[str, str], str] = {
    ("openfactory/cli.py", "project_add"):
        "the door's own FLAGS are two vendors' (`--board-owner`, `--organization`, "
        "`--ado-project`, `--work-item-type`) and one branch builds one vendor's two rows from "
        "them; the help and the refusal describe those flags",
    ("openfactory/cli.py", "project_init"):
        "one branch recognises one vendor's clone URL and sends it to `project add`, the door "
        "that has the flags above",
    ("openfactory/cli.py", "bot_token"):
        "a command about one vendor's App credential, whose options are that App's",
    ("openfactory/cli.py", "_foreign_refusal"):
        "`GH_HOST` is how one vendor's forge claims an enterprise host (`doors.py`), and the way "
        "out is offered where the claim is read",
    ("openfactory/cli.py", "product_init"):
        "describes the reference shapes `normalize_repo` parses — the parser knows two vendors' "
        "shapes, and the sentence says what the parser does",
    ("openfactory/product/config.py", "resolve_product_link"):
        "the same sentence about `normalize_repo`, from the link's side",
    ("openfactory/cli_refusals.py", "_CAUSES"):
        "a refusal is named from an exception's text with NO PROJECT IN HAND, so there is no row "
        "to ask; the markers beside each remedy are vendors' error codes too",
    ("openfactory/onboarding/deployment.py", "QUESTIONS"):
        "`init` asks two questions only one vendor has (App or token; organisation or personal)",
    ("openfactory/onboarding/deployment.py", "_github_block"):
        "the environment file's block for one shipped vendor — an add-on's block already comes "
        "from its row (`plugins.environment`, `plugins.how_to`); the shipped ones are still here",
    ("openfactory/onboarding/deployment.py", "render"):
        "the same generator's blocks for the other two shipped vendors",
    ("openfactory/registry.py", "_spanning_message"):
        "one process holds one App installation, which belongs to one organisation: a limit of "
        "one vendor's credential, checked here by `github_owners`",
    ("openfactory/registry.py", "_warn_foreign_pointers"):
        "the same limit, as a warning",
    ("openfactory/techlead/classify.py", "_RULES"):
        "a PATTERN over one vendor's refusal text, not a sentence anybody reads",
}


def _findings(rel: str, exempt: frozenset[str] = frozenset()) -> list[str]:
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    words = _shipped_names() | STRANGERS | _shipped_variables()
    kinds = _vendor_kinds() | STRANGER_KINDS
    said = [f"{rel}:{n}: in `{scope}` — {text[:100]!r}"
            for n, scope, text in vendor_sentences(tree, words, kinds, exempt)]
    chosen = [f"{rel}:{n}: in `{scope}` — words chosen by the kind {kind}"
              for n, scope, kind in vendor_branches(tree, kinds, exempt)]
    return said + chosen


def test_the_second_rule_knows_the_vendors_words() -> None:
    """The positive twin: an empty vocabulary passes everything."""
    assert {"github", "azure_devops", "jira"} <= _vendor_kinds()
    assert "local" not in _vendor_kinds(), "`local` needs no credential: this machine, no vendor"
    assert {"AZURE_DEVOPS_PAT", "JIRA_API_TOKEN"} <= _shipped_variables()


def test_no_generic_module_says_a_vendors_sentence() -> None:
    offenders = []
    for rel in _generic_modules():
        offenders += _findings(rel, frozenset(n for path, n in LEDGER if path == rel))

    assert not offenders, (
        "generic code says a vendor's words, or chooses words by a vendor's kind — so a row it "
        "has never heard of is told somebody else's remedy, and saying the right one means "
        "editing the core. Declare the sentence on the row and ask it (`plugins.sentence`):\n  "
        + "\n  ".join(offenders))


def test_the_second_rule_can_see_the_offence_and_only_the_offence() -> None:
    planted = ast.parse(
        'def remedy(kind, options):\n'
        '    """A docstring about GitHub and AZURE_DEVOPS_PAT, which is prose and must not count."""\n'
        '    default = {"github": "OPENFACTORY_BOT_TOKEN"}.get(kind, "github")\n'
        '    where = "https://github.com/settings/tokens or docs/setup/github.md"\n'
        '    if kind == "github":\n'
        '        return "create a GitHub App and install it"\n'
        '    if kind == "jira":\n'
        '        return "check that the account can browse the project"\n'
        '    if kind in ("azure_devops", "local"):\n'
        '        client = build(kind)\n'
        '    shape = f"{options[0]}/{options[1]}" if kind == "gitlab" else options[0]\n'
        '    note = "set AZURE_DEVOPS_PAT for this process"\n'
        '    list_of = "one of github, gitlab or jira is what this build ships"\n'
        '    return default, where, client, shape, note, list_of\n'
        'WHY = {"jira": "the project is the board, so there is nothing to create"}\n')
    words = frozenset({"GitHub", "AZURE_DEVOPS_PAT"})
    kinds = frozenset({"github", "jira", "azure_devops", "gitlab"})

    assert [(n, scope) for n, scope, _ in vendor_sentences(planted, words, kinds)] == [
        (6, "remedy"), (12, "remedy"), (13, "remedy")], (
        "the name in a sentence, the variable in a sentence and the kinds in prose — and not the "
        "key, the default, the host, the path or the docstring")
    assert [(n, kind) for n, _, kind in vendor_branches(planted, kinds)] == [
        (5, "github"), (7, "jira"), (11, "gitlab"), (15, "jira")], (
        "two branches that SAY something, a format chosen by kind and a table of sentences — and "
        "not the branch that only builds a client, nor the table of variables")
    assert not vendor_sentences(planted, words, kinds, frozenset({"remedy"}))
    assert [n for n, _, _ in vendor_branches(planted, kinds, frozenset({"remedy"}))] == [15], (
        "an exemption is by the name of the function or the assignment, and only it")


def test_every_ledger_entry_still_names_something_that_is_there() -> None:
    """A ledger nobody prunes is a standing permission for the next offence in that function."""
    for (rel, name), why in LEDGER.items():
        others = frozenset(n for path, n in LEDGER if path == rel and n != name)
        with_it = _findings(rel, others)
        assert with_it, f"{rel}::{name} names no vendor now — delete its entry ({why})"
        assert not _findings(rel, others | {name}), f"{rel}: a finding outside `{name}`"


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


# ═══ what a row SAYS: the one rule, the shipped rows, and a stranger's ═══════════════════════════

_CREDENTIAL_VARS = (
    "ACME_TOKEN", "AZURE_DEVOPS_PAT", "JIRA_API_TOKEN", "OPENFACTORY_FORGE_TOKEN",
    "OPENFACTORY_BOT_TOKEN", "OPENFACTORY_TRACKER_TOKEN", "OPENFACTORY_GH_APP_ID",
    "OPENFACTORY_GH_APP_INSTALLATION_ID", "OPENFACTORY_GH_APP_KEY",
    "OPENFACTORY_GH_APP_KEY_CONTENT",
)


def test_only_a_non_empty_string_is_a_sentence(caplog) -> None:
    row = SimpleNamespace(when_missing=" run `acme login` ", blank="  ",
                          coordinates=lambda project: f"acme-hq/{project}",
                          broken=lambda project: 1 / 0)

    assert plugins.sentence(row, "when_missing", "generic") == "run `acme login`"
    assert plugins.sentence(row, "coordinates", "?", "api") == "acme-hq/api", "asked ABOUT something"
    assert plugins.sentence(row, "blank", "generic") == "generic"
    assert plugins.sentence(row, "never_heard_of_it", "generic") == "generic"
    assert plugins.sentence(None, "when_missing", "generic") == "generic", "no row at all"
    assert plugins.sentence(MagicMock(), "when_missing", "generic", "api") == "generic", (
        "a test double answers every attribute and every call, and is not a declaration")
    with caplog.at_level("WARNING", logger="openfactory.plugins"):
        assert plugins.sentence(row, "broken", "generic", "api") == "generic"
    assert "`broken` raised" in caplog.text, "a row's words that raise are said so, not swallowed"


def test_the_shipped_rows_say_what_generic_code_used_to_spell() -> None:
    github, azure = cred.credential_row("github"), cred.credential_row("azure_devops")

    assert "OPENFACTORY_GH_APP_ID" in github.when_missing and "GitHub App" in github.when_refused
    assert "az login" in azure.when_missing and "AZURE_DEVOPS_PAT" in azure.when_missing
    assert "Code (Read & write)" in azure.when_refused and "GitHub" not in azure.when_refused
    for kind in sorted(_vendor_kinds()):
        row = boards.BOARDS[kind]
        assert callable(getattr(row, "coordinates", None)), f"board.{kind} cannot say WHICH board"
        assert plugins.sentence(row, "when_unreadable", "", _a_project(kind)), (
            f"board.{kind} has no remedy of its own for a board that could not be read")
        assert plugins.display_name(row, ""), f"board.{kind} is shown by its key"
    for kind in ("github", "azure_devops"):
        assert plugins.sentence(forges.FORGES[kind], "when_unreadable", ""), kind


def _a_project(kind: str, **options: str) -> Project:
    ref = ProviderRef(kind=kind, repo="hq/api", options=options)
    return Project(name="podbeam", repo_path="/tmp/podbeam", tracker=ref, forge=ref)


@pytest.mark.parametrize(("kind", "options", "where"), [
    ("github", {"board_owner": "AcmeFixtures", "board_number": "1"}, "AcmeFixtures/1"),
    ("azure_devops", {"organization": "acme", "project": "Deskline"}, "acme/Deskline"),
    ("jira", {"site": "acme.atlassian.net", "project_key": "CONT"}, "acme.atlassian.net CONT"),
])
def test_each_shipped_board_is_located_in_its_own_coordinates(kind, options, where) -> None:
    """What the doctor's three branches answered, answered by the rows — unchanged."""
    assert doctor._board_coordinates(_a_project(kind, **options)) == where  # noqa: SLF001


# ── a stranger's vendor, through the doctor's REAL findings ─────────────────────────────────────

class _RefusingForge:
    def pr_status(self, *, pr, repo=""):
        raise RuntimeError("GET /pulls/1 → 401 Unauthorized")


class _UnreadableBoard:
    def column_names(self):
        return None  # the port's "could not read"


def _acme_credential():
    return cred.CredentialRow(
        env="ACME_TOKEN",
        when_missing="run `acme login`, or set ACME_TOKEN — the Acme console issues one a workspace",
        when_refused="renew the token in the Acme console: they last thirty days")


def _quiet_credential():
    return cred.CredentialRow(env="ACME_TOKEN")


def _acme_forge(project, **kw):
    return _RefusingForge()


def _quiet_forge(project, **kw):
    return _RefusingForge()


def _acme_board(project, *, token, token_provider, options):
    return _UnreadableBoard()


def _quiet_board(project, *, token, token_provider, options):
    return _UnreadableBoard()


_acme_forge.when_unreadable = "On Acme specifically: a repository is private to its workspace."
_acme_board.display_name = "Acme Boards"
_acme_board.coordinates = lambda project: f"{project.tracker.options['workspace']}:{project.tracker.repo}"
_acme_board.when_unreadable = lambda project: (
    f"check that {project.tracker.options.get('token_env') or 'ACME_TOKEN'} may read the "
    f"workspace — the Acme console lists what a token covers")


@pytest.fixture
def a_vendor_nobody_heard_of(monkeypatch):
    """`credential.acme`, `forge.acme` and `board.acme`, served through the real entry-point
    mechanism, on a machine that holds no credential of anybody's."""
    for name in _CREDENTIAL_VARS:
        monkeypatch.delenv(name, raising=False)

    def install(*, credential, forge=_acme_forge, board=_acme_board) -> Project:
        vendor_addons.install(monkeypatch, declared_rows=False, extra=tuple(
            SimpleNamespace(name=f"{axis}.acme", value=f"acme:{axis}", load=lambda row=row: row)
            for axis, row in (("credential", credential), ("forge", forge), ("board", board))))
        return _a_project("acme", workspace="acme-hq")
    return install


def _names_a_vendor(text: str) -> list[str]:
    """Every shipped vendor's word in `text` — by the RULE's own vocabulary, not a list here."""
    return [word for word in sorted(_shipped_names() | _shipped_variables() | STRANGERS)
            if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text)] + [
        marker for marker in ("OPENFACTORY_GH_APP", "OPENFACTORY_BOT_TOKEN") if marker in text]


def _the_forge_finding(project) -> doctor.Finding:
    """The REAL forge probes of this project under the real `diagnose`, every other probe pinned."""
    real = doctor.probes_for(project)
    report = doctor.diagnose(a_fully_pinned_probe_set(
        forge_reachable=real.forge_reachable, forge_remedy=real.forge_remedy))
    return next(f for f in report.findings if f.check == "forge_access")


def test_a_strangers_own_remedy_reaches_the_doctors_finding(a_vendor_nobody_heard_of) -> None:
    finding = _the_forge_finding(a_vendor_nobody_heard_of(credential=_acme_credential))

    assert not finding.ok and "no forge credential" in finding.message
    assert finding.remedy.startswith("run `acme login`, or set ACME_TOKEN"), finding.remedy
    assert not _names_a_vendor(finding.remedy), finding.remedy


def test_and_so_do_its_words_for_a_credential_the_forge_refused(a_vendor_nobody_heard_of,
                                                                monkeypatch) -> None:
    project = a_vendor_nobody_heard_of(credential=_acme_credential)
    monkeypatch.setenv("ACME_TOKEN", "expired")

    finding = _the_forge_finding(project)

    assert not finding.ok and "refused" in finding.message and "401" in finding.message
    assert finding.remedy.startswith("renew the token in the Acme console"), finding.remedy
    assert "registry entry" in finding.remedy, "where the probe's coordinates came from is still said"


def test_a_row_that_says_nothing_is_told_its_own_variable_and_no_vendors_remedy(
        a_vendor_nobody_heard_of, monkeypatch) -> None:
    """The add-on that never heard of `when_missing`: degraded honestly, from what it DID declare.
    Before, it was sent to create a GitHub App."""
    project = a_vendor_nobody_heard_of(credential=_quiet_credential)

    missing = _the_forge_finding(project)
    monkeypatch.setenv("ACME_TOKEN", "expired")
    refused = _the_forge_finding(project)

    assert "set ACME_TOKEN" in missing.remedy and "forge.options.token_env" in missing.remedy
    assert "has not expired" in refused.remedy and "forge.options.token_env" in refused.remedy
    assert not _names_a_vendor(missing.remedy + refused.remedy), (missing.remedy, refused.remedy)


def test_with_no_probe_to_ask_the_finding_names_no_vendor() -> None:
    """An older `Probes` — and every test that fakes the probe — has no row to ask."""
    for detail in ("no forge credential is configured", "GET /pulls/1 → 401 Unauthorized"):
        finding = doctor._forge(a_fully_pinned_probe_set(  # noqa: SLF001
            forge_reachable=lambda detail=detail: (False, detail), forge_remedy=None))

        assert not finding.ok and len(finding.remedy) > 40, "a red finding owes a remedy"
        assert not _names_a_vendor(finding.remedy), finding.remedy


def test_one_vendors_refused_credential_is_not_answered_with_anothers_remedy(monkeypatch) -> None:
    """Measured before: an Azure DevOps PAT that expired read "a GitHub App: grant it access"."""
    for name in _CREDENTIAL_VARS:
        monkeypatch.delenv(name, raising=False)
    azure = doctor.probes_for(_a_project("azure_devops", organization="acme", project="Deskline"))

    finding = doctor._forge(a_fully_pinned_probe_set(  # noqa: SLF001
        forge_reachable=lambda: (False, "POST … → 401 Unauthorized"),
        forge_remedy=azure.forge_remedy))

    assert "Code (Read & write)" in finding.remedy and "GitHub" not in finding.remedy


def test_a_strangers_board_is_located_and_remedied_in_its_own_words(
        a_vendor_nobody_heard_of) -> None:
    project = a_vendor_nobody_heard_of(credential=_acme_credential)

    finding = doctor._board(doctor.probes_for(project))  # noqa: SLF001

    assert not finding.ok and "the board acme-hq:hq/api is configured" in finding.message
    assert finding.remedy.startswith("check that ACME_TOKEN may read the workspace")


def test_a_board_that_says_nothing_is_located_by_its_repo_and_given_the_generic_remedy(
        a_vendor_nobody_heard_of) -> None:
    """It was located in ANOTHER vendor's option names (`site`, `project_key`)."""
    project = a_vendor_nobody_heard_of(credential=_quiet_credential, board=_quiet_board)

    finding = doctor._board(doctor.probes_for(project))  # noqa: SLF001

    assert "the board hq/api is configured" in finding.message
    assert "tracker.options.token_env" in finding.remedy
    assert not _names_a_vendor(finding.remedy), finding.remedy


# ── the command, the page's payload, and the page ───────────────────────────────────────────────

def _declare(monkeypatch, tmp_path, project: Project) -> str:
    from typer.testing import CliRunner

    from openfactory.cli import app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    ProjectRegistry().add(project)
    monkeypatch.setattr("openfactory.product.onboard.context_reachability",
                        lambda project, repo: (False, "the runtime credential cannot read it"))
    result = CliRunner().invoke(app, ["product", "declare", project.name, "hq/docs"])
    assert result.exit_code == 1 and "RECORDED, BUT NOT READABLE" in result.output, result.output
    return result.output


def test_product_declare_offers_the_forges_own_likely_cause(a_vendor_nobody_heard_of,
                                                            monkeypatch, tmp_path) -> None:
    project = a_vendor_nobody_heard_of(credential=_acme_credential)

    said = _declare(monkeypatch, tmp_path, project)

    assert "On Acme specifically: a repository is private to its workspace." in said
    assert "GitHub" not in said and "Azure" not in said


def test_and_a_forge_that_offers_none_is_offered_nobody_elses(a_vendor_nobody_heard_of,
                                                              monkeypatch, tmp_path) -> None:
    project = a_vendor_nobody_heard_of(credential=_acme_credential, forge=_quiet_forge)

    said = _declare(monkeypatch, tmp_path, project)

    assert "specifically" not in said and "GitHub" not in said and "Azure" not in said


def test_the_cause_is_the_FORGES_because_the_forge_reads_the_repository(monkeypatch,
                                                                        tmp_path) -> None:
    """It was chosen over the forge AND the tracker: an Azure Repos repository whose cards live
    on GitHub was offered GitHub's cause about a repository GitHub never sees."""
    mixed = Project(name="podbeam", repo_path="/tmp/podbeam",
                    tracker=ProviderRef(kind="github", repo="hq/api"),
                    forge=ProviderRef(kind="azure_devops", repo="api",
                                      options={"organization": "acme", "project": "Deskline"}))

    said = _declare(monkeypatch, tmp_path, mixed)

    assert "On Azure DevOps specifically" in said and "On GitHub specifically" not in said


def _init(monkeypatch, where: Path, url: str) -> str:
    """`project add` then `project init`, with a tracker that has no board to CREATE."""
    from typer.testing import CliRunner

    from openfactory.cli import app

    where.mkdir()
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(where / "registry.yaml"))
    for name in (*_CREDENTIAL_VARS, "GH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("openfactory.adapters.board_setup.registry.board_creator",
                        lambda kind: None)
    monkeypatch.chdir(where)
    added = CliRunner().invoke(app, ["project", "add", "demo", url])
    assert added.exit_code == 0, added.output
    result = CliRunner().invoke(app, ["project", "init", "demo"])
    assert result.exit_code == 0 and "brings its own" in result.output, result.output
    return result.output


def test_a_board_there_is_nothing_to_create_for_says_its_own_setup(monkeypatch, tmp_path) -> None:
    """The line ended "(azure_devops states: docs/setup/azure-devops.md §3)" for EVERY tracker."""
    azure = _init(monkeypatch, tmp_path / "a", "https://dev.azure.com/acme/Deskline/_git/api")
    other = _init(monkeypatch, tmp_path / "b", "https://github.com/acme/demo.git")

    assert "work item states" in azure and "azure-devops.md §3" in azure
    assert "azure" not in other.lower(), "one vendor's recipe, offered to another's tracker"


def test_the_cockpits_payload_names_the_hosted_boards_by_their_rows(a_vendor_nobody_heard_of):
    from openfactory.api import app as api

    a_vendor_nobody_heard_of(credential=_acme_credential)

    hosted = api._hosted_boards()  # noqa: SLF001

    assert {"GitHub Projects", "Azure Boards", "Jira", "Acme Boards"} <= set(hosted)
    assert plugins.display_name(boards.BOARDS["local"], "") not in hosted, (
        "the page already says this panel holds one itself — `hosted` is the others")


def test_and_the_route_carries_it(tmp_path, monkeypatch) -> None:
    from starlette.testclient import TestClient

    from openfactory.api import app as api

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKEN", raising=False)
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKENS", raising=False)
    monkeypatch.setattr("openfactory.registry.ProjectRegistry.get",
                        lambda self, name: _a_project("github"))

    body = TestClient(api.app).get("/api/factory/podbeam").json()

    assert body["hosted_boards"] == api._hosted_boards() != []  # noqa: SLF001


def _what_the_page_says() -> str:
    """`panel.html` with its comments removed — what is left is what a browser runs and shows."""
    text = (PACKAGE / "api" / "panel.html").read_text(encoding="utf-8")
    text = re.sub(r"<!--.*?-->|/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"""(?<![:"'])//[^\n]*""", "", text)


def test_the_page_spells_no_board_and_draws_the_servers_list() -> None:
    page = _what_the_page_says()
    assert "this panel holds one itself" in page and len(page) > 100_000, "the how-to moved"

    spelled = [name for name in boards.board_names(hosted=False) if name in page]

    assert not spelled, f"panel.html spells {spelled}: an add-on's board is not in that sentence"
    assert "f.hosted_boards" in page, "the how-to no longer draws the list the server sends"
