"""No document and no refusal may hand somebody `pip install <a name this tree publishes nowhere>`.

THE ONE REMEDY A STUCK OPERATOR HAD WAS A COMMAND THAT FAILS (pre-launch audit, 2026-08-26).
A project declaring a chat channel on a core without the package was refused — correctly, by
name — and the sentence ended `pip install openfactory-slack`. That name resolves on no index:
nothing in this repository publishes a distribution anywhere, and `docs/STATUS.md`'s own table
called the packages private twenty lines from the page that repeated the command. So the
platform's help at the moment it refused to run was a 404, in three places at once (the runtime
refusal, `docs/README.md`, `docs/STATUS.md`) — and reserving the empty names on an index would
have been worse: a name that installs a stub is a name that installs nothing while looking
installed.

WHAT THIS GUARD PINS IS THE CAUSE, NOT THE THREE SITES. A bare-name `pip install` is a promise
that an index serves that name. This tree makes no such promise — it holds no publish step at
all — so the class rule is: while nothing here publishes, nothing here may spell that command
for one of our own distributions. Say where the row comes from and what entry point answers for
it instead; both are true today, and the second is the whole contract a stranger needs to write
the package themselves.

THE DAY SOMEBODY DOES PUBLISH, this guard skips by name rather than lying in either direction —
the premise it is built on has changed, and the sentence it forbids has become true.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import tomllib

# `pytest` was imported for the wholesale `pytest.skip` this file used to take the day anything
# started publishing. It no longer skips: publishing became a PER-DISTRIBUTION fact on 2026-08-30
# (the core is served, the add-on packages are not), so the rule narrows instead of standing down.
from openfactory import plugins

ROOT = pathlib.Path(__file__).resolve().parents[1]

def our_distributions() -> set[str]:
    """Every distribution this repository builds — the core, plus each package the platform's own
    rows ship in. `plugins.SHIPS_IN` lives in the core, so this answers in the public tree too,
    where `addons/` is absent and there is nothing else to read the names off."""
    core = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["name"]
    return {core, *plugins.SHIPS_IN.values()}


#: THE VERB IS A CLASS, NOT A COMMAND. `pip install` was the only spelling this scanned, and
#: `pip3 install`, `uv add`, `uv pip install`, `poetry add` and `pipx install` all walked past it
#: while handing a reader exactly the same unfollowable name (reviewer's cuts, 2026-08-26). What
#: the rule is about is a command that resolves a DISTRIBUTION NAME on an index, so every
#: installer that does that is here, and `python -m pip` reduces to the same verb.
_INSTALLER = (r"(?:pip[0-9.]*|pipx|uv[ \t]+pip|conda|mamba)[ \t]+install"
              r"|(?:uv|poetry|pdm|rye|hatch)[ \t]+add")

#: `<installer> [-flags] <target>` — the target is what a reader would actually type.
_PIP_INSTALL = re.compile(rf"(?:{_INSTALLER})\s+((?:-{{1,2}}[A-Za-z][\w-]*(?:[ \t]+\S+)?[ \t]+)*)"
                          r"['\"]?([^\s'\"`,)]+)")

#: What a publish step looks like, in whatever runs one: CI, the Makefile, a script.
_PUBLISHES = re.compile(r"twine\s+upload|gh-action-pypi-publish|(?:flit|poetry|uv|hatch)\s+publish"
                        r"|pypi-publish", re.IGNORECASE)

#: SOMEWHERE A NAME RESOLVES. `_PIP_INSTALL` catches the command; this catches the PROMISE, which
#: is the half a rewrite kept while dropping the command — "ships in openfactory-slack, available
#: from PyPI" is green under every rule above and is false in this tree, which publishes nothing.
#: A remedy may say the opposite, and the real one does ("which is on no public index"), so the
#: mention is an offence only where no denial stands directly in front of it.
_AN_INDEX = re.compile(r"\bpypi\b|\bpublic index\b|\bpackage index\b|\bindex-url\b", re.I)
#: A denial the mention is standing right behind. The 20 characters are MEASURED, not chosen: the
#: three real denials ("on no public index", "never published to PyPI", "not on any package
#: index") span at most 19, and a sentence that denies something ELSE and then promises the index
#: ("not optional and ships from PyPI") spans 25 and is reported.
_DENIED = re.compile(r"\b(?:no|not|never|without|neither)\b[^.]{0,20}$", re.I)


def _promises_an_index(text: str) -> list[str]:
    """Every mention of somewhere a distribution name resolves that is not being denied."""
    return [text[max(0, m.start() - 30):m.end()] for m in _AN_INDEX.finditer(text)
            if not _DENIED.search(text[:m.start()])]


#: Two kinds of file nobody follows as instructions.
#:
#: Sabotage scripts hold, on purpose, the exact text a guard must catch — `tools/mutate.py`
#: writes them into the tree and takes them out again. Scanning them would make the harness that
#: proves this guard the guard's own first offender.
#:
#: An ADR is history, on the same terms `test_the_docs_name_no_vendor_as_the_core.py` gives it:
#: it describes the world on the day it was accepted, and rewriting one is the single thing a
#: decision record forbids. `0034` sketches a commercial shape in which the core comes from a
#: public index; that is a record of an intention, not a remedy handed to anyone stuck today —
#: and where the same sketch appears in doctrine (`core/07-extensibility.md` §8) it says so.
_NOT_A_READER: tuple[str, ...] = ("tools/mutations/", "docs/adr/")

_TEXT = (".md", ".py", ".toml", ".yml", ".yaml", ".example", ".sh", ".cfg", ".txt", ".html")


def _tracked_text_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True,
                         timeout=120)
    assert out.returncode == 0, out.stderr[:200]
    return [p for p in out.stdout.split("\0")
            if p and p.endswith(_TEXT) and not p.startswith(_NOT_A_READER)
            and p != f"tests/{pathlib.Path(__file__).name}"]


def _bare_name_installs(text: str, distributions: set[str]) -> list[str]:
    """Every `pip install <one of ours>` in `text` — a path or a wheel is not one of them."""
    found = []
    for match in _PIP_INSTALL.finditer(text):
        target = match.group(2)
        name = target.split("[", 1)[0]  # `openfactory[runtime]` names `openfactory`
        if name in distributions:
            found.append(match.group(0))
    return found


def _publishing_step() -> str:
    for rel in _tracked_text_files():
        hit = _PUBLISHES.search((ROOT / rel).read_text(encoding="utf-8", errors="ignore"))
        if hit:
            return f"{rel}: {hit.group(0)}"
    return ""


# ── the premise ─────────────────────────────────────────────────────────────────────────────────

def _published_distributions() -> set[str]:
    """WHICH of our distributions an index serves — not WHETHER any is served.

    THE PREMISE CHANGED ON 2026-08-30 AND THE GUARD GOT NARROWER RATHER THAN QUIETER. Until then
    nothing here published anything, so a single tree-wide fact was enough and this module's
    docstring promised that the day somebody published, the rule would "skip by name rather than
    lying in either direction". Skipping is what it would have done, and it would have been wrong:
    `.github/workflows/release.yml` publishes the CORE and nothing else. The add-on packages are
    still on no index — deliberately, `openfactory/plugins.py::install_hint` says so — and they are
    the exact case that earned this file, because the refusal a stuck operator read ended
    `pip install openfactory-slack`. A wholesale skip would have retired the guard at the moment
    its subject became the only subject left.

    DERIVED FROM WHAT THE PUBLISH STEP ACTUALLY BUILDS. The one publish step in this tree runs
    `python -m build` at the repository ROOT, which produces the distribution `pyproject.toml`
    names and nothing else; the add-on packages are built out of `addons/` by their own script
    (`addons/overlay_build.py`) and no step uploads them. So a publish step means the core is
    served, and says nothing about the rest."""
    if not _publishing_step():
        return set()
    return {tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["name"]}


def test_the_packages_the_platforms_own_rows_ship_in_are_still_on_no_index():
    """The premise, restated the day it changed. It is no longer "this tree publishes nothing" —
    it is "this tree publishes the core, and the add-on packages remain unpublished", which is the
    fact the rule below rests on.

    If THIS ever fails, nothing is broken: somebody started publishing an add-on package, and the
    rule under it should be re-read rather than deleted — exactly what happened to its
    predecessor."""
    unpublished = our_distributions() - _published_distributions()

    assert set(plugins.SHIPS_IN.values()) <= unpublished, (
        f"an add-on package is published now ({set(plugins.SHIPS_IN.values()) & _published_distributions()}). "
        "A bare-name `pip install` of it may be true again — re-read `plugins.install_hint` and "
        "the pages that describe it before relaxing anything.")
    assert unpublished, "every distribution is published — this guard has no subject left"


# ── the rule ────────────────────────────────────────────────────────────────────────────────────

def test_nothing_hands_a_reader_a_pip_install_of_a_name_no_index_serves():
    """The rule, now aimed at the distributions an index does NOT serve.

    A bare-name `pip install` is a promise that an index resolves that name. For the core that
    promise became true on 2026-08-30 and the command is followable; for the add-on packages it is
    still a 404 wherever it is followed, and that is the sentence this file exists to keep out of
    every document and every refusal."""
    unpublished = our_distributions() - _published_distributions()
    assert len(unpublished) >= 2, f"only {unpublished} — the scan has almost no subject"

    offenders = {}
    for rel in _tracked_text_files():
        hits = _bare_name_installs((ROOT / rel).read_text(encoding="utf-8", errors="ignore"),
                                   unpublished)
        if hits:
            offenders[rel] = hits

    assert not offenders, (
        "these tell somebody to install one of this repository's own distributions by name, and "
        "no index serves it — the command fails wherever it is followed. Name the wheel or the "
        f"checkout path instead (`pip install addons/<package>`): {offenders}")


def test_the_scan_can_SEE_the_sentence_that_was_here_and_leaves_a_real_path_alone():
    """Verify the verifier, on the exact line that shipped — built here rather than spelled, so
    this file is not its own first offender."""
    distributions = our_distributions()
    package = plugins.SHIPS_IN["channel.slack"]

    was_here = f" — 'slack' ships in the add-on package {package}: `pip install {package}`"
    assert _bare_name_installs(was_here, distributions) == [f"pip install {package}"]

    core = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["name"]
    assert _bare_name_installs(f"pip install '{core}[runtime]' {package}", distributions), (
        "an extra in brackets hides the distribution name from the scan")

    # every installer that resolves a name on an index is the same sentence in another spelling,
    # and each of these walked past the `pip install` literal (reviewer's cuts, 2026-08-26)
    for spelling in (f"pip3 install {package}", f"pipx install {package}",
                     f"uv add {package}", f"uv pip install {package}",
                     f"poetry add {package}", f"python -m pip install {package}",
                     f"pip install --upgrade {package}"):
        assert _bare_name_installs(spelling, distributions), (
            f"{spelling!r} hands a reader a name no index serves and the scan did not see it")

    for followable in (f"pip install addons/{package}", f"pip install -e addons/{package}",
                       "pip install -e '.[dev]'", f"pip install ./{package}-1.0-py3-none-any.whl",
                       "pip install -q pytest", f"uv add ./addons/{package}",
                       f"the {package} package", f"pip uninstall {package}"):
        assert _bare_name_installs(followable, distributions) == [], followable


# ── the positive twin: the remedy still exists, it is just a true one ───────────────────────────

def test_every_shipped_row_still_gets_a_remedy_that_names_the_package_and_the_entry_point():
    """The rule above is satisfiable by saying nothing, which would be the same operator stuck
    with less. Every row the platform's own packages carry must still answer with BOTH halves:
    which distribution holds it, and the entry-point name any other package may declare to
    answer for that kind instead."""
    assert plugins.SHIPS_IN, "there are no shipped rows — this measures nothing"
    for key, package in plugins.SHIPS_IN.items():
        axis, _, kind = key.partition(".")
        hint = plugins.install_hint(axis, kind)
        assert package in hint, (key, hint)
        assert key in hint, (f"{key}: the hint does not name the entry point a stranger would "
                             f"declare, which is the half that does not depend on us: {hint!r}")
        assert not _bare_name_installs(hint, our_distributions()), (key, hint)
        assert not _promises_an_index(hint), (
            f"{key}: the remedy says the package can be fetched from somewhere, and "
            f"`test_this_tree_publishes_no_distribution_anywhere` measures that nothing here puts "
            f"it there — a reader who follows it gets a 404 from the sentence that was supposed to "
            f"unstick them: {_promises_an_index(hint)}")


def test_the_index_promise_scan_can_SEE_the_rewrite_and_leaves_the_real_denial_alone():
    """Verify the verifier, on the sentence that ships and on the one a reviewer wrote over it."""
    package = plugins.SHIPS_IN["channel.slack"]
    shipped = plugins.install_hint("channel", "slack")
    assert "public index" in shipped and _promises_an_index(shipped) == [], shipped

    for rewritten in (f"ships in {package}, available from PyPI",
                      f"ships in {package}; it is on the public index",
                      f"ships in {package} — add its index-url to your pip config",
                      f"{package} is not optional and ships from PyPI"):
        assert _promises_an_index(rewritten), rewritten
    for denied in ("which is on no public index", "never published to PyPI",
                   "not on any package index"):
        assert _promises_an_index(denied) == [], denied

    assert plugins.install_hint("channel", "matrix") == "", (
        "a kind nobody publishes now gets a remedy — the negative twin of the table")
