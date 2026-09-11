"""The public cut is written down where a reader checks it, and the documents agree with the tree.

THE DECISION (owner, 2026-08-24/26): the public repository receives the tracked tree by
`git archive` minus the AWS realisation, the chat connectors, the reference deployment's
documents and the tests that exist only for them; Azure DevOps and Jira stay beside GitHub —
*not a lock-in, an option*. Two documents carry it: `docs/STATUS.md` lists the excluded paths
(the ONE place they are written), and `docs/core/07-extensibility.md` §10 marks every vendor
entry of its ledger as leaving or staying.

WHY A GUARD. A path list in a document is documentation of the tree on the day it was written
(§10's own ledger had two phantom entries pass for a day, 2026-08-25). A `leaves` beside a path
that the export does not exclude is a reader sent to install an add-on for a file they already
have; a `stays` beside a path that leaves is a reference provider that vanishes at export. And a
package name in the README that STATUS does not know is a name a reader cannot find. So every
claim here is held to the tree and to the other document:

  · every excluded path exists AND is tracked — a stale line is not a list;
  · every excluded path under `openfactory/` is on §10's vendor side — the two lists partition
    the same world, and a core path cannot be excluded;
  · §10's `leaves`/`stays` mark on every vendor entry equals what STATUS excludes;
  · every entry that stays is imported by a module that stays — a reference provider the export
    keeps and nothing reaches would be built, tested, reached by nothing;
  · every entry that leaves is reached by something — an entry point in `pyproject.toml`, a
    registry row, or another leaving module — and the registry rows that still reach one are
    the two doors §10 and STATUS name, so the "not a directory delete yet" sentence cannot
    outlive the rows it describes, nor be deleted while they stand;
  · the README's tree and the reader's and contributor's pages name the add-on packages STATUS
    names, and the contributor's page lists exactly the axes the loader publishes;
  · and — the last three sections, added 2026-08-26 after the export could not run its own first
    command — nothing the export SHIPS executes against a path the export REMOVES: no tracked
    Dockerfile instruction, no Makefile recipe and no shipped example may name an excluded path
    except as an optional glob or under an existence test, every target that names one refuses by
    name with the package that carries it, and no recipe announces a file a failed command did
    not produce. Those guards do not skip in either tree; the ones above them do, which is how a
    blocker lived under 7,961 green tests;
  · the images' install step is RUN, not read. That rule above judged the SHAPE of the optional
    install — a glob among the COPY sources, an existence test somewhere in the RUN — and a
    reviewer changed `[ -d "$p" ]` to `[ -f README.md ]`, which is always true in that WORKDIR:
    23 green guards over a public build back at exit 1. The step is one tracked script now, and
    it is executed in a planted public tree and a planted private one;
  · and a document that sends a reader INSIDE a directory the export removes says so where they
    start. Not by carrying one of three vocabulary words somewhere in the file — that check
    survived deleting the banner outright, and survived inverting it to say the directory ships
    here — but by making the claim, in the opening, naming the package that carries it.
"""

from __future__ import annotations

import json
import os
import pathlib
import posixpath
import re
import shlex
import shutil
import subprocess

import add_ons
import pytest
import yaml
from test_the_core_addon_ledger import _imported_modules, _ledger, _module_name

from openfactory import plugins

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATUS = ROOT / "docs" / "STATUS.md"
DOC = ROOT / "docs" / "core" / "07-extensibility.md"
README = ROOT / "README.md"
HEADING = "## What the public repository contains"

#: The two core registries that HELD a chat row until 2026-08-26 — `slack` in the channel table,
#: `slack` and `telegram` in the notifier's — each importing its module lazily, so that with the
#: chat modules absent `channel: slack` raised a `ModuleNotFoundError` out of the row. Their rows
#: are `openfactory-slack`'s entry points now; the guards below hold the measured importer set
#: to EMPTY and these two tables to the panel alone.
REGISTRY_DOORS = frozenset({
    "openfactory/adapters/channel/registry.py",
    "openfactory/adapters/notify/registry.py",
})


def _private_tree() -> None:
    """The guards that hold the cut's list to the TREE measure the private repository — the
    one that still carries the excluded paths and the packages under `addons/`. In the export
    the paths are gone by construction, and a guard that asks for them there would fail for the
    reason it exists; it skips by name instead."""
    if add_ons.is_public_tree():
        pytest.skip(f"this is the public tree (no {add_ons.public_tree_signal()}) — the cut's list "
                    f"is held to the private one")


def _section(text: str = "") -> str:
    text = text or STATUS.read_text()
    assert HEADING in text, f"docs/STATUS.md no longer has the section {HEADING!r}"
    body = text[text.index(HEADING) + len(HEADING):]
    nxt = body.find("\n## ")
    return body if nxt < 0 else body[:nxt]


def _excluded(text: str = "") -> dict[str, str]:
    """path → the 'where it lives instead' cell, from the section's table."""
    rows = re.findall(r"^\| `([^`]+)` \| (.+?) \|$", _section(text), re.M)
    return {path: where for path, where in rows}


def _packages(where: str) -> set[str]:
    return set(re.findall(r"`?(openfactory-[a-z]+)`?", where))


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True,
                         timeout=120)
    assert out.returncode == 0, out.stderr[:200]
    return [p for p in out.stdout.split("\0") if p]


def _is_excluded(rel: str, excluded: dict[str, str]) -> bool:
    return any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in excluded)


def _core_files() -> list[tuple[pathlib.Path, str]]:
    return [(p, p.relative_to(ROOT).as_posix())
            for p in sorted(ROOT.joinpath("openfactory").rglob("*.py")) if p.is_file()]


def _importers_of(entry: str, excluded: dict[str, str]) -> set[str]:
    """Every module under `openfactory/` that STAYS and imports `entry` by path."""
    name = _module_name(entry)
    hits: set[str] = set()
    for path, rel in _core_files():
        if rel == entry or _is_excluded(rel, excluded) or rel.startswith(entry):
            continue
        if any(m == name or m.startswith(name + ".") for m in _imported_modules(path, rel)):
            hits.add(rel)
    return hits


def _entry_point_targets() -> set[str]:
    """The modules the platform's own packages reach through the group — from `addons/`, since
    the core's pyproject declares no row (2026-08-26)."""
    from vendor_addons import declared

    return {target.partition(":")[0] for target in declared().values()}


def _ledger_marks() -> dict[str, str]:
    """vendor path → the first word of its comment (`leaves` / `stays`), from §10's yaml."""
    text = DOC.read_text()
    marks: dict[str, str] = {}
    for block in re.findall(r"```yaml\n(.*?)```", text, re.DOTALL):
        for line in block.splitlines():
            m = re.match(r"\s*- (\S+)\s*#\s*(\w+)", line)
            if m:
                marks[m.group(1)] = m.group(2).lower()
    return marks


# ── the list is real ────────────────────────────────────────────────────────────────────────────

def test_the_status_page_lists_the_excluded_paths_and_each_one_is_tracked():
    _private_tree()
    excluded = _excluded()
    assert len(excluded) >= 8, f"the table lists {len(excluded)} paths — this measures nothing"
    tracked = _tracked()
    missing = sorted(p for p in excluded
                     if not any(t == p or (p.endswith("/") and t.startswith(p)) for t in tracked))
    assert not missing, (
        f"docs/STATUS.md excludes paths that are not tracked in this repository — a stale line "
        f"is not a list: {missing}")


def test_the_table_parser_can_SEE_a_row_and_ignores_the_header():
    """Verify the verifier on the exact shape the table uses."""
    planted = (f"{HEADING}\n\n| excluded | where |\n|---|---|\n"
               "| `openfactory/runtime/x/` | `openfactory-x` — the x |\n"
               "| `docs/Y.md` | leaves with nobody; not named yet |\n\n## Next\n| `not/this` | no |\n")
    assert _excluded(planted) == {"openfactory/runtime/x/": "`openfactory-x` — the x",
                                  "docs/Y.md": "leaves with nobody; not named yet"}
    assert _packages("`openfactory-x` — the x") == {"openfactory-x"}
    assert _packages("leaves with nobody; not named yet") == set()


# ── the two documents partition the same world ──────────────────────────────────────────────────

def test_every_excluded_package_path_is_on_the_ledgers_vendor_side():
    vendor_modules, vendor_packages, _ = _ledger()
    excluded = _excluded()
    off = sorted(p for p in excluded if p.startswith("openfactory/")
                 and p not in vendor_modules | vendor_packages)
    assert not off, (
        f"docs/STATUS.md excludes these from the public tree and §10's ledger does not own them "
        f"as vendor paths — a core path cannot leave: {off}")


def test_the_ledger_marks_every_vendor_entry_the_way_the_export_treats_it():
    vendor_modules, vendor_packages, _ = _ledger()
    excluded = _excluded()
    marks = _ledger_marks()
    wrong = []
    for entry in sorted(vendor_modules | vendor_packages):
        expected = "leaves" if entry in excluded else "stays"
        if marks.get(entry) != expected:
            wrong.append(f"{entry}: marked {marks.get(entry)!r}, the export says {expected!r}")
    assert not wrong, (
        "§10's ledger disagrees with docs/STATUS.md about what leaves the public tree:\n  "
        + "\n  ".join(wrong))
    assert {"leaves", "stays"} <= set(marks.values()), "the ledger no longer marks both sides"


# ── what stays is reached, what leaves is reached only through the named doors ──────────────────

def test_every_vendor_entry_that_stays_is_imported_by_a_module_that_stays():
    vendor_modules, vendor_packages, _ = _ledger()
    excluded = _excluded()
    staying = sorted(e for e in vendor_modules | vendor_packages if e not in excluded)
    assert len(staying) >= 10, f"only {staying} stay — this measures nothing"
    orphans = [e for e in staying if not _importers_of(e, excluded)]
    assert not orphans, (
        f"these reference providers stay in the public tree and no module that stays imports "
        f"them — built, tested, reached by nothing: {orphans}")


def test_every_leaving_entry_is_reached_and_only_through_a_registry_row_or_an_entry_point():
    _private_tree()
    excluded = _excluded()
    targets = _entry_point_targets()
    unreached, leaking = [], []
    for entry in sorted(p for p in excluded if p.startswith("openfactory/")):
        importers = _importers_of(entry, excluded)
        outside = sorted(importers - REGISTRY_DOORS)
        if outside:
            leaking.append(f"{entry} ← {outside}")
        name = _module_name(entry)
        via_group = any(t == name or t.startswith(name + ".") for t in targets)
        via_leaving = any(_is_excluded(rel, excluded) and rel != entry
                          and not rel.startswith(entry)
                          and any(m == name or m.startswith(name + ".")
                                  for m in _imported_modules(path, rel))
                          for path, rel in _core_files())
        if not (importers or via_group or via_leaving):
            unreached.append(entry)
    assert not leaking, (
        "a core module that stays imports a leaving path by name outside a registry row — the "
        "export would break it:\n  " + "\n  ".join(leaking))
    assert not unreached, f"these leave and nothing reaches them at all: {unreached}"


def test_no_registry_holds_a_chat_row_any_more_and_the_documents_say_so():
    """Both directions, flipped on 2026-08-26: NO module that stays reaches a leaving path — the
    two registries that held a chat row (`REGISTRY_DOORS`) hold the panel only — and the two
    documents describe the chat side as a directory delete, with the sentence that said
    otherwise gone from both."""
    _private_tree()
    excluded = _excluded()
    doors: set[str] = set()
    for entry in (p for p in excluded if p.startswith("openfactory/")):
        doors |= _importers_of(entry, excluded)
    assert doors == set(), (
        f"these modules that stay still import a leaving path: {sorted(doors)} — the export "
        f"would ship a row that raises ModuleNotFoundError instead of refusing by name")
    doc, status = DOC.read_text(), _section()
    assert "not a directory delete yet" not in doc and "not yet" not in status, (
        "a document still says the chat side is not a directory delete, and no row reaches it")
    assert "directory delete" in doc and "directory delete" in status, (
        "the documents no longer say the chat side IS a directory delete — the measured fact "
        "must be written where a reader checks it")
    # AND NAME THE TWO TABLES that now hold the panel alone: the reader who meets a refusal goes
    # to the registry the document names, and a door renamed in prose points at no file (the
    # doctrine plan's cut of this sentence survived once the old guard flipped, 2026-08-26)
    for door in sorted(REGISTRY_DOORS):
        assert f"`{door.removeprefix('openfactory/')}`" in doc, (
            f"§10 no longer names {door}, one of the two tables the chat rows left")


def test_the_two_registries_that_held_a_chat_row_hold_the_panel_only():
    """The positive twin of the empty door set, on the tables themselves rather than the import
    graph: a row that imported lazily would pass an import scan and still be a door."""
    from openfactory.adapters.channel.registry import CHANNELS
    from openfactory.adapters.notify.registry import NOTIFIERS

    assert set(CHANNELS) == {"panel"} and set(NOTIFIERS) == {"panel"}
    for door in sorted(REGISTRY_DOORS):
        assert (ROOT / door).exists(), f"{door} is gone — this guard names a file that is not there"


# ── the front doors name what STATUS names ──────────────────────────────────────────────────────

def _readme_tree_line(directory: str) -> str:
    text = README.read_text()
    tree = text[text.index("## The shape"):]
    tree = tree[:tree.index("\n## ", 1)]
    line = next((ln for ln in tree.splitlines()
                 if re.match(rf"^│\s+[├└]── {re.escape(directory)}\s", ln)), None)
    assert line, f"the README's tree has no `{directory}` line"
    return line


def test_the_readme_tree_names_the_add_on_package_STATUS_names_for_each_axis():
    excluded = _excluded()
    for directory, path in (("channel/", "openfactory/adapters/channel/slack.py"),
                            ("sandbox/", "openfactory/runtime/fargate/")):
        named = _packages(excluded[path])
        assert named, f"docs/STATUS.md names no package for {path}"
        line = _readme_tree_line(directory)
        assert any(pkg in line for pkg in named), (
            f"the README's `{directory}` line does not name the add-on package "
            f"docs/STATUS.md says {path} lives in ({sorted(named)}): {line!r}")


#: A container image this project publishes, wherever it is written: `ghcr.io/<org>/<name>[:tag]`.
#:
#: AN IMAGE REFERENCE IS NOT A PACKAGE NAME, and until 2026-08-30 nothing here knew the difference
#: because the README named no images. The moment it did — the one-line install, the un-piped
#: equivalent, the `docker pull` of the box — `openfactory-cli` and `openfactory-sandbox` became
#: "add-on packages docs/STATUS.md does not list" and the sweep below went red over a change that
#: was entirely correct.
#:
#: THE FIX IS NOT A WIDER ALLOWLIST. Adding two names to a hard-coded exemption set would have made
#: the next image invisible in the same way, and would have taught the guard that a name it does
#: not recognise is probably fine — the opposite of its job. Image references are REMOVED from the
#: text first, and then judged by their own guard (`..._is_one_the_release_publishes`, below),
#: which is a stronger claim than the one they were escaping: a package name only has to be listed
#: in a document, while an image name has to be one a workflow actually builds.
_IMAGE_REFERENCE = re.compile(r"ghcr\.io/[a-z0-9-]+/[a-z0-9-]+(?::[^\s`'\"]+)?")


def _prose_without_image_references(text: str) -> str:
    return _IMAGE_REFERENCE.sub(" ", text)


def test_the_readme_tree_does_not_name_a_package_STATUS_does_not_know():
    """The twin: a name in the README that STATUS never lists is a name a reader cannot find."""
    known = set()
    for where in _excluded().values():
        known |= _packages(where)
    assert len(known) >= 2, f"docs/STATUS.md names {sorted(known)} — this measures nothing"
    prose = _prose_without_image_references(README.read_text())
    stray = sorted(set(re.findall(r"openfactory-[a-z]+", prose)) - known
                   - {"openfactory-core", "openfactory-work", "openfactory-worktrees",
                      "openfactory-knowledge"})
    assert not stray, f"the README names add-on packages docs/STATUS.md does not list: {stray}"


def test_the_image_stripper_removes_a_reference_and_leaves_a_package_name_alone():
    """Verify the verifier, on the one distinction this whole pair turns on. A stripper that ate
    too much would let a genuine stray package name through the sweep above; one that ate too
    little puts the guard back where it was."""
    stripped = _prose_without_image_references(
        "pull ghcr.io/open-factory-digital/openfactory-sandbox:v1.0.0 now")
    assert "openfactory-sandbox" not in stripped and stripped.split() == ["pull", "now"]
    assert "openfactory-slack" in _prose_without_image_references(
        "the openfactory-slack package")
    assert _prose_without_image_references(
        "ghcr.io/open-factory-digital/openfactory-cli").strip() == ""


def test_every_image_the_readme_names_is_one_the_release_publishes():
    """THE TWIN, and the reason stripping the references is an upgrade rather than an escape.

    A package name in a document is judged by whether another document lists it. An image name is
    judged by whether a workflow BUILDS it — which is a fact about the distribution rather than
    about prose, and it is the failure a reader actually meets: `docker pull` answering `manifest
    unknown` for a reference the README told them to type."""
    published = {row["image"] for row in yaml.safe_load(
        (ROOT / ".github" / "workflows" / "release.yml").read_text()
    )["jobs"]["images"]["strategy"]["matrix"]["include"]}
    assert published, "release.yml publishes nothing — this guard has no subject"

    named = {reference.split("/")[-1].split(":")[0]
             for reference in _IMAGE_REFERENCE.findall(README.read_text())}
    assert named, "the README names no images — this guard has lost its subject"

    stray = sorted(named - published)
    assert not stray, (
        f"the README tells a reader to pull {stray}, and release.yml publishes "
        f"{sorted(published)} — `docker pull` would answer `manifest unknown` for a reference the "
        f"README handed them")


def test_the_reader_and_contributor_pages_name_the_real_group_and_the_packages():
    known = set()
    for where in _excluded().values():
        known |= _packages(where)
    for rel in ("docs/README.md", "CONTRIBUTING.md"):
        text = (ROOT / rel).read_text()
        assert f"`{plugins.GROUP}`" in text, f"{rel} never names the entry-point group the loader reads"
        for pkg in sorted(known):
            assert pkg in text, f"{rel} does not name `{pkg}`, which docs/STATUS.md lists"


def test_the_contributor_page_lists_exactly_the_axes_the_loader_publishes():
    text = (ROOT / "CONTRIBUTING.md").read_text()
    m = re.search(r"`openfactory/plugins\.py::AXES` \(([^)]+)\)", text)
    assert m, "CONTRIBUTING.md no longer lists the axes beside `plugins.py::AXES`"
    listed = {a.strip() for a in re.split(r",\s*", m.group(1))}
    assert listed == set(plugins.AXES), (
        f"CONTRIBUTING.md lists {sorted(listed)}; the loader publishes {sorted(plugins.AXES)}")


# ── the public-tree signal is a row of the table ────────────────────────────────────────────────

def test_the_public_tree_signal_is_a_row_of_the_excluded_table():
    """Four guards tell the trees apart by ONE path's presence (`add_ons.public_tree_signal`) —
    the ledger, the cut's own tree guards, `vendor_addons.require`, the install proof. Until
    2026-08-26 that path was typed in each of them and was NOT a row of this table, so an export
    that followed the table would have shipped the packages, and CI's `make install` there would
    have registered seven entry points naming modules the tree does not hold. The signal is
    spelled once and must be a row; the packages' directory is shipped by no package."""
    signal = add_ons.public_tree_signal()
    excluded = _excluded()
    assert signal in excluded, (
        f"docs/STATUS.md's table has no `{signal}` row — the path the guards test for to tell the "
        f"public tree from the private one is not what the export excludes")
    assert _packages(excluded[signal]) == set(), (
        f"the `{signal}` row names a package — the packages' own directory ships in none of them")
    assert signal.endswith("/") and add_ons.is_public_tree() == (not (ROOT / signal).is_dir())


# ── no document that stays links to a document that leaves ─────────────────────────────────────

_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _links_into_excluded(documents: list[tuple[str, str]], excluded: dict[str, str]) -> list[str]:
    """`doc:target` for every relative link in a STAYING document that resolves into an excluded
    path. Pure, on (repo-relative path, text) pairs, so the twin below can plant a tree."""
    hits = []
    for rel, text in documents:
        if _is_excluded(rel, excluded):
            continue
        for target in _LINK.findall(text):
            target = target.split("#", 1)[0].strip()
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(rel), target))
            if resolved.startswith("../"):
                continue
            if _is_excluded(resolved, excluded) or _is_excluded(resolved + "/", excluded):
                hits.append(f"{rel}:{target}")
    return hits


def test_no_document_that_stays_links_to_a_document_that_leaves():
    """Six documents linked `docs/DEPLOYMENT.md` and `docs/runtime-architecture.md` while both
    left with the cloud package — every link resolved HERE and dangled in the export, where the
    front-door guard found them one probe too late (2026-08-26). Walked over every tracked
    markdown file that stays, resolved against the table."""
    excluded = _excluded()
    documents = [(rel, (ROOT / rel).read_text()) for rel in _tracked() if rel.endswith(".md")]
    assert len(documents) > 20, "the walk found almost no document"
    hits = _links_into_excluded(documents, excluded)
    assert not hits, (
        "these documents stay in the public tree and link to a path that leaves it — a reader of "
        "the export meets a 404; say what package carries it instead:\n  " + "\n  ".join(hits))


def test_the_link_walk_can_SEE_a_link_to_a_leaving_document():
    """Verify the verifier on the exact shapes: a sibling link, a `../` link from a
    subdirectory, a link into an excluded DIRECTORY, an anchor, and a link from a document that
    itself leaves (not a finding)."""
    excluded = {"docs/GONE.md": "`openfactory-x`", "infra/": "`openfactory-x`"}
    planted = [
        ("docs/README.md", "see [gone](GONE.md) and [ok](STATUS.md)"),
        ("docs/setup/github.md", "see [gone](../GONE.md#part) and [ok](../STATUS.md)"),
        ("CONTRIBUTING.md", "see [infra](infra/deploy.sh) and [outside](../elsewhere.md)"),
        ("docs/GONE.md", "a leaving document may link [itself](GONE.md)"),
    ]
    assert _links_into_excluded(planted, excluded) == [
        "docs/README.md:GONE.md", "docs/setup/github.md:../GONE.md",
        "CONTRIBUTING.md:infra/deploy.sh"]


def test_every_relative_link_in_the_add_on_packages_documents_resolves():
    """The two documents moved under `addons/openfactory-aws/docs/` keep links into `docs/`;
    the adopter-surface link guard does not walk the packages, so this one does."""
    _private_tree()
    documents = [rel for rel in _tracked()
                 if rel.startswith(add_ons.public_tree_signal()) and rel.endswith(".md")]
    assert documents, "the packages carry no document — the walk has no subject"
    broken = []
    for rel in documents:
        for target in _LINK.findall((ROOT / rel).read_text()):
            target = target.split("#", 1)[0].strip()
            if target and "://" not in target and not (ROOT / rel).parent.joinpath(target).exists():
                broken.append(f"{rel}:{target}")
    assert not broken, f"links in the packages' documents that resolve to nothing: {broken}"


# ── nothing the export ships EXECUTES against a path the export removes ────────────────────────
#
# THE STRUCTURAL REASON A BLOCKER GOT THROUGH (pre-launch audit, 2026-08-26). Every guard above
# that holds the cut to the tree calls `_private_tree()` and skips itself the moment `addons/` is
# absent — that is, in the ONE tree where the cut can be wrong. 7,961 tests were green over a
# repository whose documented first command could not build: `docker/worker.Dockerfile` and
# `docker/sandbox.Dockerfile` both did `COPY addons ./addons`, `addons/` is a row of the table
# above, and the export therefore died at `failed to compute cache key: "/addons": not found` —
# on `docker compose --env-file .env.compose up -d --build`, which is README.md's first command
# and the one the whole of docs/ONBOARDING.md stands behind. Four of the Makefile's ten
# advertised targets were dead there for the same reason, one of them echoing "created …" over a
# `cp` that had failed.
#
# So the guards below run where those files are AUTHORED — the private tree, which HAS the paths
# — and judge the shape the EXPORT would have. They never skip: nothing here needs an excluded
# path to exist, which is exactly the point.
#
# THE RULE. No tracked Dockerfile instruction, no Makefile recipe and no shipped example may name
# a path this table excludes, unless it is named in a form that survives the path's absence:
#
#   · a GLOB — `addon[s]`, `addons/*/`, `deploy/registry.yam[l]`: matches where the path exists
#     and matches nothing, WITHOUT erroring, where it does not;
#   · an EXISTENCE TEST on that same path (or on a directory above it) — `[ -d "$p" ]`,
#     `if [ ! -e infra/deploy.sh ]` — so the command that needs it either runs or refuses.
#
# make's own `$(wildcard …)` is a third form and needs no rule of its own: the Makefile is read as
# MAKE expands it in a directory that holds no excluded path, so an empty wildcard is simply not a
# reference while a bare `infra/deploy.sh` still is.
#
# PROSE IS NOT A REFERENCE. A comment naming `addons/openfactory-aws` explains the rule it sits
# above; comments are stripped before anything is judged (eight guards in one fortnight broke on
# the comment that explained them).

#: `*`, `?` and `[` — the metacharacters that make a name match nothing instead of erroring.
_GLOB = re.compile(r"[*?\[]")
#: The same, plus the closing bracket, for reading the PATH out of a glob: `addon[s]` → `addons`.
_UNGLOB = re.compile(r"[*?\[\]]")
#: A path token ends at whitespace or at a shell/make separator that cannot be part of a path.
_TOKEN_SEP = re.compile(r"""[\s;&|()"'`]+""")
#: `[ -f x ]`, `[[ ! -d "x" ]]`, `test -e x` — the capture is the path the test is ABOUT.
_EXISTENCE_TEST = re.compile(
    r"""(?:\[\[?|\btest)\s+(?:!\s+)?-[a-zA-Z]\s+("[^"]*"|'[^']*'|[^\s;&|)]+)""")


def _path_key(token: str) -> str:
    """`./addons/x`, `"addons/x"`, `/build/addons/x` → a slash-delimited key, so that a path is
    compared by whole components and `myinfra/` never reads as `infra/`."""
    token = token.strip("\"'")
    while token.startswith("./"):
        token = token[2:]
    return "/" + token.strip("/") + "/"


def _names(token: str, path: str) -> bool:
    """True when `token`, read as a path, IS the excluded path or lies under it — at any depth,
    so an absolute in-image or `$(CURDIR)`-rooted spelling counts as much as a relative one."""
    return ("/" + path.strip("/") + "/") in _path_key(token)


def _named(unit: str, excluded, tokens: list[str] | None = None) -> list[str]:
    """Every token of `unit` that names an excluded path in a form its absence would break."""
    found = []
    for token in (_TOKEN_SEP.split(unit) if tokens is None else tokens):
        if token and not _GLOB.search(token) and any(_names(token, p) for p in excluded):
            found.append(token)
    return found


def _unguarded(unit: str, excluded, tokens: list[str] | None = None) -> list[str]:
    """Those of `_named` that no existence test on the same path (or on a directory above it)
    stands in front of. `unit` is the whole enclosing command — one Dockerfile instruction, one
    target's recipe — because that is the scope a shell `if` actually covers."""
    operands = [_path_key(op) for op in _EXISTENCE_TEST.findall(unit)]
    return [token for token in _named(unit, excluded, tokens)
            if not any(_path_key(token).startswith(op) for op in operands)]


def _dockerfile_instructions(text: str) -> list[tuple[str, str]]:
    """`(INSTRUCTION, arguments)` per instruction, comment lines dropped and `\\`-continuations
    joined — the way the Docker parser reads the file, rather than line by line."""
    body = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    out = []
    for chunk in body.replace("\\\n", " ").splitlines():
        m = re.match(r"\s*([A-Za-z]+)\s+(.+)", chunk)
        if m:
            out.append((m.group(1).upper(), m.group(2)))
    return out


def _copy_sources(args: str) -> list[str]:
    """A `COPY`/`ADD`'s SOURCES, in BOTH of Docker's forms: its flags and its destination are not
    paths in this tree, and the destination has to stay literal for the optional-glob form to have
    somewhere to land.

    THE JSON FORM IS THE SAME INSTRUCTION IN ANOTHER SPELLING, and reading it word by word made
    this walk blind to it in the worst possible way: `COPY ["addons", "./addons"]` aborts the
    public build exactly like `COPY addons ./addons`, but its first word is `["addons",` — whose
    leading `[` is a glob metacharacter, so `_named` read the very defect this guard exists for as
    an optional glob and said nothing (reviewer's cut, 2026-08-26). An exec form that will not
    parse is returned WHOLE rather than dropped: unreadable is judged, never waved through."""
    words = [w for w in args.split() if not w.startswith("--")]
    rest = " ".join(words).strip()
    if rest.startswith("["):
        try:
            items = [str(item) for item in json.loads(rest)]
        except ValueError:
            return [rest]
        return items[:-1]
    return words[:-1]


def _without_hash_comments(text: str) -> str:
    """A YAML/env/example file without its `#` comments — whole-line and trailing. Not
    `tests/terraform_text.strip_comments`: that stripper's home is the reference deployment's
    `.tf` files and it skips where `infra/` is absent, while this one has to read in both trees."""
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            out.append("")
            continue
        cut = re.search(r"(?:^|\s)#", line)
        out.append((line[:cut.start()] if cut else line).rstrip())
    return "\n".join(out)


def _is_dockerfile(rel: str) -> bool:
    """Every spelling Docker itself accepts for one. `Dockerfile.worker` is as buildable as
    `worker.Dockerfile`, and a walk that knew only two of the three spellings would let the same
    aborting `COPY` in under the third."""
    name = rel.rsplit("/", 1)[-1]
    return name == "Dockerfile" or name.startswith("Dockerfile.") or name.endswith(".Dockerfile")


#: The file names Docker Compose looks for on its own, and the override that layers onto whichever
#: it finds. The export's first command is `docker compose --env-file .env.compose up -d --build`,
#: so any of these that is tracked is read BY THAT COMMAND — and a single literal `docker-compose.yml`
#: is a walk that another of Compose's own spellings walks straight past.
_COMPOSE_NAMES = frozenset(f"{stem}{part}{ext}"
                           for stem in ("compose", "docker-compose")
                           for part in ("", ".override")
                           for ext in (".yaml", ".yml"))


def _is_compose(rel: str) -> bool:
    return rel.rsplit("/", 1)[-1] in _COMPOSE_NAMES


def _compose_dockerfiles() -> set[str]:
    """Every Dockerfile a tracked compose file names — `build: {dockerfile: …}` — resolved against
    the build context beside it. The positive twin of the walk above: the images the first command
    actually builds have to be in the set that walk judges."""
    found: set[str] = set()
    for rel in _tracked():
        if not _is_compose(rel):
            continue
        for service in (yaml.safe_load((ROOT / rel).read_text()) or {}).get("services", {}).values():
            build = service.get("build") if isinstance(service, dict) else None
            if isinstance(build, dict) and build.get("dockerfile"):
                context = build.get("context", ".")
                found.add(posixpath.normpath(posixpath.join(context, str(build["dockerfile"]))))
    return found


def test_no_dockerfile_names_a_path_the_export_removes_in_a_form_its_absence_breaks():
    excluded = _excluded()
    files = [rel for rel in _tracked() if _is_dockerfile(rel) and not _is_excluded(rel, excluded)]
    assert len(files) >= 3, f"the walk found {files} — this measures nothing"
    findings = []
    for rel in files:
        for kind, args in _dockerfile_instructions((ROOT / rel).read_text()):
            tokens = _copy_sources(args) if kind in {"COPY", "ADD"} else None
            findings += [f"{rel}: {kind} names {token}" for token in _unguarded(args, excluded,
                                                                               tokens)]
    assert not findings, (
        "these Dockerfile instructions name a path docs/STATUS.md removes from the public tree, "
        "and name it in a form that ABORTS the build where the path is absent — write it as an "
        "optional glob (`addon[s]`) or reach it under an existence test:\n  "
        + "\n  ".join(findings))


def test_every_dockerfile_the_first_command_builds_is_in_the_walk():
    """The positive twin of the walk itself. `_is_dockerfile` is a name test, and a name test can
    quietly stop matching — so the images `docker compose … up --build` names are read out of the
    compose file and required to be in the set the rule above judged."""
    excluded = _excluded()
    walked = {rel for rel in _tracked() if _is_dockerfile(rel) and not _is_excluded(rel, excluded)}
    built = _compose_dockerfiles()
    assert built, "no compose file names a Dockerfile — the first command builds nothing"
    assert built <= walked, (
        f"the first command builds {sorted(built - walked)}, and the Dockerfile rule above never "
        f"read them — it walked {sorted(walked)}")


# ── THE INSTALL STEP IS RUN, NOT READ ───────────────────────────────────────────────────────────
#
# WHY THIS REPLACED A SHAPE CHECK. The guard that stood here asserted the shape of the images'
# optional-install loop: a glob among the COPY sources, and an existence test somewhere inside the
# RUN. A reviewer changed `if [ -d "$p" ]` to `if [ -f README.md ]` — README.md is COPYied into
# that very WORKDIR, so the test is always true — and every one of this file's 23 guards stayed
# green while the public build went back to `pip install ./addons/openfactory-*` and exit 1: the
# launch blocker, byte for byte, invisible (measured 2026-08-26).
#
# A shape cannot be judged. So the images' install step is now ONE tracked script with one
# argument, and these guards RUN it — the real file, with the real argument list read out of the
# real RUN instruction — in a directory planted to look like the public export and again in one
# planted to look like this repository. What is asserted is the outcome: with the packages absent
# the step succeeds and installs nothing from them; with them present it installs each of them;
# and a failing install takes the build down instead of being swallowed.

#: The script both images run, spelled once. WHICH images run it is derived below, so a third
#: image is judged the day it is written.
INSTALL_SCRIPT = "docker/install-addons.sh"

#: The two images the distribution builds. The set below is DERIVED — and a derived set can shrink
#: to nothing without a word, taking its guards with it (an image that stops copying the core drops
#: straight out of the walk), so these two are asserted by name the way `NAMED_SHIPPED_FILES` is in
#: `tests/test_the_namespace_is_the_products_name.py`.
IMAGES_THAT_BAKE_THE_PLATFORM = ("docker/sandbox.Dockerfile", "docker/worker.Dockerfile")

#: A recording stand-in for `pip`, first on PATH while the install step runs. It answers the way
#: pip does for the one case that decides this: a target naming a path that is not there is an
#: ERROR, never a no-op — so the defect the public build had (`pip install ./addons/openfactory-*`
#: over a glob that matched nothing) shows up as a non-zero exit as well as in the log.
#: `PIP_FAILS` is a shell pattern, so a test can make one install fail and watch what follows.
_RECORDING_PIP = """#!/bin/sh
printf '%s\\n' "$*" >> "$PIP_LOG"
status=0
for arg in "$@"; do
    case "$arg" in
        install|-*) continue ;;
    esac
    case "$arg" in
        */*) [ -e "$arg" ] || { echo "ERROR: no such path: $arg" >&2; status=1; } ;;
    esac
    case "$arg" in
        ${PIP_FAILS:-@@nothing@@}) echo "ERROR: refusing $arg" >&2; status=1 ;;
    esac
done
exit $status
"""


def _images_that_bake_the_platform() -> list[str]:
    """Every tracked Dockerfile that COPIES the core package in — the images that install this
    platform, derived from the instructions rather than listed."""
    excluded = _excluded()
    found = []
    for rel in _tracked():
        if not _is_dockerfile(rel) or _is_excluded(rel, excluded):
            continue
        instructions = _dockerfile_instructions((ROOT / rel).read_text())
        if any(kind in {"COPY", "ADD"} and any(_names(src, "openfactory")
                                               for src in _copy_sources(args))
               for kind, args in instructions):
            found.append(rel)
    return sorted(found)


#: Shell operators. The install step must be the script and nothing else: `RUN sh …/install-addons.sh
#: '.[runtime]' || true` runs the same script and throws its exit status away, so the image builds
#: green over a package that failed to install — the very outcome the script's `set -e` exists for,
#: undone one word later, in the file the guards below do NOT execute.
_SHELL_OPERATOR = frozenset({"||", "&&", ";", "|", "&"})


def _install_step(rel: str) -> list[str]:
    """The word list the image's RUN passes the shared script — read out of the Dockerfile, so
    these guards exercise the instruction that is really there rather than a copy of it."""
    for kind, args in _dockerfile_instructions((ROOT / rel).read_text()):
        if kind != "RUN":
            continue
        try:
            words = shlex.split(args)
        except ValueError:
            continue
        if any(_names(word, INSTALL_SCRIPT) for word in words):
            return words
    return []


@pytest.mark.parametrize("rel", _images_that_bake_the_platform())
def test_the_install_step_is_the_script_and_nothing_around_it(rel):
    """What the guards below run is the SCRIPT; what the image runs is the RUN instruction. The
    two are the same claim only while nothing stands between them — so the instruction may hold
    the shell, the script and its arguments, and no operator that could swallow what the script
    decides."""
    words = _install_step(rel)
    assert words, f"{rel} no longer runs `{INSTALL_SCRIPT}`"
    stray = sorted(set(words) & _SHELL_OPERATOR)
    assert not stray, (
        f"{rel}'s install step is `{' '.join(words)}` — the {stray} around it means the layer's "
        f"exit status is no longer the script's, and every outcome measured below is measured on "
        f"something the image does not do")


def _planted_context(root: pathlib.Path, *, with_packages: bool) -> pathlib.Path:
    """A directory shaped like the image's WORKDIR at the moment the install step runs.

    README.md, LICENSE, NOTICE AND pyproject.toml ARE PLANTED ON PURPOSE: the COPY above the
    install step lands all four, and the cut this guard exists for tested `[ -f README.md ]`
    instead of the package directory. A fixture without them would let that cut pass here for the
    wrong reason — the file it tests would simply be missing."""
    context = root / "context"
    (context / "openfactory").mkdir(parents=True)
    (context / "openfactory" / "__init__.py").write_text("")
    for name in ("pyproject.toml", "README.md", "LICENSE", "NOTICE"):
        (context / name).write_text(f"# planted {name}\n")
    if with_packages:
        for package in ("openfactory-aws", "openfactory-slack"):
            (context / "addons" / package).mkdir(parents=True)
            (context / "addons" / package / "pyproject.toml").write_text("# planted\n")
        # debris the glob matches and pip must never be handed: a note beside the packages, and a
        # directory of the packages' own build machinery that is not one of them
        (context / "addons" / "openfactory-notes.md").write_text("not a package\n")
        (context / "addons" / "overlay_build.py").write_text("# not a package\n")
    return context


def _run_install_step(rel: str, root: pathlib.Path, *, with_packages: bool,
                      pip_fails: str = "") -> tuple[subprocess.CompletedProcess, list[str]]:
    """Run `rel`'s install step in a planted context. Returns the process and every target the
    recording pip was handed, in order."""
    words = _install_step(rel)
    assert words, (
        f"{rel} no longer runs `{INSTALL_SCRIPT}` — these guards judge the install step by RUNNING "
        f"it, and an image that installs the platform some other way is unjudged")
    index = next(i for i, word in enumerate(words) if _names(word, INSTALL_SCRIPT))

    context = _planted_context(root, with_packages=with_packages)
    stand_in = root / "bin"
    stand_in.mkdir()
    (stand_in / "pip").write_text(_RECORDING_PIP)
    (stand_in / "pip").chmod(0o755)
    log = root / "pip.log"

    run = subprocess.run(["sh", str(ROOT / INSTALL_SCRIPT), *words[index + 1:]], cwd=context,
                         capture_output=True, text=True, timeout=120,
                         env={"PATH": f"{stand_in}:{os.environ.get('PATH', '')}",
                              "PIP_LOG": str(log), "PIP_FAILS": pip_fails})
    targets = []
    for line in (log.read_text().splitlines() if log.exists() else []):
        targets += [word for word in shlex.split(line)
                    if word != "install" and not word.startswith("-")]
    return run, targets


def test_the_images_that_bake_the_platform_are_the_ones_this_walk_found():
    found = _images_that_bake_the_platform()
    missing = [rel for rel in IMAGES_THAT_BAKE_THE_PLATFORM if rel not in found]
    assert not missing, (
        f"{missing} bake this platform and the walk below did not find them — its guards would "
        f"have measured {found} and said nothing about the rest")


@pytest.mark.skipif(not shutil.which("sh"), reason="no POSIX shell on this machine")
@pytest.mark.parametrize("rel", _images_that_bake_the_platform())
def test_the_install_step_installs_NOTHING_from_the_packages_where_they_are_absent(rel, tmp_path):
    """The public export, planted: `addons/` is not there. The step must succeed — it is the first
    command README.md gives a stranger — and must hand pip no target under that directory."""
    signal = add_ons.public_tree_signal()
    run, targets = _run_install_step(rel, tmp_path, with_packages=False)

    assert run.returncode == 0, (
        f"{rel}'s install step exits {run.returncode} in a tree without `{signal}` — the published "
        f"repository cannot build its own first command:\n{run.stdout}{run.stderr}")
    reached = [target for target in targets if _names(target, signal)]
    assert reached == [], (
        f"{rel}'s install step handed pip {reached} in a tree that has no `{signal}` — pip is "
        f"given a path that is not there, which is exit 1 wherever it is really run")
    assert targets, (
        f"{rel}'s install step installed nothing at all — the rule above is satisfied by an image "
        f"that stopped installing the platform, which is not the fix")


@pytest.mark.skipif(not shutil.which("sh"), reason="no POSIX shell on this machine")
@pytest.mark.parametrize("rel", _images_that_bake_the_platform())
def test_the_install_step_installs_EVERY_package_the_tree_carries(rel, tmp_path):
    """The positive twin, and the half "installs nothing where they are absent" is also satisfied
    by an image that installs them nowhere: this repository's shape, planted, must produce an
    install of each package and of neither piece of debris beside them."""
    signal = add_ons.public_tree_signal()
    run, targets = _run_install_step(rel, tmp_path, with_packages=True)

    assert run.returncode == 0, f"{rel}: {run.stdout}{run.stderr}"
    reached = sorted(_path_key(target).strip("/") for target in targets if _names(target, signal))
    assert reached == ["addons/openfactory-aws", "addons/openfactory-slack"], (
        f"{rel}'s install step installed {reached} from a tree carrying both packages and two "
        f"pieces of debris — a worker without them refuses `channel: slack` and "
        f"`OPENFACTORY_SANDBOX=fargate` by name, in the tree that has them")


@pytest.mark.skipif(not shutil.which("sh"), reason="no POSIX shell on this machine")
@pytest.mark.parametrize("rel", _images_that_bake_the_platform())
def test_a_failing_package_install_takes_the_build_down_instead_of_being_swallowed(rel, tmp_path):
    """The third outcome, and the one the old shape check described in a comment and measured
    nowhere. A `pip install` that fails inside a loop is the loop's exit status only if it is the
    LAST iteration: without propagation an image ships green, missing a package it was told to
    carry, and the first report comes from a job that refuses a row the operator configured."""
    run, targets = _run_install_step(rel, tmp_path, with_packages=True,
                                     pip_fails="*openfactory-aws")

    assert run.returncode != 0, (
        f"{rel}'s install step survived a failing package install and exited 0 — the image is "
        f"built, stamped and shipped without it:\n{run.stdout}{run.stderr}")
    assert not any("openfactory-slack" in target for target in targets), (
        f"{rel}'s install step carried on to the next package after one failed: {targets}")


@pytest.mark.parametrize("rel", _images_that_bake_the_platform())
def test_each_image_still_copies_the_packages_directory_as_an_optional_glob(rel):
    """The install step above can only install what the build context holds. `addon[s]` copies the
    directory where it exists and matches NOTHING, without erroring, where it does not — a bare
    `COPY addons ./addons` aborts the public build before any script runs."""
    signal = add_ons.public_tree_signal()
    copies = [src for kind, args in _dockerfile_instructions((ROOT / rel).read_text())
              if kind in {"COPY", "ADD"} for src in _copy_sources(args)]
    assert any(_GLOB.search(src) and _names(_UNGLOB.sub("", src), signal) for src in copies), (
        f"{rel} no longer copies `{signal}` as an optional glob — its sources are {copies}")


def _make_targets(text: str) -> list[str]:
    """The targets `make help` advertises — the same `## ` rows the help recipe greps for."""
    return re.findall(r"^([A-Za-z0-9_-]+):.*?## ", text, re.M)


def _expanded_recipes(workdir: pathlib.Path) -> dict[str, str]:
    """`target → the commands make would run`, expanded BY MAKE in a directory that holds the
    Makefile and NONE of the excluded paths. Reading make's own expansion of the public shape is
    what makes `$(wildcard addons)` honest — there it expands to nothing, so it is not a
    reference — while a bare `infra/deploy.sh` still is."""
    shutil.copy(ROOT / "Makefile", workdir / "Makefile")
    env = {k: v for k, v in os.environ.items() if k not in {"TFVARS", "NAME", "DIR", "REPO"}}
    recipes = {}
    for target in _make_targets((ROOT / "Makefile").read_text()):
        shown = subprocess.run(["make", "-n", target], cwd=workdir, capture_output=True,
                               text=True, timeout=120, env=env)
        recipes[target] = shown.stdout
    return recipes


def _package_that_ships(path: str) -> str:
    """The package `docs/STATUS.md` says carries `path` — or, under the packages' own directory,
    the package the path IS. The `addons/` row deliberately names none (the directory ships in no
    package), and `addons/openfactory-aws/docs/DEPLOYMENT.md` obviously ships in
    `openfactory-aws`, so the name is read off the path rather than kept in a second map here."""
    named = add_ons.package_for(path)
    if named:
        return named
    parts = _path_key(path).strip("/").split("/")
    return parts[1] if len(parts) > 1 and parts[0] + "/" == add_ons.public_tree_signal() else ""


@pytest.mark.skipif(not shutil.which("make"), reason="no make on this machine")
def test_no_makefile_recipe_runs_against_a_path_the_export_removes(tmp_path):
    excluded = _excluded()
    recipes = _expanded_recipes(tmp_path)
    assert len(recipes) >= 8, f"the Makefile advertises {sorted(recipes)} — this measures nothing"
    findings = [f"make {target} runs against {token}"
                for target, script in recipes.items()
                for token in _unguarded(script, excluded)]
    assert not findings, (
        "these Makefile recipes run against a path docs/STATUS.md removes from the public tree, "
        "with nothing testing that it is there — a reader of the export gets `No such file or "
        "directory` from a target `make help` advertises:\n  " + "\n  ".join(findings))


@pytest.mark.skipif(not shutil.which("make"), reason="no make on this machine")
def test_every_target_that_names_a_leaving_path_refuses_BY_NAME_where_it_is_absent(tmp_path):
    """The positive twin, and the one that measures a REFUSAL rather than the absence of a
    reference: a recipe whose every mention of a leaving path sits under an existence test passes
    the rule above even when the test's other branch says nothing at all, or exits 0. So every
    such target is RUN — in a directory holding the Makefile and none of the excluded paths — and
    has to exit non-zero naming both the path it wanted and the package that carries it."""
    excluded = _excluded()
    recipes = _expanded_recipes(tmp_path)
    wants = {target: sorted(set(_named(script, excluded)))
             for target, script in recipes.items() if _named(script, excluded)}
    assert wants, (
        "no target `make help` advertises names a path the export removes any more. If the cloud "
        "targets moved into the add-on package, delete this guard in the same commit — do not "
        "leave it passing over an empty set")
    env = {k: v for k, v in os.environ.items() if k not in {"TFVARS", "NAME", "DIR", "REPO"}}
    for target, paths in sorted(wants.items()):
        run = subprocess.run(["make", target], cwd=tmp_path, capture_output=True, text=True,
                             timeout=120, env=env)
        said = run.stdout + run.stderr
        assert run.returncode != 0, (
            f"`make {target}` needs {paths}, which the public tree does not have, and still exited "
            f"0 — it reported success over a command that could not have run:\n{said}")
        answered = [p for p in paths
                    if p in said and _package_that_ships(p)
                    and f"pip install {_package_that_ships(p)}" in said]
        assert answered, (
            f"`make {target}` failed without naming what it wanted AND the command that gets it. "
            f"It needs {paths} (carried by {sorted({_package_that_ships(p) for p in paths})}), so "
            f"the refusal has to name a path and `pip install <package>` — the same answer "
            f"`channel: slack` gives. A reader of the export got:\n{said}")


@pytest.mark.skipif(not shutil.which("make"), reason="no make on this machine")
def test_a_recipe_never_announces_a_file_it_did_not_create(tmp_path):
    """`make tfvars` printed `cp: …: No such file or directory`, echoed "created …" over that
    failure and exited 0 (audit, 2026-08-26). Both branches are measured here, over a PLANTED
    template so the guard runs in either tree: the copy that works is announced, and the copy
    that fails is not announced and is not survived."""
    shutil.copy(ROOT / "Makefile", tmp_path / "Makefile")
    template = tmp_path / "infra" / "terraform" / "deployment.tfvars.example"
    template.parent.mkdir(parents=True)
    template.write_text("# a planted template\n")
    env = {k: v for k, v in os.environ.items() if k not in {"TFVARS", "NAME", "DIR", "REPO"}}

    made = subprocess.run(["make", "tfvars", f"TFVARS={tmp_path / 'out.tfvars'}"], cwd=tmp_path,
                          capture_output=True, text=True, timeout=120, env=env)
    assert made.returncode == 0 and (tmp_path / "out.tfvars").read_text() == template.read_text()
    assert "created" in made.stdout, f"a copy that worked was not announced:\n{made.stdout}"

    failed = subprocess.run(["make", "tfvars", "TFVARS=/no/such/directory/out.tfvars"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=120, env=env)
    assert failed.returncode != 0, (
        f"`cp` could not have written /no/such/directory/out.tfvars and make exited 0:\n"
        f"{failed.stdout}{failed.stderr}")
    assert "created" not in failed.stdout, (
        f"a copy that FAILED was announced as done:\n{failed.stdout}{failed.stderr}")


def test_no_shipped_example_or_workflow_names_a_path_the_export_removes():
    """The same rule over the rest of what the export ships and something reads: the compose file
    the first command runs, every `*.example` template, and the CI workflow a fork inherits."""
    excluded = _excluded()
    files = [rel for rel in _tracked()
             if not _is_excluded(rel, excluded)
             and (rel.endswith(".example") or _is_compose(rel)
                  or rel.startswith(".github/workflows/"))]
    assert len(files) >= 5, f"the walk found {files} — this measures nothing"
    assert any(_is_compose(rel) for rel in files), (
        f"no compose file is in the walk — the first command reads one of {sorted(_COMPOSE_NAMES)} "
        f"and this rule would say nothing about it")
    findings = [f"{rel} names {token}" for rel in files
                for token in _unguarded(_without_hash_comments((ROOT / rel).read_text()), excluded)]
    assert not findings, (
        "these files ship in the public tree and name a path it does not have, outside a comment "
        "— a reader of the export follows them into nothing:\n  " + "\n  ".join(findings))


def test_the_shape_judge_can_SEE_the_defect_it_exists_for_and_clears_the_fix():
    """Verify the verifier, on the exact texts of 2026-08-26 — before and after."""
    excluded = {"addons/": "the packages themselves", "infra/": "`openfactory-aws`"}

    assert _copy_sources("addons ./addons") == ["addons"]
    assert _unguarded("addons ./addons", excluded, _copy_sources("addons ./addons")) == ["addons"]
    assert _copy_sources("addon[s] ./addons") == ["addon[s]"]
    assert _named("addon[s] ./addons", excluded, _copy_sources("addon[s] ./addons")) == []
    assert _copy_sources("--from=toolbox /toolbox /opt/src") == ["/toolbox"]

    # Docker's OTHER form of the same instruction, and the reviewer's cut of 2026-08-26: read word
    # by word, `["addons",` opens with a glob metacharacter and the defect read as an optional glob
    exec_form = '["addons", "./addons"]'
    assert _copy_sources(exec_form) == ["addons"]
    assert _unguarded(exec_form, excluded, _copy_sources(exec_form)) == ["addons"]
    assert _copy_sources('--from=toolbox ["/toolbox", "/opt/src"]') == ["/toolbox"]
    assert _copy_sources('["addon[s]", "./addons"]') == ["addon[s]"]
    assert _copy_sources('["addons", ') == ['["addons",'], "an unreadable exec form was dropped"

    # a Dockerfile is any of the three names Docker builds, and only those
    assert all(_is_dockerfile(rel) for rel in
               ("Dockerfile", "docker/worker.Dockerfile", "docker/Dockerfile.worker"))
    assert not any(_is_dockerfile(rel) for rel in ("docs/Dockerfiles.md", "src/mydockerfile"))
    assert _is_compose("compose.yaml") and _is_compose("docker-compose.override.yml")
    assert not _is_compose("docker-compose.yml.example")

    broken = ("pip install --no-cache-dir '.[runtime]' ./addons/openfactory-aws "
              "./addons/openfactory-slack")
    assert _unguarded(broken, excluded) == ["./addons/openfactory-aws", "./addons/openfactory-slack"]
    fixed = ("pip install --no-cache-dir '.[runtime]'  && for p in ./addons/openfactory-*; do "
             'if [ -d "$p" ]; then pip install --no-cache-dir "$p" || exit 1; fi;     done')
    assert _named(fixed, excluded) == [] and _unguarded(fixed, excluded) == []

    # the old `tfvars`: the tested path is a SIBLING of the one `cp` reads, so the test guards
    # nothing — an existence test somewhere in the recipe must not read as compliance
    old = ('if [ -f "/w/infra/terraform/deployment.tfvars" ]; then echo exists; '
           'else cp infra/terraform/deployment.tfvars.example "/w/infra/terraform/deployment.tfvars"; '
           "echo created; fi")
    assert _unguarded(old, excluded) == ["infra/terraform/deployment.tfvars.example"]
    new = ('if [ ! -e "infra/terraform/deployment.tfvars.example" ]; then exit 1; fi\n'
           'cp "infra/terraform/deployment.tfvars.example" "/w/out" && echo created')
    assert _unguarded(new, excluded) == []

    # prose is not a reference, a continuation is one instruction, and a component is whole
    assert _dockerfile_instructions("# COPY addons ./addons\nCOPY addon[s] ./addons\n") == [
        ("COPY", "addon[s] ./addons")]
    kind, args = _dockerfile_instructions("RUN a \\\n# why\n && b\n")[0]
    assert (kind, args.split()) == ("RUN", ["a", "&&", "b"]) and "why" not in args
    assert _without_hash_comments("a: b  # see infra/deploy.sh\n# and addons/\nc: d") == \
        "a: b\n\nc: d"
    assert not _names("myinfra/x", "infra/") and _names("/build/addons/x", "addons/")
    assert _package_that_ships("infra/deploy.sh") == "openfactory-aws"
    assert _package_that_ships("addons/openfactory-aws/docs/DEPLOYMENT.md") == "openfactory-aws"


# ── a document that sends a reader INSIDE a leaving directory says so where they start ─────────
#
# THE FRAMING CHECK WAS A WORD. `tests/test_the_docs_name_no_vendor_as_the_core.py` holds every
# document that may name a vendor's products to `add-?on|connector|adapter` — ANYWHERE in the
# file. A reviewer deleted docs/runbook.md's whole banner, left one sentence further down that
# happened to contain "adapter", and the gate stayed green; so did keeping the banner and
# INVERTING it, to say the directory it drives SHIPS in this tree (2026-08-26). A word is not a
# claim, and a claim made on line 400 is not made where a reader forms their belief.
#
# So the condition is asserted instead, scoped to the opening — everything before the first `##`,
# which is the only part a person reads before following an instruction. The subject is DERIVED,
# and deliberately not a list of file names: a document leaving the public cut takes its own row
# in docs/STATUS.md's table and drops out of the walk by itself, and one added tomorrow is judged
# the day it is written.
#
# NAMING THE DIRECTORY IS A MENTION; NAMING A FILE UNDER IT IS AN INSTRUCTION. `infra/` in a
# sentence about what leaves is the table's own vocabulary — the two documents that describe the
# cut carry it by the dozen. `infra/deploy.sh` is a path the reader TYPES. Only the second puts
# them in a directory they may not have, and only directories docs/STATUS.md says a PACKAGE
# carries are in scope: the packages' own directory ships in none of them, so there is nothing to
# send anybody to.

#: A word for the repository the reader is holding.
_THIS_TREE = re.compile(r"\bth(?:is|e)\s+(?:tree|repository|repo|export|distribution)\b", re.I)
#: A denial. Whatever follows it in the sentence is being said NOT to be the case.
_NEGATION = re.compile(r"\b(?:not|no|never|neither|nor|without|outside)\b|n't", re.I)
#: Verbs that assert presence. `is`/`are` are deliberately absent — "which IS NOT in this tree"
#: is the sentence being looked for, and a rule that read its copula as a presence claim would
#: reject the very shape it exists to accept.
_PRESENCE = re.compile(r"\b(?:ship(?:s|ped|ping)?|live[sd]?|reside[sd]?|belong(?:s|ed)?"
                       r"|included|bundled|carried|present)\b", re.I)


def _states_absence(opening: str, path: str) -> bool:
    """True when `opening` claims `path` is absent from this tree.

    The shape, inside ONE paragraph: the path, then a negation, then a word for this tree — with
    no presence verb in between that a negation does not already carry. That last clause is what
    separates "`infra/`, which is not in this tree" (accepted) from "`infra/`, which SHIPS in this
    tree" (rejected, and it was the reviewer's cut) and from "`infra/`, which is not optional and
    ships in this tree" (rejected: the denial and the claim are about different things). A
    reworded "`infra/` does not ship in this tree" is accepted, because there the negation is the
    one carrying the verb."""
    for paragraph in re.split(r"\n\s*\n", opening):
        for mention in re.finditer(rf"`?{re.escape(path)}", paragraph):
            tail = paragraph[mention.end():]
            tree = _THIS_TREE.search(tail)
            if not tree:
                continue
            span = tail[:tree.start()]
            if not _NEGATION.search(span):
                continue
            if any(not _NEGATION.search(span[max(0, verb.start() - 14):verb.start()])
                   for verb in _PRESENCE.finditer(span)):
                continue
            return True
    return False


def _opening(text: str) -> str:
    """Everything before the document's first `##` heading — its title, its banners and nothing
    else. Where a reader is before they have followed anything."""
    heading = re.search(r"^##\s", text, re.M)
    return text[:heading.start()] if heading else text


def _documents_that_drive_a_leaving_directory() -> dict[str, set[str]]:
    """`document → the excluded directories it sends a reader INSIDE`. Decision records are
    excluded on the terms this repository gives them everywhere: an ADR describes the world on
    the day it was accepted."""
    excluded = _excluded()
    directories = [path for path in excluded
                   if path.endswith("/") and add_ons.package_for(path)]
    found: dict[str, set[str]] = {}
    for rel in _tracked():
        if not rel.endswith(".md") or _is_excluded(rel, excluded) or rel.startswith("docs/adr/"):
            continue
        drives = {path for token in _TOKEN_SEP.split((ROOT / rel).read_text())
                  for path in directories
                  if _names(token, path) and not _path_key(token).endswith(
                      "/" + path.strip("/") + "/")}
        if drives:
            found[rel] = drives
    return found


def test_a_document_that_drives_a_leaving_directory_exists_at_all():
    """The floor, and it is the honest kind: if every such document has left the public cut, the
    guard below is parametrised over nothing and passes in silence. Delete it in that commit
    rather than leaving it standing over an empty set."""
    drivers = _documents_that_drive_a_leaving_directory()
    assert drivers, (
        "no document that stays in the public tree sends a reader inside a directory the export "
        "removes any more — the banner rule below now measures nothing")


@pytest.mark.parametrize("rel", sorted(_documents_that_drive_a_leaving_directory()))
def test_a_document_that_drives_a_leaving_directory_says_so_in_its_OPENING(rel):
    opening = _opening((ROOT / rel).read_text())
    for path in sorted(_documents_that_drive_a_leaving_directory()[rel]):
        package = add_ons.package_for(path)
        assert package in opening, (
            f"{rel} sends a reader to files inside `{path}`, which the public tree does not have, "
            f"and its opening never names `{package}` — docs/STATUS.md says that package carries "
            f"the directory, and the reader has no way to get it")
        assert _states_absence(opening, path), (
            f"{rel} sends a reader to files inside `{path}` and its opening never states that "
            f"`{path}` is not in this tree. A banner that names the package while claiming the "
            f"directory ships here is worse than none: the reader follows the paths and finds "
            f"nothing. Say it once, at the top, before the first section")


def test_the_absence_claim_can_SEE_the_cuts_it_was_written_for():
    """Verify the verifier, on the reviewer's own cuts of 2026-08-26 and on the sentence that
    was really here."""
    was_here = ("> **This page drives `infra/`, which is not in this tree.** That directory and "
                "the deployment it stands up ship with the `openfactory-aws` **add-on package**.\n")
    assert _states_absence(was_here, "infra/")

    inverted = was_here.replace("which is not in this tree", "which SHIPS in this tree")
    assert not _states_absence(inverted, "infra/"), "the banner was inverted and read as compliant"
    assert "add-on" in inverted, "the inversion has to keep the vocabulary, or it proves nothing"

    assert not _states_absence("the page drives `infra/deploy.sh`; an adapter is an add-on", "infra/")
    assert not _states_absence(
        "> `infra/`, which is not optional and ships in this tree.\n", "infra/")
    assert _states_absence("> `infra/` does not ship in this tree.\n", "infra/")
    assert _states_absence("> its `infra/`, not a directory of this repository\n", "infra/")

    # …and the claim has to be in the paragraph the reader is in, not two sections away
    assert not _states_absence("> drives `infra/`.\n\nit is not in this tree\n", "infra/")

    # …and the OPENING is where a reader is before they have followed anything: a page that moves
    # the banner under a heading has moved it past everybody who acted on the first instruction
    page = "# Title\n\n> `infra/` is not in this tree\n\n## Steps\n\n> `infra/` is not in this tree\n"
    assert _states_absence(_opening(page), "infra/")
    moved = page.replace("> `infra/` is not in this tree\n\n## Steps", "## Steps", 1)
    assert _states_absence(moved, "infra/") and not _states_absence(_opening(moved), "infra/")

    # the subject is a document that sends the reader INSIDE, never one that names the row
    excluded = _excluded()
    assert _names("infra/deploy.sh", "infra/") and _names("infra/", "infra/")
    assert _path_key("infra/").endswith("/infra/") and not _path_key("infra/deploy.sh").endswith(
        "/infra/")
    assert "infra/" in excluded and add_ons.package_for("infra/")
