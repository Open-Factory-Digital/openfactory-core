"""This repository is about to be public. It must not carry one company's infrastructure.

The product owner's instruction was literal: *"este produto não pode ter nosso passado"* — this
product cannot carry our past. It came from reading `docs/ONBOARDING.md`, which opened with

    The factory is **already deployed** (AWS, GitHub App, Temporal, panel, secrets…)

and then named an AWS account number, a GitHub App, three SSM parameter paths and a `.secrets/`
folder belonging to "the deployment owner". That is not an onboarding guide for a stranger who
downloaded the project; it is a guide for somebody joining OUR deployment, and on a public
repository it is also a disclosure of live infrastructure coordinates.

TWO KINDS OF PAST, AND ONLY ONE IS A LEAK.

  * **Infrastructure coordinates** — account ids, an App's name, SSM paths. These have no business
    being here at all, and this file refuses them outright.
  * **Provenance** — "found live on <client>, 2026-08-05". The measurement is what makes this
    codebase's comments trustworthy and it must survive; the client's identity must not. So the
    rule is anonymise, never delete: the date, the number, the mechanism and the lesson stay.

WHAT THIS FILE DELIBERATELY DOES NOT POLICE. Code identifiers and test fixture values. A project
literally named `books` in a fixture is not a disclosure, it is a string two lines of a test
agree on — and renaming one occurrence and not its twin breaks the test for nothing. The scan
below reads PROSE, and treats code as out of scope by construction rather than by exception list.

WHERE THE COORDINATES ARE, AND WHY THEY ARE NOT HERE. Until 2026-08-25 this file carried two live
account ids and a live App name in `FORBIDDEN`, and exempted itself — a guard whose one tracked
copy of the coordinates was the guard against publishing them. They now live in the gitignored
list `tests/identity_forbidden.py` reads, and this module keeps a SYNTHETIC account id and App
name of the same shape so the scan and its twin run on every machine.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

from tests import identity_forbidden as identity

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: WHAT IS NEVER PUBLISHED, whatever it says, is `identity.refused(root)` — one list for both
#: identity guards (the synthetic shapes plus this machine's real list), resolved at TEST time and
#: read by the scan AND by its twins, so an entry cannot be declared and never scanned. Nothing is
#: resolved at import: a malformed real list used to raise at module scope here and abort
#: collection of the whole suite. Each entry IDENTIFIES a specific tenant: an account number and
#: an App name point at one company's running infrastructure and at nobody else's.
#:
#: SSM PARAMETER PATHS ARE DELIBERATELY NOT IN IT, and the first version of the list had them.
#: `/sdlc/panel-token` is a NAMING CONVENTION — it names no account, no region and no tenant, and
#: every deployment that follows this project's own documentation will use exactly the same
#: string. Forbidding it was the guard overreaching, and the overreach cost something real: a
#: sweep obeying it introduced an `OPENFACTORY_SSM_PREFIX` knob that NO task definition sets, so a
#: deployment changing terraform's `ssm_prefix` would move its parameters while the panel kept
#: asking for `/sdlc/agent-tokens` — an AccessDenied swallowed by a bare `except`, reported as a
#: token count. A rule that forces a worse defect than the one it prevents is the wrong rule.
#:
#: NOT A PROPERTY PATTERN EITHER. A bare `\b\d{12}\b` was measured against the tree and fired on
#: three correct lines (a zero-GUID segment in the Azure DevOps adapter and two fixtures), so the
#: list names ids, and a new deployment's id is one more line in the gitignored file.

#: Where a stranger's eyes land first. These carry the highest bar: no old brand, no client name,
#: no personal attribution — they ARE the product's front door. Four pages, floored by
#: `test_the_front_door_is_its_four_pages_and_each_EXISTS`: a page dropped from here is a page
#: nobody judges.
#:
#: THE FOURTH PAGE IS `docs/STATUS.md` SINCE 2026-08-26. It used to be `docs/site-guide.md`, which
#: was the website's copy source and left the public tree with the documents cut; a front-door
#: entry naming a path the export excludes turns this file's own floor red in the export, where
#: the page genuinely is not there. STATUS is the page a stranger is told to read before deciding
#: anything, and it is the most heavily guarded document in the tree — so it is the one that
#: belongs here.
FRONT_DOOR = ("README.md", "NOTICE", "docs/ONBOARDING.md", "docs/STATUS.md")

_SKIP_DIRS = (".git", ".venv", "build", ".secrets", "node_modules", "__pycache__",
              ".claude", ".pytest_cache")

#: THE GUARDS ARE EXEMPT FROM THE SHAPES THEY PLANT, AND FROM NOTHING ELSE. They are the files
#: that put the forbidden shapes into their positive twins, because a scanner that cannot name
#: what it forbids cannot be tested. What they plant is SYNTHETIC; the real list is local and never
#: scanned as content. So these files are read with the REAL entries only (`identity.real_only`)
#: rather than skipped — a skipped file is where a real name sits unseen, and one did. Any OTHER
#: file claiming the same exemption is the leak this guard exists to catch, so the exemption is a
#: closed set owned by one module, not a pattern.
_EXEMPT = identity.ALLOWED_TO_NAME_THEM
#: Directories whose whole purpose is to record history, including the rename itself.
_HISTORY = ("docs/adr/",)


def _shippable(root: pathlib.Path) -> list[str]:
    """Repo-relative paths a clone receives or a `git add -A` would stage: tracked, plus untracked
    and not ignored. Sorted, so the report is stable.

    A directory that is NOT a repository has declared nothing local, so every file in it counts —
    that is the shape of the scratch trees the twins below build, and it is also the honest answer
    for a bare export: nothing there is ignored because nothing there is a `.gitignore`."""
    got = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root,
                         capture_output=True, text=True, timeout=60)
    if got.returncode != 0 or got.stdout.strip() != "true":
        return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    out: list[str] = []
    for extra in ((), ("--others", "--exclude-standard")):
        listed = subprocess.run(["git", "ls-files", "-z", *extra], cwd=root,
                                capture_output=True, text=True, timeout=120)
        assert listed.returncode == 0, f"git ls-files failed in {root}: {listed.stderr[:200]}"
        out.extend(p for p in listed.stdout.split("\0") if p)
    return sorted(set(out))


def _published_files(root: pathlib.Path = ROOT, exempt_too: bool = False):
    """Every file that would ship, as (repo-relative path, text). The exempt files only when
    asked for — the coordinate scan reads them with a narrower pattern, the provenance count
    does not read them at all."""
    # WHAT COULD SHIP, ASKED OF GIT — never the disk. The first version walked `rglob("*")` and
    # judged whatever the maintainer's machine happened to hold: an `*.egg-info/` left by an
    # editable install under the former package name, and `deploy/registry.yaml` — the live
    # pilot registry, gitignored, full of the very names this guard forbids (2026-08-26). Both
    # ship to nobody. The set a clone receives is what git tracks, plus what an unwary
    # `git add -A` would stage next: untracked files that are NOT ignored. Ignored files are, by
    # the repository's own declaration, local — and a guard that reports them teaches people to
    # delete the guard. Your machine is not the reference.
    for rel in _shippable(root):
        path = root / rel
        if not path.is_file() or rel.startswith(identity.LOCAL_ONLY) or any(
                f"/{d}/" in f"/{rel}" or rel.startswith(f"{d}/") for d in _SKIP_DIRS):
            continue
        if rel in _EXEMPT and not exempt_too:
            continue
        if path.suffix not in (".md", ".py", ".yaml", ".yml", ".html", ".tf", ".sh", ".toml",
                               ".example", ".txt", ".cfg"):
            continue
        try:
            yield rel, path.read_text(errors="ignore")
        except OSError:
            continue


def _coordinate_hits(root: pathlib.Path = ROOT) -> list[str]:
    """Every `path:line (what)` in the published prose that names an identity. An exempt file is
    read with the real entries only; on a machine without the real list there is nothing further
    to refuse in it."""
    refused = identity.refused(root)
    what_of = {token.lower(): what for token, what in refused.entries}
    hits = []
    for rel, text in _published_files(root, exempt_too=True):
        rx = refused.in_exempt if rel in _EXEMPT else refused.everywhere
        if rx is None:
            continue
        hits.extend(f"{rel}:{i} ({what_of[m.group(0).lower()]})"
                    for i, line in enumerate(text.splitlines(), 1)
                    if (m := rx.search(line)))
    return hits


def test_no_live_infrastructure_coordinate_is_published():
    """The non-negotiable half. An account id in a public repo is a disclosure, not a typo.

    One test over the whole list rather than one per entry: what is COLLECTED must not change
    with a file outside the clone, and the real list is exactly that."""
    hits = _coordinate_hits()
    assert not hits, (
        f"a tenant's coordinate is published in: {', '.join(hits[:12])}"
        + (f" (+{len(hits) - 12} more)" if len(hits) > 12 else "")
    )


def test_this_scan_can_SEE_a_coordinate_it_is_given():
    """The positive twin. A scanner that stopped matching would report a clean repository, and
    absence reading as compliance is how three guards here stayed green over live defects. Planted
    with the SYNTHETIC id and App name, so the twin is identical on every machine; the real
    lines are checked by `test_every_REAL_line_this_machine_knows_is_caught_too` next door."""
    planted = "the account is 123456789012 and the app is ExampleCoBot"
    refused = identity.refused()
    found = {what for token, what in refused.entries
             if re.search(re.escape(token), planted, re.I)}
    assert found >= {"an AWS account id", "the name of a live GitHub App"}, (
        f"the forbidden-coordinate list no longer carries both shapes: {sorted(found)}")
    assert refused.everywhere.search(planted), "the pattern the scan uses does not see the planted line"
    # And it does NOT fire on a naming convention every adopter will share — see the note above
    # FRONT_DOOR. A guard that flags correct code is a guard somebody deletes.
    assert not refused.everywhere.search("parameter = '/sdlc/panel-token'"), (
        "an SSM path is being treated as a tenant coordinate again"
    )


def test_a_synthetic_shape_in_a_NON_exempt_published_file_is_reported(tmp_path):
    """The scan's own road, on a tree of its own. The twin above verifies the pattern; nothing
    walked a tree, so a scan reading every non-exempt file with the real-only pattern (nothing
    at all on a fork), or a walk that dropped `.md` or skipped `docs/`, stayed green (reviewer's
    cuts, 2026-08-26). Two files, two shapes, and the exact report."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text(
        "# A product\n\nExampleperson decided the board has four columns.\n")
    (tmp_path / "docs" / "guide.md").write_text(
        "# Guide\n\nClone git@github.com:ExampleCo/platform.git first.\n")

    assert _coordinate_hits(tmp_path) == [
        "README.md:3 (a person's first name)",
        "docs/guide.md:3 (the organisation that builds the product)"]


def test_the_scan_reads_the_ONE_object_its_twins_read(tmp_path, monkeypatch):
    """`identity.refused(root)` is what the twins verify, so it must be what the scan reads — a
    scan building its own pattern from the same source is indistinguishable on any tree until
    the day the two builds differ. The resolver is handed one invented token; only a scan that
    reads the shared object can report it."""
    (tmp_path / "README.md").write_text("# A product\n\nplantedname wrote this.\n")
    planted = (("plantedname", "an invented identity"),)
    monkeypatch.setattr(identity, "refused", lambda root=ROOT: identity.Refused(
        planted, identity.pattern(list(planted)), None))

    assert _coordinate_hits(tmp_path) == ["README.md:3 (an invented identity)"], (
        "the scan did not read the object its twins verify")


def _a_tree_whose_exempt_file_names_a_real_person(root: pathlib.Path) -> str:
    """A tree with a real list naming a person, and the first exempt file carrying that person's
    login beside a synthetic shape. Returns the exempt file's path."""
    (root / "tests").mkdir()
    (root / "tests" / ".identity-forbidden.txt").write_text(
        "forbid:\n  jdoe   a maintainer's login\nmust_catch:\n  the login was jdoe\n")
    exempt = sorted(_EXEMPT)[0]
    (root / exempt).parent.mkdir(parents=True, exist_ok=True)
    (root / exempt).write_text("# Measured: the login was jdoe, and the shape is exampleco\n")
    return exempt


def test_an_EXEMPT_file_is_read_for_the_real_names_it_may_not_carry(tmp_path):
    """Per token, not per file. The reviewer's cut appended a real login to an exempt guard file
    and this scan, which skipped the file outright, stayed green. Proven on a tree of its own so
    it holds on a machine without the real list."""
    exempt = _a_tree_whose_exempt_file_names_a_real_person(tmp_path)

    assert _coordinate_hits(tmp_path) == [f"{exempt}:1 (a maintainer's login)"]


def test_but_the_shapes_an_EXEMPT_file_plants_are_not_offences(tmp_path):
    """The other direction: without a real list the exempt file is exempt from everything the
    tree knows, and the scan must not turn an empty real list into a match-everything pattern."""
    _a_tree_whose_exempt_file_names_a_real_person(tmp_path)
    (tmp_path / "tests" / ".identity-forbidden.txt").unlink()

    assert _coordinate_hits(tmp_path) == []


def test_the_scan_judges_what_could_ship_and_not_what_the_machine_holds(tmp_path):
    """Both directions, on a repository of its own. A file a `git add -A` would stage next is
    reported; a file the repository has declared local — gitignored, like the live registry and
    a build's egg-info on the maintainer's disk — is not. The first version walked the disk and
    reported the maintainer's own local files as published coordinates (2026-08-26)."""
    def git(*a):
        return subprocess.run(["git", *a], cwd=tmp_path, capture_output=True, timeout=60)

    git("init", "-q")
    (tmp_path / ".gitignore").write_text("deploy/registry.yaml\n*.egg-info/\n")
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "registry.yaml").write_text("owner: Exampleperson\n")
    (tmp_path / "x.egg-info").mkdir()
    (tmp_path / "x.egg-info" / "SOURCES.txt").write_text("exampleco/README.md\n")
    (tmp_path / "NOTES.md").write_text("# Notes\n\nExampleperson wrote these.\n")

    assert _coordinate_hits(tmp_path) == ["NOTES.md:3 (a person's first name)"], (
        "the scan reports what the repository declared local, or misses what would ship next")


def test_a_MALFORMED_real_list_fails_the_scan_with_the_line_that_is_wrong(tmp_path):
    """A hand-edited list fails the tests that read it, at test time, naming the line — never
    collection (`test_a_MALFORMED_real_list_does_not_abort_COLLECTION` next door collects a copy
    of this module over such a file). Both readers of the list in this module are held to it."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / ".identity-forbidden.txt").write_text(
        "# edited by hand\nacmeholdings   the parent company\nforbid:\n")
    (tmp_path / "README.md").write_text("# A product\n")

    with pytest.raises(ValueError, match="line 2 belongs to no section"):
        _coordinate_hits(tmp_path)
    with pytest.raises(ValueError, match="line 2 belongs to no section"):
        _front_door_offences(tmp_path / "README.md", root=tmp_path)


#: What the front door refuses, beyond every identity in the shared list: rules about the
#: PRODUCT's own past rather than about a name. Personal names and the former parent company
#: used to be spelled here as their own two rules; moving them into the shared list lost both
#: (the real first name is a commented entry in the gitignored file until the legacy guards
#: stop quoting it), and a personal name planted in the README passed on every machine. The
#: shared list now carries a synthetic first name and a synthetic former company, and
#: `test_the_front_door_check_can_SEE_every_shape_it_refuses` plants each.
_FRONT_DOOR_RULES: tuple[tuple[str, str], ...] = (
    (r"[Dd]ark ?[Ff]actory", "the former product name"),
    (r"\.secrets/", "a credentials folder only we have"),
    (r"already deployed", "an assumption that the reader is joining OUR deployment"),
)

_A_NAME = "the name of an owner, a person or a client"


def _front_door_offences(page: pathlib.Path, root: pathlib.Path = ROOT) -> list[str]:
    """What a front-door page still carries, by shape. TAKES THE PAGE, READS IT HERE, AND REFUSES
    AN EMPTY READ: the first version took text, and a caller handing it `''` judged nothing and
    stayed green (reviewer's cut, 2026-08-26) — the four real pages were never read."""
    text = page.read_text()
    assert text.strip(), f"{page} was read as an empty page — nothing here was judged"
    rules = [*_FRONT_DOOR_RULES, (identity.refused(root).everywhere.pattern, _A_NAME)]
    return [what for pattern, what in rules if re.search(pattern, text, re.IGNORECASE)]


def test_the_front_door_is_its_four_pages_and_each_EXISTS():
    """The floor under the parametrisation below: dropping a page from `FRONT_DOOR` used to drop
    it from judgement, and a page that does not exist used to be a skip. Four named pages, each
    on disk — a missing README is not "nothing to judge", it is a product with no front door."""
    assert set(FRONT_DOOR) >= {"README.md", "NOTICE", "docs/ONBOARDING.md", "docs/STATUS.md"}
    missing = [doc for doc in FRONT_DOOR if not (ROOT / doc).is_file()]
    assert not missing, f"front-door pages that do not exist: {missing}"


@pytest.mark.parametrize("doc", FRONT_DOOR)
def test_the_front_door_carries_nobodys_past(doc):
    """What a stranger reads first must be about THEIR project, not about ours."""
    offences = _front_door_offences(ROOT / doc)
    assert not offences, (
        f"{doc} still carries {' and '.join(offences)} — this is the first page somebody reads "
        f"about a product they are deciding whether to adopt"
    )


@pytest.mark.parametrize("doc", FRONT_DOOR)
def test_the_front_door_check_READS_the_page_it_is_pointed_at(doc, tmp_path):
    """The wiring, proven per page: a COPY of each real front-door page with one offender
    appended must be reported — a check that reads the page it is pointed at reports it, a check
    reading anything else (nothing, a constant) cannot."""
    copy = tmp_path / pathlib.Path(doc).name
    shutil.copy(ROOT / doc, copy)
    with copy.open("a") as f:
        f.write("\nExampleperson decided the board has four columns.\n")

    assert _front_door_offences(copy) == [_A_NAME], (
        f"an offender appended to a copy of {doc} is not reported — the check is not reading "
        f"the page it is given")


def test_the_front_door_check_refuses_an_EMPTY_page(tmp_path):
    """The read is asserted, not assumed: a page that reads as nothing is a failure naming the
    page, never a clean verdict."""
    (tmp_path / "README.md").write_text("")
    with pytest.raises(AssertionError, match="empty page"):
        _front_door_offences(tmp_path / "README.md")


@pytest.mark.parametrize(("planted", "what"), [
    # THE FORMER PRODUCT NAME IS AN IDENTITY, not a rule of its own: it lives in the identity list
    # (synthetic here, the real spelling in the local file), so the front door reports it under
    # the identity label like a person's or a client's name — one list, one label, never a second
    # copy of the same token in a tracked dict (the merge of 2026-08-26 is where two copies met).
    ("built by the FormerProduct team", _A_NAME),
    ("keys live in .secrets/ next to the checkout", "a credentials folder only we have"),
    ("the factory is already deployed for you", "an assumption that the reader is joining OUR "
                                                "deployment"),
    ("Exampleperson decided the board has four columns", _A_NAME),
    ("the first version was written at FormerCoAI", _A_NAME),
    ("questions to maint@example.invalid", _A_NAME),
    ("the pilot ran at ExampleClient", _A_NAME),
])
def test_the_front_door_check_can_SEE_every_shape_it_refuses(planted, what, tmp_path):
    """Verify the verifier, one planted sentence per shape. The first name and the former company
    are the two this check lost once without anybody noticing — a personal name in the README
    passed on a machine WITH the real list, because the real entry was commented out and no
    synthetic one stood in for it."""
    page = tmp_path / "page.md"
    page.write_text(f"# A product\n\nAn ordinary paragraph.\n\n{planted}\n")
    assert _front_door_offences(page) == [what], (
        f"the front door does not see {what}: {planted!r}")


def test_the_front_door_check_leaves_an_ordinary_page_alone(tmp_path):
    """Its twin: a clean page raises nothing, or the check is a list of words that fires on
    everything."""
    page = tmp_path / "page.md"
    page.write_text("# OpenFactory\n\nClone it, run `openfactory doctor`, open the panel.\n")
    assert _front_door_offences(page) == []


def test_the_onboarding_guide_assumes_nothing_the_reader_does_not_have():
    """It used to open by listing what somebody ELSE had already set up for you.

    The whole first hour has to run on a laptop, and the document has to say so, or a team that
    downloads this cannot get past the first heading.
    """
    text = (ROOT / "docs/ONBOARDING.md").read_text()
    assert "does not assume a cloud account" in text or "assumes about you: nothing" in text, (
        "the guide no longer states that it needs nothing the reader does not have"
    )
    for needed in ("docker compose --env-file .env.compose up", "openfactory box prove", "openfactory env check",
                   "openfactory env rehearse"):
        assert needed in text, f"the first hour no longer includes `{needed}`"
    assert "make deploy" not in text, (
        "the guide sends a new reader at a deploy script for infrastructure they do not have"
    )


def test_every_command_the_onboarding_guide_prints_is_one_that_EXISTS():
    """A first-hour guide whose commands do not run is worse than no guide.

    Checked against the CLI itself, not against a list somebody maintains by hand — the guide and
    the binary drift silently otherwise, and the drift surfaces in front of a client.
    """
    import subprocess
    import sys

    text = (ROOT / "docs/ONBOARDING.md").read_text()
    top = subprocess.run([sys.executable, "-m", "openfactory.cli", "--help"],
                         capture_output=True, text=True, cwd=str(ROOT)).stdout
    top = re.sub(r"\x1b\[[0-9;]*m", "", top)

    missing = []
    for group, sub in sorted(set(re.findall(r"openfactory ([a-z-]+)(?: ([a-z-]+))?", text))):
        if group not in top:
            missing.append(group)
            continue
        if not sub:
            continue
        out = subprocess.run([sys.executable, "-m", "openfactory.cli", group, "--help"],
                             capture_output=True, text=True, cwd=str(ROOT)).stdout
        out = re.sub(r"\x1b\[[0-9;]*m", "", out)
        if "Commands" not in out:
            # a leaf command (`onboard myapp`, `doctor myapp`): the lowercase token after it
            # is its ARGUMENT — the CLI's own --help is the authority on which kind it is
            continue
        if not re.search(rf"^\s*\W?\s*{re.escape(sub)}\b", out, re.M) and f"--{sub}" not in out:
            missing.append(f"{group} {sub}")
    assert not missing, f"the onboarding guide prints commands that do not exist: {missing}"


def test_provenance_is_ANONYMISED_and_not_deleted():
    """The other half, and the one that is easy to get wrong in the destructive direction.

    Stripping a client's name is right. Stripping the measurement with it would throw away what
    makes these comments worth reading — this codebase's defect notes carry dates, exit codes and
    turn counts, and those are the reason a stranger believes any of it.
    """
    measured = 0
    for rel, text in _published_files():
        if not rel.startswith(("openfactory/", "docs/")) or any(rel.startswith(h) for h in _HISTORY):
            continue
        measured += len(re.findall(r"[Ff]ound live|[Mm]easured (?:on|live|it)|reproduced", text))
    # THE FLOOR IS MEASURED, NOT GUESSED. 54 such notes existed when this guard was written (I
    # asserted 60 from memory first and the count said 54 — the same mistake this file exists to
    # prevent, one layer up). 40 is deliberately well under it: this is a ratchet against a purge
    # that GUTS the record, not a target that fails on ordinary editing.
    assert measured >= 40, (
        f"only {measured} measured-provenance notes survive across openfactory/ and docs/ — a "
        f"purge that "
        f"removed the measurements along with the names took the evidence with the identity"
    )
