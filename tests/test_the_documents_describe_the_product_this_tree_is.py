"""Four documents described a product this tree is no longer, and one diagnostic regressed.

WHAT WAS MEASURED, 2026-08-26, on the tree about to be published:

  · `docs/knowledge-layer.md` said the knowledge layer was **opt-in and OFF for every project**
    in four places — the header status, §21 twice, §23's "Still open" — while
    `openfactory/contracts/manifest.py` has carried `knowledge_map: bool = True` since ADR-0035.
    A stranger reads the page as the current truth and switches on a thing that is already on.
  · `docs/operations.md` called three SHIPPED behaviours future work: the post-PR lifecycle
    ("D-12 — not yet built", while `PromotionRunner` walks it), the dependency cache
    ("wiring is a near-term optimization", while the box mounts the volume), and the board
    ("labels are the v1 board movement", while the column move is the movement and the label is
    what happens when it fails).
  · `docs/rotation-and-retention.md` re-certified "keep last 10" for two repositories whose
    terraform says 20 and 30 — and said 20 and 30 itself, eighty lines earlier.
  · `docs/agents.md` named three harnesses of four, sent readers to a `deploy/registry.yaml`
    this tree does not contain, and cited `org_defaults/roles/reviewer.md`, a prompt file that
    has never existed (the reviewer's is built, in `adapters/reviewer/harness.py`).
  · `worker._readable` preferred the first sentence unconditionally, so a vendor dump —
    `Request failed. status=503 body={…}`, 384 characters — logged as `Request failed.` The
    twin that shipped with it only ever exercised a LONG first sentence, which is why nothing
    caught it: the case it was blind to is the case that regressed.

SO NONE OF THESE GUARDS READS A SECOND COPY OF A STRING. Each renders the sentence the document
must carry FROM the code (`f"`knowledge_map` defaults to `{default}`"`, the harness count out of
`HARNESSES`, the mount point out of a real `docker run` argv, the counts out of the terraform),
or asserts the CONDITION the prose describes (the label call's branch tests the board's own
result, so "primary" and "fallback" cannot be swapped in the page without going red here). A
guard that only looked for a vocabulary word would be satisfied by the word surviving an
inversion, which is the failure this round was told to stop shipping.
"""

from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import types

import add_ons
import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The documents this package owns. Every scan below runs over all of them, so a defect fixed in
#: one page cannot reappear in the next by being written somewhere else.
OWNED = (
    "docs/agents.md",
    "docs/knowledge-layer.md",
    "docs/operations.md",
    "docs/rotation-and-retention.md",
    "docs/engineering-lessons.md",
)


def _text(rel: str) -> str:
    return (ROOT / rel).read_text()


def _squashed(rel: str) -> str:
    """The page with every run of whitespace collapsed to one space.

    A LINE BREAK IS NOT A DIFFERENT CLAIM. `Leave it\\noff (the default)` is the sentence this
    file exists to catch, and it was wrapped exactly there — a scan over raw lines reads it as
    absent, which is the absence-as-compliance shape one directory over."""
    return re.sub(r"\s+", " ", _text(rel))


# ══ 1. the knowledge layer's default is the manifest's, in every sentence that states one ══════


def _knowledge_default() -> bool:
    """What the code actually defaults to — asked of the model, never typed here."""
    from openfactory.contracts.manifest import Manifest

    return bool(Manifest.model_fields["knowledge_map"].default)


def _default_sentence(on: bool) -> str:
    """The sentence the page must carry, RENDERED from the default. Flip the manifest and this
    string changes, so the page can only satisfy it by agreeing with the code."""
    return f"`knowledge_map` defaults to `{str(on).lower()}`"


#: Phrasings that assert the layer is withheld unless a project asks for it. The first five are
#: verbatim from the page as it stood on 2026-08-26; the rest are how somebody would naturally
#: rewrite one of them. Matched against the whitespace-collapsed page, case-insensitively.
SAYS_WITHHELD = (
    "off for every project", "fully opt-in", "opt-in", "opt in", "off by default",
    "leave it off", "stays off", "off everywhere", "switched off", "turned off",
    "disabled by default", "not enabled by default", "unless a project opts in",
    "only when a project sets", "off unless",
)

#: …and the mirror, for the day the default goes back to `false`. The guard picks which list to
#: forbid FROM THE CODE, which is what makes it a binding rather than a spelling preference.
SAYS_GIVEN = (
    "on by default", "opt-out", "opt out", "enabled by default", "on for every project",
    "on everywhere", "unless a project declares", "every project gets",
)


def _claims(page: str, phrases: tuple[str, ...]) -> list[str]:
    low = page.lower()
    return [p for p in phrases if p.lower() in low]


def _status_block(rel: str) -> str:
    """Everything above the page's first horizontal rule — the status a reader meets first."""
    head = _text(rel).split("\n---", 1)[0]
    assert head.strip(), f"{rel} has no status block above its first rule"
    return re.sub(r"\s+", " ", head)


def test_the_default_the_knowledge_page_states_is_rendered_from_the_manifest():
    """The positive half, and it is what stops the negative one being satisfied by silence: the
    page has to SAY which way the flag falls, in a form computed from the field's own default.

    IN THE STATUS BLOCK, and that is not decoration. A first version of this asked only that the
    sentence appear SOMEWHERE, and a cut that replaced the header's claim with "the flag is
    there for projects that want to think about it" stayed green — §21 mentions the default too,
    forty sections down, and satisfied the assertion on the header's behalf. The claim has to be
    where somebody deciding whether to switch the layer on actually looks."""
    on = _knowledge_default()
    page = _squashed("docs/knowledge-layer.md")
    header = _status_block("docs/knowledge-layer.md")
    assert _default_sentence(on) in header, (
        f"docs/knowledge-layer.md's status block does not state {_default_sentence(on)!r}, which "
        f"is what `Manifest.knowledge_map` actually defaults to. A reader deciding whether to "
        f"switch the layer on has no answer where the page answers that question.")
    assert _default_sentence(not on) not in page, (
        f"the page states {_default_sentence(not on)!r} and the manifest says otherwise")


def test_the_knowledge_page_makes_no_claim_about_the_default_that_the_manifest_denies():
    """The negative half. Which list is forbidden is decided by the code, so this is red either
    way round: flip `knowledge_map` and the page's current wording becomes the offence."""
    on = _knowledge_default()
    page = _squashed("docs/knowledge-layer.md")
    denied = _claims(page, SAYS_WITHHELD if on else SAYS_GIVEN)
    assert not denied, (
        f"`Manifest.knowledge_map` defaults to {on!r}, and docs/knowledge-layer.md still says "
        f"{denied} — the four sentences this guard exists for were exactly this shape. Either "
        f"the page is stale or the default moved and the page was not brought with it.")


def test_the_default_scan_can_SEE_the_sentences_that_were_on_the_page():
    """Verify the verifier, on the five real lines — and the fourth is why the scan collapses
    whitespace first: it was wrapped between `Leave it` and `off (the default)`."""
    was_here = [
        "opt-in, and **OFF for every project** pending the cost/ticket A/B.",
        "Nothing runs by default — it is fully opt-in — so existing behaviour is unchanged",
        "- **Injection (opt-in, OFF by default).** A manifest flag `knowledge_map: true` makes",
        "Then set `knowledge_map: true` in the project's file. Leave it\noff (the default) to "
        "keep today's behaviour.",
        "`knowledge_map` stays\n  OFF everywhere until the numbers say otherwise.",
    ]
    missed = [line for line in was_here
              if not _claims(re.sub(r"\s+", " ", line), SAYS_WITHHELD)]
    assert not missed, f"the scan walks past sentences that really were on the page: {missed}"

    ours = ["the map says where to look, not what is true",
            "a missing, stale or orphaned bundle degrades to injecting nothing",
            "production is human-gated, whatever the client calls it",
            "the branch holds the knowledge directory and nothing else"]
    false = [line for line in ours if _claims(line, SAYS_WITHHELD)]
    assert not false, f"the scan fires on sentences that state no default at all: {false}"


# ══ 2. every path and symbol a page cites is one a stranger can open ═══════════════════════════

_EXT = "py|md|ya?ml|tf|sh|toml|json|cfg|ini"

#: A backticked citation that names a PATH — it carries a directory separator, which is what
#: distinguishes `openfactory/knowledge/bundle.py` from `modules.yaml`, the name of an artefact.
CITED_PATH = re.compile(rf"`([A-Za-z0-9_][A-Za-z0-9_./-]*/[A-Za-z0-9_.*-]+\.(?:{_EXT}))`")

#: The same claim made in bare prose. BACKTICKS ARE A CONVENTION, NOT A CONTRACT: a cut that
#: rewrote "`deploy/registry.yaml` → `product.admins`" as "the deploy/registry.yaml file,
#: product.admins" walked through a backticks-only scan while sending the reader to exactly the
#: same absent file. Measured against every page here, this pattern finds one bare citation
#: (`docs/setup/github.md`) and it resolves — so the cost of reading prose too is nothing.
BARE_PATH = re.compile(
    rf"(?<![`\w/.\-])([A-Za-z_][A-Za-z0-9_.\-]*(?:/[A-Za-z0-9_.*\-]+)+\.(?:{_EXT}))(?![\w\-])")


def _prose(text: str) -> str:
    """The page with the parts a path scan must not read removed: fenced blocks are commands
    rather than citations, inline code is what `CITED_PATH` already covers, and a link target is
    a link. What is left is the sentences."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`[^`]*`", " ", text)
    return re.sub(r"\]\([^)]*\)", "] ", text)

#: A citation that names a path AND a symbol in it: `<path>` → `<Symbol>` (an em dash or an
#: ASCII arrow reads the same to a person, so all three separators are accepted — otherwise
#: swapping the character is a way through).
CITED_SYMBOL = re.compile(
    r"`([A-Za-z0-9_][A-Za-z0-9_./-]*/[A-Za-z0-9_.-]+\.py)`\s*(?:→|—|->)\s*`([A-Za-z_][A-Za-z0-9_.]*)`"
)

#: Citations that name a path in a repository the platform DRIVES rather than in this one, each
#: with the reason it cannot resolve here. Short and explicit on purpose, and
#: `test_every_foreign_path_exemption_is_still_cited` keeps it from becoming a hiding place.
NOT_OURS = {
    "knowledge/*.yaml": "the module map, in the CLIENT's repository on the published branch",
}


def _defined_in(rel: str) -> set[str]:
    """Every name a module binds — functions, classes, methods, module and class attributes.

    Methods count: `JobWorkflow._journal_outcome` and `_pause_backoff` are what the operator
    pages cite, and a guard that only saw top-level defs would call both of them missing."""
    tree = ast.parse((ROOT / rel).read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _unresolved_paths(rel: str) -> list[str]:
    text = _text(rel)
    out = []
    for pattern, body in ((CITED_PATH, text), (BARE_PATH, _prose(text))):
        for match in pattern.finditer(body):
            cited = match.group(1)
            if cited in NOT_OURS:
                continue
            found = bool(list(ROOT.glob(cited))) if "*" in cited else (ROOT / cited).exists()
            # A PATH THE TABLE EXCLUDES IS NOT A DEAD END, it is a path with a forwarding address:
            # `docs/STATUS.md` says which package carries it. Without this the rule was true only
            # in the tree that still has everything — the private one — and the export reported a
            # correct sentence ("the add-on package's `infra/terraform/alerting.tf`") as a broken
            # citation (measured 2026-08-26).
            if not found and any(cited == x or (x.endswith("/") and cited.startswith(x))
                                 for x in add_ons.excluded_paths()):
                continue
            if not found:
                out.append(f"{rel}  {cited}")
    return sorted(set(out))


@pytest.mark.parametrize("rel", OWNED)
def test_every_path_a_page_cites_is_in_this_tree(rel):
    """`deploy/registry.yaml` (three rows of the agents page's "Where to change things"),
    `scripts/deploy_app.sh` and `terraform/modules/ecr/main.tf` (a client's own operations) were
    all cited here and none of them is in the repository a stranger clones."""
    unresolved = _unresolved_paths(rel)
    assert not unresolved, (
        "these pages send a reader to a path this tree does not carry — either the path moved, "
        "or the sentence describes somebody else's repository:\n  " + "\n  ".join(unresolved))


@pytest.mark.parametrize("rel", OWNED)
def test_every_symbol_a_page_cites_is_defined_where_it_says(rel):
    """A path that resolves is not the same as a claim that is true. `org_defaults/roles/` has
    seven prompt files and `reviewer.md` is not among them — the reviewer's instructions are
    BUILT — so the agents page pointed a reader at a file to edit that has never existed."""
    text = _text(rel)
    wrong = []
    for match in CITED_SYMBOL.finditer(text):
        path, symbol = match.group(1), match.group(2)
        line = text.count("\n", 0, match.start()) + 1
        if not (ROOT / path).exists():
            wrong.append(f"{rel}:{line}  {path} does not exist")
            continue
        missing = [part for part in symbol.split(".") if part not in _defined_in(path)]
        if missing:
            wrong.append(f"{rel}:{line}  {path} defines no {missing}")
    assert not wrong, "\n  ".join(["a page names a symbol its own citation cannot produce:", *wrong])


def _tracked() -> frozenset[str]:
    """Every path this repository carries, as a clone receives it."""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                         capture_output=True, text=True, timeout=120)
    return frozenset(p for p in out.stdout.split("\0") if p)


def test_the_citation_scan_can_SEE_the_citations_that_were_here_and_reads_the_live_ones():
    """Verify the verifier, both ways: the three dead citations must be flagged, and a citation
    that IS true must not be — a scan that flagged everything would be turned off within a week."""
    dead = ["`deploy/registry.yaml`", "`scripts/deploy_app.sh`",
            "`terraform/modules/ecr/main.tf`"]
    for cited in dead:
        found = CITED_PATH.findall(cited)
        assert found, f"the path pattern does not even see {cited}"
        # TRACKED, NOT ON DISK. `deploy/registry.yaml` is deployment state and gitignored:
        # it exists on a machine that has run the platform and nowhere else, so `.exists()`
        # made this fixture answer differently on the author's laptop and on CI. What a
        # citation resolves against is what a clone CARRIES.
        assert found[0] not in _tracked(), f"{cited} is tracked — pick a different fixture"

    live = "`openfactory/adapters/reviewer/harness.py` → `build_review_prompt`"
    pair = CITED_SYMBOL.search(live)
    assert pair, "the symbol pattern does not see the arrow form the pages use"
    assert (ROOT / pair.group(1)).exists() and pair.group(2) in _defined_in(pair.group(1)), (
        "the symbol scan cannot confirm a citation that is true, so it measures nothing")

    stale = "`openfactory/org_defaults/roles/reviewer.md`"
    assert not (ROOT / CITED_PATH.findall(stale)[0]).exists(), (
        "a reviewer prompt file exists now — this fixture no longer describes the defect")

    #: …and an artefact NAME is not a path claim, or every `modules.yaml` on the page is noise
    assert not CITED_PATH.findall("`modules.yaml` and `manifest.yaml`")

    # …and the same claim with the backticks taken off is still a claim
    unbackticked = "| who may authorise | the deploy/registry.yaml file, product.admins |"
    assert BARE_PATH.findall(_prose(unbackticked)) == ["deploy/registry.yaml"], (
        "dropping the backticks is a way past the path scan, and it was")
    assert not BARE_PATH.findall(_prose("see `deploy/registry.yaml` for the shape")), (
        "the prose scan re-reads what the backticked scan already read, and would double-report")


def test_every_foreign_path_exemption_is_still_cited():
    """An entry in `NOT_OURS` that no page cites any more is a door standing open."""
    everything = "\n".join(_text(rel) for rel in OWNED)
    orphans = [p for p in NOT_OURS if f"`{p}`" not in everything]
    assert not orphans, (
        f"these are exempted from the path scan and no page cites them: {orphans} — drop them")


# ══ 3. what the operations page calls built, the code has to do ════════════════════════════════


def test_the_post_pr_lifecycle_the_page_calls_built_exists_and_is_reached():
    """D-12 was "not yet built" on the page for as long as `PromotionRunner` has walked it.
    Built AND reached: a class nobody constructs is the defect this repository is named for."""
    from openfactory.orchestrator.promotion import PromotionRunner

    for gesture in ("promote", "release_prod"):
        assert callable(getattr(PromotionRunner, gesture, None)), (
            f"the page says the chain is built and `PromotionRunner` has no {gesture}")

    assert "PromotionRunner" in _constructed_in_factory(), (
        "nothing in the composition root constructs a PromotionRunner, so the page's 'built' "
        "would be a class with green tests and no caller")


def _docker_run_argv(**knobs) -> list[str]:
    """The argv the box would hand the daemon — captured, never run."""
    import openfactory.adapters.sandbox.container as mod
    from openfactory.adapters.sandbox.registry import build_sandbox

    seen: list[list[str]] = []
    original = mod._host

    def _capture(args, timeout=None):
        seen.append(list(args))
        return (0, "")

    mod._host = _capture
    try:
        box = build_sandbox("container", image="img", **knobs)
        box.prepare(repo_path=ROOT, base_branch="main", branch="openfactory/probe")
    finally:
        mod._host = original
    return next(argv for argv in seen if "run" in argv)


def _cache_mount_target() -> str:
    """WHERE the box mounts a declared dependency-cache volume, read off the real argv — `""`
    when it mounts it nowhere, which is the state the page used to describe."""
    argv = _docker_run_argv(cache_volume="openfactory_probe_cache")
    mount = next((part for part in argv if part.startswith("openfactory_probe_cache:")), "")
    return mount.split(":", 1)[1] if mount else ""


#: A backticked absolute path — the shape a page uses to name a mount point inside the box.
_MOUNT_POINT = re.compile(r"`(/[A-Za-z0-9_./-]+)`")


def _mount_points_the_page_offers() -> set[str]:
    """Every place docs/operations.md names as somewhere inside the box the cache lives.

    EVERY paragraph about the cache, not the first one that agrees. `f"at `{target}`" in page`
    was the first version of this check, and the plan's cut walked straight through it: the page
    names `/cache` twice — once as the mount and once telling a reader what to point
    `PIP_CACHE_DIR` at — so moving the MOUNT left the other sentence behind to satisfy the
    assertion. One vocabulary token surviving an inversion is exactly the shape this file's
    docstring says it will not ship."""
    about_the_cache = [p for p in re.split(r"\n\s*\n", _text("docs/operations.md"))
                       if "cache" in p.lower() and _MOUNT_POINT.search(p)]
    assert about_the_cache, "docs/operations.md names no mount point for the cache at all"
    return {m for p in about_the_cache for m in _MOUNT_POINT.findall(p)}


def test_the_dependency_cache_the_page_describes_is_the_mount_the_box_makes():
    """"Designed; wiring is a near-term optimization" outlived the wiring. The page now names a
    mount point, and that string is rendered from an argv rather than remembered."""
    target = _cache_mount_target()
    assert target, "the box mounts a declared cache volume nowhere — the page's whole paragraph " \
                   "is about a mount that no longer happens"
    offered = _mount_points_the_page_offers()
    assert offered == {target}, (
        f"the box mounts the cache volume at {target!r} and docs/operations.md sends a reader to "
        f"{sorted(offered)} — every sentence about the cache has to name the same place, or the "
        f"one that is wrong is the one somebody copies")


def test_a_box_that_declares_no_cache_volume_mounts_none():
    """The twin, and it is what makes "off unless you ask for it" a fact rather than a hope."""
    argv = _docker_run_argv()
    target = _cache_mount_target()
    mounts = [argv[i + 1] for i, part in enumerate(argv[:-1]) if part == "-v"]
    assert not [m for m in mounts if m.endswith(f":{target}")], (
        f"a box with no `cache_volume` still mounts something at {target}: {mounts}")


def _set_state_body() -> ast.FunctionDef:
    tree = ast.parse((ROOT / "openfactory/adapters/tracker/github.py").read_text())
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and any(
                   isinstance(f, ast.FunctionDef) and f.name == "set_state" for f in n.body))
    return next(f for f in cls.body
                if isinstance(f, ast.FunctionDef) and f.name == "set_state")


def test_the_label_runs_only_when_the_board_did_not_move_the_card():
    """The page said labels were "the v1 board movement" and the column move a richer option.
    It is the other way round, and this asserts the CONDITION rather than either word: the
    branch that writes the label tests the value the board's own call produced. Swap the two —
    label first, board as fallback — and the name that branch tests is no longer bound above it.
    """
    fn = _set_state_body()
    moved: str | None = None
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "set_status"
                and isinstance(node.targets[0], ast.Name)):
            moved = node.targets[0].id
    assert moved, "`set_state` no longer records what the board answered — there is no fallback " \
                  "condition left to test, only two writes in a row"

    guarded = [branch for branch in ast.walk(fn) if isinstance(branch, ast.If)
               and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                       and c.func.attr == "_transition_label" for c in ast.walk(branch))]
    assert guarded, "the state label is written unconditionally — it is no longer a fallback"
    assert any(moved in {n.id for n in ast.walk(branch.test) if isinstance(n, ast.Name)}
               for branch in guarded), (
        f"the label is written without consulting {moved!r} — the page says the label is what "
        f"happens when the board move does not, and nothing in the code says that any more")


def test_the_page_names_the_label_the_code_actually_writes():
    """The rendered half: the prefix comes out of the module, so renaming it reddens the page."""
    from openfactory.adapters.tracker.github import _STATE_LABEL_PREFIX

    page = _squashed("docs/operations.md")
    assert f"`{_STATE_LABEL_PREFIX}<state>`" in page, (
        f"docs/operations.md does not name the {_STATE_LABEL_PREFIX}<state> label the fallback "
        f"writes")


def _board_move_is_primary() -> bool:
    """Whether the state label is written only when the board did not move the card — the
    condition `test_the_label_runs_only_when_the_board_did_not_move_the_card` asserts, as a
    value the page can be measured against."""
    fn = _set_state_body()
    moved = None
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "set_status"
                and isinstance(node.targets[0], ast.Name)):
            moved = node.targets[0].id
    if not moved:
        return False
    return any(moved in {n.id for n in ast.walk(branch.test) if isinstance(n, ast.Name)}
               for branch in ast.walk(fn) if isinstance(branch, ast.If)
               and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                       and c.func.attr == "_transition_label" for c in ast.walk(branch)))


#: The phrasings that put a capability in the future. The first four are verbatim from the three
#: sentences measured on 2026-08-26; the rest are how one of them would naturally be rewritten.
FUTURE_WORK = (
    "not yet built", "not built", "designed;", "near-term optimization", "the v1 board",
    "a richer implementation", "not implemented", "still to be built", "future work",
    "is planned", "will be built", "intend to", "we will", "is a design", "not there yet",
    "once built", "when it ships", "roadmap", "is coming", "yet to be",
)

#: capability → (the CODE CITATION that identifies its paragraph, a predicate answering whether
#: the code does it). The anchor is a citation on purpose: the paragraph cannot slip out of this
#: guard's reach without also dropping the path the citation guards above hold it to.
CAPABILITIES = {
    "the post-PR lifecycle": ("`openfactory/orchestrator/promotion.py`",
                              lambda: "PromotionRunner" in _constructed_in_factory()),
    "the dependency cache": ("`box.cache_volume`", lambda: bool(_cache_mount_target())),
    # the log line the fallback emits — a token only the paragraph about the fallback carries,
    # where the adapter's PATH is cited twice on this page (the move, and the column names)
    "the board movement": ("`OPENFACTORY_BOARD_MOVE_FAILED`", _board_move_is_primary),
}


def _constructed_in_factory() -> set[str]:
    tree = ast.parse((ROOT / "openfactory/factory.py").read_text())
    return {node.func.id for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}


def _paragraph_naming(rel: str, anchor: str) -> str:
    paragraphs = [p for p in re.split(r"\n\s*\n", _text(rel)) if anchor in p]
    assert len(paragraphs) == 1, (
        f"{rel} has {len(paragraphs)} paragraphs naming {anchor} — this guard reads the claim "
        f"about that capability out of exactly one")
    return re.sub(r"\s+", " ", paragraphs[0])


@pytest.mark.parametrize("capability", sorted(CAPABILITIES))
def test_the_operations_page_calls_future_exactly_what_the_code_has_not_done(capability):
    """Both directions, and the second is the one that makes this a binding rather than a style
    rule. If the code DOES it, the paragraph may not put it in the future — that is the three
    sentences this package was given. If the code stops doing it, the paragraph MUST say so:
    take the `PromotionRunner` construction out of the composition root and this turns red on a
    page that still calls the chain built, which is the worse error of the two."""
    anchor, does_it = CAPABILITIES[capability]
    paragraph = _paragraph_naming("docs/operations.md", anchor)
    deferred = _claims(paragraph, FUTURE_WORK)
    if does_it():
        assert not deferred, (
            f"the code does {capability} and docs/operations.md still says {deferred} about it — "
            f"a reader plans around a gap that closed")
    else:
        assert deferred, (
            f"the code does NOT do {capability} and docs/operations.md describes it as shipped. "
            f"Saying 'built' about something that is not is the worse half of this defect.")


def test_the_future_work_scan_can_SEE_the_three_sentences_that_were_here():
    """Verify the verifier, on the exact prose that shipped."""
    was_here = [
        "Beyond the PR (D-12 — not yet built): merge→staging, tag→prod, observe, notify.",
        "in the deps. (Designed; wiring is a near-term optimization.)",
        "refinement). Labels are the v1 board movement; GitHub Projects *column* moves are\n"
        "a richer implementation behind the same `TrackerAdapter.set_state` seam.",
    ]
    missed = [s for s in was_here if not _claims(re.sub(r"\s+", " ", s), FUTURE_WORK)]
    assert not missed, f"the scan walks past sentences that really were on the page: {missed}"

    ours = ["the chain is built and driven post-merge",
            "the box mounts that Docker volume at `/cache`",
            "the card's Status column is the movement, and the label is the fallback"]
    false = [s for s in ours if _claims(s, FUTURE_WORK)]
    assert not false, f"the scan fires on sentences that defer nothing: {false}"


# ══ 4. the retention counts a page certifies are the ones the terraform declares ═══════════════

#: terraform lifecycle-policy resource → the repository suffix the page calls it by.
_ECR_POLICIES = {"sandbox": "-python", "worker": "-worker"}
_ALERTING = "infra/terraform/alerting.tf"


def _declared_counts() -> dict[str, int]:
    """`{resource: countNumber}` out of the terraform, one regex over one file."""
    text = (ROOT / _ALERTING).read_text()
    out: dict[str, int] = {}
    for block in re.finditer(
            r'resource\s+"aws_ecr_lifecycle_policy"\s+"([a-z_]+)"\s*\{(.*?)\n\}',
            text, re.S):
        count = re.search(r"countNumber\s*=\s*(\d+)", block.group(2))
        if count:
            out[block.group(1)] = int(count.group(1))
    return out


def _stated_counts() -> dict[str, int]:
    """`{repository suffix: the number the page's table states}` — off the table rows."""
    out: dict[str, int] = {}
    for line in _text("docs/rotation-and-retention.md").splitlines():
        if not line.startswith("|"):
            continue
        repo = re.search(r"`<prefix>(-[a-z]+)`", line)
        count = re.search(r"\*\*(\d+)\*\*", line)
        if repo and count:
            out[repo.group(1)] = int(count.group(1))
    return out


def test_the_retention_counts_the_page_certifies_are_the_terraforms():
    """The page said "keep last 10" about two repositories the terraform bounds at 20 and 30 —
    and said 20 and 30 itself, eighty lines earlier, so the document disagreed with itself as
    well as with the infrastructure. Read from the terraform, both directions."""
    if not (ROOT / _ALERTING).exists():
        pytest.skip(f"{_ALERTING} leaves the public tree with openfactory-aws "
                    f"(docs/STATUS.md) — the numbers cannot be read here")
    declared = _declared_counts()
    assert set(declared) == set(_ECR_POLICIES), (
        f"{_ALERTING} declares lifecycle policies for {sorted(declared)}, and this guard knows "
        f"about {sorted(_ECR_POLICIES)} — a repository gained or lost a policy")
    stated = _stated_counts()
    expected = {suffix: declared[resource] for resource, suffix in _ECR_POLICIES.items()}
    assert stated == expected, (
        f"docs/rotation-and-retention.md states {stated} and {_ALERTING} declares {expected} — "
        f"an operator sizing a rollback window would plan against a number that is not live")


def test_the_terraform_parse_reads_a_real_policy_and_refuses_a_planted_one():
    """Verify the verifier: the parse has to come back with two numbers that differ, or it could
    be returning the same constant twice and the comparison above would prove nothing."""
    if not (ROOT / _ALERTING).exists():
        pytest.skip(f"{_ALERTING} leaves the public tree with openfactory-aws (docs/STATUS.md)")
    declared = _declared_counts()
    assert len(set(declared.values())) == len(declared), (
        f"the two policies read as the same count {declared} — the worker repository holds two "
        f"images per deploy and the box repository one, so equal numbers mean unequal history")
    assert all(count > 0 for count in declared.values()), declared


# ══ 5. the agents page lists what the registries ship ══════════════════════════════════════════

_COUNT_WORD = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven"}


def _harness_paragraph() -> str:
    """The paragraph that names the harness table — located by the table's own name."""
    paragraphs = re.split(r"\n\s*\n", _text("docs/agents.md"))
    found = [p for p in paragraphs if "`HARNESSES`" in p]
    assert len(found) == 1, (
        f"docs/agents.md has {len(found)} paragraphs naming `HARNESSES`; this guard reads the "
        f"list of shipped harnesses out of exactly one")
    return re.sub(r"\s+", " ", found[0])


def test_the_agents_page_lists_every_harness_the_registry_ships_and_no_other():
    """Four ship. The page named three for as long as `opencode` had been a row — and a page
    that lists three of four is worse than one that lists none, because a reader stops looking.
    Both directions: a retired harness left on the page is the same defect facing backwards."""
    from openfactory.adapters.agent.registry import HARNESSES

    paragraph = _harness_paragraph()
    listed = {m.group(1) for m in re.finditer(r"`([a-z][a-z_]*)`", paragraph)}
    assert listed == set(HARNESSES), (
        f"the registry ships {sorted(HARNESSES)} and the page lists {sorted(listed)}")


def test_the_agents_page_states_the_harness_count_the_registry_holds():
    """The count is rendered from the table's length, so adding a harness reddens the sentence
    as well as the list — a number and the thing it counts, in one place."""
    from openfactory.adapters.agent.registry import HARNESSES

    word = _COUNT_WORD[len(HARNESSES)]
    assert f"**{word} harnesses ship**" in _squashed("docs/agents.md"), (
        f"{len(HARNESSES)} harnesses are registered and docs/agents.md does not say "
        f"'{word} harnesses ship'")


def _product_admins_field() -> tuple[str, list[str]]:
    """`("admins", [legacy aliases])`, straight off the contract."""
    from openfactory.contracts.product import ProductConfig

    field = ProductConfig.model_fields["admins"]
    choices = list(getattr(field.validation_alias, "choices", []) or [])
    return "admins", [c for c in choices if c != "admins"]


def test_the_agents_page_names_the_field_the_contract_declares():
    """Rendered from the model: rename the field and the page goes red with it."""
    canonical, aliases = _product_admins_field()
    assert aliases, "ProductConfig.admins declares no legacy alias — this guard has no subject"
    page = _text("docs/agents.md")
    assert f"ProductConfig.{canonical}" in page, (
        f"docs/agents.md does not name `ProductConfig.{canonical}`, the field an operator sets")


def test_the_agents_page_never_offers_a_retired_alias_as_the_thing_to_set():
    """The twin. `slack_admins` still parses, so it may be MENTIONED — but a line that names it
    without saying it is an alias reads as the current field name, which is how two rows of the
    page went on telling operators to edit a name the contract stopped calling canonical."""
    canonical, aliases = _product_admins_field()
    about_it = re.compile(r"\balias\b|\bold\b|\bformer\b|\bretired\b|\brenamed\b|no longer",
                          re.IGNORECASE)
    stale = []
    for number, line in enumerate(_text("docs/agents.md").splitlines(), 1):
        for alias in aliases:
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])", line) \
                    and not about_it.search(line):
                stale.append(f"docs/agents.md:{number}  {line.strip()[:90]}")
    assert not stale, (
        f"these read as instructions to set {aliases}, and the contract's field is "
        f"{canonical!r}:\n  " + "\n  ".join(stale))


# ══ 6. the reason a worker logs is bounded, and says something ═════════════════════════════════
#
# The twin that shipped with `_readable` lives in `tests/test_the_chat_is_a_directory_delete.py`
# (`test_a_reason_that_is_not_a_sentence_is_still_bounded`) and exercises a long first sentence,
# a sentence longer than any human message, and no sentence at all. The case below is the one it
# had no row for, and it is the one that regressed.


def test_a_short_first_sentence_does_not_throw_away_the_diagnosis():
    """`Request failed. status=503 body={…}` — the shape a vendor SDK raises. Preferring the
    first sentence unconditionally logged four words and dropped the status code, which is
    strictly less than the fixed slice this helper was written to improve on."""
    from openfactory.runtime.temporal import worker

    dump = "Request failed. status=503 body={" + "x" * 350 + "}"
    assert len(dump) > 200, "the fixture is short enough to pass through untouched"
    got = worker._readable(Exception(dump))
    assert "status=503" in got, (
        f"the reason a person reads is {got!r} — the status code is what tells them whether to "
        f"retry or to go and look")
    assert len(got) == 200, f"bounded at the cap, and this is {len(got)}"


def test_a_long_first_sentence_is_still_preferred_whole():
    """The half that must not regress in the other direction: the platform's own refusals put
    the remedy after the complaint, and a fixed slice is what cut it off."""
    from openfactory.runtime.temporal import worker

    remedy = "w" * 300
    got = worker._readable(Exception(f"the kind is refused, and here is what to do: {remedy}. "
                                     f"And then the boilerplate tail."))
    assert got.endswith(".") and remedy in got, got
    assert len(got) > 200, "the whole point is that it outgrew the cap and was kept anyway"


def test_the_reason_is_bounded_whichever_form_wins():
    """Neither branch may become "print anything, at any length"."""
    from openfactory.runtime.temporal import worker

    ceiling = worker._SENTENCE_CAP + 1
    for reason in ("x" * 5000, "y" * 2000 + ". tail",
                   "short. " + "z" * 900 + ". tail", "a" * 400):
        assert len(worker._readable(Exception(reason))) <= ceiling, reason[:40]


# ══ 7. the compose file names no vendor's credential variable, and forwards them all ═══════════


def _compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text())


def _environment_keys(service: dict) -> set[str]:
    """The variable NAMES a service pins, whichever of Compose's two spellings it uses.

    BOTH SPELLINGS, because one of them was a way through. `environment:` accepts a mapping
    (`NAME: value`) and a list (`- NAME=value`), and a scan that only knew the mapping read a
    list-form pin as the string `NAME=value` — so moving the row to the other syntax would have
    left the guard green with the variable back in the file."""
    declared = service.get("environment") or {}
    if isinstance(declared, dict):
        return set(declared)
    return {str(row).split("=", 1)[0].strip() for row in declared}


def _vendor_variables() -> set[str]:
    """Every axis vendor's DEFAULT credential variable, from the rows the vendors declare."""
    from openfactory import credentials
    from openfactory.adapters.credential.registry import CREDENTIALS

    named = {credentials.vendor_default_env(types.SimpleNamespace(kind=kind))
             for kind in CREDENTIALS}
    return {n for n in named if n}


def test_no_vendors_default_credential_variable_is_pinned_in_the_compose_environment():
    """One of the two was listed and the other was not, so the file read as if one tracker were
    closer to the core. Worse: `environment:` beats `env_file:`, and `${JIRA_API_TOKEN:-}`
    expands to the empty string, so the row could only ever OVERRIDE what .env.compose carried.
    Derived from the credential rows, so a stranger's add-on kind is covered the day it lands."""
    vendors = _vendor_variables()
    assert len(vendors) >= 2, (
        f"only {sorted(vendors)} declare a default variable — this guard needs the vendors it "
        f"is about")
    pinned = {name: sorted(_environment_keys(svc) & vendors)
              for name, svc in _compose()["services"].items()
              if _environment_keys(svc) & vendors}
    assert not pinned, (
        f"docker-compose.yml pins a vendor's credential variable in `environment:`: {pinned}. "
        f"The registry NAMES the variable per project (`tracker.options.token_env`), so a list "
        f"written here can never be complete — and a row that expands to '' shadows the "
        f"env_file value it was meant to help.")


def test_the_services_that_need_a_projects_credential_forward_the_whole_env_file():
    """The twin, and without it the rule above is satisfied by a compose file that delivers no
    credential at all. The mechanism has to exist AND the file a reader copies has to name each
    vendor's variable, or "put it in .env.compose" is advice with nowhere to land."""
    compose = _compose()
    for service in ("worker", "panel"):
        rows = compose["services"][service].get("env_file") or []
        named = {row["path"] if isinstance(row, dict) else row for row in rows}
        assert ".env.compose" in named, (
            f"the {service} service no longer forwards .env.compose, so no per-project "
            f"credential reaches it at all")

    example = (ROOT / ".env.compose.example").read_text()
    absent = sorted(v for v in _vendor_variables() if v not in example)
    assert not absent, (
        f".env.compose.example does not name {absent} — the compose file stopped pinning them "
        f"on the promise that this file carries them")


# ══ 8. an add-on's first command runs where its README is read ═════════════════════════════════

_PIP_TARGET = re.compile(r"^pip install\s+(?!-)(\S+)", re.M)


def _quickstart(readme: pathlib.Path) -> str:
    """The FIRST fenced block — the one a reader copies before reading anything else."""
    blocks = re.findall(r"```[a-z]*\n(.*?)```", readme.read_text(), re.S)
    assert blocks, f"{readme} has no fenced block — there is no quickstart to check"
    return blocks[0]


def _install_targets(block: str) -> list[str]:
    """The path arguments, with quoting and an extras suffix stripped (`'.[runtime]'` → `.`)."""
    return [re.sub(r"\[.*?\]", "", target.strip("'\"")) for target in _PIP_TARGET.findall(block)]


@pytest.mark.parametrize("package", sorted(p.name for p in (ROOT / "addons").glob("openfactory-*"))
                         if (ROOT / "addons").is_dir() else [])
def test_an_add_ons_quickstart_installs_from_the_directory_its_readme_sits_in(package):
    """`pip install addons/openfactory-aws` is correct from the repository root and wrong from
    the directory the README is in — which is where a reader meeting the package first stands.
    The build itself does not care: `setup.py` resolves the checkout from its OWN location, so
    both spellings work and the page has to offer the one that matches where you are."""
    here = ROOT / "addons" / package
    targets = _install_targets(_quickstart(here / "README.md"))
    assert targets, f"{package}'s quickstart runs no `pip install` at all"

    from_here = [t for t in targets if (here / t).exists()]
    assert from_here, (
        f"{package}/README.md offers {targets}, and none of them resolves from the directory "
        f"the file is in — a reader who cd'd into the package cannot run its own first command")

    nowhere = [t for t in targets if not (here / t).exists() and not (ROOT / t).exists()]
    assert not nowhere, (
        f"{package}/README.md offers {nowhere}, which resolves neither from the package "
        f"directory nor from the repository root")


def test_the_quickstart_scan_can_SEE_the_command_that_was_here():
    """Verify the verifier on the exact block that shipped: root-relative only, which is the
    defect, and the reader standing in the package directory is who it fails."""
    was_here = "pip install addons/openfactory-aws   # from this checkout\n"
    here = ROOT / "addons" / "openfactory-aws"
    if not here.is_dir():
        pytest.skip("addons/ leaves the public tree (docs/STATUS.md)")
    targets = _install_targets(was_here)
    assert targets == ["addons/openfactory-aws"], targets
    assert not [t for t in targets if (here / t).exists()], (
        "the old command resolves from the package directory after all — the guard would have "
        "passed on the defect it is written for")
    assert [t for t in targets if (ROOT / t).exists()], (
        "…and it does not resolve from the root either, so this fixture is not the defect")


# ══ 9. a lesson and the record it summarises name the same thing ═══════════════════════════════

_POOL_VARIABLE = re.compile(r"(?<![A-Za-z0-9_])([A-Z][A-Z0-9]*_AGENT_TOKENS)(?![A-Za-z0-9_])")
_RECORD = "docs/adr/0009-durability-and-resilience-hardening.md"


def test_the_lesson_names_the_pool_variable_the_code_reads_today():
    """The lesson had the incident's variable rewritten to the platform's current spelling while
    ADR-0009 §8 kept the one that was there — two accounts of one event, disagreeing, with the
    ADR the account that may not be edited. So the lesson names TODAY's variable and defers the
    historical one to the record, and this holds it to a name the code actually reads."""
    from openfactory.environ import names_read

    named = set(_POOL_VARIABLE.findall(_text("docs/engineering-lessons.md")))
    assert named, (
        "docs/engineering-lessons.md names no agent-token pool variable at all — the fix was to "
        "name the live one, not to delete the sentence")
    unread = sorted(n for n in named if n not in names_read())
    assert not unread, (
        f"the lesson names {unread}, which nothing in `openfactory/` reads. A lesson points at a "
        f"variable a reader can go and set; the name that was there on the day is the decision "
        f"record's to keep ({_RECORD}).")


def test_the_record_still_carries_the_name_the_lesson_defers_to():
    """The twin: the deferral is only honest while the ADR still holds the historical name. An
    ADR is history — if this ever fails, the record was edited, which is the one thing the
    directory forbids."""
    historical = set(_POOL_VARIABLE.findall(_text(_RECORD)))
    assert historical, (
        f"{_RECORD} no longer names the pool variable, so the lesson defers to a record that "
        f"has stopped carrying it")
    from openfactory.environ import names_read

    assert not (historical & names_read()), (
        f"{_RECORD} now names a variable the code still reads ({sorted(historical)}) — the two "
        f"accounts no longer describe different moments, so the deferral says nothing")
