"""A project can say what it IS, and the platform treats it differently for saying so.

The defect these cover is not a crash. It is a sentence that used to be true of the whole
platform — `_org_defaults` injected every framework guideline *"into EVERY job regardless of
project"* — and whose consequence was that a throwaway proof-of-concept and a regulated bank's
legacy monolith received the same twelve engineering rules and the same TDD mandate.

Three properties are load-bearing and each has a test that fails if it is lost:

  1. WITH NO PROFILE NOTHING MOVES. A dimension that quietly re-rules existing projects is a
     migration disguised as a feature.
  2. A NAME THAT DOES NOT RESOLVE IS A HOLD. Degrading to "no profile" runs a regulated project
     under generic rules exactly when the wiring is wrong.
  3. THE SET IS OPEN AND A PROFILE MAY ONLY TIGHTEN THE GATE. An enum is wrong at the first
     client with a nature nobody anticipated; a profile that could loosen is a hole.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

from openfactory.contracts import (
    Component,
    Manifest,
    RunResult,
    Ticket,
    ValidationResult,
)
from openfactory.contracts.profile import Profile, RiskPolicy
from openfactory.contracts.state import RiskLevel
from openfactory.orchestrator import context as ctx
from openfactory.orchestrator.merge_policy import should_auto_merge
from openfactory.policy import profiles as prof
from openfactory.policy.conformance import profile_gate_reason

_PASS = [ValidationResult(name="test", command="t", exit_code=0, passed=True)]


def _result(**kw) -> RunResult:
    base = dict(ticket_id="#1", state="pr_open", validations=_PASS)
    base.update(kw)
    return RunResult(**base)


def _write(repo: Path, name: str, body: dict) -> None:
    """Lay a profile out exactly the way `docs/project.yaml.example` tells a client to.

    THE TESTS TAKE THE CHECKOUT ROOT, not the profiles directory, because that is the contract a
    client has to get right. An earlier version of this helper wrote to `tmp_path / "profiles"`
    and passed `project_dir=tmp_path`, which made every test pass against a layout the
    documentation never described — the one thing nothing in the repo pinned.
    """
    d = repo / ".openfactory" / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")


# ── the set is open, and it composes ────────────────────────────────────────────────────────────


def test_a_profile_name_the_core_never_heard_of_resolves_from_the_projects_own_layer(tmp_path):
    """The failure this refuses is an enum. `poc | legacy | greenfield` is wrong at the first
    client with a nature nobody anticipated, so a name the core has never seen must work."""
    _write(tmp_path, "insurance-mainframe-2003", {
        "name": "insurance-mainframe-2003", "summary": "a nature nobody anticipated"})

    resolved = prof.resolve_profile("insurance-mainframe-2003", project_dir=tmp_path)

    assert resolved is not None
    assert resolved.name == "insurance-mainframe-2003"
    assert resolved.summary == "a nature nobody anticipated"


def test_the_projects_own_layer_wins_over_the_shipped_example(tmp_path):
    """The opposite of `role_prompt`'s supply-chain rule, on purpose: there the overriding layer
    is a third-party ADD-ON, here it is the client's own repository declaring their own policy."""
    _write(tmp_path, "prototype", {"name": "prototype", "summary": "ours, not yours"})

    resolved = prof.resolve_profile("prototype", project_dir=tmp_path)

    assert resolved is not None
    assert resolved.summary == "ours, not yours"


def test_extends_composes_and_the_leaf_wins(tmp_path):
    _write(tmp_path, "base", {
        "name": "base", "summary": "base", "guidelines": {"waive": ["tdd.md"]}})
    _write(tmp_path, "leaf", {
        "name": "leaf", "extends": "base", "summary": "leaf"})

    resolved = prof.resolve_profile("leaf", project_dir=tmp_path)

    assert resolved is not None
    assert resolved.names == ("base", "leaf")          # base first — the leaf is applied last
    assert resolved.summary == "leaf"
    # accumulated, never un-waived: a leaf cannot resurrect what its base dropped, or the strength
    # of a class would depend on the order two authors happened to write their files in.
    assert resolved.waived_guidelines() == ("tdd.md",)


def test_a_cycle_in_extends_is_refused_rather_than_walked(tmp_path):
    _write(tmp_path, "a", {"name": "a", "extends": "b"})
    _write(tmp_path, "b", {"name": "b", "extends": "a"})

    with pytest.raises(prof.ProfileError, match="cycle"):
        prof.resolve_profile("a", project_dir=tmp_path)


def test_extends_nested_too_deep_is_refused(tmp_path):
    for i in range(6):
        _write(tmp_path, f"p{i}", {"name": f"p{i}", "extends": f"p{i + 1}"})
    _write(tmp_path, "p6", {"name": "p6"})

    with pytest.raises(prof.ProfileError, match="nested deeper"):
        prof.resolve_profile("p0", project_dir=tmp_path)


# ── a name that does not resolve is a hold, not a shrug ─────────────────────────────────────────


def test_a_profile_that_does_not_resolve_raises_rather_than_degrading_to_none(tmp_path):
    """THE FAILURE THIS EXISTS FOR. Reading an unresolvable profile as "no profile" would run a
    project that believes it is regulated under the generic rules, silently."""
    with pytest.raises(prof.ProfileError) as exc:
        prof.resolve_profile("regulated-by-a-name-nobody-wrote", project_dir=tmp_path)

    # the message has to be actionable: where it looked, and what IS available here
    assert "regulated-by-a-name-nobody-wrote" in str(exc.value)
    assert "Looked in" in str(exc.value)


def test_declaring_no_profile_is_ordinary_and_is_not_the_same_fact(tmp_path):
    """`declares_nothing` versus `undeclared_paths`, one layer up: not naming a class is a
    legitimate configuration, and it is not the same as naming one that could not be found."""
    assert prof.resolve_profile(None, project_dir=tmp_path) is None
    assert prof.resolve_profile("   ", project_dir=tmp_path) is None


def test_an_empty_profile_file_is_refused_rather_than_read_as_no_opinion(tmp_path):
    d = tmp_path / ".openfactory" / "profiles"
    d.mkdir(parents=True)
    (d / "hollow.yaml").write_text("# nothing but a comment\n", encoding="utf-8")

    with pytest.raises(prof.ProfileError, match="empty"):
        prof.resolve_profile("hollow", project_dir=tmp_path)


# ── the guidelines: the one thing a profile may take away ───────────────────────────────────────


def test_with_no_profile_the_baseline_is_exactly_what_it_always_was(tmp_path):
    """Property 1. Existing projects must not move."""
    before = ctx._org_defaults()
    assert before, "the framework ships a baseline; a test that asserts nothing is not a test"
    assert ctx._org_defaults(None, tmp_path) == before


def test_a_prototype_stops_receiving_the_tdd_mandate_and_keeps_the_rest(tmp_path):
    """THE HEADLINE. This is the POC and the bank ceasing to be the same project."""
    baseline_names = sorted(p.name for p in ctx.ORG_DEFAULTS_DIR.glob("*.md"))
    assert "tdd.md" in baseline_names and "engineering.md" in baseline_names

    resolved = prof.resolve_profile("prototype")           # the shipped worked example
    assert resolved is not None
    injected = ctx._org_defaults(resolved, tmp_path)

    tdd = (ctx.ORG_DEFAULTS_DIR / "tdd.md").read_text()[:100]
    engineering = (ctx.ORG_DEFAULTS_DIR / "engineering.md").read_text()[:100]
    assert not any(doc.startswith(tdd) for doc in injected), "tdd.md was waived and still arrived"
    assert any(doc.startswith(engineering) for doc in injected), "the rest of the baseline is gone"
    assert len(injected) == len(baseline_names) - 1


def test_waiving_a_name_the_baseline_does_not_have_changes_nothing_and_says_so(tmp_path, caplog):
    """The expensive silence: an operator believing the class is looser than it is."""
    p = Profile.model_validate({"name": "typo", "guidelines": {"waive": ["tdd.markdown"]}})
    resolved = prof.ResolvedProfile([p])

    with caplog.at_level("WARNING"):
        injected = ctx._org_defaults(resolved, tmp_path)

    assert len(injected) == len(list(ctx.ORG_DEFAULTS_DIR.glob("*.md")))
    assert "tdd.markdown" in caplog.text


def test_a_replacement_that_is_not_in_the_checkout_keeps_the_frameworks_own(tmp_path, caplog):
    """A replacement that is not there must not SUBTRACT: the project asked for a different rule,
    not for no rule, and honouring half of that drops a baseline standard on a bad path."""
    p = Profile.model_validate(
        {"name": "housestyle", "guidelines": {"replace": {"tdd.md": "docs/our-tdd.md"}}})
    resolved = prof.ResolvedProfile([p])

    with caplog.at_level("WARNING"):
        injected = ctx._org_defaults(resolved, tmp_path)

    tdd = (ctx.ORG_DEFAULTS_DIR / "tdd.md").read_text()[:100]
    assert any(doc.startswith(tdd) for doc in injected)
    assert "docs/our-tdd.md" in caplog.text


def test_a_replacement_that_is_there_substitutes_whole(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "our-tdd.md").write_text("OUR test-first rules", encoding="utf-8")
    p = Profile.model_validate(
        {"name": "housestyle", "guidelines": {"replace": {"tdd.md": "docs/our-tdd.md"}}})

    injected = ctx._org_defaults(prof.ResolvedProfile([p]), tmp_path)

    assert "OUR test-first rules" in injected
    tdd = (ctx.ORG_DEFAULTS_DIR / "tdd.md").read_text()[:100]
    assert not any(doc.startswith(tdd) for doc in injected)


def test_extend_appends_the_projects_own_content_last(tmp_path):
    """Order is weight in a prompt, and the project's own content earning the last position is
    the point."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "house.md").write_text("HOUSE RULE", encoding="utf-8")
    p = Profile.model_validate({"name": "x", "guidelines": {"extend": ["docs/house.md"]}})

    injected = ctx._org_defaults(prof.ResolvedProfile([p]), tmp_path)

    assert injected[-1] == "HOUSE RULE"


# ── risk becomes an axis, and it may only tighten ───────────────────────────────────────────────


def test_a_profile_may_only_strengthen_the_merge_gate_never_weaken_it():
    """There is no value here that would loosen, and that asymmetry is the design."""
    with pytest.raises(ValueError, match="only 'human'"):
        RiskPolicy.model_validate({"merge": "auto"})


def test_a_replacement_that_names_nothing_is_refused_at_validation():
    """A blank path lands in the "replacement is not there" branch — the right outcome — but the
    warning then reads `replaces 'tdd.md' with ''`, which sends somebody to read OUR code."""
    with pytest.raises(ValueError, match="name nothing"):
        Profile.model_validate({"name": "x", "guidelines": {"replace": {"tdd.md": "  "}}})


def test_a_filename_and_a_declared_name_may_not_diverge(tmp_path):
    """`profiles/bank.yaml` declaring `name: regulated` resolves under `bank` and then reports
    `regulated` in `names` — the field a PR body prints so a reader sees the composition. The
    reader would be shown a name the manifest never wrote."""
    _write(tmp_path, "bank", {"name": "regulated", "summary": "ours"})

    with pytest.raises(prof.ProfileError, match="filed as"):
        prof.resolve_profile("bank", project_dir=tmp_path)


def test_the_strictest_merge_opinion_in_the_chain_survives(tmp_path):
    _write(tmp_path, "base", {"name": "base", "risk": {"high": {"merge": "human"}}})
    _write(tmp_path, "leaf", {"name": "leaf", "extends": "base"})

    resolved = prof.resolve_profile("leaf", project_dir=tmp_path)

    assert resolved is not None
    # the leaf said nothing about merge; extending a stricter base can never relax it
    assert resolved.risk_policy(RiskLevel.HIGH).merge == "human"


def test_gates_field_strips_blanks_and_defaults_empty():
    """The same accident `GuidelinePolicy._no_blanks` guards on a sibling field."""
    p = RiskPolicy.model_validate({"gates": ["security", "  ", "test"]})
    assert p.gates == ["security", "test"]
    assert RiskPolicy().gates == []


def test_gates_accumulate_across_the_chain_and_do_not_inherit_across_levels(tmp_path):
    _write(tmp_path, "base", {"name": "base", "risk": {"high": {"gates": ["security"]}}})
    _write(tmp_path, "leaf", {
        "name": "leaf", "extends": "base", "risk": {"high": {"gates": ["security", "test"]}}})

    resolved = prof.resolve_profile("leaf", project_dir=tmp_path)

    assert resolved is not None
    # unioned and de-duplicated, not doubled because both layers name `security`
    assert resolved.risk_policy(RiskLevel.HIGH).gates == ["security", "test"]
    # NOT inherited to a level neither layer named — the same discipline `merge` follows
    assert resolved.risk_policy(RiskLevel.NORMAL).gates == []


def test_a_profile_naming_a_gate_no_layer_defines_holds_the_job_with_a_voice(tmp_path):
    """THE FIELD THAT WAS DROPPED, AND THE REASON KEPT AS A TEST. `gates:` was accumulated and
    read by nothing once — no validation runner, no floor merge, no conformance check — so
    `regulated.yaml` promised more evidence and delivered none, and `gates: [scurity]` resolved
    silently. It arrives now with a consumer AND a refusal: a role no layer defines holds the job
    before any agent call, the same way an unresolvable profile name does.

    `lint`, NOT `security`, IS THE ROLE NAMED HERE — deliberately, so this test does not depend on
    what `org_defaults/floor.yaml` happens to ship advisory today."""
    _write(tmp_path, "wishful", {"name": "wishful", "risk": {"high": {"gates": ["lint"]}}})
    resolved = prof.resolve_profile("wishful", project_dir=tmp_path)

    reason = profile_gate_reason(Manifest(), resolved)

    assert reason is not None
    assert "lint" in reason
    assert "high" in reason
    assert "wishful" in reason


def test_the_undefined_role_check_covers_every_level_not_only_the_one_a_diff_would_hit(tmp_path):
    """A typo at `normal` must not wait for the first HIGH-risk ticket to be the one that catches
    it — there is no diff yet at this point in the job, so every level the profile declares is
    checked, not only whichever one today's change happens to land on."""
    _write(tmp_path, "normal-typo", {
        "name": "normal-typo", "risk": {"normal": {"gates": ["lint"]}}})
    resolved = prof.resolve_profile("normal-typo", project_dir=tmp_path)

    reason = profile_gate_reason(Manifest(), resolved)

    assert reason is not None
    assert "lint" in reason
    assert "normal" in reason


def test_profile_gate_reason_is_a_no_op_with_no_profile_or_no_gates(tmp_path):
    """Property 1, for the new check specifically: with no profile — or a profile that names no
    gate at all, like the shipped `prototype` — nothing about this check may move."""
    assert profile_gate_reason(Manifest(), None) is None

    resolved = prof.resolve_profile("prototype")           # ships with no `risk:` block at all
    assert resolved is not None
    assert profile_gate_reason(Manifest(), resolved) is None

    _write(tmp_path, "merge-only", {"name": "merge-only", "risk": {"high": {"merge": "human"}}})
    merge_only = prof.resolve_profile("merge-only", project_dir=tmp_path)
    assert profile_gate_reason(Manifest(), merge_only) is None


def test_promoted_gates_is_level_scoped_and_none_promotes_nothing(tmp_path):
    _write(tmp_path, "regulated-x", {"name": "regulated-x", "risk": {"high": {"gates": ["lint"]}}})
    resolved = prof.resolve_profile("regulated-x", project_dir=tmp_path)

    assert resolved is not None
    assert resolved.promoted_gates(None) == frozenset()
    assert resolved.promoted_gates(RiskLevel.NORMAL) == frozenset()
    assert resolved.promoted_gates(RiskLevel.HIGH) == frozenset({"lint"})


def test_a_promoted_gate_becomes_blocking_and_an_unpromoted_one_stays_advisory():
    """THE HEADLINE CASE THIS CHANGE EXISTS FOR — what makes `regulated.yaml`'s promise checkable
    rather than asserted. The deployment floor ships `security` ADVISORY on purpose
    (`org_defaults/floor.yaml`, C-37, so a noisy scanner does not become the first thing a client
    disables); a profile naming `gates: [security]` at the attempt's risk level is what turns a
    finding that would only ever be reported into one that blocks the merge and feeds the repair
    loop. Deliberately coupled to the REAL floor rather than a hand-built gate, because this is
    the exact path `regulated.yaml` relies on."""
    from openfactory.orchestrator.machine import JobRunner

    holder = type("_H", (), {
        "manifest": Manifest(),  # inherits `security` ADVISORY from the real floor, nothing else
        "sandbox": type("_S", (), {"run": lambda self, workspace=None, command=None,
                                    timeout=None: (1, "a finding")})(),
        "_emit": lambda self, *a, **kw: None,
    })()

    promoted = JobRunner._run_validations(
        holder, None, [], None, promoted_gates=frozenset({"security"}))
    unpromoted = JobRunner._run_validations(
        holder, None, [], None, promoted_gates=frozenset())

    assert {vr.name: vr.advisory for vr in promoted}["security"] is False
    assert {vr.name: vr.advisory for vr in unpromoted}["security"] is True


def test_a_level_a_profile_says_nothing_about_permits_nothing_extra(tmp_path):
    """Absence is "this class has no opinion at this level", never "permits everything here"."""
    _write(tmp_path, "quiet", {"name": "quiet"})
    resolved = prof.resolve_profile("quiet", project_dir=tmp_path)

    assert resolved is not None
    assert resolved.requires_human(RiskLevel.HIGH) is False
    assert resolved.risk_policy(RiskLevel.NORMAL).merge is None


def test_a_class_does_not_re_gate_a_project_that_simply_does_not_use_components(tmp_path):
    """THE DESIGN ERROR THIS CAUGHT, kept as a test because it was not obvious. Reading `None` as
    HIGH looks like prudence and is the mistake `risk.py` names in full: it *"would send every
    simple project on `merge_policy: auto` to a human for ever, which is the fix doing more damage
    than the defect"*. The dangerous half — a change outside every DECLARED component — is gated
    before the profile is asked, by `RiskAssessment.needs_a_human`."""
    _write(tmp_path, "regulated-x", {
        "name": "regulated-x", "risk": {"high": {"merge": "human"}}})
    resolved = prof.resolve_profile("regulated-x", project_dir=tmp_path)

    assert resolved is not None
    assert resolved.requires_human(None) is False
    assert resolved.requires_human(RiskLevel.HIGH) is True


# ── the merge gate actually reads it ────────────────────────────────────────────────────────────


def test_the_class_reaches_the_agent_through_build_context_not_only_the_helper(tmp_path):
    """THE WIRING, AND THE MUTATION THAT SURVIVED WITHOUT THIS. Every guideline test above calls
    `_org_defaults` directly, so a `build_context` that resolved the class and then asked for the
    unfiltered baseline passed all of them — the POC and the bank identical again, with the whole
    mechanism present and simply not plugged in."""
    (tmp_path / ".openfactory").mkdir(parents=True)
    resolved = prof.resolve_profile("prototype")
    ticket = Ticket(id="#1", title="t", objective="o", repo="acme/app")

    built = ctx.build_context(Manifest(profile="prototype"), tmp_path, ticket, profile=resolved)

    tdd = (ctx.ORG_DEFAULTS_DIR / "tdd.md").read_text()[:100]
    engineering = (ctx.ORG_DEFAULTS_DIR / "engineering.md").read_text()[:100]
    assert not any(doc.startswith(tdd) for doc in built.guidelines), (
        "the class was resolved and the agent still received the mandate it waives")
    assert any(doc.startswith(engineering) for doc in built.guidelines)


def test_the_class_is_the_ONLY_reason_a_normal_change_goes_to_a_person(tmp_path):
    """THE SECOND MUTATION THAT SURVIVED. The high-risk case below proves nothing on its own: a
    HIGH component is already human-gated by `RiskAssessment`, so deleting the profile check
    entirely left that assertion green. This is the case where the class is the only thing
    standing between the change and an automatic merge."""
    _write(tmp_path, "four-eyes", {
        "name": "four-eyes", "risk": {"normal": {"merge": "human"}}})
    resolved = prof.resolve_profile("four-eyes", project_dir=tmp_path)
    m = Manifest(merge_policy="auto", profile="four-eyes",
                 components={"app": Component(path="app/**", stack="python")})
    result = _result(touched_components=["app"])

    # the same manifest and the same change, with the class removed, merges by itself
    assert should_auto_merge(Manifest(merge_policy="auto",
                                      components={"app": Component(path="app/**",
                                                                   stack="python")}),
                             result) is True
    assert should_auto_merge(m, result, profile=resolved) is False


def test_the_class_sends_a_high_risk_change_to_a_person_even_on_auto(tmp_path):
    m = Manifest(merge_policy="auto", profile="regulated",
                 components={"infra": Component(path="infra/**", stack="terraform",
                                                risk=RiskLevel.HIGH)})
    resolved = prof.resolve_profile("regulated")           # the shipped worked example

    # without the class this is exactly the merge the platform already refuses on `high`; the
    # case that matters is a NORMAL component, which auto-merges today and still does.
    normal = Manifest(merge_policy="auto", profile="regulated",
                      components={"app": Component(path="app/**", stack="python")})
    assert should_auto_merge(normal, _result(touched_components=["app"]),
                             profile=resolved) is True
    assert should_auto_merge(m, _result(touched_components=["infra"]), profile=resolved) is False


def test_a_manifest_that_names_a_class_the_caller_did_not_resolve_does_not_auto_merge():
    """The closed direction. Reading an unresolved profile as "no extra opinion" would auto-merge
    a regulated project under generic rules precisely when the wiring is wrong."""
    m = Manifest(merge_policy="auto", profile="regulated")

    assert should_auto_merge(m, _result()) is False
    assert should_auto_merge(m, _result(), profile=prof.resolve_profile("regulated")) is True


def test_a_manifest_with_no_class_is_untouched_by_any_of_this():
    """Property 1 at the merge gate."""
    assert should_auto_merge(Manifest(merge_policy="auto"), _result()) is True


# ── the manifest ────────────────────────────────────────────────────────────────────────────────


def test_the_manifest_accepts_a_profile_and_defaults_to_none():
    assert Manifest().profile is None
    assert Manifest(profile="prototype").profile == "prototype"


def test_the_core_ships_worked_examples_rather_than_only_a_mechanism():
    """A mechanism with no example is a feature nobody can start from — and the packaging trap
    that hides it is documented in `pyproject.toml`, one directory shallower."""
    assert set(prof.available_profiles()) >= {"prototype", "regulated"}


# ── REACHABILITY: the defect this suite could not see ───────────────────────────────────────────
#
# Every test above supplies the resolved profile itself, so all of them passed while the feature
# had NO PRODUCTION CALLER: `build_context` gained a `profile` parameter none of its callers
# passed, `should_auto_merge` gained one `machine.py` did not pass, and the only branch that fired
# in production was `if manifest.profile and profile is None: return False` — which turned
# declaring ANY class into a permanent hold, while the guideline half stayed inert. A prototype got
# the TDD mandate it waives AND lost auto-merge for ever. Reported by review on PR #17.
#
# These are the guards that fail when the wiring goes away again. The `ast` idiom is this repo's
# own, from `test_the_language_reaches_every_unprompted_surface.py`.


def _machine_source() -> ast.Module:
    from openfactory.orchestrator import machine

    return ast.parse(Path(machine.__file__).read_text(encoding="utf-8"))


def _calls_named(tree: ast.Module, name: str) -> list[ast.Call]:
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and (getattr(n.func, "id", None) == name or getattr(n.func, "attr", None) == name)]


def test_the_machine_resolves_the_class_at_all():
    """Without this call the whole mechanism is unreachable outside the test suite."""
    assert _calls_named(_machine_source(), "resolve_profile"), (
        "nothing in machine.py resolves the manifest's profile — the feature has no production "
        "caller and every behavioural test above passes anyway")


def test_every_context_the_machine_builds_carries_the_class():
    """A `build_context` call without `profile=` is a job whose agent never hears about the class."""
    calls = _calls_named(_machine_source(), "build_context")

    assert calls, "machine.py no longer builds a context — this guard is measuring nothing"
    for call in calls:
        assert any(kw.arg == "profile" for kw in call.keywords), (
            f"build_context at machine.py:{call.lineno} does not pass `profile=`, so the "
            f"guidelines the class waives are injected anyway")


def test_the_merge_gate_the_machine_calls_is_told_the_class():
    """THE INVERSION. Without `profile=`, `manifest.profile and profile is None` is always true and
    declaring any class disables auto-merge for that project for ever."""
    calls = _calls_named(_machine_source(), "should_auto_merge")

    assert calls, "machine.py no longer decides the merge — this guard is measuring nothing"
    for call in calls:
        assert any(kw.arg == "profile" for kw in call.keywords), (
            f"should_auto_merge at machine.py:{call.lineno} does not pass `profile=`, so every "
            f"project that declares a class is permanently human-gated")


def test_a_class_that_does_not_resolve_holds_the_job_with_a_voice(tmp_path):
    """A hold nobody is told about is the shrug this design refuses, wearing a hold's clothes.
    The failure has to reach the ticket, before the agent runs — not as a silent `False` at PR
    time, in the same branch as an ordinary ready-for-review PR."""
    src = Path(_machine_file()).read_text(encoding="utf-8")
    block = src[src.index("try:\n            self._profile = resolve_profile("):][:600]

    assert "ProfileError" in block, "an unresolvable class must be caught, not raised at a client"
    assert "self._emit(" in block, "the hold must say something — a silent hold is a shrug"
    assert "_hold(" in block, "an unresolvable class must stop the job, not colour a later gate"


def test_the_machine_checks_the_profiles_gates_before_any_agent_call():
    """Without this call, a profile naming an undefined gate role resolves silently and promotes
    nothing — the exact defect `gates:` shipped with once, one call site later."""
    assert _calls_named(_machine_source(), "profile_gate_reason"), (
        "nothing in machine.py checks the profile's gates against what the manifest can run")


def test_an_undefined_gate_role_holds_the_job_with_a_voice():
    """Mirrors `test_a_class_that_does_not_resolve_holds_the_job_with_a_voice`: a profile that
    promises a gate no layer can run must stop the job and say why, not silently promote
    nothing."""
    src = Path(_machine_file()).read_text(encoding="utf-8")
    block = src[src.index("if (gate_issue := profile_gate_reason("):][:400]

    assert "self._emit(" in block, "the hold must say something — a silent hold is a shrug"
    assert "_hold(" in block, "an undefined gate role must stop the job, not colour a later gate"


def test_the_class_reaches_a_real_runners_context(tmp_path):
    """The behavioural half of the reachability guards above: a JobRunner carrying a resolved
    class builds a context without the mandate that class waives."""
    from openfactory.orchestrator.machine import JobRunner

    runner = JobRunner(tracker=object(), forge=object(), agent=object(), sandbox=object(),
                       manifest=Manifest(profile="prototype"), repo_path=tmp_path)
    runner._profile = prof.resolve_profile("prototype")

    built = runner._build_context(Ticket(id="#1", title="t", objective="o", repo="acme/app"))

    tdd = (ctx.ORG_DEFAULTS_DIR / "tdd.md").read_text()[:100]
    assert not any(doc.startswith(tdd) for doc in built.guidelines)


def _machine_file() -> str:
    from openfactory.orchestrator import machine

    return machine.__file__
