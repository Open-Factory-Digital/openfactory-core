"""The page PyPI shows describes the project, and every promise on it can be followed (#368).

MEASURED ON 0.4.0: the project's page on the index said "The author of this package has not
provided a project description". `pyproject.toml` declared a one-line `description` and no
`readme`, so the wheel carried no long description and the index had nothing to show the person who
had just arrived there — the one visitor who is a single command away from installing it.

THE README COULD NOT SIMPLY BE POINTED AT, and that is why the page is its own file:

  · its links are relative (`docs/STATUS.md`, `LICENSE`), and the index resolves none of them — a
    relative link on the index is a dead link on the project's front page;
  · its one-machine door starts from `git clone` and `pip install -e`, while a visitor on the index
    has the other door in hand — `pip install` of the name — and that door had been measured to
    work (a clean Python 3.12 venv installed 0.4.0 with its `runtime` extra, and `openfactory
    init --runtime local` in a clean `$HOME` wrote `~/.openfactory/env` at 0600 and named
    `openfactory up` as the next step).

So `docs/pypi.md` is written for the index, and each guard here holds one way it can stop being
true without any build going red: the declaration and the file; every link absolute; every command
one this CLI has; every extra one this package declares; every harness the registry ships and no
other; the metadata a visitor reads beside the page. The wheel guard
(`test_the_wheel_ships_what_the_platform_needs.py`) reads the description back out of a BUILT
wheel's METADATA, which is the only place the upload's text is knowable; the last test here renders
it the way the index does, and skips by name where the renderer is not installed.
"""

from __future__ import annotations

import ast
import re
import subprocess
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from test_the_docs_do_not_drift import _the_cli_tree

ROOT = Path(__file__).resolve().parents[1]
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]

#: Where this project's files are served from on the forge, read off the package's own metadata —
#: the base every link to a file of this tree must start from.
REPOSITORY = PROJECT["urls"]["Repository"].rstrip("/")


def _declared_page() -> Path:
    readme = PROJECT.get("readme")
    assert isinstance(readme, dict) and readme.get("file"), (
        f"pyproject.toml declares no long-description FILE (readme = {readme!r}) — the index shows "
        f"'The author of this package has not provided a project description'")
    return ROOT / readme["file"]


def _page() -> str:
    return _declared_page().read_text(encoding="utf-8")


# ── the declaration ─────────────────────────────────────────────────────────────────────────────

def test_the_package_declares_the_page_and_the_page_exists():
    """Declared as markdown, present in the tree, and TRACKED — an untracked page builds on the
    machine that wrote it and on no other, which is the shape of the `floor.yaml` defect the wheel
    guard was written for."""
    readme = PROJECT["readme"]
    page = _declared_page()

    assert readme.get("content-type") == "text/markdown", (
        f"the page is declared as {readme.get('content-type')!r} — the index renders it as plain "
        f"text, and every heading and link on it is a row of punctuation")
    assert page.is_file(), f"pyproject.toml declares {readme['file']}, and there is no such file"
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", readme["file"]], cwd=ROOT,
                             capture_output=True, timeout=60)
    assert tracked.returncode == 0, f"{readme['file']} is not tracked, so no build but this one has it"
    assert page.resolve() != (ROOT / "README.md").resolve(), (
        "the page is the README again — its relative links are dead on the index and its door "
        "starts from a clone")


# ── every link absolute ─────────────────────────────────────────────────────────────────────────

#: `[text](target)` and `![alt](target)`, with an optional title after the target.
_INLINE = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]*)>?(?:\s+\"[^\"]*\")?\s*\)")
#: `[label]: target` — a reference definition, at the start of a line.
_REFERENCE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)", re.M)
#: `<https://…>` — an autolink.
_AUTOLINK = re.compile(r"<((?:[a-z][a-z0-9+.-]*:)[^>\s]*)>", re.I)
#: `href="…"` / `src="…"` in raw HTML, either quote.
_HTML = re.compile(r"\b(?:href|src)\s*=\s*[\"']([^\"']*)[\"']", re.I)


def _outside_code(text: str) -> str:
    """The page without its fenced blocks and inline code — what the renderer turns into links.
    A `<owner>` inside a command is a placeholder, not an autolink."""
    text = re.sub(r"^```.*?^```", "", text, flags=re.M | re.S)
    return re.sub(r"`[^`\n]*`", "", text)


def _links(text: str) -> list[str]:
    """Every target a reader can click or an image the renderer fetches, in the four shapes
    markdown has for one."""
    prose = _outside_code(text)
    return [m.group(1) for pattern in (_INLINE, _REFERENCE, _AUTOLINK, _HTML)
            for m in pattern.finditer(prose)]


def _not_absolute(targets: list[str]) -> list[str]:
    """The targets the index cannot resolve: anything that is not `https://host/…`. An anchor
    alone (`#section`) is one of them — the index gives headings no ids of its own."""
    return [t for t in targets
            if not (urlsplit(t).scheme == "https" and urlsplit(t).netloc)]


def _repository_files(targets: list[str]) -> list[tuple[str, str]]:
    """(link, path in this tree) for every link to a FILE of this repository on the forge."""
    out = []
    for target in targets:
        m = re.match(re.escape(REPOSITORY) + r"/(?:blob|tree)/[^/]+/([^#?]+)", target)
        if m:
            out.append((target, m.group(1)))
    return out


def test_every_link_and_image_on_the_page_is_absolute():
    targets = _links(_page())

    assert len(targets) >= 5, f"the scan found {targets} — the pattern is wrong, or the page lost its links"
    assert not _not_absolute(targets), (
        f"the page links to {_not_absolute(targets)} — the index resolves no relative link, so each "
        f"is a dead link on the project's front page; write it as https://… (the website, or "
        f"{REPOSITORY}/blob/main/<path>)")


def test_every_file_the_page_links_to_is_in_this_tree():
    """Absolute is necessary and not sufficient: `blob/main/docs/STATUS.md` is absolute and a 404
    the day the file moves. The page's links and the package's own `project.urls` are read the
    same way, because both are what a visitor on the index clicks."""
    linked = _repository_files(_links(_page()) + list(PROJECT["urls"].values()))

    assert linked, "the page links to no file of this repository — the scan has no subject"
    missing = [link for link, rel in linked if not (ROOT / rel).exists()]
    assert not missing, f"these links name files this tree does not have: {missing}"


def test_the_link_scan_can_SEE_every_shape_a_relative_link_takes():
    """Verify the verifier, on the shapes the README actually uses and the ones markdown allows."""
    for planted in ("see [the status](docs/STATUS.md)", "![badge](docs/badge.svg)",
                    "[below](#the-coding-agents)", "[licence][l]\n\n[l]: LICENSE",
                    '<a href="SECURITY.md">security</a>', '<img src="logo.png">',
                    "[help](http://openfactory.digital)"):
        assert _not_absolute(_links(planted)), f"the scan let {planted!r} through"
    for fine in ("[site](https://openfactory.digital)",
                 f"[status]({REPOSITORY}/blob/main/docs/STATUS.md)",
                 "`cd openfactory && exec worker <owner>`",
                 "```bash\ncurl -fsSL https://openfactory.digital/install.sh | sh\n```"):
        assert _not_absolute(_links(fine)) == [], fine
    assert _repository_files([f"{REPOSITORY}/blob/main/docs/NOPE.md#x"]) == [
        (f"{REPOSITORY}/blob/main/docs/NOPE.md#x", "docs/NOPE.md")]


# ── every command one this CLI has ──────────────────────────────────────────────────────────────

#: `openfactory <command> [<subcommand>]` anywhere in a command — after `&&`, after `exec worker`,
#: at the start of a continuation line — and never `openfactory[extra]`, `openfactory-cli` or
#: `openfactory.digital`, which are names, not invocations.
_INVOCATION = re.compile(
    r"(?<![\w./-])openfactory[ \t]+([a-z][a-z0-9-]*)(?:[ \t]+([a-z][a-z0-9_-]*))?")


def _code(text: str) -> list[str]:
    """Every fenced block and every inline code span: what a reader copies."""
    fenced = re.findall(r"^```[^\n]*\n(.*?)^```", text, flags=re.M | re.S)
    return fenced + re.findall(r"`([^`\n]+)`", re.sub(r"^```.*?^```", "", text, flags=re.M | re.S))


def _invocations(text: str) -> list[tuple[str, str | None]]:
    return [(m.group(1), m.group(2)) for block in _code(text)
            for m in _INVOCATION.finditer(block)]


def _not_commands(invocations: list[tuple[str, str | None]]) -> list[str]:
    tree = _the_cli_tree()
    wrong = []
    for top, sub in invocations:
        if top not in tree:
            wrong.append(f"`openfactory {top}` is not a command")
        elif tree[top] and sub not in tree[top]:
            wrong.append(f"`openfactory {top} {sub or ''}` names no subcommand of {top} "
                         f"(it has: {', '.join(sorted(tree[top]))})")
    return wrong


def test_every_command_the_page_hands_a_reader_is_one_this_cli_has():
    """`docs/setup/one-machine.md` once said `openfactory panel`, which does not exist — measured
    by walking the page as written (2026-09-11). On the index there is no tree beside the page to
    notice, so the page is held to the CLI it ships with."""
    found = _invocations(_page())

    assert not _not_commands(found), (
        "the page tells a reader to type something this build cannot run:\n"
        + "\n".join(_not_commands(found)))
    # THE DOOR THE PAGE EXISTS FOR, as the issue measured it: the deployment's file, the project,
    # the check, the start. A page that lost one of these still passes the rule above. A leaf
    # command's argument is not part of its name, so it is dropped before comparing.
    tree = _the_cli_tree()
    named = {(top, sub if tree.get(top) else None) for top, sub in found}
    door = {("init", None), ("project", "init"), ("doctor", None), ("up", None)}
    assert door <= named, f"the one-machine door is missing {sorted(door - named, key=str)}"


def test_the_command_scan_can_SEE_a_command_this_cli_does_not_have():
    for planted in ("```bash\nopenfactory panel\n```", "run `openfactory dashboard`",
                    "```bash\ncd of && docker compose exec worker \\\n  openfactory project create x\n```",
                    "```\nopenfactory box\n```"):
        assert _not_commands(_invocations(planted)), f"the scan let {planted!r} through"
    # the install line is built rather than spelled: the bare-name rule
    # (test_the_remedy_a_refusal_hands_you_can_be_followed.py) reads every tracked file, this one too
    for fine in (f"```bash\npip install '{PROJECT['name']}[runtime]'\ncd openfactory && ls\n```",
                 "the `openfactory-cli` image", "`openfactory up`"):
        assert not _not_commands(_invocations(fine)), fine


# ── every extra one this package declares ───────────────────────────────────────────────────────

_EXTRAS = re.compile(r"(?<![\w-])openfactory\[([^\]]+)\]")


def _named_extras(text: str) -> set[str]:
    return {extra.strip() for m in _EXTRAS.finditer(text) for extra in m.group(1).split(",")}


def test_every_extra_the_page_names_is_one_the_package_declares():
    """An install of the core with an extra it does not declare installs the core, WARNS that the
    extra does not exist, and exits 0 — so a page naming an extra that was renamed hands the reader
    an install that looks fine and lacks the half they asked for."""
    named = _named_extras(_page())
    declared = set(PROJECT["optional-dependencies"])

    assert "runtime" in named, f"the page names {sorted(named)} and not the extra the worker runs on"
    assert named <= declared, (
        f"the page names extras {sorted(named - declared)} that pyproject.toml does not declare "
        f"(it declares {sorted(declared)})")
    assert _named_extras(f"'{PROJECT['name']}[runtime, nope]'") == {"runtime", "nope"}


# ── every harness the registry ships, and no other ──────────────────────────────────────────────

def _harness_rows(text: str) -> set[str]:
    """The `harness:` column of the page's table of coding agents: a row's second cell, when it is
    one backticked kind."""
    return set(re.findall(r"^\|[^|\n]*\|\s*`([a-z][a-z0-9_]*)`\s*\|", text, flags=re.M))


def test_the_page_lists_every_harness_the_registry_ships_and_no_other():
    """The README names the four agents in one breath; the page says where each one STANDS,
    because one of them does not run today (#362). A harness added to the registry and missing
    here is a status nobody wrote down; a row for a retired one is a promise nobody keeps."""
    from openfactory.adapters.agent.registry import HARNESSES

    assert _harness_rows(_page()) == set(HARNESSES), (
        f"the registry ships {sorted(HARNESSES)} and the page's table lists "
        f"{sorted(_harness_rows(_page()))}")


# ── the metadata a visitor reads beside the page ────────────────────────────────────────────────

def _imports_fcntl_at_module_scope() -> list[str]:
    hits = []
    for path in sorted((ROOT / "openfactory").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            if "fcntl" in names:
                hits.append(str(path.relative_to(ROOT)))
    return hits


def test_the_metadata_beside_the_page_says_where_to_read_more_and_where_it_runs():
    """The sidebar of the index's page: the documentation, the changelog and the security policy
    each one click away, and the operating systems the package can actually run on.

    THE SYSTEMS ARE DERIVED, NOT CHOSEN. `fcntl` does not exist on Windows, and a module that
    imports it at module scope fails to import there — `openfactory/registry.py` is one, so the
    CLI cannot register a project. While that holds, a classifier claiming Windows or
    `OS Independent` is a promise the first command breaks."""
    urls = PROJECT["urls"]
    for label in ("Documentation", "Changelog", "Security"):
        assert label in urls, f"project.urls has no {label!r} — the sidebar does not offer it"
        assert not _not_absolute([urls[label]]), f"project.urls[{label!r}] = {urls[label]!r}"
    assert urls["Changelog"].rstrip("/").endswith("/releases"), urls["Changelog"]

    classifiers = PROJECT["classifiers"]
    assert "Environment :: Console" in classifiers, "the package does not say it is a console tool"
    systems = [c for c in classifiers if c.startswith("Operating System ::")]
    assert systems, "no operating system is declared"
    if _imports_fcntl_at_module_scope():
        wrong = [c for c in systems if "Windows" in c or "Independent" in c]
        assert not wrong, (
            f"the classifiers claim {wrong}, and {_imports_fcntl_at_module_scope()} import "
            f"`fcntl`, which Windows does not have")


# ── rendered as the index renders it ────────────────────────────────────────────────────────────

def test_the_page_renders_the_way_the_index_renders_it():
    """The index renders a markdown description with `readme_renderer` (GitHub-flavoured) and
    SANITISES the result; `twine check` asks the same library. A description that
    fails to render is shown as nothing at all, and a link the sanitiser strips is a word that no
    longer goes anywhere — neither is visible from the source.

    `readme-renderer[md]` IS IN THE `dev` EXTRA, so CI — which installs `dev` — runs this. It is
    still SKIPPED BY NAME where the library is absent: a venv made before it joined `dev`, or one
    that cannot reach an index to fetch it, says so here rather than failing on an import.

    SKIPPED BY CAPABILITY, NEVER BY A BACKEND'S NAME (review of #542). This skipped on `cmarkgfm`,
    and readme-renderer 46 renders GitHub-flavoured markdown through `comrak` instead: with `dev`
    installed the guard skipped everywhere, CI included, and checked nothing. It now asks the
    renderer to render, and skips only when the renderer itself cannot be imported."""
    markdown = pytest.importorskip(
        "readme_renderer.markdown",
        reason="readme_renderer is not installed — the renderer the index uses, in the `dev` "
               "extra (`readme-renderer[md]`); reinstall `dev` where this guard must run")
    text = _page()
    try:
        html = markdown.render(text, variant="GFM")
    except ImportError as exc:      # the GFM backend of this readme-renderer is absent
        pytest.skip(f"readme_renderer cannot render GitHub-flavoured markdown here ({exc}) — "
                    f"reinstall `dev`, whose `readme-renderer[md]` brings the backend")

    assert html, "the description does not render — the index would show it as nothing"
    stripped = [t for t in _links(text) if f'href="{t}"' not in html and f'src="{t}"' not in html]
    assert not stripped, f"the renderer dropped these links: {stripped}"
