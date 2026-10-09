"""What `pip install` actually delivers — asserted against a BUILT WHEEL, not the source tree.

`pyproject.toml` globbed `org_defaults/*.md` at one level. That matched `engineering.md` and
`tdd.md` and left `org_defaults/roles/*.md` — product, techlead, executor, recovery, coordinator,
planner, sizer — out of the wheel entirely. ~27 KB of what `adapters/agent/techlead.py` calls
"the platform's opinion", absent from every pip install.

WHY IT SURVIVED, AND WHY THIS FILE HAS TO BUILD A PACKAGE TO CATCH IT. Every other test in this
suite runs from the source tree, where those files exist — so every one of them passed, and would
have kept passing after the regression. The deployed worker escapes by accident too: its WORKDIR
shadows site-packages, so the container finds the files on disk rather than in the installed
package. The `openfactory` console script does not escape.

It therefore only breaks in the one place we never test: **a client's machine**. That is the exact
scenario the founder named — *"este código será distribuído, será colocado em uma empresa — e aí?"*

Slow by nature (it builds a wheel), so it is one test, not a suite.
"""

from __future__ import annotations

import email.parser
import importlib.metadata
import json
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: The first setuptools that can build this package: `license = "Apache-2.0"` is a PEP 639
#: expression, and 68/75/76 refuse it ("`project.license` must be valid exactly by one
#: definition (2 matches found)" → metadata-generation-failed) while 77.0.1 is the first green.
#: Measured 2026-08-24 from a pristine `git archive`, one scratch venv per version; the reasoning
#: is in the comment above `[build-system]` in pyproject.toml, which this number is checked against.
FIRST_SETUPTOOLS_THAT_BUILDS = 77

#: A build that cannot START here — no index reachable, no backend to fetch — is the one honest
#: reason to skip. Anything else pip says about this package's own metadata is a defect in
#: pyproject.toml and must FAIL: until 2026-08-25 every non-zero build skipped, so a broken
#: `[project]` table would have read as "could not build here" forever.
CANNOT_BUILD_HERE = re.compile(
    r"Could not find a version that satisfies the requirement setuptools|"
    r"No matching distribution found for setuptools|"
    r"Temporary failure in name resolution|Could not fetch URL|"
    r"ProxyError|NewConnectionError|Network is unreachable|"
    r"No module named pip", re.IGNORECASE)


def _declared_floor() -> int:
    """The setuptools floor `[build-system]` declares, as its major version."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    specs = [r for r in data["build-system"]["requires"] if r.startswith("setuptools")]
    assert len(specs) == 1, f"expected one setuptools requirement, found {specs}"
    m = re.fullmatch(r"setuptools\s*>=\s*(\d+)(?:\.\d+)*", specs[0])
    assert m, f"the setuptools requirement is not a plain floor: {specs[0]!r}"
    return int(m.group(1))


def _isolation_flags() -> list[str]:
    """`--no-build-isolation` when the running interpreter's own setuptools satisfies the declared
    floor, so the floor is MEASURED by the build rather than resolved past: an isolated build
    fetches the newest setuptools whatever the floor says, which is exactly how a false floor
    stayed green for weeks. Isolated otherwise (no setuptools here, or one too old to be a fair
    test of the floor)."""
    try:
        have = int(importlib.metadata.version("setuptools").split(".")[0])
    except (importlib.metadata.PackageNotFoundError, ValueError):
        return []
    return ["--no-build-isolation"] if have >= _declared_floor() else []

#: Every data file the platform reads at runtime and ships in the package. Named explicitly rather
#: than globbed, because a glob here would reproduce the very bug it guards.
MUST_SHIP = [
    *[f"openfactory/org_defaults/roles/{r}.md" for r in
      ("product", "techlead", "executor", "recovery", "coordinator", "planner", "sizer")],
    "openfactory/org_defaults/engineering.md",
    "openfactory/org_defaults/tdd.md",
    "openfactory/presets/security-oss.yaml",
    # THE DEPLOYMENT'S DEFAULT GATES (#99). Measured absent from a freshly built wheel while the
    # source tree was green: `org_defaults/**/*.md` does not match a `.yaml`, and the belief that
    # `include-package-data` carries every git-tracked file is wrong — it carries what these globs
    # select. Without it `org_default_validation()` returns None in every pip install and no
    # project inherits a floor gate.
    "openfactory/org_defaults/floor.yaml",
    # THE SHIPPED PROFILES, one directory deeper than floor.yaml and therefore the same defect
    # waiting to repeat: `org_defaults/*.yaml` matches the floor and NOT these. Without them the
    # mechanism ships with no worked example, `available_profiles()` is empty in every pip
    # install, and a manifest naming `prototype` is a ProfileError on a deployment while it
    # resolves fine on the developer tree that wrote it.
    "openfactory/org_defaults/profiles/prototype.yaml",
    "openfactory/org_defaults/profiles/regulated.yaml",
    "openfactory/api/panel.html",
    # THE EVIDENCE PACK'S PUBLISHED SCHEMA (#356). `certify deployment` validates every pack
    # against it before writing; absent from a wheel, no pip install could write a pack.
    "openfactory/certify/pack.schema.json",
    # THE THRESHOLDS `certify verify` HOLDS A PACK TO (#356). Absent from a wheel, verify could
    # not judge a pack by the numbers the submissions bot uses.
    "openfactory/certify/thresholds.yaml",
]



def _pristine_source(into: str) -> Path:
    """A copy of the project holding ONLY what the build backend reads — no `build/`, no
    `*.egg-info`, no previous wheel's leftovers.

    An allowlist rather than an ignore-list, deliberately: an ignore-list has to predict every
    artefact a future tool leaves behind, and the one it misses is the one that makes this guard
    lie. It also keeps the copy at ~10 MB instead of the tree's 700 (the terraform providers under
    `infra/`), which is what makes building from scratch affordable at all."""
    src = Path(into) / "pristine"
    src.mkdir()
    shutil.copytree(ROOT / "openfactory", src / "openfactory",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for f in ("pyproject.toml", "LICENSE", "NOTICE", "README.md", *_the_declared_description()):
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, src / f)
    return src


def _the_declared_description() -> list[str]:
    """The long-description file `pyproject.toml` declares, as a path to copy — read off the
    declaration, because it is something the backend legitimately reads (#368).

    A COPY WITHOUT IT DOES NOT FAIL, AND THAT IS THE TRAP. Measured with setuptools 80.9: the
    backend warns that the file "cannot be found", writes `Description-Content-Type:
    text/markdown` all the same, and ships an EMPTY description — a wheel that looks declared and
    shows the index nothing. So the body is compared below, not only the content type."""
    readme = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"].get("readme")
    if isinstance(readme, dict) and readme.get("file"):
        return [readme["file"]]
    return [readme] if isinstance(readme, str) else []


def _what_the_backend_reads_beside_pyproject() -> list[str]:
    """Every file `pyproject.toml` names for the build backend to read, relative to it: the long
    description and the licence files. Derived, so a file declared tomorrow is required tomorrow."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    return [*_the_declared_description(), *project.get("license-files", [])]


# ── the images build the package too ───────────────────────────────────────────────────────────

def _landings(args: str, workdir: str) -> list[tuple[str, str]]:
    """`(source as written, where it lands in the image)` for one COPY/ADD, in either of Docker's
    forms. A destination ending in `/`, a `.`, or one shared by several sources is a directory and
    each FILE lands under its own basename — which is how `COPY pyproject.toml docs/pypi.md ./`
    puts the page at `./pypi.md`, where the backend does not look."""
    from test_the_public_cut_is_written_down import _copy_sources

    words = [w for w in args.split() if not w.startswith("--")]
    rest = " ".join(words).strip()
    dest = str(json.loads(rest)[-1]) if rest.startswith("[") else words[-1]
    sources = _copy_sources(args)
    into = dest.endswith("/") or dest in {".", ".."} or len(sources) > 1
    base = posixpath.join(workdir, dest)
    return [(posixpath.normpath(src), posixpath.normpath(
                posixpath.join(base, posixpath.basename(src)) if into else base))
            for src in sources]


def _what_the_build_context_lacks(text: str) -> list[str] | None:
    """For a Dockerfile that copies `pyproject.toml` in to build the package: each file the
    backend reads beside it that does not land beside it — `[]` when all do. `None` for a file
    that builds no package, so the caller can tell "carries everything" from "not one of these"."""
    from test_the_public_cut_is_written_down import _dockerfile_instructions

    workdir, landed = "/", {}
    for kind, args in _dockerfile_instructions(text):
        if kind == "WORKDIR":
            workdir = posixpath.normpath(posixpath.join(workdir, args.strip()))
        elif kind in {"COPY", "ADD"} and "--from=" not in args:
            landed.update(_landings(args, workdir))
    if "pyproject.toml" not in landed:
        return None
    beside = posixpath.dirname(landed["pyproject.toml"])
    return [rel for rel in _what_the_backend_reads_beside_pyproject()
            if landed.get(posixpath.normpath(rel)) != posixpath.join(beside, rel)]


def test_every_image_that_builds_the_package_carries_what_pyproject_declares():
    """THE IMAGES ARE THE OTHER BUILD, AND NOTHING BUILDS THEM BEFORE A TAG (#368). Each image
    copies `pyproject.toml` and the package into its WORKDIR and installs from there — and they
    copied `pyproject.toml README.md LICENSE NOTICE` while the declared long description is
    `docs/pypi.md`. setuptools 80.9 only warns and installs an empty description; the image
    builds run with build isolation and fetch whatever setuptools is current on the release day,
    and a backend that refuses a missing declared file breaks the image build on the tag — the
    one build nothing runs earlier. So what the image's build context carries is held to what
    the declaration says the backend reads, at the path it reads it from."""
    import dockerfiles

    lacking, building = {}, []
    for dockerfile in dockerfiles.tracked():
        gaps = _what_the_build_context_lacks(dockerfile.read_text())
        if gaps is None:
            continue
        building.append(dockerfile.name)
        if gaps:
            lacking[dockerfile.name] = gaps

    # DERIVED, WITH A FLOOR NAMED: an image that stops copying `pyproject.toml` the way this
    # reads it drops out of the set without a word, taking the rule with it
    assert {"cli.Dockerfile", "sandbox.Dockerfile", "worker.Dockerfile"} <= set(building), (
        f"the images that build the package are {building} — the reader no longer sees them")
    assert not lacking, (
        f"these images build the package without files pyproject.toml declares, at the path it "
        f"declares them: {lacking} — `COPY <file> ./<file>` beside `pyproject.toml`")


def test_the_context_reader_can_SEE_a_missing_or_misplaced_declared_file():
    """Verify the verifier, on the shape the images had and the two ways to get the fix wrong."""
    page = _the_declared_description()[0]
    head = "FROM python:3.12-slim\nWORKDIR /opt/openfactory\n"
    was_here = head + "COPY pyproject.toml README.md LICENSE NOTICE ./\nCOPY openfactory ./openfactory\n"
    flattened = head + f"COPY pyproject.toml README.md LICENSE NOTICE {page} ./\n"
    elsewhere = head + f"COPY pyproject.toml LICENSE NOTICE ./\nWORKDIR /tmp\nCOPY {page} ./{page}\n"
    fixed = head + f"COPY pyproject.toml README.md LICENSE NOTICE ./\nCOPY {page} ./{page}\n"
    exec_form = head + f'COPY ["pyproject.toml", "LICENSE", "NOTICE", "./"]\nCOPY ["{page}", "./{page}"]\n'

    for lacking in (was_here, flattened, elsewhere):
        assert _what_the_build_context_lacks(lacking) == [page], lacking
    for carries in (fixed, exec_form):
        assert _what_the_build_context_lacks(carries) == [], carries
    assert _what_the_build_context_lacks(head + "COPY --from=x /pyproject.toml ./\n") is None


@pytest.mark.slow
def test_every_runtime_data_file_is_inside_the_built_wheel():
    with tempfile.TemporaryDirectory() as out:
        built = subprocess.run(
            # `--no-cache-dir` IS LOAD-BEARING, NOT HYGIENE. Without it pip serves a wheel it
            # built earlier, so this guard tests the artefact from BEFORE the change — measured:
            # a mutation that removed the role prompts from the package still passed, in 1.5s,
            # which is not enough time to build anything. A guard that validates a cached copy of
            # the thing it is guarding is decoration.
            #
            # AND `--no-cache-dir` ALONE WAS NOT ENOUGH, measured the same way one level down. It
            # disables PIP's cache; it does nothing about SETUPTOOLS' state in the source tree.
            # Building `ROOT` in place reuses `build/lib/` and any `*.egg-info/SOURCES.txt` left
            # by an earlier build, and those carry files the current configuration no longer
            # selects: with `openfactory/org_defaults/floor.yaml` deliberately removed from
            # `[tool.setuptools.package-data]`, an in-tree build still shipped it (True), while the
            # same build from a pristine copy did not (False). The guard was passing for the
            # reason its own docstring warns about. So it builds from a copy that contains only
            # what the backend legitimately reads, and no artefact of any previous build.
            [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-cache-dir",
             *_isolation_flags(), "--wheel-dir", out, str(_pristine_source(out))],
            capture_output=True, text=True, timeout=600,
        )
        if built.returncode != 0:
            said = built.stderr + built.stdout
            if CANNOT_BUILD_HERE.search(said):
                pytest.skip(f"could not build a wheel here: {said[-400:]}")
            pytest.fail(
                "the package does not build — this is pyproject.toml, not this machine, and a "
                "`pip install` of the platform fails the same way on a client's:\n"
                + said[-1200:])

        wheels = list(Path(out).glob("*.whl"))
        assert wheels, "pip produced no wheel, so this guard checked nothing"
        shipped = set(zipfile.ZipFile(wheels[0]).namelist())

        # THE LICENCE TRAVELS OR THE DISTRIBUTION IS NOT A DISTRIBUTION. Without it the package is
        # legally "all rights reserved" wherever it lands: a stranger who installs it has no right
        # to use it, and an enterprise legal review stops at that line before reading any code. It
        # is checked HERE rather than in its own file because the question is identical — what does
        # `pip install` actually deliver — and because the answer is only knowable from the artefact.
        licences = [n for n in shipped if n.endswith(("/LICENSE", "/NOTICE"))]
        assert len(licences) >= 2, (
            f"the wheel carries no LICENSE/NOTICE, so every install of it is 'all rights "
            f"reserved': {sorted(shipped)[:8]}…"
        )

        # ONE CONSOLE SCRIPT, AND IT IS THE PRODUCT'S. Asserted positively — the exact set, not
        # "no old name" — because an absent alias and an absent entry-points file read the same
        # to a negative check. The former name shipped as a second script until 2026-08-25.
        entry_points = next((n for n in shipped if n.endswith("/entry_points.txt")), None)
        assert entry_points, f"the wheel declares no entry points at all: {sorted(shipped)[:8]}"
        declared = zipfile.ZipFile(wheels[0]).read(entry_points).decode()
        scripts = re.findall(r"^(\w+)\s*=", declared.split("[console_scripts]", 1)[1], re.M)
        assert scripts == ["openfactory"], (
            f"`pip install` delivers these console scripts: {scripts} — the product has one name")

        # THE PAGE THE INDEX SHOWS IS THE ONE IN THE WHEEL'S METADATA (#368), and nowhere else:
        # the upload carries METADATA, not `pyproject.toml`, so a declaration that never reaches
        # the artefact is the 0.4.0 page again — "The author of this package has not provided a
        # project description". Read out of the built wheel, as the index reads it: the content
        # type, so the page renders as markdown and not as plain text, and the body, so it is the
        # page that was written for the index and not some other file.
        metadata_file = next((n for n in shipped if n.endswith(".dist-info/METADATA")), None)
        assert metadata_file, f"the wheel carries no METADATA: {sorted(shipped)[:8]}…"
        metadata = email.parser.Parser().parsestr(
            zipfile.ZipFile(wheels[0]).read(metadata_file).decode("utf-8"))
        content_type = (metadata.get("Description-Content-Type") or "").split(";")[0].strip()
        assert content_type == "text/markdown", (
            f"the wheel's METADATA says Description-Content-Type {content_type!r} — the index "
            f"shows the page as plain text, or not at all")
        declared = _the_declared_description()
        assert len(declared) == 1, (
            f"pyproject.toml declares {declared} as the long description — one page, written for "
            f"the index, is what the guards in test_the_pypi_page_describes_the_project.py hold")
        page = (ROOT / declared[0]).read_text(encoding="utf-8")
        body = metadata.get_payload() or metadata.get("Description") or ""
        assert body.strip() == page.strip(), (
            f"the wheel's description is not {declared[0]} — the index shows {len(body)} "
            f"characters beginning {body[:80]!r}")

    missing = [f for f in MUST_SHIP if f not in shipped]
    assert not missing, (
        "these ship in the repository and NOT in the wheel, so a `pip install` of this platform "
        f"is missing them and nothing at runtime will say so: {missing}"
    )


def test_the_declared_build_floor_can_actually_build_this_package():
    """The floor is a published fact: `setuptools>=68` told every offline, mirrored or pinned
    build that 68 was enough, and 68 refuses this package's licence expression. A number written
    from care is the shape this file guards against, so the number here is anchored to a
    measurement (see `FIRST_SETUPTOOLS_THAT_BUILDS`) rather than to a memory of one."""
    floor = _declared_floor()
    assert floor >= FIRST_SETUPTOOLS_THAT_BUILDS, (
        f"[build-system] declares setuptools>={floor}, and {floor} cannot read "
        f"`license = \"Apache-2.0\"` (PEP 639 needs {FIRST_SETUPTOOLS_THAT_BUILDS}): a build that "
        f"honours the floor fails with metadata-generation-failed")


def test_a_build_that_fails_on_OUR_metadata_is_a_failure_not_a_skip():
    """The twin of the skip allowlist: pip's own wording for a broken `[project]` table must not
    match the "cannot build here" patterns, or a defect in pyproject.toml reads as a machine
    without a network. The strings are what pip 26 and setuptools 77 actually print."""
    for ours in ("configuration error: `project.license-files` must be array",
                 "error: metadata-generation-failed",
                 "ValueError: invalid pyproject.toml config: `project.license`.",
                 "ERROR: Failed to build 'file:///x' when getting requirements to build wheel"):
        assert not CANNOT_BUILD_HERE.search(ours), f"a metadata defect would be skipped: {ours!r}"
    for theirs in ("Could not find a version that satisfies the requirement setuptools>=77",
                   "Temporary failure in name resolution"):
        assert CANNOT_BUILD_HERE.search(theirs), f"a machine without a network would FAIL: {theirs!r}"


def test_the_role_prompts_exist_to_be_shipped_at_all():
    """The positive twin. If the files were deleted, the wheel test above would pass vacuously —
    absence reads as compliance, which is how three guards in this repository stayed green over a
    live defect."""
    roles = ROOT / "openfactory" / "org_defaults" / "roles"
    found = sorted(p.name for p in roles.glob("*.md"))

    assert len(found) >= 7, f"the role prompts themselves are gone: {found}"


def test_a_missing_role_prompt_is_said_out_loud(caplog, monkeypatch):
    """The degrade stays; the silence does not.

    Returning "" so the caller falls back to its own prompt is right — an agent that crashes
    because a file is absent is worse. But silence is what made the packaging bug invisible: every
    role ran with no instructions and nothing said so.
    """
    from openfactory.adapters.agent import roles

    monkeypatch.setattr(roles, "_MISSING_SAID", set())
    with caplog.at_level("WARNING"):
        assert roles.role_prompt("no-such-role") == ""

    assert "OPENFACTORY_ROLE_PROMPT_MISSING" in caplog.text
    assert "incomplete installation" in caplog.text, (
        "the message must say it is a broken install, not a configuration choice — otherwise the "
        "reader looks for a setting that does not exist"
    )


def test_it_is_said_ONCE_per_role_not_once_per_call(caplog, monkeypatch):
    """This is read on every job. A warning per call is noise, and noise teaches people to filter
    the channel that carries the real one."""
    from openfactory.adapters.agent import roles

    monkeypatch.setattr(roles, "_MISSING_SAID", set())
    with caplog.at_level("WARNING"):
        for _ in range(5):
            roles.role_prompt("no-such-role")

    assert caplog.text.count("OPENFACTORY_ROLE_PROMPT_MISSING") == 1
