"""OpenFactory belongs to nobody's company (#137).

The product owner, 2026-08-17: *"a openfactory nao podera ter nenhuma relacao com a [the company
that built it], sera opensource com contributors"*.

THE RULE, stated so it survives the company that happens to be holding it today: the product must
not carry the name of the ORGANISATION THAT BUILDS IT, or the identity of any single person who
maintains it. Not in the package, not in the panel, not in the docs, not in a fixture. A contributor
who arrives next month should find nothing in the tree that says whose it is.

WHY A GUARD AND NOT A SWEEP. A one-off grep is true on the day it runs. The name of a deployment,
an org login or a maintainer's home directory arrives in a fixture, an example command or a pasted
error message every week — three did, and one of them was a binary artefact committed by accident
whose absolute paths published the maintainer's home directory to every clone.

WHERE THE NAMES ARE, AND WHY THEY ARE NOT HERE. Until 2026-08-25 this file carried the real
lists and exempted itself from its own scan — so the one tracked file that named the maintainer,
the company and every client was the guard against naming them, and a fresh history would have
shipped it in commit 1. The lists now live in a gitignored file and this module keeps only
SYNTHETIC entries of the same shapes; `tests/identity_forbidden.py` explains the split and the
file format. Everything below runs on both kinds of machine and means the same thing on each.

WHAT THIS DOES NOT CLAIM. The repository still LIVES at a URL under an organisation, and git
history still holds what history holds. Both are outside a test's reach and are the owner's call;
this asserts what a fresh clone's WORKING TREE says about who owns the product.

WHERE THIS ENDS AND `test_the_product_carries_no_ones_past.py` BEGINS — read both before widening
either. That file forbids one tenant's INFRASTRUCTURE COORDINATES (account ids, a live App name)
and deliberately scans PROSE only, on a documented reason: a fixture project called `books` is not
a disclosure, it is a string two lines of a test agree on, and renaming one occurrence and not its
twin breaks a test for nothing.

TWO RULES LIVE HERE, AND THE SECOND ONE IS NOT A LIST. Everything above is a deny list, and on
2026-08-26 a deny list failed the way deny lists fail: a client's three-letter organisation
abbreviation shipped ten times across five files as the leading segment of a code namespace, and
every scan here was green — nobody had listed the token, and the bare three letters could not be
listed (they are an ordinary Portuguese word stem). So
`test_no_namespace_in_the_tree_belongs_to_an_UNDECLARED_ORGANISATION` derives instead: a dotted
coordinate's ROOT segment must be one this tree DECLARED, either as a vendor's published protocol
or as its own invention. Undeclared is refused. It needs no foresight about whose name arrives
next, it has no exemption set, and it would have caught that abbreviation the day it landed.

This file is the one exception to that doctrine, and only for IDENTITIES — an organisation's name,
a maintainer's login. A person's GitHub login in a fixture is not a neutral value like `books`: it
is a real account, and a public repository full of it says whose product this is on every page. So
identities are refused everywhere, including code and fixtures, and everything else stays under
the prose-only rule next door. Do not move generic fixture values into the forbidden list.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests import identity_forbidden as identity

ROOT = Path(__file__).resolve().parent.parent

#: The paths that legitimately mention a (synthetic) name: the module that defines the shapes,
#: the two guards that plant them in their positive twins, and the mutation plans that prove the
#: guards bite. One set, owned by the module, so the two guards cannot disagree about it.
ALLOWED = identity.ALLOWED_TO_NAME_THEM

#: WHAT THE SCAN REFUSES IS RESOLVED BY `identity.refused(root)`, AT TEST TIME, AND NOWHERE ELSE.
#: The scan and every twin below read that one object — a pattern built here and a different one
#: verified below is how a list gets declared and never read, and this file did exactly that once
#: while its own comment said the opposite. Nothing is resolved at import: a malformed real list
#: used to raise at module scope and abort collection of the WHOLE suite on that machine
#: (`test_a_MALFORMED_real_list_does_not_abort_COLLECTION` is the proof it no longer can).


def _tracked(root: Path = ROOT) -> list[str]:
    """Every file a fresh clone gets. `git ls-files` rather than a glob: the question is what a
    CONTRIBUTOR receives, and an untracked scratch file on somebody's laptop is not that."""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True,
                         timeout=120)
    assert out.returncode == 0, f"git ls-files failed: {out.stderr[:200]}"
    return [p for p in out.stdout.split("\0") if p]


def _content(rel: str, root: Path = ROOT) -> str | None:
    """What a fresh clone RECEIVES for this path, or None when there is no text to judge.

    READ FROM THE INDEX WHEN THE WORKING TREE HAS NOTHING, because those are different questions
    and only one of them is this file's. A tracked file deleted from my checkout is still shipped
    to everybody who clones — and reading it off disk turns that into a `FileNotFoundError` that
    the old code caught beside the binary case and skipped into silence.

    IT HID A REAL DISCLOSURE. `.mutate-in-flight` is the mutation runner's crash marker; it exists
    on disk only DURING a round and names the wound as two absolute paths out of the maintainer's
    home directory. A `git add -A` swept it into 015f806, the next round finished and removed it,
    and from that moment the guard could never see it again: tracked, shipped, and invisible. It
    was found by reading a diff, not by this test.

    ABSENCE READ AS COMPLIANCE — the shape this repository keeps paying for. A guard that says
    "nothing contains X" cannot see a thing that is MISSING from where it looks."""
    try:
        return (root / rel).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None  # binary — judged by `test_no_BINARY_artefact_is_tracked` instead
    except OSError:
        pass
    out = subprocess.run(["git", "show", f":{rel}"], cwd=root, capture_output=True, timeout=60)
    if out.returncode != 0:
        return None  # staged for deletion: tracked here, absent from the next clone
    try:
        return out.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _offenders(root: Path = ROOT) -> list[str]:
    """Every `path:line  token` in the tracked tree that names an identity.

    THE EXEMPT FILES ARE SCANNED TOO, for the names they are not allowed to plant. The set in
    `identity.ALLOWED_TO_NAME_THEM` used to mean "skip this file", and a reviewer's cut proved
    what that means: a real login appended to an exempt guard file left the whole guard green,
    and the first version of the shared module's own docstring carried the maintainer's surname
    that way. So an exempt file is read with the REAL entries only — the union minus the
    synthetic shapes it exists to plant — and on a machine without the real list there is
    nothing further to refuse in it, which is what an empty pattern must mean (never "match
    everything")."""
    refused = identity.refused(root)

    offenders = []
    for rel in _tracked(root):
        rx = refused.in_exempt if rel in ALLOWED else refused.everywhere
        if rx is None:
            continue
        text = _content(rel, root)
        if text is None:
            continue
        for hit in rx.finditer(text):
            line = text.count("\n", 0, hit.start()) + 1
            offenders.append(f"{rel}:{line}  {hit.group(0)}")
    return offenders


def test_the_tracked_tree_names_no_owner():
    files = _tracked()
    assert len(files) > 200, f"only {len(files)} tracked files — the listing is not the repository"

    offenders = _offenders()

    assert not offenders, (
        "the product names the organisation or person that owns it, or a client that pays for "
        "it — this is an open-source product and a contributor must find nothing in the tree "
        "that says whose it is, nor anything that says who its clients are. The EVIDENCE a "
        "client's case gave you is worth keeping; write the property, not the name:\n  "
        + "\n  ".join(offenders))


def test_no_BINARY_artefact_is_tracked():
    """The half a text search cannot see. `.coverage` is a SQLite file whose rows are ABSOLUTE
    paths from whoever ran the suite — it was committed by accident and published the maintainer's
    home directory to every clone. Nothing in this repository needs to ship a build artefact, so
    the honest guard is that none is tracked at all."""
    artefacts = [f for f in _tracked()
                 if re.search(r"(^|/)\.coverage|\.pyc$|\.sqlite\d?$|(^|/)metrics\.db$|"
                              r"\.log$|(^|/)__pycache__/", f)]
    assert not artefacts, (
        "build artefacts are tracked; they carry absolute paths from the machine that made "
        "them:\n  " + "\n  ".join(artefacts))


def test_the_PACKAGE_identifies_itself_by_the_product():
    """The positive twin. "No owner's name anywhere" is satisfied by a package with no identity at
    all, and the thing a contributor first reads is exactly this."""
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert 'name = "openfactory"' in pyproject, "the package no longer calls itself the product"
    assert "openfactory" in pyproject.lower().split("[project.urls]")[0] or \
           "openfactory" in pyproject.lower(), "the package's own metadata does not name it"


# ── trees of their own: what the scan does is proven where this repository cannot show it ───────

def _committed_tree(tmp_path: Path, files: dict[str, str]) -> None:
    """A repository holding exactly these files, committed — the shape every twin below needs,
    because on THIS repository the defects they prove are fixed and a guard asserting against
    the live tree would pass whether the fix is present or not."""
    def run(*a):
        return subprocess.run(["git", *a], cwd=tmp_path, capture_output=True, timeout=60)

    run("init", "-q")
    run("config", "user.email", "guard@example.invalid")
    run("config", "user.name", "Guard")
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
        run("add", rel)
    assert run("commit", "-qm", "a tree of its own").returncode == 0


# ── the derived rule: a namespace root is a vendor's, or ours, or nobody ships it ────────────────

#: Coordinates in the shape a client's own taxonomy arrives in, BUILT FROM PARTS and never written
#: out. A guard that spells a foreign coordinate as a literal is one more tracked file carrying a
#: foreign coordinate — the very defect this scan refuses, and the defect the shared module's own
#: first docstring committed. Composing them is also why this scan needs no exemption set at all:
#: there is nothing in the tree for it to be exempt from.
_FOREIGN_COORDINATES = (
    ".".join(("ZZQ", "CF", "Deskline", "Context")),      # an organisation abbreviation as a root
    ".".join(("Undeclaredco", "Core", "Scheduling")),    # and a whole word as a root
)


def _foreign_coordinates(root: Path = ROOT) -> list[str]:
    """Every `path:line  literal` in the tracked tree whose namespace root is undeclared.

    NO EXEMPTION SET, deliberately. The deny list next door needs one, because a guard against
    names has to name them; this one needs none, because every twin below composes its offender
    at run time. An exemption is the one hole a scan has, and this scan does not have it."""
    offenders = []
    for rel in _tracked(root):
        text = _content(rel, root)
        if text is None:
            continue
        offenders += [f"{rel}:{line}  {literal}"
                      for line, literal in identity.foreign_namespaces(text)]
    return offenders


def test_no_namespace_in_the_tree_belongs_to_an_UNDECLARED_ORGANISATION():
    """The derived half of the doctrine, and the guard the leak of 2026-08-26 needed.

    A client's abbreviation shipped as `<THEIRS>.<Sub>.<Product>.<Thing>` in two onboarding
    modules and three test files, and every list-based scan was green over it because nobody had
    written the token down — and nobody could, because the three letters are also a Portuguese
    word stem that four innocent tracked files contain. Enumeration was not the fix available.

    So this asks a question that needs no foresight: WHOSE taxonomy is this? A root is either a
    vendor's published protocol or something this tree invented, and both are declared in
    `identity_forbidden`. Anything else belongs to somebody, and it fails CLOSED — the polarity
    the deny list cannot have."""
    files = _tracked()
    assert len(files) > 200, f"only {len(files)} tracked files — the listing is not the repository"

    offenders = _foreign_coordinates()

    assert not offenders, (
        "a dotted namespace in the tree is rooted in a name this repository never declared — a "
        "coordinate's first segment says whose taxonomy it is, and this one is neither a vendor's "
        "published protocol nor anything we invented, so it is a client's. Rewrite it onto the "
        "synthetic family the fixtures already use; declare the root in "
        "`identity_forbidden.OUR_NAMESPACE_ROOTS` ONLY if we made the name up:\n  "
        + "\n  ".join(offenders))


@pytest.mark.parametrize("coordinate", _FOREIGN_COORDINATES)
def test_a_FOREIGN_namespace_root_IS_REPORTED(tmp_path, coordinate):
    """The positive twin: plant a coordinate rooted in a name nobody declared and watch it fire.
    On a tree of its own, because on THIS repository the defect is fixed and a twin asserting
    against the live tree would pass whether the rule works or not.

    Two roots, because the two ways a taxonomy is rooted are not the same string: an organisation
    ABBREVIATION (which is how it actually leaked) and a whole word."""
    _committed_tree(tmp_path, {
        "openfactory/onboarding/context.py": f'"""Their layout is `{coordinate}`."""\n'})

    assert _foreign_coordinates(tmp_path) == [
        f"openfactory/onboarding/context.py:1  {coordinate}"]


def test_but_a_VENDORS_and_OUR_OWN_roots_are_left_alone(tmp_path):
    """Its other half. A rule that fires on `Microsoft.VSTS.Common.StackRank` — the field name an
    Azure DevOps adapter is REQUIRED to send — is a rule that gets deleted, not obeyed; and one
    that fires on the synthetic family the fixtures already use makes the safe rewrite impossible.
    Both roots are declared, so both must pass, and this is the twin that says so."""
    _committed_tree(tmp_path, {
        "adapter.py": 'FIELD = "Microsoft.VSTS.Common.StackRank"\n',
        "fixture.py": 'PURPOSE = "Painel de admissao (ACM.CA.Deskline.UI)."\n',
        "dotnet.py": 'CS = "[assembly: System.Reflection.AssemblyTitleAttribute(\'F\')]"\n',
    })

    assert _foreign_coordinates(tmp_path) == []


def test_the_rule_leaves_ORDINARY_TWO_SEGMENT_CODE_alone():
    """The false-positive twin, measured rather than hoped. Two dotted segments is how every
    attribute access and every module path in this repository is spelled; a rule that counted
    those would report hundreds of them on day one and be switched off on day two. Three is the
    floor, and a lowercase root is not a coordinate at all."""
    for innocent in ("evidence = Evidence.excerpt",
                     "from openfactory.onboarding.context import ContextLayout",
                     "path = Path.home() / '.openfactory'",
                     "re.Pattern[str] is the annotation",
                     "self.forge.repo == 'acme/widgets'",
                     "See docs/setup/azure-devops.md for the rest."):
        assert identity.foreign_namespaces(innocent) == [], (
            f"the rule fires on ordinary code: {innocent!r}")


def test_every_DECLARED_root_is_used_by_something():
    """The twin that keeps the allow-list honest. Declaring a root is the claim "a vendor
    publishes this" or "we made this name up", and an entry nothing uses is a hole waiting for
    the next name to be dropped into it — the shape `ALLOWED_TO_NAME_THEM` is held to next door,
    for the same reason. So every declared root must actually root a literal in the tree."""
    used = set()
    for rel in _tracked():
        text = _content(rel)
        if text is None:
            continue
        used |= {m.group(0).split(".")[0] for m in identity.NAMESPACE_LITERAL.finditer(text)}

    declared = identity.VENDOR_NAMESPACE_ROOTS | identity.OUR_NAMESPACE_ROOTS
    assert declared, "the declared roots are empty — every coordinate would be reported"
    idle = sorted(declared - used)
    assert not idle, (
        "namespace roots are declared and nothing in the tree uses them; an idle entry is an "
        "exemption waiting to be used, not a fact about this repository:\n  " + "\n  ".join(idle))


def _repo_with_a_swept_marker(tmp_path: Path) -> None:
    """A repository in the state 015f806 was in: a scratch file carrying an absolute path out of
    somebody's home directory, committed by a `git add -A` that was aimed at something else."""
    _committed_tree(tmp_path, {
        "marker.json": '{"file": "/Users/example-maintainer/Projects/x.py"}'})


def test_a_tracked_file_DELETED_from_the_working_tree_is_still_judged(tmp_path):
    """The blind spot, rebuilt from scratch — because on THIS repository it can no longer be
    reproduced: the offending file has been untracked, so a guard asserting against the live tree
    would pass whether the fix is present or not.

    The sequence is the one that actually happened. A scratch file exists during a mutation round,
    `git add -A` commits it, the round finishes and deletes it. Tracked, shipped to every clone,
    and gone from the only place the old code looked."""
    _repo_with_a_swept_marker(tmp_path)

    assert _tracked(tmp_path) == ["marker.json"]
    (tmp_path / "marker.json").unlink()  # the mutation round finishes and cleans up after itself

    text = _content("marker.json", tmp_path)

    assert text is not None, (
        "a tracked file that is absent from the working tree reads as having no content — every "
        "clone gets it and this guard cannot see it")
    assert identity.refused().everywhere.search(text), (
        "the index content came back without what it carries")


def test_but_a_file_STAGED_FOR_DELETION_is_not_shipped_and_is_not_judged(tmp_path):
    """The positive twin. Falling back to the index must not resurrect a file somebody has already
    removed — that would make the guard fire on content no clone will ever receive, which is how a
    guard gets deleted rather than obeyed.

    This is the repair being made in this very commit, asserted rather than assumed."""
    _repo_with_a_swept_marker(tmp_path)
    subprocess.run(["git", "rm", "-q", "-f", "marker.json"], cwd=tmp_path, capture_output=True,
                   timeout=60)

    assert _tracked(tmp_path) == [], "the file is still tracked — this asserts nothing"
    assert _content("marker.json", tmp_path) is None


def test_a_synthetic_shape_in_a_NON_exempt_tracked_file_is_reported(tmp_path):
    """The scan's own road, on a tree of its own — the twin every bite test below is not. Those
    verify the pattern; none of them walked a tree, so a scan reading every non-exempt file with
    the real-only pattern (nothing at all on a fork), or with one entry of the list, stayed green
    (reviewer's cuts, 2026-08-26). Two files, two shapes, and the exact report."""
    _committed_tree(tmp_path, {
        "README.md": "# A product\n\nExampleperson decided the board has four columns.\n",
        "docs/guide.md": "# Guide\n\nClone git@github.com:ExampleCo/platform.git first.\n",
    })

    assert _offenders(tmp_path) == ["README.md:3  Exampleperson", "docs/guide.md:3  ExampleCo"]


def test_the_scan_reads_the_ONE_object_its_twins_read(tmp_path, monkeypatch):
    """`identity.refused(root)` is what the twins verify, so it must be what the scan reads — a
    scan building its own pattern from the same source is indistinguishable on any tree until
    the day the two builds differ, and that is the day the twins verify nothing. So the resolver
    is handed a list of one invented token and the scan has to report that token: the only way
    that happens is by reading the shared object."""
    _committed_tree(tmp_path, {"README.md": "# A product\n\nplantedname wrote this.\n"})
    planted = (("plantedname", "an invented identity"),)
    monkeypatch.setattr(identity, "refused", lambda root=ROOT: identity.Refused(
        planted, identity.pattern(list(planted)), None))

    assert _offenders(tmp_path) == ["README.md:3  plantedname"], (
        "the scan did not read the object its twins verify")


@pytest.mark.parametrize("smuggled", identity.SYNTHETIC_MUST_CATCH)
def test_the_guard_ACTUALLY_BITES(smuggled):
    """Verify the verifier. A name list is exactly the shape that passes because it missed — so
    feed it the ways a name actually arrived in this tree (a board URL, a clone URL, a home
    directory, a pasted API error, evidence in a docstring, an internal repository URL, a support
    address, an account id beside an App name) before trusting a green run. Parametrised over the
    SYNTHETIC lines, so the list is the same on every machine and the collection never changes
    with a local file."""
    assert identity.refused().everywhere.search(smuggled), (
        f"an owner's name walked straight past the guard: {smuggled!r}")


def test_every_REAL_line_this_machine_knows_is_caught_too():
    """The same verification over the real list, where present. The real `must_catch:` lines are
    the exact strings that were in this tree on 2026-08-24 — evidence in a docstring, a fixture
    identifier, an internal URL in a how-to, the pilot's own repository, an address — and a real
    list whose pattern misses one of its own lines is a list that passes for the wrong reason.

    One test rather than a parametrisation, on purpose: what is COLLECTED must not depend on a
    file outside the clone (`tests/test_ci_runs_what_we_run.py` is the guard for that shape)."""
    lines = identity.must_catch()
    assert len(lines) >= len(identity.SYNTHETIC_MUST_CATCH), "the synthetic lines went missing"
    everywhere = identity.refused().everywhere
    missed = [line for line in lines if not everywhere.search(line)]
    assert not missed, (
        "lines the real list says MUST be caught walk past the pattern the scan uses:\n  "
        + "\n  ".join(missed))


def test_every_forbidden_token_has_a_line_that_must_catch_it():
    """The floor under verify-the-verifier. The `must_catch` lines are how the pattern is proven
    to see the shapes a name arrives in — and a reviewer's cut deleted the address-in-prose line
    and nothing went red, so the list could shrink to nothing and the verifier would verify
    nothing. Two floors: every token the machine forbids (synthetic and real) is carried by at
    least one line, and the synthetic list keeps at least its measured size.

    THE SIZE FLOOR IS A RATCHET AND IT HAD ROTTED. It was written as ten when the list held ten;
    an eleventh line arrived with the infrastructure-coordinate shapes and the floor stayed at
    ten, so exactly one line could be deleted with everything green — and one was, by a mutation
    cut that survived on 2026-08-26. The floor is raised with the list, deliberately, or it
    measures the list as it was rather than as it is. Eleven lines for nine shapes: two of them
    arrive by two roads (an organisation as a board URL and as a clone URL; a login as a home
    directory and as a pasted API error), which is why a token surviving elsewhere does not make
    a deleted line redundant."""
    lines = [line.lower() for line in identity.must_catch()]
    uncarried = [f"{token!r} ({what})" for token, what in identity.refused().entries
                 if not any(token.lower() in line for line in lines)]
    assert not uncarried, (
        "tokens the guard forbids that no must_catch line carries — the verifier is not "
        "verified for them:\n  " + "\n  ".join(uncarried))
    assert len(identity.SYNTHETIC_MUST_CATCH) >= 11, (
        f"the synthetic must_catch list shrank to {len(identity.SYNTHETIC_MUST_CATCH)} lines. A "
        f"line whose token has a second road is NOT redundant — it is a shape the name arrives "
        f"in, and dropping it is how the verifier stops verifying that shape. Raise this floor "
        f"when the list grows; never lower it to match a deletion")


def test_the_guard_leaves_the_PRODUCT_alone():
    """Its positive twin: a name list broad enough to catch "openfactory" or "github" would fire on
    every file and be deleted within a week."""
    everywhere = identity.refused().everywhere
    for innocent in ("openfactory doctor podbeam",
                     "https://github.com/acme/widgets",
                     "the operator ran `openfactory act enable`",
                     "OPENFACTORY_STATE_DIR=/var/lib/openfactory",
                     "guard@example.invalid committed it",
                     "the account id has twelve digits"):
        assert not everywhere.search(innocent), (
            f"the guard fires on ordinary product text: {innocent!r}")


def test_the_list_is_neither_empty_nor_unread():
    """The twin the scan cannot provide for itself. `test_the_tracked_tree_names_no_owner` passes
    just as green with an EMPTY list, or with a list built and then not scanned — absence reading
    as compliance, which is this repository's most expensive shape.

    So this asserts the three things the scan takes for granted: every shape has an entry, the
    real list (when present) was unioned in rather than replacing them, and the pattern the scan
    actually uses carries every entry."""
    shapes = {what for _, what in identity.SYNTHETIC_FORBID}
    assert len(shapes) >= 8, f"the synthetic list no longer covers every shape: {sorted(shapes)}"
    refused = identity.refused()
    tokens = {token for token, _ in refused.entries}
    assert {token for token, _ in identity.SYNTHETIC_FORBID} <= tokens, (
        "the synthetic entries are not in the scanned list — the real file REPLACED them, so a "
        "machine without it scans for nothing")
    for token, what in refused.entries:
        assert refused.everywhere.search(f"…{token}…"), (
            f"{token!r} ({what}) is declared and the pattern the scan uses does not carry it")


def test_the_exemption_set_is_CLOSED_and_every_entry_earns_its_place():
    """The exemption is the one hole the scan has, so it is held to two things. Closed: only a
    guard or a mutation plan may be in it — a document or a package module added to the set
    would exempt real content from the scan (a mutation that added `README.md` survived until
    this twin existed, because the scan honoured the set without asking what was in it). Earned:
    every entry actually plants a synthetic shape; an exempt file that names nothing is an
    exemption waiting to be used. (And exempt from the shapes ONLY — `_offenders` reads these
    files with the real entries, proven on a tree of its own below.)"""
    pattern = identity.pattern(list(identity.SYNTHETIC_FORBID))
    for rel in sorted(ALLOWED):
        assert rel.startswith(("tests/", "tools/mutations/")) and rel.endswith(".py"), (
            f"{rel} is exempt from the identity scan and is neither a guard nor a mutation plan")
        text = _content(rel)
        assert text is not None and pattern.search(text), (
            f"{rel} is exempt from the identity scan and plants no synthetic shape — the "
            f"exemption is idle, and an idle exemption is a hole")


def _repo_with_an_exempt_file_naming_a_real_person(tmp_path: Path) -> None:
    """A repository whose gitignored real list names a person, and whose EXEMPT guard file — the
    one allowed to plant the synthetic shapes — carries that person's login next to a synthetic
    shape, the way the shared module's first docstring did."""
    exempt = sorted(ALLOWED)[0]
    _committed_tree(tmp_path, {
        exempt: '"""Measured: `git grep -n jdoe` gave 12 hits.\n\nSYNTHETIC = "exampleco"\n"""\n'})
    # the real list stays untracked, as .gitignore keeps it
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / ".identity-forbidden.txt").write_text(_A_REAL_LIST)


def test_an_EXEMPT_file_is_still_scanned_for_the_real_names(tmp_path):
    """The exemption is per token, not per file. The reviewer's cut: `# evidence: the login was
    <login>` appended to an exempt guard file, and the guard stayed green because the file was
    never read. On a tree of its own, so the proof does not depend on this machine having the
    real list."""
    _repo_with_an_exempt_file_naming_a_real_person(tmp_path)
    exempt = sorted(ALLOWED)[0]

    offenders = _offenders(tmp_path)

    assert any(o.startswith(f"{exempt}:1  jdoe") for o in offenders), (
        f"a real login inside an exempt file walked past the scan: {offenders}")
    assert not any("exampleco" in o for o in offenders), (
        f"the exempt file's own synthetic shape is reported as an offence: {offenders}")


def test_but_WITHOUT_a_real_list_an_exempt_file_has_nothing_further_to_refuse(tmp_path):
    """The other direction: on a fork (no real list) the exempt files plant synthetic shapes and
    nothing else is known — the scan must not turn an empty real list into a pattern that fires
    on everything, and must not report the shapes the file exists to plant."""
    _repo_with_an_exempt_file_naming_a_real_person(tmp_path)
    (tmp_path / "tests" / ".identity-forbidden.txt").unlink()

    assert _offenders(tmp_path) == []


# ── the real list: read when present, optional everywhere ───────────────────────────────────────

_A_REAL_LIST = """\
# a list written by hand, with the shapes a maintainer would actually type
forbid:
  acmeholdings        the parent company
  jdoe                a maintainer's login
  jdoe@acme.example   a maintainer's address
must_catch:
  clone git@github.com:AcmeHoldings/platform.git
  questions to jdoe@acme.example
"""

#: The hand edit a reviewer actually made: a token line before the `forbid:` header.
_A_MALFORMED_REAL_LIST = "# a list edited by hand\nacmeholdings   the parent company\nforbid:\n"


def test_a_real_list_on_disk_is_UNIONED_with_the_synthetic_one(tmp_path):
    """The mechanism, on a tree of its own. A file that is read must ADD to the synthetic shapes,
    not replace them — and its `must_catch:` lines must be caught by the pattern built from the
    union, which is the only pattern the scan uses."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / ".identity-forbidden.txt").write_text(_A_REAL_LIST)

    entries = identity.forbidden(tmp_path)
    tokens = [token for token, _ in entries]
    assert "jdoe" in tokens and "acmeholdings" in tokens and "jdoe@acme.example" in tokens
    assert "exampleco" in tokens, "the real file replaced the synthetic shapes instead of joining them"
    assert dict(entries)["jdoe"] == "a maintainer's login", "the description was not read"

    rx = identity.refused(tmp_path).everywhere
    for line in identity.must_catch(tmp_path):
        assert rx.search(line), f"a line the file says must be caught is not: {line!r}"


def test_without_the_file_the_synthetic_list_is_the_whole_list(tmp_path):
    """The twin: an absent file is not an error on a contributor's machine — the synthetic shapes
    carry the mechanism, and nothing here depends on what a fork cannot have."""
    (tmp_path / "tests").mkdir()
    assert identity.forbidden(tmp_path) == list(identity.SYNTHETIC_FORBID)
    assert identity.must_catch(tmp_path) == list(identity.SYNTHETIC_MUST_CATCH)


def test_a_MALFORMED_real_list_raises_rather_than_forbidding_nothing():
    """A file that is present and unreadable must not read as a file with no names in it."""
    with pytest.raises(ValueError, match="belongs to no section"):
        identity.parse("acmeholdings   a token before any section header\n")


def test_a_MALFORMED_real_list_fails_the_scan_with_the_line_that_is_wrong(tmp_path):
    """…and it fails the SCAN, at test time, with `parse`'s sentence naming the line — the shape
    a maintainer can act on. (What it must NOT do is abort collection; the next test is that.)"""
    _committed_tree(tmp_path, {"README.md": "# A product\n"})
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / ".identity-forbidden.txt").write_text(_A_MALFORMED_REAL_LIST)

    with pytest.raises(ValueError, match="line 2 belongs to no section"):
        _offenders(tmp_path)


def _collect_the_identity_guards_over(tmp_path: Path, real_list: str,
                                      extra_module: str | None = None) -> subprocess.CompletedProcess:
    """Collect copies of the two identity guards and their shared module in a tree of their own,
    with THIS real list on disk — pytest is run there, with its own ini so the rootdir (and so
    `tests.identity_forbidden`) is the copy, not this repository."""
    tests = tmp_path / "tests"
    tests.mkdir()
    for name in ("identity_forbidden.py", "test_the_product_carries_no_owners_name.py",
                 "test_the_product_carries_no_ones_past.py"):
        shutil.copy(ROOT / "tests" / name, tests / name)
    (tests / ".identity-forbidden.txt").write_text(real_list)
    if extra_module:
        (tests / "test_zz_eager.py").write_text(extra_module)
    (tmp_path / "pytest.ini").write_text("[pytest]\npythonpath = .\n")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-c", str(tmp_path / "pytest.ini"), "-q",
         "-p", "no:randomly", "-p", "no:cacheprovider", "--collect-only", "tests"],
        cwd=tmp_path, capture_output=True, text=True, timeout=300)


def test_a_MALFORMED_real_list_does_not_abort_COLLECTION(tmp_path):
    """The property `tests/test_ci_runs_what_we_run.py` states — collection must not depend on
    optional working state — proven for the PRESENT-BUT-WRONG direction, which that guard cannot
    see (the file is gitignored, so CI and forks never have one). Reproduced 2026-08-26 with a
    hand-edited list: both guards resolved it at module scope, `Interrupted: 2 errors during
    collection`, 7659 tests collected and ZERO run."""
    proc = _collect_the_identity_guards_over(tmp_path, _A_MALFORMED_REAL_LIST)

    counted = re.search(r"(\d+) tests? collected", proc.stdout)
    assert proc.returncode == 0 and counted and "Interrupted" not in proc.stdout, (
        "a malformed real list aborts collection — every test on this machine is skipped, not "
        f"just the ones that read the list:\n{(proc.stdout + proc.stderr)[-1500:]}")
    assert int(counted.group(1)) >= 40, (
        f"only {counted.group(1)} tests collected from the two identity guards — the copies are "
        f"not the guards")


def test_but_the_collection_proof_can_SEE_an_abort(tmp_path):
    """Verify the verifier: the same run with a module that DOES resolve the list at import must
    be reported as an abort, or the test above passes for any reason at all."""
    proc = _collect_the_identity_guards_over(
        tmp_path, _A_MALFORMED_REAL_LIST,
        extra_module="from tests import identity_forbidden as identity\n"
                     "EAGER = identity.refused()\n\n\ndef test_nothing():\n    pass\n")

    assert proc.returncode != 0 and "Interrupted" in proc.stdout, (
        f"a module resolving the list at import did not abort collection — the proof above "
        f"can see nothing:\n{proc.stdout[-800:]}")
    assert "line 2 belongs to no section" in proc.stdout, "the abort does not name the line"


def test_the_real_entries_are_exactly_the_union_minus_the_shapes(tmp_path):
    """What the exempt files are scanned with: the real file's tokens and none of the synthetic
    ones — and, without the file, nothing at all (an empty list, which `pattern` refuses to turn
    into a match-everything alternation)."""
    (tmp_path / "tests").mkdir()
    assert identity.real_only(tmp_path) == []
    assert identity.refused(tmp_path).in_exempt is None

    (tmp_path / "tests" / ".identity-forbidden.txt").write_text(_A_REAL_LIST)
    tokens = [token for token, _ in identity.real_only(tmp_path)]
    assert tokens == ["acmeholdings", "jdoe", "jdoe@acme.example"]
    assert not {token for token, _ in identity.SYNTHETIC_FORBID} & set(tokens)
    in_exempt = identity.refused(tmp_path).in_exempt
    assert in_exempt is not None and in_exempt.search("jdoe") and not in_exempt.search("exampleco")
