"""The `preview` axis: a runtime is a row, born with two, open to a third (#265 slice 2; ADR-0050
D11; the design's §2.4 and §5.1).

What these tests hold:

- THE KIND IS THE DEPLOYMENT'S. `OPENFACTORY_PREVIEW_RUNTIME` names it and `none` is what a
  deployment that says nothing gets — never a runtime chosen from a file the agent can write.
- `none` REFUSES BY NAME. Every door that asks gets the same sentence; a deployment reported ready
  for previews that then runs nothing is the silence this platform exists to end.
- A STRANGER'S ROW IS CHECKED LIKE OURS, and what it builds must be a `PreviewRuntime` — a runtime
  that cannot `down` would leave every preview it starts running for ever.
- THE CONFORMANCE CHECK plants a plan admission would refuse and asks `up` to refuse it: a green
  built-in, a red offender.
"""

from __future__ import annotations

import pytest

from openfactory import plugins
from openfactory.adapters.preview import compose
from openfactory.adapters.preview.base import PreviewRuntime, PreviewTraits, refusals
from openfactory.adapters.preview.compose import Ran
from openfactory.adapters.preview.none import REFUSAL, NoRuntime
from openfactory.adapters.preview.registry import (
    RUNTIMES,
    _check_row,
    build_runtime,
    runtime_traits,
)
from openfactory.conformance import CHECKS, check_preview
from openfactory.preview.plan import PreviewUp


class _Point:
    def __init__(self, name, value):
        self.name, self._value = name, value

    def load(self):
        return self._value


@pytest.fixture
def installs(monkeypatch):
    def _install(*points):
        plugins.reset_cache()
        monkeypatch.setattr("importlib.metadata.entry_points",
                            lambda group=None: list(points) if group == plugins.GROUP else [])
        plugins.reset_cache()
    yield _install
    plugins.reset_cache()


class _Runs:
    """A stranger's runtime that satisfies the port — and runs WHATEVER it is handed."""

    def prerequisites(self):
        return []

    def up(self, plan):
        return PreviewUp(ok=True, services=dict(plan.expose))

    def watch(self, compose_project):
        return None

    def logs(self, compose_project, log_dir):
        return []

    def down(self, compose_project, workdir):
        return []

    def running(self):
        return []

    def prove(self, plan):
        return self.up(plan)


class _CannotDown:
    def prerequisites(self):
        return []

    def up(self, plan):
        return PreviewUp(ok=False)


# ── the axis ─────────────────────────────────────────────────────────────────────────────────────


def test_the_axis_is_published_and_born_with_two():
    assert "preview" in plugins.AXES
    assert set(RUNTIMES) == {"compose", "none"}
    assert runtime_traits("compose") == PreviewTraits(name="compose", builds=True,
                                                      reaches=("network", "loopback"))
    assert runtime_traits("none").reaches == ()
    assert isinstance(build_runtime("compose"), PreviewRuntime)
    assert isinstance(build_runtime("NONE"), NoRuntime), "the kind is read case-blind"


def test_the_deployment_names_the_kind_and_says_nothing_means_none(monkeypatch):
    from openfactory.runtime.temporal.io import default_preview_runtime

    monkeypatch.delenv("OPENFACTORY_PREVIEW_RUNTIME", raising=False)
    assert default_preview_runtime() == "none"
    monkeypatch.setenv("OPENFACTORY_PREVIEW_RUNTIME", " Compose ")
    assert default_preview_runtime() == "compose"


def test_none_refuses_by_name_at_every_door():
    rt = build_runtime("none")

    assert rt.prerequisites() == [REFUSAL]
    assert "OPENFACTORY_PREVIEW_RUNTIME=none" in REFUSAL
    assert rt.up(None).why == REFUSAL and not rt.up(None).ok
    assert rt.prove(None).why == REFUSAL
    assert (rt.watch("x"), rt.running(), rt.logs("x", "/"), rt.down("x", "/")) == (None, [], [],
                                                                                   [])


def test_an_unknown_runtime_is_refused_naming_what_is_installed(installs):
    installs(_Point("preview.acme_k8s", lambda: (PreviewTraits(name="acme_k8s", builds=True,
                                                               reaches=("network",)), _Runs)))

    with pytest.raises(ValueError) as refused:
        build_runtime("acme_k8")

    said = str(refused.value)
    assert "unknown preview runtime 'acme_k8'" in said
    assert "acme_k8s" in said and "compose" in said and "none" in said
    assert "OPENFACTORY_PREVIEW_RUNTIME" in said


def test_a_strangers_row_is_the_one_that_is_built(installs):
    installs(_Point("preview.acme_k8s", lambda: (PreviewTraits(name="acme_k8s", builds=True,
                                                               reaches=("network",)), _Runs)))

    assert isinstance(build_runtime("acme_k8s"), _Runs)
    assert runtime_traits("acme_k8s").name == "acme_k8s"


@pytest.mark.parametrize("row, said", [
    (lambda: _Runs, "must be (PreviewTraits, factory)"),
    (lambda: ("acme", _Runs), "does not start with PreviewTraits"),
    (lambda: (PreviewTraits(name="other", builds=False), _Runs), "describes 'other'"),
    (lambda: (PreviewTraits(name="acme_k8s", builds=False, reaches=("ingress",)), _Runs),
     "reaches the panel cannot route"),
])
def test_a_strangers_row_that_is_not_a_row_is_refused_in_our_words(installs, row, said):
    installs(_Point("preview.acme_k8s", row))

    with pytest.raises(TypeError, match=said.replace("(", r"\(").replace(")", r"\)")):
        build_runtime("acme_k8s")


def test_a_runtime_that_cannot_down_is_refused_rather_than_used(installs):
    installs(_Point("preview.acme_k8s", lambda: (PreviewTraits(name="acme_k8s", builds=False),
                                                 _CannotDown)))

    with pytest.raises(TypeError) as refused:
        build_runtime("acme_k8s")
    assert "'down'" in str(refused.value) and "leaves every preview it starts running" in str(
        refused.value)


def test_a_built_in_wins_a_collision(installs):
    installs(_Point("preview.compose", lambda: (PreviewTraits(name="compose", builds=True),
                                                _Runs)))

    assert not isinstance(build_runtime("compose"), _Runs)


def test_the_built_in_rows_pass_the_check_the_add_ons_are_held_to():
    for kind, row in RUNTIMES.items():
        assert _check_row(kind, row) is row


def test_an_unknown_knob_to_the_compose_row_is_a_TypeError_naming_itself():
    with pytest.raises(TypeError, match="takes no \\['cpus'\\]"):
        build_runtime("compose", cpus="4")


# ── the conformance check ────────────────────────────────────────────────────────────────────────


def test_the_check_table_carries_the_preview_port():
    assert CHECKS["preview"] == (check_preview, PreviewRuntime)


def test_both_built_in_rows_are_conformant(monkeypatch, tmp_path):
    """The compose row on a faked daemon that answers nothing is running: it reads, it downs
    nothing that is not there, and it refuses the planted plan BEFORE any docker call."""
    calls = []

    def daemon(argv, **kw):
        calls.append(list(argv))
        if list(argv[:3]) == ["docker", "network", "rm"]:
            return Ran(1, "", "Error response from daemon: network not found")
        return Ran(0, "", "")

    monkeypatch.setattr(compose, "_host", daemon)
    monkeypatch.setenv("OPENFACTORY_WORK_DIR", str(tmp_path))

    assert check_preview(build_runtime("compose", panel_container="")) == []
    assert check_preview(build_runtime("none")) == []
    assert not any(c[:2] == ["docker", "compose"] and "up" in c for c in calls), (
        f"the check brought something up: {calls}")


def test_a_runtime_that_runs_what_admission_refuses_is_named():
    findings = check_preview(_Runs())

    assert [f.rule for f in findings] == ["preview.up-refuses-what-admission-refuses"]
    assert "refusals(plan)" in findings[0].taught_by


def test_a_runtime_missing_a_method_is_refused_by_name_and_never_called():
    findings = check_preview(_CannotDown())

    assert [f.rule for f in findings] == ["preview.protocol"]
    assert "down" in findings[0].detail and "running" in findings[0].detail


def test_a_runtime_that_raises_or_answers_a_handle_is_named():
    class _Raises(_Runs):
        def running(self):
            raise RuntimeError("no socket")

        def watch(self, compose_project):
            return object()

        def down(self, compose_project, workdir):
            return ["something I did not remove"]

        def up(self, plan):
            return PreviewUp(ok=False)

    rules = [f.rule for f in check_preview(_Raises())]

    assert rules == ["preview.watch-answers-data", "preview.running-never-raises",
                     "preview.down-of-nothing-is-nothing"]


# ── the plan a row may run ───────────────────────────────────────────────────────────────────────


def test_what_the_assembler_writes_passes_the_rows_second_look(tmp_path, monkeypatch):
    from tests.test_the_shape_is_read_and_admitted import (
        S1_CFG,
        _canonical,
        _diff,
        _layout,
        _ok,
        _plan,
        _workdir,
    )

    monkeypatch.setenv("ACME_PV_DATABASE_URL", "x")
    wd = _workdir(tmp_path, "s1")
    plan = _ok(_plan(_canonical("s1", wd), S1_CFG, _layout(wd, _diff("s1"))))

    assert refusals(plan) == []
    stranger = plan.model_copy(update={"compose_project": "openfactory",
                                       "workdir": "/var/lib/openfactory-state"})
    said = " ".join(refusals(stranger))
    assert "is not a preview's" in said and "is not named after the unit" in said
