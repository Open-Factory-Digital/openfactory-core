"""build_context assembles the agent's manual from the manifest globs (D-9/D-10)."""

from __future__ import annotations

from pathlib import Path

from openfactory import namespace
from openfactory.contracts import Manifest, Ticket
from openfactory.contracts.profile import Profile
from openfactory.orchestrator import operator_guidelines as og
from openfactory.orchestrator.context import build_context
from openfactory.policy.profiles import ResolvedProfile


def _ticket() -> Ticket:
    return Ticket(id="#1", title="t", objective="o", repo="o/x")


def test_loads_constraints_guidelines_and_derived_index(tmp_path: Path):
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "docs" / "adr" / "0001.md").write_text("# ADR 1\nDomain must not import FastAPI.")
    (tmp_path / "docs" / "arch").mkdir(parents=True)
    (tmp_path / "docs" / "arch" / "reconcile.md").write_text(
        "---\nsummary: how matching works\n---\n# Reconcile\n..."
    )
    (tmp_path / namespace.DIR).mkdir()
    (tmp_path / namespace.DIR / "exec.md").write_text("100% coverage is enforced.")

    manifest = Manifest(
        docs={
            "constraints": "docs/adr/**",
            "architecture": "docs/arch/**",
            "guidelines": [f"{namespace.DIR}/exec.md"],
        }
    )
    ctx = build_context(manifest, tmp_path, _ticket())

    assert any("must not import FastAPI" in c for c in ctx.constraints)
    assert any("100% coverage" in g for g in ctx.guidelines)
    assert "reconcile.md — how matching works" in ctx.doc_index  # derived from frontmatter
    assert "Edit" in ctx.allowed_tools


def test_a_guideline_the_manifest_names_and_the_checkout_lacks_is_WARNED(tmp_path: Path,
                                                                         caplog):
    """The two globs warned on zero matches; the guidelines LIST dropped missing entries in
    silence (v2 verification pass, 2026-08-10) — a rule the team wrote down, followed by
    nobody, with nothing saying so. Same warning, same reason."""
    manifest = Manifest(docs={"guidelines": ["docs/rules-that-do-not-exist.md"]})

    with caplog.at_level("WARNING"):
        ctx = build_context(manifest, tmp_path, _ticket())

    assert "rules-that-do-not-exist.md" in caplog.text
    assert "WITHOUT" in caplog.text
    # tolerated, not fatal — the framework baseline still arrives
    assert any("Engineering baseline" in g for g in ctx.guidelines)


def test_missing_docs_are_tolerated(tmp_path: Path):
    ctx = build_context(Manifest(), tmp_path, _ticket())
    # project docs are empty, but the framework baseline guidelines are ALWAYS injected
    assert ctx.constraints == [] and ctx.doc_index == ""
    assert any("Engineering baseline" in g for g in ctx.guidelines)


def test_framework_baseline_always_present(tmp_path: Path):
    ctx = build_context(Manifest(), tmp_path, _ticket())
    assert ctx.guidelines, "org_defaults must be injected for every job"


def test_knowledge_map_off_by_default(tmp_path: Path):
    """Flag off (the default) → no map injected, existing behaviour unchanged — even if a
    bundle happens to be present."""
    from openfactory.knowledge import build_bundle, write_bundle

    write_bundle(build_bundle(tmp_path, commit="c", generated_at="t"), tmp_path)
    ctx = build_context(Manifest(), tmp_path, _ticket())  # knowledge_map defaults False
    assert ctx.knowledge_map == ""


def test_knowledge_map_injected_when_enabled_and_fresh(tmp_path: Path):
    """Flag on + a fresh bundle → the rendered module map is present in the context."""
    from openfactory.knowledge import build_bundle, write_bundle

    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "__init__.py").write_text('"""Core rules."""\n')
    write_bundle(build_bundle(tmp_path, commit="c", generated_at="t"), tmp_path)

    ctx = build_context(Manifest(knowledge_map=True), tmp_path, _ticket())
    assert "### core" in ctx.knowledge_map
    assert "ground truth" in ctx.knowledge_map.lower()


def test_knowledge_map_not_injected_when_stale(tmp_path: Path):
    """Flag on but the bundle is stale (a source changed after generation) → nothing injected;
    the agent falls back to searching the code (§12 fail-safe)."""
    from openfactory.knowledge import build_bundle, write_bundle

    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "__init__.py").write_text('"""Core."""\n')
    write_bundle(build_bundle(tmp_path, commit="c", generated_at="t"), tmp_path)
    (tmp_path / "core" / "__init__.py").write_text('"""Core CHANGED."""\n')  # drift

    ctx = build_context(Manifest(knowledge_map=True), tmp_path, _ticket())
    assert ctx.knowledge_map == ""


def test_knowledge_map_override_is_reused_not_recomputed(tmp_path: Path):
    """The clean-pass freshness decision is REUSED for repair/recovery: a passed knowledge_map is
    used verbatim, so the agent's OWN uncommitted edits (a dirty tree during repair) can't
    spuriously flag the bundle stale — the false positive we fix. None → compute (clean pass)."""
    from openfactory.knowledge import build_bundle, write_bundle

    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "__init__.py").write_text('"""Core."""\n')
    write_bundle(build_bundle(tmp_path, commit="c", generated_at="t"), tmp_path)
    (tmp_path / "core" / "__init__.py").write_text('"""agent edited this."""\n')  # dirty tree

    # recomputing against the dirty tree → stale → "" (exactly the repair-time false positive)
    assert build_context(Manifest(knowledge_map=True), tmp_path, _ticket()).knowledge_map == ""
    # passing the clean-pass value through → reused verbatim, the dirty tree is not re-judged
    reused = build_context(Manifest(knowledge_map=True), tmp_path, _ticket(),
                           knowledge_map="THE-CLEAN-MAP").knowledge_map
    assert reused == "THE-CLEAN-MAP"


# ── the operator's central guidelines directory (#318) ───────────────────────────────────────────


def _op_dir(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "central"
    d.mkdir()
    monkeypatch.setenv(og.ENV_VAR, str(d))
    return d


def test_operator_guidelines_land_after_the_baseline_and_before_the_project(tmp_path, monkeypatch):
    """The order is the weight: framework baseline, THEN the operator's own, THEN the project's."""
    d = _op_dir(tmp_path, monkeypatch)
    (d / "central.md").write_text("CENTRAL OPERATOR STANDARD")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "house.md").write_text("PROJECT HOUSE RULE")
    manifest = Manifest(docs={"guidelines": ["docs/house.md"]})

    ctx = build_context(manifest, tmp_path, _ticket())

    central = next(i for i, g in enumerate(ctx.guidelines) if "CENTRAL OPERATOR STANDARD" in g)
    house = next(i for i, g in enumerate(ctx.guidelines) if "PROJECT HOUSE RULE" in g)
    baseline = max(i for i, g in enumerate(ctx.guidelines) if "Engineering baseline" in g
                   or "test-driven development" in g)
    assert baseline < central < house


def test_a_path_outside_the_operator_dir_is_refused_not_silently_read(tmp_path, monkeypatch):
    """Containment: a symlink leading out of the directory is ignored — its content never reaches
    the prompt — with a warning naming the file."""
    d = _op_dir(tmp_path, monkeypatch)
    secret = tmp_path / "secret.md"
    secret.write_text("ABSOLUTELY-SECRET-CONTENT")
    (d / "escape.md").symlink_to(secret)
    (d / "real.md").write_text("legitimate central rule")

    ctx = build_context(Manifest(), tmp_path, _ticket())

    assert any("legitimate central rule" in g for g in ctx.guidelines)
    assert not any("ABSOLUTELY-SECRET-CONTENT" in g for g in ctx.guidelines)


def test_a_missing_operator_dir_warns(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv(og.ENV_VAR, str(tmp_path / "not-there"))
    with caplog.at_level("WARNING"):
        build_context(Manifest(), tmp_path, _ticket())
    assert og.ENV_VAR in caplog.text and "not-there" in caplog.text


def test_an_empty_operator_dir_warns(tmp_path, monkeypatch, caplog):
    d = _op_dir(tmp_path, monkeypatch)
    (d / "readme.txt").write_text("no markdown")
    with caplog.at_level("WARNING"):
        build_context(Manifest(), tmp_path, _ticket())
    assert og.ENV_VAR in caplog.text and "no .md" in caplog.text


def test_a_profile_waives_an_operator_guideline_by_name_like_a_framework_one(tmp_path, monkeypatch):
    """A profile drops an operator guideline by filename, exactly as it drops `tdd.md` — and
    without the 'no such guideline' warning that a genuine typo earns."""
    d = _op_dir(tmp_path, monkeypatch)
    (d / "waivable.md").write_text("CENTRAL RULE THIS CLASS DROPS")
    (d / "kept.md").write_text("CENTRAL RULE THIS CLASS KEEPS")
    profile = ResolvedProfile([Profile.model_validate(
        {"name": "poc", "guidelines": {"waive": ["waivable.md"]}})])

    ctx = build_context(Manifest(), tmp_path, _ticket(), profile=profile)

    assert not any("CENTRAL RULE THIS CLASS DROPS" in g for g in ctx.guidelines)
    assert any("CENTRAL RULE THIS CLASS KEEPS" in g for g in ctx.guidelines)


def test_waiving_an_operator_guideline_is_not_warned_as_a_typo(tmp_path, monkeypatch, caplog):
    d = _op_dir(tmp_path, monkeypatch)
    (d / "waivable.md").write_text("central")
    profile = ResolvedProfile([Profile.model_validate(
        {"name": "poc", "guidelines": {"waive": ["waivable.md"]}})])

    with caplog.at_level("WARNING"):
        build_context(Manifest(), tmp_path, _ticket(), profile=profile)

    assert "no such framework or operator guideline exists" not in caplog.text


def test_a_profile_replaces_an_operator_guideline_by_name(tmp_path, monkeypatch):
    d = _op_dir(tmp_path, monkeypatch)
    (d / "style.md").write_text("THE CENTRAL STYLE RULE")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "our-style.md").write_text("THE PROJECTS OWN STYLE RULE")
    profile = ResolvedProfile([Profile.model_validate(
        {"name": "x", "guidelines": {"replace": {"style.md": "docs/our-style.md"}}})])

    ctx = build_context(Manifest(), tmp_path, _ticket(), profile=profile)

    assert any("THE PROJECTS OWN STYLE RULE" in g for g in ctx.guidelines)
    assert not any("THE CENTRAL STYLE RULE" in g for g in ctx.guidelines)


def _reference_dir(tmp_path, monkeypatch):
    """An operator directory with one inlined guideline and one on-demand reference document."""
    d = _op_dir(tmp_path, monkeypatch)
    (d / "central.md").write_text("inlined central rule")
    ref = d / "reference"
    ref.mkdir()
    (ref / "big.md").write_text(
        "---\nsummary: the long central standard\n---\n# Big\nVERY-LONG-BODY-TEXT")
    return d


def test_reference_docs_are_INDEXED_not_INLINED(tmp_path, monkeypatch):
    """The on-demand tier: a `reference/` document appears in doc_index (title + summary) and its
    body is NOT inlined into the guidelines on every job."""
    d = _reference_dir(tmp_path, monkeypatch)

    ctx = build_context(Manifest(), tmp_path, _ticket(), reference_root=str(d))

    assert f"{d}/reference/big.md — the long central standard" in ctx.doc_index
    assert not any("VERY-LONG-BODY-TEXT" in g for g in ctx.guidelines)


def test_the_index_names_the_path_THE_AGENT_can_open(tmp_path, monkeypatch):
    """The entry is the box's own path, not one relative to a directory the box has never heard of.

    The label used to read `reference/big.md`, like `docs.architecture`'s repo-relative entries —
    and the agent works from the CHECKOUT. On a container box the operator directory is not
    mounted, and on a worktree box that label resolves inside the repository, where it finds
    nothing or, worse, a different file when the project has a `reference/` of its own. So the
    entry carries the path the box answered with, and that is what the agent opens (review of
    #328).
    """
    _reference_dir(tmp_path, monkeypatch)
    (tmp_path / "reference").mkdir()  # the project has one of its own — the trap
    (tmp_path / "reference" / "big.md").write_text("# The WRONG big.md, inside the checkout")

    ctx = build_context(Manifest(), tmp_path, _ticket(),
                        reference_root="/opt/openfactory-guidelines")

    assert "/opt/openfactory-guidelines/reference/big.md — the long central standard" \
        in ctx.doc_index
    # and never the bare relative label, which is what the checkout's own file would answer to
    assert "\nreference/big.md" not in "\n" + ctx.doc_index


def test_a_box_that_cannot_reach_the_dir_indexes_NOTHING_and_says_so(tmp_path, monkeypatch,
                                                                     caplog):
    """No `reference_root` means no box could name a path — so the documents are left out.

    An entry the agent cannot open is worse than no entry: it spends a tool call and comes back
    reading as a document somebody deleted. The omission is the safe half; the warning is what
    keeps it from being the quiet kind.
    """
    d = _reference_dir(tmp_path, monkeypatch)

    with caplog.at_level("WARNING"):
        ctx = build_context(Manifest(), tmp_path, _ticket())  # no reference_root

    assert "big.md" not in ctx.doc_index
    assert "NOT indexed" in caplog.text and str(d) in caplog.text
    # the INLINED tier is unaffected — it is read here, not by the agent
    assert any("inlined central rule" in g for g in ctx.guidelines)


def test_a_name_in_BOTH_tiers_is_named_when_a_profile_addresses_it(tmp_path, monkeypatch,
                                                                   caplog):
    """One `waive:` silently drops two files, and the operator is told which name did it.

    Guidelines are addressed by bare filename and the same profile runs against both tiers, so an
    organisation shipping its own copy of a name `org_defaults/` already uses has a profile that
    acts on two documents while reading as though it acted on one (review of #328).
    """
    from openfactory.contracts.profile import Profile
    from openfactory.orchestrator.context import ORG_DEFAULTS_DIR
    from openfactory.policy.profiles import ResolvedProfile

    shared = sorted(p.name for p in ORG_DEFAULTS_DIR.glob("*.md") if p.is_file())[0]
    d = _op_dir(tmp_path, monkeypatch)
    (d / shared).write_text("the organisation's own copy of that name")
    profile = ResolvedProfile([Profile.model_validate(
        {"name": "ours", "guidelines": {"waive": [shared]}})])

    with caplog.at_level("WARNING"):
        build_context(Manifest(), tmp_path, _ticket(), profile=profile)

    assert shared in caplog.text and "BOTH copies" in caplog.text


def test_a_name_in_one_tier_only_is_not_warned_about(tmp_path, monkeypatch, caplog):
    """The warning is for the ambiguity, not for having an operator tier at all — a name the
    framework does not use is unambiguous, and saying so would train the reader to ignore it."""
    from openfactory.contracts.profile import Profile
    from openfactory.policy.profiles import ResolvedProfile

    d = _op_dir(tmp_path, monkeypatch)
    (d / "a-name-the-framework-does-not-use.md").write_text("ours alone")
    profile = ResolvedProfile([Profile.model_validate(
        {"name": "ours", "guidelines": {"waive": ["a-name-the-framework-does-not-use.md"]}})])

    with caplog.at_level("WARNING"):
        build_context(Manifest(), tmp_path, _ticket(), profile=profile)

    assert "BOTH copies" not in caplog.text


def test_md_files_double_star_matches_files_recursively(tmp_path: Path):
    """`dir/**` must yield the .md files under dir (direct + nested) on every Python —
    a bare trailing `**` matched only directories on 3.12, turning CI red while local
    3.11 was green (constraints loaded empty)."""
    from openfactory.orchestrator.context import _md_files

    (tmp_path / "docs" / "adr" / "sub").mkdir(parents=True)
    (tmp_path / "docs" / "adr" / "0001.md").write_text("a")
    (tmp_path / "docs" / "adr" / "sub" / "0002.md").write_text("b")
    got = sorted(p.name for p in _md_files(tmp_path, "docs/adr/**"))
    assert got == ["0001.md", "0002.md"]


# ── the map must describe the code the AGENT is looking at, not the shared base clone ────────────

class _NoRemoteForge:
    """No push remote → nothing published, so the injector falls back to a bundle committed in
    the repo itself (the Phase-1 shape, still supported)."""

    def push_remote(self):
        return None


class _Sink:
    def emit(self, event):
        pass


def _runner(manifest, repo_path):
    from openfactory.orchestrator import JobRunner

    r = JobRunner.__new__(JobRunner)
    r.manifest, r.repo_path = manifest, repo_path
    r.forge, r.events = _NoRemoteForge(), _Sink()
    return r


def _bundled(root: Path, marker: str) -> Path:
    """A repo whose single module's purpose is `marker` — so the rendered map says which tree
    it came from."""
    from openfactory.knowledge import build_bundle, write_bundle

    (root / "core").mkdir(parents=True)
    (root / "core" / "__init__.py").write_text(f'"""{marker}"""\n')
    write_bundle(build_bundle(root, commit="c", generated_at="t"), root)
    return root


def test_knowledge_comes_from_the_job_workspace_not_the_base_clone(tmp_path: Path):
    """`repo_path` is the shared, long-lived base-branch clone; the agent works in the sandbox
    workspace. A map is a claim about the code the agent is about to read, so it must be loaded
    and verified against THAT tree — otherwise we vouch for a tree nobody is looking at."""
    from openfactory.adapters.sandbox.base import Workspace

    base = _bundled(tmp_path / "base", "THE BASE CLONE")
    work = _bundled(tmp_path / "work", "THE JOB WORKSPACE")
    r = _runner(Manifest(knowledge_map=True), base)
    ws = Workspace(path=Path("/work"), host_path=work, branch="b", base_branch="main")

    ctx = r._build_context(_ticket(), ws)
    assert "THE JOB WORKSPACE" in ctx.knowledge_map
    assert "THE BASE CLONE" not in ctx.knowledge_map


def test_clean_pass_verdict_is_reused_once_the_workspace_is_dirty(tmp_path: Path):
    """Freshness is only meaningful on the clean checkout. Once the agent has edited the
    workspace, a repair/recovery context must REUSE the clean verdict — recomputing would flag
    the bundle stale against the agent's own uncommitted work and drop a map that is still
    valid."""
    from openfactory.adapters.sandbox.base import Workspace

    work = _bundled(tmp_path / "work", "THE JOB WORKSPACE")
    r = _runner(Manifest(knowledge_map=True), tmp_path / "base")
    ws = Workspace(path=Path("/work"), host_path=work, branch="b", base_branch="main")

    clean = r._build_context(_ticket(), ws).knowledge_map
    assert "THE JOB WORKSPACE" in clean

    # the agent now edits the tree — a recomputation here would say "stale" and inject nothing
    (work / "core" / "__init__.py").write_text('"""edited mid-run"""\n')
    from openfactory.knowledge import load_agent_knowledge

    assert load_agent_knowledge(work, enabled=True) == ""  # (the false positive we avoid)
    assert r._build_context(_ticket(), ws).knowledge_map == clean  # reused verbatim


# ── the A/B arm the runner reports (ADR-0017's gate) ─────────────────────────────────────────────

def test_the_arm_records_what_the_agent_SAW_not_what_was_configured(tmp_path: Path):
    """The comparison is only honest if a flag-on job that never received a map counts as a
    CONTROL. Bucketing by config instead of by what reached the prompt would dilute the treatment
    arm with runs that saw nothing — which is exactly how #478 was recorded.

    WHAT CHANGED WITH ADR-0023: `unavailable` used to be reachable through STALENESS — a published
    map describing an older commit than the job's checkout. It is not reachable that way any more,
    because the map is generated from the tree the agent reads and cannot drift from it.
    `unavailable` now means one thing: generation produced nothing. That is a narrower and far more
    useful signal — it went from "somebody merged something somewhere" to "something is wrong here".
    """
    from openfactory.adapters.sandbox.base import Workspace

    # opted out
    # `knowledge_map=False` is now EXPLICIT: ADR-0035 flipped the default to on, so a bare
    # `Manifest()` records `unavailable` (flag on, nothing reached the prompt) rather than `off`.
    # This test is about the off arm, and off is a choice a project makes now.
    off = _runner(Manifest(knowledge_map=False), tmp_path / "a")
    off._build_context(_ticket(), None)
    assert off.knowledge_arm() == "off"

    # opted in, a real tree → treatment, generated from that very tree
    work = _bundled(tmp_path / "w", "THE MAP")
    on = _runner(Manifest(knowledge_map=True), tmp_path / "b")
    ws = Workspace(path=Path("/work"), host_path=work, branch="b", base_branch="main")
    assert on._build_context(_ticket(), ws).knowledge_map != ""
    assert on.knowledge_arm() == "injected"

    # opted in, but there is nothing to map → a control, and flagged as such
    barren = tmp_path / "barren"
    (barren / "docs").mkdir(parents=True)
    (barren / "docs" / "readme.txt").write_text("no source here\n")
    none = _runner(Manifest(knowledge_map=True), tmp_path / "c")
    ws2 = Workspace(path=Path("/work"), host_path=barren, branch="b", base_branch="main")
    assert none._build_context(_ticket(), ws2).knowledge_map == ""
    assert none.knowledge_arm() == "unavailable"
