"""The diff is the source of truth for what a ticket touched, what runs, and whether it grew too
big (ADR-0001 D-6; F-03, #28).

WHY THIS FILE EXISTS. `resolve_touched_components` and `applicable_validations` are load-bearing —
called from three sites in `orchestrator/machine.py`, on every job this platform runs — and had
ZERO direct tests before this file. "Language diversity proves almost nothing... repository shape
is the opposite" (F-03's own words): these two functions ARE the repository-shape logic, and they
had never been exercised by a real diff.

`scope_explosion` did not exist until this same change. `max_touched_components` and
`max_diff_lines` have sat on the manifest since before ADR-0013's transitional plan-gate rewrite,
commented "abort to refinement past this" — and nothing read them. A field with a promise in its
own comment and no code behind it is the shape this house calls a hole nobody opened on purpose.
ADR-0002 §3 names exactly this mechanism as D-6's post-diff complement to the pre-execution plan
gate; it is implemented here, in the same module as its two siblings, for the same reason they
belong together — all three answer "what did the diff actually do", not "what was planned".
"""

from __future__ import annotations

from openfactory.contracts import Component, Manifest
from openfactory.orchestrator.validation import (
    applicable_validations,
    resolve_touched_components,
    scope_explosion,
)


def _manifest(**kw) -> Manifest:
    return Manifest(
        components={
            "api": Component(path="services/api", stack="python",
                             validate={"lint": "ruff check services/api"}),
            "worker": Component(path="services/worker", stack="python"),
            "functions": Component(path="functions", stack="python"),
        },
        **kw,
    )


# ── resolve_touched_components ──────────────────────────────────────────────────────────────────

def test_a_file_inside_a_component_touches_it():
    m = _manifest()
    assert resolve_touched_components(["services/api/routes.py"], m) == ["api"]


def test_a_diff_across_two_components_touches_both():
    m = _manifest()
    touched = resolve_touched_components(
        ["services/api/routes.py", "services/worker/queue.py"], m)
    assert set(touched) == {"api", "worker"}


def test_a_file_OUTSIDE_every_component_touches_nothing():
    m = _manifest()
    assert resolve_touched_components(["README.md"], m) == []


def test_the_component_PATH_ITSELF_as_a_changed_file_still_counts():
    """A component whose path names one file rather than a directory (e.g. a single-file
    component) — the diff entry equals the path exactly, with no trailing segment."""
    m = Manifest(components={"config": Component(path="config.py", stack="python")})
    assert resolve_touched_components(["config.py"], m) == ["config"]


def test_a_sibling_directory_that_merely_SHARES_A_PREFIX_is_not_touched():
    """`services/api` must not match `services/api2/...` — string prefix matching without a
    boundary check would silently blame the wrong component for someone else's change."""
    m = _manifest()
    assert resolve_touched_components(["services/api2/routes.py"], m) == []


def test_an_untracked_component_produces_no_crash_and_no_match():
    """An empty `components` dict (a project with no shape declared) must resolve to nothing,
    not raise — the repo-wide validations still run via `applicable_validations`."""
    m = Manifest(components={})
    assert resolve_touched_components(["anything.py"], m) == []


# ── applicable_validations — the precedence D-6 documents ────────────────────────────────────────

def test_a_touched_components_STACK_PRESET_contributes_its_validate_commands():
    m = _manifest()
    cmds = applicable_validations(["worker"], m)
    # the python preset's own commands, whatever they are, must be present
    from openfactory.policy import load_preset

    assert set(load_preset("python").get("validate", {})).issubset(cmds)


def test_REPO_WIDE_validation_overlays_the_preset():
    """Precedence: preset < repo-wide < component-specific (the module's own docstring)."""
    m = _manifest(validate={"test": "pytest -q REPO-WIDE"})
    cmds = applicable_validations(["api"], m)
    assert cmds["test"] == "pytest -q REPO-WIDE"


def test_COMPONENT_SPECIFIC_wins_over_repo_wide():
    m = _manifest(validate={"lint": "ruff check REPO-WIDE"})
    cmds = applicable_validations(["api"], m)
    # "api" declares its own `lint`, which must win over the repo-wide value above
    assert cmds["lint"] == "ruff check services/api"


def test_an_UNTOUCHED_components_validation_never_runs():
    m = _manifest()
    cmds = applicable_validations(["api"], m)
    assert "worker" not in cmds  # the worker component contributes nothing when not touched


def test_no_touched_components_still_runs_the_repo_wide_gate():
    """A diff outside every declared component (docs, config) is not exempt from validation —
    the repo-wide commands are the floor everything stands on."""
    m = _manifest(validate={"test": "pytest -q"})
    cmds = applicable_validations([], m)

    assert cmds["test"] == "pytest -q"
    # AND THE DEPLOYMENT'S FLOOR IS HERE TOO, which is the strongest form of this test's own
    # thesis. `org_defaults/floor.yaml` exists so a required role runs on a diff that reaches no
    # declared component — precisely the diff this test is about — and this map is the one the job
    # executes. Asserted as an exact set, not a subset: an inherited gate that quietly stopped
    # arriving would otherwise read as a pass.
    from openfactory.policy.presets import org_default_validation

    assert set(cmds) == {"test"} | set(org_default_validation() or {})


# ── scope_explosion — D-6's post-diff catch, previously unimplemented ────────────────────────────

_SMALL_DIFF = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n+one line\n"


def _diff_of(changed_lines: int) -> str:
    body = "\n".join(f"+line {n}" for n in range(changed_lines))
    return f"diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n{body}\n"


def test_neither_threshold_set_means_this_project_opted_out():
    m = _manifest()  # max_touched_components and max_diff_lines both None
    assert scope_explosion(["api", "worker", "functions"], _diff_of(10_000), m) == ""


def test_touching_more_components_than_the_cap_is_refused():
    m = _manifest(max_touched_components=1)
    reason = scope_explosion(["api", "worker"], _SMALL_DIFF, m)
    assert "2 components" in reason and "api" in reason and "worker" in reason
    assert "limit of 1" in reason


def test_touching_EXACTLY_the_cap_is_fine():
    """The threshold is a LIMIT, not a target one under — `> cap`, never `>= cap`."""
    m = _manifest(max_touched_components=2)
    assert scope_explosion(["api", "worker"], _SMALL_DIFF, m) == ""


def test_touching_fewer_components_than_the_cap_is_fine():
    m = _manifest(max_touched_components=5)
    assert scope_explosion(["api"], _SMALL_DIFF, m) == ""


def test_a_diff_past_the_LINE_cap_is_refused_even_in_ONE_component():
    """The component-count threshold alone would miss this: one function nobody split, all
    inside a single component, that a person still cannot review as one changeset."""
    m = _manifest(max_diff_lines=50)
    reason = scope_explosion(["api"], _diff_of(51), m)
    assert "51 lines" in reason and "limit of 50" in reason


def test_a_diff_AT_the_line_cap_is_fine():
    m = _manifest(max_diff_lines=50)
    assert scope_explosion(["api"], _diff_of(50), m) == ""


def test_FILE_HEADERS_are_never_counted_as_changed_lines():
    """`+++`/`---` share the `+`/`-` prefix with an added/removed blank line. Counting them would
    over-report by exactly the number of files touched — worst on a diff that adds many small
    files, which is precisely the scope-explosion shape this function exists to catch honestly."""
    diff = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n+one\n"
        "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n+two\n"
    )
    m = _manifest(max_diff_lines=2)
    assert scope_explosion([], diff, m) == "", "the four header lines were counted as content"


def test_the_component_check_is_reported_even_when_the_line_count_is_fine():
    """Both thresholds are independent gates — either alone is sufficient to refuse."""
    m = _manifest(max_touched_components=1, max_diff_lines=10_000)
    reason = scope_explosion(["api", "worker"], _SMALL_DIFF, m)
    assert "components" in reason


def test_the_line_check_still_fires_when_the_component_count_is_fine():
    m = _manifest(max_touched_components=10, max_diff_lines=1)
    reason = scope_explosion(["api"], _diff_of(2), m)
    assert "lines" in reason


# ── glob paths resolve — found live by the first fx-mono run (F-03) ─────────────────────────────

def test_a_component_declared_as_a_GLOB_is_visible():
    """The docs' own example shape (`services/api/**`) resolved to NOTHING: the resolver treated
    the glob as a literal prefix, so every manifest that followed the documentation had invisible
    components — the per-component gates never ran and the repo-wide one masked it. Caught by the
    fixture run, which is precisely what F-03 exists for."""
    m = Manifest(components={
        "functions": Component(path="functions/**", stack="python"),
        "api": Component(path="services/api/**", stack="python"),
    })

    assert resolve_touched_components(["functions/thumbnail.py"], m) == ["functions"]
    assert resolve_touched_components(["services/api/routes.py"], m) == ["api"]
    assert resolve_touched_components(["services/api2/routes.py"], m) == []


def test_a_glob_component_drives_its_own_validation():
    """The consequence that mattered on the live run: the component's `validate:` must win for
    its area once the component is visible at all."""
    m = Manifest(
        validate={"test": "pytest -q"},
        components={"functions": Component(path="functions/**", stack="python",
                                           validate={"test": "pytest -q functions"})},
    )

    touched = resolve_touched_components(["functions/thumbnail.py"], m)
    assert applicable_validations(touched, m)["test"] == "pytest -q functions"


def test_bare_prefix_paths_did_not_move():
    m = Manifest(components={"api": Component(path="services/api", stack="python")})

    assert resolve_touched_components(["services/api/routes.py"], m) == ["api"]
    assert resolve_touched_components(["services/api2/x.py"], m) == []
