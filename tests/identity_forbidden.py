"""The identities this product may not ship — the SHAPES in the tree, the NAMES out of it.

Two guards refuse identities: `test_the_product_carries_no_owners_name.py` (the organisation that
builds the product, its maintainers, its clients) and `test_the_product_carries_no_ones_past.py`
(one tenant's infrastructure coordinates). Until 2026-08-25 both carried the real lists — a
maintainer's login, an e-mail, a home directory, the former company, four client names, two live
AWS account ids and a live App name — and exempted themselves from their own scan. Measured at the
point of publishing: a `git grep` for the maintainer's surname and login gave 12 hits, ALL in the
two guards and their mutation plans. A guard that must name what it forbids publishes what it
forbids; on a public repository the guard file IS the disclosure, and the first commit of a fresh
history ships it. The first version of THIS module repeated the defect one layer up: its docstring
quoted the grep with the surname in it, and a reviewer's `git grep` found it. Nothing in here may
quote a value — only a shape.

THE SPLIT. The mechanism stays in the tree with SYNTHETIC entries of every shape the real ones take
(an organisation, a former parent company, a maintainer's login, a person's first name, an
address, a client, a 12-digit account id, an App name), so the scan, its bite tests and its
positive twins run on every contributor's machine and mean the same thing there. The REAL entries
live in `tests/.identity-forbidden.txt`, which is gitignored, and are UNIONED in whenever the file
is present.

THE REAL LIST IS OPTIONAL EVERYWHERE, decided 2026-08-25. A public repository has forks and
contributors who will never hold it, and a test that fails without a secret is a red CI on every
fork's pull request — the repository's own lesson is that a red that is normal is a CI that runs
nothing. So no run REQUIRES the file: the maintainers' machines carry it, and writing it in CI
from a repository secret is a later, optional convenience, not a gate. What the tree guarantees
without it is that the SCANNER works (the synthetic entries are the proof — a scanner that stopped
matching would report a clean tree, and the bite tests are for that); what a machine with the file
adds is the scan over the real names, verified the same way: every `must_catch:` line in the file
must be matched by the pattern the scan actually uses.

THE EXEMPTION IS PER TOKEN, NOT PER FILE. The guards and the plans that plant the synthetic shapes
must be allowed to carry THOSE, and only those — a file that is skipped outright is a file where a
real name can sit unseen, which is exactly what happened to this module's first docstring. So the
files in `ALLOWED_TO_NAME_THEM` are scanned with `real_only()`: everything the machine knows that
is not a synthetic shape.

THE FILE FORMAT, kept trivial so it needs no parser dependency and survives a hand edit:

    # comments and blank lines are ignored
    forbid:
      <token>   <what it is, free text, used in the failure message>
    must_catch:
      <a whole line, exactly as the name once arrived in this tree>

Tokens are matched as case-insensitive SUBSTRINGS, escaped — not as words and not as digests.
Both alternatives were measured and rejected: a word boundary misses a company name inside a
compound (`FormerCoAI`-shaped, which is how the former parent company actually spelled itself)
and the address inside a URL, and a digest cannot be checked in the tree (a wrong digest is
permanent green blindness). A malformed file RAISES rather than reading as empty.

A DENY LIST IS ONLY AS GOOD AS WHAT SOMEBODY THOUGHT TO WRITE DOWN, so there is a second rule
below it that DERIVES instead of enumerating — see `NAMESPACE_LITERAL` and `foreign_namespaces`.
It exists because the first one failed exactly the way its shape fails: on 2026-08-26 a client's
three-letter organisation abbreviation was found shipping ten times across five files as the
leading segment of a code namespace, and every scan here was green over it. Nothing was broken.
Nobody had listed the token, and the bare three letters could not BE listed — they are an
ordinary Portuguese word stem, and a bare token fires on four tracked files of innocent prose.
The derived rule needs no such foresight and fails CLOSED: a namespace root that is neither a
vendor's nor ours is refused today, whoever's it turns out to be tomorrow.

AND IT RAISES INSIDE A TEST, NEVER AT IMPORT. The first version of the two guards resolved the
list at module scope, and a reviewer hand-edited the real file (a token line before the
`forbid:` header): both modules raised during collection, `Interrupted: 2 errors during
collection`, 7659 tests collected and ZERO run — the card-id guard in the same invocation did
not run either. Collection must not depend on optional working state (the property
`tests/test_ci_runs_what_we_run.py` states, and had only proven for the ABSENT direction). So
`refused(root)` below is the ONE resolver the scans and their twins call, at test time; a bad
file fails exactly the tests that read the list, each with `parse`'s sentence naming the line,
and takes nothing else with it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: The gitignored real list. One path, never a pattern: a second file claiming the same role
#: would be a second place a name can hide.
REAL_FILE = ROOT / "tests" / ".identity-forbidden.txt"

#: Local-only content the prose scanner must skip: the real list itself, and mutation plans that
#: plant real names (run by path, never committed — `.gitignore` names both).
LOCAL_ONLY = ("tests/.identity-forbidden.txt", "tools/mutations/local/")

#: One entry per SHAPE a real identity takes. Invented names on reserved example domains, so they
#: can never be somebody's; kept in the tree so the bite tests, the positive twins and the union
#: mechanism run identically on a machine that has the real file and on one that does not.
#:
#: The first name and the former company are here because the front-door check used to spell
#: both as its own rules, lost them when it moved to the shared list, and nothing noticed: a
#: personal name in the README passed on every machine. Each shape the front door refuses now
#: has a synthetic entry the front-door twin plants.
SYNTHETIC_FORBID: tuple[tuple[str, str], ...] = (
    ("exampleco", "the organisation that builds the product"),
    ("formerco", "the former parent company"),
    # THE FORMER PRODUCT NAME AS AN IDENTIFIER — its own shape, not a tenant coordinate: it names
    # nobody's account, but a product that no longer exists survived as the author's fixture
    # directory in two test modules until 2026-08-25, and a front-door page saying "built by the
    # <old name> team" is the same disclosure in prose. The real spelling is in the local list.
    ("formerproduct", "the former product name as an identifier"),
    ("example-maintainer", "a maintainer's login"),
    ("exampleperson", "a person's first name"),
    ("maint@example.invalid", "a maintainer's address"),
    ("exampleclient", "a client's name"),
    ("123456789012", "an AWS account id"),
    ("ExampleCoBot", "the name of a live GitHub App"),
)

#: The shapes the real names actually arrived in — a board URL, a clone URL, a home directory, a
#: pasted API error, an attribution by first name, a company name inside a compound, evidence in
#: a docstring, an internal repository URL, a support address, an account id beside an App name
#: — with the synthetic names in the same positions. A list that misses a shape the name arrives
#: in passes for the wrong reason, and a list that shrinks passes for the same reason: every
#: synthetic token must be carried by at least one line here, and the guard counts them.
SYNTHETIC_MUST_CATCH: tuple[str, ...] = (
    "the board lives under https://github.com/ExampleCo/projects/7",
    "clone git@github.com:ExampleCo/exampleco-sdlc-platform.git",
    "the first version was built at FormerCoAI, before the split",
    "built by the FormerProduct team, back when the fixtures lived in FormerProductDemoProjects",
    "/Users/example-maintainer/Projects/openfactory",
    "Could not resolve to a User with the login of example-maintainer.",
    "Exampleperson decided on 2026-08-17 that the product carries nobody's name",
    "an ExampleClient-shaped deployment was told no credential is configured",
    "repo_path: https://dev.azure.com/exampleclient/Deskline/_git/dsk-api",
    "questions to maint@example.invalid",
    "the account is 123456789012 and the app is ExampleCoBot",
)

#: The tracked paths that legitimately carry the SYNTHETIC tokens: this module, the two guards
#: that plant them in their positive twins, and the mutation plans that put them back into the
#: tree to prove the guards bite. None of these may carry a real one, and that is SCANNED, not
#: trusted: both guards read these files with `real_only()` — the union minus the synthetic
#: shapes — so an exempt file is exempt from the shapes it plants and from nothing else.
ALLOWED_TO_NAME_THEM = frozenset({
    "tests/identity_forbidden.py",
    "tests/test_the_product_carries_no_owners_name.py",
    "tests/test_the_product_carries_no_ones_past.py",
    "tools/mutations/137_owners_name.py",
    "tools/mutations/189_no_client_name_either.py",
    "tools/mutations/public_identity_guard_has_no_names.py",
})


# ── THE DERIVED RULE: what is refused without anyone having listed it ────────────────────────────
#
# A dotted coordinate of three or more capitalised segments — `<Root>.<Sub>.<Thing>` — is how a
# .NET or Java namespace, an Azure DevOps field reference and a tenant's own code taxonomy are all
# spelled, and its ROOT segment says WHOSE taxonomy it is. Measured over the tracked tree on
# 2026-08-26: nine distinct literals in twenty-six places, and every one of them falls into one of
# two kinds a reader who knows nothing about our clients can still check —
#
#   - a root a PLATFORM VENDOR publishes, which an adapter has to spell exactly;
#   - a root THIS TREE invented, in a fixture or an example.
#
# A root that is neither is somebody else's BY CONSTRUCTION. That is the opposite polarity from the
# deny list above: there, an unlisted name reads as compliance; here, an undeclared root is a
# failure. The token that leaked in the first place would have been caught by this on the day it
# arrived, by a rule written before anybody had heard of it.

#: The shape. THREE segments minimum, not two: two is how ordinary code spells an attribute
#: (`Evidence.excerpt`, `Path.home`), and measured, a two-segment rule reports hundreds of them and
#: would be deleted within a week. Case matters — a namespace root is capitalised, a Python module
#: path is not, and `openfactory.onboarding.context` is not a coordinate.
NAMESPACE_LITERAL = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:\.[A-Z][A-Za-z0-9]*){2,}\b")

#: Roots a platform VENDOR owns and publishes. `Microsoft.VSTS.Common.StackRank` is the field an
#: Azure DevOps board adapter must send under that exact name, and `System.*` is the .NET base
#: library a knowledge fixture parses. These name a protocol; they name no tenant, so they say
#: nothing about who our clients are.
VENDOR_NAMESPACE_ROOTS: frozenset[str] = frozenset({"Microsoft", "System"})

#: Roots THIS TREE invented, each traceable to where it was invented. `ACM` is the synthetic
#: organisation the fixtures already use everywhere else (`AcmeCorp`, `acme-ai`, `AcmeFixtures`),
#: as the three-letter shape a namespace segment takes; `Flows` is the namespace root of the .NET
#: module `tests/test_knowledge.py` writes for itself before parsing it back.
#:
#: NOTHING GOES IN HERE TO SILENCE A FAILURE. The entry is the claim "we made this name up", and
#: `test_every_DECLARED_root_is_used_by_something` refuses an idle one — an allow-list entry that
#: nothing uses is a hole waiting for the next name to be dropped into.
OUR_NAMESPACE_ROOTS: frozenset[str] = frozenset({"ACM", "Flows"})


def foreign_namespaces(text: str) -> list[tuple[int, str]]:
    """Every `(line, literal)` in `text` whose namespace root this tree has not declared.

    Line numbers rather than offsets, because the report a maintainer acts on is `path:line`."""
    declared = VENDOR_NAMESPACE_ROOTS | OUR_NAMESPACE_ROOTS
    return [(text.count("\n", 0, m.start()) + 1, m.group(0))
            for m in NAMESPACE_LITERAL.finditer(text)
            if m.group(0).split(".")[0] not in declared]


def parse(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """The two sections of a list file. Raises on a line that belongs to no section: a file that
    is present and unreadable must not read as a file that forbids nothing."""
    forbid: list[tuple[str, str]] = []
    must_catch: list[str] = []
    section = ""
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line in ("forbid:", "must_catch:"):
            section = line[:-1]
            continue
        if section == "forbid":
            token, _, what = line.partition(" ")
            forbid.append((token, what.strip() or "an identity"))
        elif section == "must_catch":
            must_catch.append(line)
        else:
            raise ValueError(f"line {n} belongs to no section (expected `forbid:` or "
                             f"`must_catch:` first): {raw!r}")
    return forbid, must_catch


def _real(root: Path) -> tuple[list[tuple[str, str]], list[str]]:
    path = root / REAL_FILE.relative_to(ROOT)
    if not path.is_file():
        return [], []
    return parse(path.read_text(encoding="utf-8"))


def forbidden(root: Path = ROOT) -> list[tuple[str, str]]:
    """Every (token, what) the scans refuse: the synthetic shapes, plus the real list when the
    machine has one. Order is stable and duplicates are dropped by token so a failure names each
    identity once."""
    seen: dict[str, str] = {}
    for token, what in [*SYNTHETIC_FORBID, *_real(root)[0]]:
        seen.setdefault(token, what)
    return list(seen.items())


def real_only(root: Path = ROOT) -> list[tuple[str, str]]:
    """What the exempt files are scanned with: every entry this machine knows that is NOT one of
    the synthetic shapes they are allowed to plant. Empty on a machine without the real file —
    and an empty list is "nothing further to refuse here", never a pattern (see `pattern`)."""
    synthetic = {token for token, _ in SYNTHETIC_FORBID}
    return [(token, what) for token, what in forbidden(root) if token not in synthetic]


def must_catch(root: Path = ROOT) -> list[str]:
    """Every line the pattern must match: the synthetic shapes, plus the real lines when the
    machine has them."""
    return [*SYNTHETIC_MUST_CATCH, *_real(root)[1]]


def pattern(entries: list[tuple[str, str]]) -> re.Pattern[str]:
    """One case-insensitive alternation over ESCAPED tokens. Escaped, because an address carries a
    dot and an unescaped `.` matches any character — a pattern that is wrong in the permissive
    direction is a guard that reports offenders nobody can find."""
    assert entries, "an empty identity list would compile to a pattern that matches everything"
    return re.compile("|".join(re.escape(token) for token, _ in entries), re.IGNORECASE)


@dataclass(frozen=True)
class Refused:
    """What one tree's scans refuse, resolved once and read by the scan AND by its twins.

    A pattern built for the scan and a different one verified by the twins is how a list gets
    declared and never read — both guards drifted into exactly that within a day of the split,
    each building its own `pattern(forbidden(root))` beside a comment saying it shared this."""

    #: Every (token, what) this tree refuses: the synthetic shapes, plus the real list when
    #: the machine has one.
    entries: tuple[tuple[str, str], ...]
    #: What a file that is NOT exempt is read with — every entry.
    everywhere: re.Pattern[str]
    #: What an exempt file is read with — the real entries only, the union minus the shapes it
    #: is allowed to plant. None on a machine without the real list: "nothing further to refuse
    #: here", never a pattern (an empty alternation would match everything).
    in_exempt: re.Pattern[str] | None


def refused(root: Path = ROOT) -> Refused:
    """THE object the identity scans and their twins share, resolved at TEST time (see the
    module docstring: a malformed real file must fail the tests that read it, not collection)."""
    entries = tuple(forbidden(root))
    real = real_only(root)
    return Refused(entries, pattern(list(entries)), pattern(real) if real else None)
