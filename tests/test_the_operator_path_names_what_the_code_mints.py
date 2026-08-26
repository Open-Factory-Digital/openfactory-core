"""At 9pm, a runbook that names something the code does not mint is worse than no runbook.

FOUR MEASURED DISAGREEMENTS, all in the operator path, all found in the pre-launch audit
(2026-08-26) and all of the same shape — a document holding a second copy of a name the code
owns, left behind when the code's copy changed:

  · `docs/runbook.md` step 1 sent an incident to a namespace and a workflow id built from the
    platform's RETIRED acronym, three lines under its own header naming the live one. Every
    entry point mints `openfactory-{project}-{issue}`; nothing has minted the other since the
    rename, so the first instruction on the page found no workflow at all.
  · The same page, and `docs/rotation-and-retention.md`, named the deployment's resources by
    that acronym. They are named by a terraform `prefix` variable whose default is the
    platform's own name.
  · `docs/operations.md` stated a bot-name fallback of the retired name against
    `credentials.bot_identity`'s actual default, and handed the reader an `export` line that
    would have stamped the abandoned acronym into every commit the factory made in a
    stranger's repository.
  · `docs/core/04` said the copyright line lives in `pyproject.toml`. It does not, and never
    did — `grep -n Copyright pyproject.toml` finds nothing.

So the guards here read the CODE and the FILES, never a second copy of the string: the workflow
prefixes come out of the modules that start workflows, by AST; the bot identity is asked of the
function with the environment cleared; the copyright claim is checked against the files the
sentence itself names. A document that drifts from any of them is red on the commit that drifts.
"""

from __future__ import annotations

import ast
import pathlib
import re
import subprocess

import add_ons
import pytest

from openfactory import credentials, namespace

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Where a workflow is started. Every one of these mints an id; the runbook sends a person to it.
STARTERS = ("openfactory/runtime/temporal/starter.py",
            "openfactory/runtime/temporal/activities.py",
            "openfactory/runtime/temporal/view.py")

#: Out of this scan by PREFIX, each for a stated reason.
#:
#: An ADR records the world on the day it was accepted; rewriting one is the single thing a
#: decision record forbids.
#:
#: `addons/` and `infra/` leave this tree with the cloud package (`docs/STATUS.md`'s table), and
#: this guard is about the operator path of the CORE — the pages a person who cloned the public
#: repository is handed. The package's own documents are its to keep true, and one of them uses
#: the four letters as the industry's acronym for a development lifecycle rather than as the
#: platform's former name, which no scan can tell apart.
#:
#: `docs/core/` WAS HERE AND IS NOT ANY MORE. That directory ships in the public tree, and a
#: prefix exemption covered all seven of its pages — including the six that spell the retired
#: name nowhere: appending retired-prefix names to `docs/core/02-boundary.md` left the whole gate
#: green (reviewer's cut, 2026-08-26). The dossier's four real pages are named below instead,
#: which is the width the exemption was actually earned at.
HISTORY = ("docs/adr/", "addons/", "infra/")

#: The one operator document that spells the retired name on purpose, and why. Held to it by
#: `test_every_retired_name_exemption_is_still_EARNED`: the line must be ABOUT the retirement,
#: or the exemption has quietly become a hiding place.
EARNED = {
    "docs/configuration.md": "states the rule that the old prefix is reserved against add-ons",
}

#: THE DOSSIER'S EXEMPTION IS DERIVED, NOT DECLARED (2026-08-26). It used to rest on one sentence
#: in `docs/core/README.md` — *"Written before the rename …"* — and on a hand-kept list of the
#: pages that sentence covered. Then the documents cut replaced that README with an index of the
#: three design documents that stay, and the banner went with it: a guard resting on a sentence
#: went red the moment somebody rewrote the page, while the pages it protected had not changed.
#:
#: What actually earns the exemption is simpler and checkable: those pages LEAVE THE PUBLIC TREE.
#: A retired name inside a document `docs/STATUS.md`'s table excludes never reaches a stranger, so
#: the exemption is exactly "the excluded documents", read from the table — no list to rot, and a
#: page that stops being excluded loses its exemption on the same commit.
def _excluded_documents() -> dict[str, str]:
    """Every `.md` the public cut leaves behind that is STILL IN THIS TREE, with the row that says
    where it goes. The filter is the whole point in the export: there the excluded documents are
    exactly the ones that are gone, so an exemption for them has no subject and the neutral rule —
    no document may carry the retired name — holds every page that is left, which is stricter."""
    return {rel: where or "the private tree"
            for rel, where in add_ons.excluded_paths().items()
            if rel.endswith(".md") and (ROOT / rel).exists()}


def _operator_documents() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z", "docs/*.md", "docs/**/*.md", "*.md",
                          "*.example", "deploy/*.example", "docker-compose.yml"],
                         cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[:200]
    return sorted(p for p in out.stdout.split("\0") if p and not p.startswith(HISTORY))


def _retired_word() -> str:
    """`sdlc` — from the code's own record of the retired directory, never typed here."""
    return namespace.RETIRED_DIR.lstrip(".")


def _minted_workflow_prefixes() -> set[str]:
    """Every literal a workflow id is built from, read out of the modules that start them.

    An id is an f-string whose first piece is the constant prefix (`openfactory-`,
    `openfactory-deploy-`); taking it from the AST means the day somebody renames it the runbook
    is measured against the new one without anybody remembering this file exists."""
    found: set[str] = set()
    for rel in STARTERS:
        tree = ast.parse((ROOT / rel).read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.JoinedStr) or not node.values:
                continue
            head = node.values[0]
            if (isinstance(head, ast.Constant) and isinstance(head.value, str)
                    and head.value.endswith("-") and re.fullmatch(r"[a-z][a-z0-9-]*-", head.value)):
                found.add(head.value)
    return found


# ── the workflow a person is sent to ────────────────────────────────────────────────────────────

def test_the_runbook_names_the_workflow_id_the_code_actually_mints():
    """Every id-shaped token the runbook shows must start with a prefix some entry point mints."""
    prefixes = _minted_workflow_prefixes()
    assert prefixes, "no workflow id could be read out of the starters — the scan has no subject"

    text = add_ons.source("addons/openfactory-aws/docs/runbook.md").read_text()
    shown = [tok for tok in re.findall(r"`([^`]+)`", text) if "{project}" in tok]
    assert shown, "the runbook no longer shows a workflow id at all — step 1 is where a 9pm "\
                  "incident starts, and 'find it yourself' is not a runbook"

    wrong = [tok for tok in shown if not any(tok.startswith(p) for p in prefixes)]
    assert not wrong, (
        f"the runbook sends an incident to {wrong}, and the code mints ids under {sorted(prefixes)} "
        f"— a person following that page finds no workflow and concludes the job never started")


def test_the_scan_can_SEE_the_id_that_was_here():
    """Verify the verifier, on the exact token the page carried."""
    prefixes = _minted_workflow_prefixes()
    was_here = f"{_retired_word()}-{{project}}-{{issue}}"
    assert not any(was_here.startswith(p) for p in prefixes), (
        "the retired id would pass this guard — the prefixes are not being read from the code")
    assert any("openfactory-{project}".startswith(p) for p in prefixes), (
        "…and the live id does not pass either, so the guard measures the wrong thing")


# ── the retired name, anywhere a reader would copy it ───────────────────────────────────────────

def _retired_hits(text: str) -> list[tuple[int, str]]:
    """Every line spelling the retired name — as a word, a path (`.sdlc/`), or the head of a
    compound (`SDLC_AGENT_TOKENS`, `sdlc-worker`). A `\\b` boundary would miss the last shape
    entirely, because `_` is a word character: the environment-variable spelling, which is
    exactly where the second name did its damage, would read as absent."""
    word = re.compile(rf"(?<![A-Za-z0-9])\.?{re.escape(_retired_word())}(?![A-Za-z0-9])",
                      re.IGNORECASE)
    return [(n, line.strip()) for n, line in enumerate(text.splitlines(), 1) if word.search(line)]


def test_no_operator_document_spells_the_retired_name():
    """The class, over every page and template an operator reads.

    Not "the runbook does not say it" — the same sentence had been copied into three files, and
    the fourth would have arrived the same way."""
    documents = _operator_documents()
    assert len(documents) > 15, f"only {len(documents)} documents scanned — this measures little"

    offenders = {rel: hits for rel in documents
                 if rel not in EARNED and rel not in _excluded_documents()
                 and (hits := _retired_hits((ROOT / rel).read_text()))}
    assert not offenders, (
        f"these spell the platform's retired name where an operator would read it as current — "
        f"the code mints the product's own name everywhere ({offenders}). If a line is genuinely "
        f"ABOUT the retirement, put the file in EARNED with the reason.")


def test_the_dossier_is_inside_the_walk_and_only_its_named_pages_are_exempt():
    """The twin of narrowing the prefix. `docs/core/` ships, and the exemption was earned by four
    of its pages; the rest must be in the scanned set, where a retired name appearing tomorrow is
    an offence like any other."""
    documents = set(_operator_documents())
    assert set(_excluded_documents()) <= documents, (
        f"an excluded document fell out of the walk: "
        f"{sorted(set(_excluded_documents()) - documents)} — an "
        f"exemption for a file nothing scans is a note, not a rule")
    rest = sorted(rel for rel in documents
                  if rel.startswith("docs/core/") and rel not in _excluded_documents())
    assert rest, (
        "every page under docs/core/ is exempt now — the prefix exemption came back under another "
        "name, and the directory ships in the public tree")


def test_the_exemption_is_exactly_what_the_public_cut_excludes():
    """The exemption has no list of its own: a document may carry the retired name only if the
    table sends it out of the public tree. Verified in both directions, so neither a page added
    to the table nor one removed from it can drift away from this rule unnoticed."""
    if add_ons.is_public_tree():
        pytest.skip("the public tree does not carry the documents the table excludes, so the exemption has no subject here and the neutral rule holds every page")

    excluded = _excluded_documents()
    assert excluded, "no excluded document is in this tree — see the skip above"
    for rel in excluded:
        assert (ROOT / rel).exists(), f"{rel} is excluded by the table and not in this tree"
    tracked = set(_operator_documents())
    for rel in sorted(excluded):
        assert rel not in tracked or rel in excluded


def test_the_exemption_protects_something_real():
    """Staleness, the house pattern, aimed at the rule rather than at each page. WHICH excluded
    documents happen to spell the retired name is a fact about history that nobody should have to
    maintain; that AT LEAST ONE does is what makes the exemption worth having. If none does, the
    exemption is a door standing open for the day somebody fills it, and the neutral rule above —
    no document that STAYS may spell the name — is the only one left."""
    if add_ons.is_public_tree():
        pytest.skip("no excluded document is in this tree — this is the export, where the exemption protects nothing because there is nothing left to protect")

    carrying = sorted(rel for rel in _excluded_documents()
                      if _retired_hits((ROOT / rel).read_text()))
    assert carrying, (
        "no document the public cut excludes spells the retired name any more — this exemption "
        "protects nothing; delete it and let the neutral rule hold every page")


def test_the_retired_name_scan_can_SEE_every_shape_it_was_written_for():
    """Verify the verifier, on the four real lines — and the last two are the reason this exists:
    a `\\b`-anchored pattern (the first thing written here) walked straight past both, because
    `_` and `-` after the name are not boundaries a word break can find."""
    word = _retired_word()
    was_here = [
        f"1. **Temporal Cloud UI** → namespace `{word}` → workflow `{word}-{{project}}-{{issue}}`:",
        f"- platform `infra/terraform/*` — the `{word}-*` repos' \"keep last 10\".",
        f'   export OPENFACTORY_BOT_NAME="{word.upper()} Bot"',
        f"finds: `{word.upper()}_AGENT_TOKENS` unreadable fell back to a *single* credential",
    ]
    missed = [line for line in was_here if not _retired_hits(line)]
    assert not missed, f"the scan walks past lines that really were here: {missed}"

    ours = ["the worker mints openfactory-{project}-{issue} for every job",
            "a self-declared lifecycle document", "OPENFACTORY_AGENT_TOKENS is the pool"]
    false = [line for line in ours if _retired_hits(line)]
    assert not false, f"the scan fires on the platform's own words: {false}"


@pytest.mark.parametrize("rel", sorted(EARNED))
def test_every_retired_name_exemption_is_still_EARNED(rel):
    """An exemption is for a sentence about the retirement, never for a leftover.

    Without this, EARNED is where the next stale line goes to be ignored."""
    hits = _retired_hits((ROOT / rel).read_text())
    assert hits, f"{rel} no longer spells the retired name at all — drop it from EARNED"
    about_it = re.compile(r"\bold\b|\bformer\b|\bretired\b|\breserved\b|\brenamed\b|no longer",
                          re.IGNORECASE)
    stale = [f"{rel}:{n}  {line[:90]}" for n, line in hits if not about_it.search(line)]
    assert not stale, (
        f"{rel} is exempt because it {EARNED[rel]}, and these lines are not that — they read as "
        f"current: {stale}")


# ── who the factory commits as ──────────────────────────────────────────────────────────────────

def test_the_bot_identity_a_document_states_is_the_one_the_code_falls_back_to(monkeypatch):
    """`docs/operations.md` tells a reader what the actor is when they declare nothing. Asked of
    the function with the environment cleared, rather than believed."""
    for var in ("OPENFACTORY_BOT_NAME", "OPENFACTORY_BOT_EMAIL", "OPENFACTORY_BOT_LOGIN"):
        monkeypatch.delenv(var, raising=False)
    identity = credentials.bot_identity()

    text = (ROOT / "docs/operations.md").read_text()
    stated = re.search(r"Falls back\s+to\s+\"([^\"]+)\"", re.sub(r"\s+", " ", text))
    assert stated, "operations.md no longer states the fallback actor at all"
    assert stated.group(1) == identity.name, (
        f"the page says the factory commits as {stated.group(1)!r} with nothing declared; "
        f"`credentials.bot_identity` answers {identity.name!r}")


def test_no_document_hands_the_reader_an_export_of_a_name_the_platform_abandoned():
    """The worse half of the same defect: a fallback stated wrongly misleads, but a copy-pasted
    `export` stamps the abandoned name into every commit the factory makes in somebody's
    repository — where it outlives the document."""
    word = _retired_word()
    offenders = {}
    for rel in _operator_documents():
        for number, line in enumerate((ROOT / rel).read_text().splitlines(), 1):
            for match in re.finditer(r"OPENFACTORY_BOT_(?:NAME|EMAIL)\s*=\s*[\"']?([^\"'\s]+)",
                                     line):
                if word.lower() in match.group(1).lower():
                    offenders[f"{rel}:{number}"] = line.strip()[:100]
    assert not offenders, (
        f"these hand a reader a command that commits under the platform's retired name: "
        f"{offenders}")


# ── the copyright line lives where the dossier says it lives ───────────────────────────────────

def test_every_file_the_licensing_page_names_really_carries_the_copyright_line():
    """The claim, checked against the files the sentence itself names — so a file added to or
    removed from that list is measured without editing this guard."""
    page = add_ons.source("docs/core/04-business-and-licensing.md").read_text()
    flat = re.sub(r"\s+", " ", page)
    sentence = re.search(r"\*\*Copyright: `([^`]+)`\*\*(.*?)\.\s", flat)
    assert sentence, "04 no longer states where the copyright line lives"

    line, claim = sentence.group(1), sentence.group(2)
    named = [f for f in re.findall(r"`([^`]+)`", claim) if "." in f or f.isupper()]
    assert named, f"the sentence names no file: {claim!r}"

    missing = [f for f in named
               if not (ROOT / f).exists() or line not in (ROOT / f).read_text()]
    assert not missing, (
        f"04 says the copyright line lives in {named}, and {missing} do not carry it. The line "
        f"is {line!r}; either put it there or stop claiming it.")


def test_the_copyright_line_is_where_the_page_can_point_at_it():
    """The positive twin — the rule above is satisfiable by naming nothing."""
    line = "Copyright 2026 The OpenFactory Authors"
    carriers = [rel for rel in ("LICENSE", "NOTICE") if line in (ROOT / rel).read_text()]
    assert carriers == ["LICENSE", "NOTICE"], (
        f"the copyright line is missing from {set(('LICENSE', 'NOTICE')) - set(carriers)}")


# ── a version this repository can be asked about ───────────────────────────────────────────────

def _tags_without_an_owner(flat: str, attribution: str) -> list[str]:
    """Cited version tags with no owner beside them — the JUDGEMENT, kept apart from the page so
    it can be fed a case that must fail. Inline it could not be: the page is correct today, so two
    cuts that disabled the rule outright passed the assertion below (2026-08-26)."""
    cited = set(re.findall(r"`(v\d+\.\d+\.\d+)`", flat))
    return [tag for tag in sorted(cited)
            if attribution not in flat[max(0, flat.index(f"`{tag}`") - 200):
                                       flat.index(f"`{tag}`") + 60]]


def test_the_tag_rule_REPORTS_a_bare_citation_and_one_attributed_to_SOMEBODY_ELSE():
    """Verify the verifier, on the two shapes that matter: a tag with no owner beside it, and a
    tag whose owner is not this repository — the second is what a rule looking for the loose
    prefix `of \u0060` would wave through."""
    assert _tags_without_an_owner("measured in the `v1.1.0` tag of `openfactory`. More.",
                                  "of `openfactory`") == []
    assert _tags_without_an_owner("measured in the `v1.1.0` tag. More.",
                                  "of `openfactory`") == ["v1.1.0"]
    assert _tags_without_an_owner("measured in the `v1.1.0` tag of `someone-else`. More.",
                                  "of `openfactory`") == ["v1.1.0"]


def test_every_version_tag_the_status_page_cites_exists_or_says_whose_it_is():
    """`docs/STATUS.md` measured 19 tickets "in the `v1.1.0` tag". A fresh-history export carries
    no tags at all, so a reader there cannot reach it — the same problem the page already solved
    for the commit it names, and with the same answer: say whose history it is.

    A tag that DOES exist here needs no such clause; one that does not must attribute itself, or
    the number beside it cannot be checked by anyone."""
    text = (ROOT / "docs/STATUS.md").read_text()
    flat = re.sub(r"\s+", " ", text)
    cited = set(re.findall(r"`(v\d+\.\d+\.\d+)`", flat))
    assert cited, "STATUS.md cites no version tag at all — this measures nothing"

    # WHOSE HISTORY, DERIVED FROM THE PAGE ITSELF. The status line already names the repository
    # its refs belong to (`main at `sha` of `openfactory``, and `cut from …` in the export); a tag
    # citation is attributed when it names that same owner. Read off line 6 rather than kept as a
    # list of acceptable phrases here — a guard that greps for "source tree" passes any sentence
    # containing those words and fails a correct one that says it differently.
    owner = re.search(r"(?:main at|cut from) `[0-9a-f]{7,}` of `([^`]+)`", flat)
    assert owner, ("docs/STATUS.md's status line no longer names whose history its commit belongs "
                   "to, so nothing here can say what attributing a tag would even look like")
    attribution = f"of `{owner.group(1)}`"
    # AND WHAT WAS DERIVED MUST BE A NAME, not a prefix. `of `` matches every attributed
    # sentence AND every sentence attributed to somebody else, so a rule built on it would
    # wave through exactly the citation a reader cannot follow (mutation, 2026-08-26).
    assert re.fullmatch(r"of `[A-Za-z0-9][\w.-]*`", attribution), (
        f"the owner read off the status line is not a repository name: {attribution!r}")

    # NO `git tag -l` HERE AT ALL, and that is the fix rather than a simplification. Asking the
    # checkout whether it holds the tag made this guard read the machine twice over: a developer's
    # clone holds every tag, so the attribution branch never ran and the rule was unmeasurable
    # here; `actions/checkout` fetches depth 1 with no tags, so on CI every citation needed one
    # and the suite went red on a page nobody had touched. A version tag is cited so a reader can
    # go and look, and whether THIS checkout can resolve it says nothing about whether the reader
    # can — so the rule is unconditional: say whose history it is, always. It costs four words and
    # it means the same thing in the source tree and in a fresh-history export.
    unreachable = _tags_without_an_owner(flat, attribution)
    assert not unreachable, (
        f"STATUS.md cites {unreachable} without saying whose history they belong to. Write "
        f"{attribution!r} beside each, the way the status line names the commit — a reader of the "
        f"public export has no way to resolve a bare tag, and a reader here should not have to "
        f"guess which repository it is a tag of.")
