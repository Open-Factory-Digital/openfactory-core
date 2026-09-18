"""A promotion chain the deployment's box cannot walk is refused before the first card (#172).

THE DEFECT. A manifest that declares `environments:` (and `promote:`) on a deployment whose box is
local — `worktree` or `container` — passed every check before the first card: `openfactory doctor`
said `ok post_merge after a merge: the promotion chain observes …` and `openfactory conformance`
said runnable. Then, after the merge, the durable workflow promoted (`should_promote =
params.promote or bool(result.environments)`) and `_run_promotion` refused non-retryably, because
only a remote box runs the promotion phase. The refusal was honest and named the fix, but it
arrived on the one path where it costs the most: the change is on the base, the job ends failed,
`_finish_at_the_merge` never runs and the card never reaches Done.

WHAT THIS HOLDS:
  1. the doctor FAILS that manifest on a local box, before any card, with or without a deploy watch;
  2. it says the SAME words the promotion raises — compared by running both speakers, never by
     copying the sentence into the test;
  3. a remote box with the same manifest, a local box without environments, and a box nothing can
     name all read exactly as they did before;
  4. the remedy's advice loads: dropping `environments:` alone leaves `promote:` naming nothing,
     which the manifest refuses, so the remedy names both keys.
"""

from __future__ import annotations

import pytest
from vendor_addons import install

from openfactory import doctor
from openfactory.adapters.sandbox.registry import BoxTraits, no_local_adapter
from openfactory.contracts.manifest import Environment, Manifest
from tests.pinned_probes import a_fully_pinned_probe_set

LOCAL_BOXES = ("worktree", "container")

#: A synthetic REMOTE box, served through the same entry-point group a stranger's add-on uses — so
#: the "remote stays green" case asks the real registry, not a stub of it.
ORBIT = BoxTraits("orbit", remote=True, honours_image=True, idempotent=False, streams=False,
                  isolates_resources=True, transfers_state=True)


class _Point:
    def __init__(self, name, obj):
        self.name, self._obj = name, obj

    def load(self):
        return self._obj


@pytest.fixture
def orbit(monkeypatch):
    install(monkeypatch, declared_rows=False,
            extra=(_Point("box.orbit",
                          lambda: (ORBIT, no_local_adapter("orbit"), lambda **kw: None)),))


def _manifest(**over) -> Manifest:
    """A REAL manifest that meets the floor, so the only thing a finding can be about is `over`."""
    return Manifest.model_validate({
        "version": 1, "base_branch": "main",
        "validate": {"test": "pytest -q",
                     "security": {"command": "bandit -q -r .", "advisory": True}},
        **over,
    })


CHAIN = {"environments": {"staging": Environment(deploy_ref="staging"),
                          "prod": Environment(deploy_ref="prod")},
         "promote": ["staging", "prod"]}
WATCH = {"post_merge_deploy": {"workflow": "deploy.yml", "env": "dev"}}


def _post_merge(manifest: Manifest, box: str | None) -> doctor.Finding:
    """The `post_merge` finding the REAL `diagnose` renders, every other probe pinned green."""
    probes = a_fully_pinned_probe_set(manifest=lambda: manifest,
                                      sandbox=(lambda: box) if box is not None else None)
    report = doctor.diagnose(probes)
    [found] = [f for f in report.findings if f.check == "post_merge"]
    return found


def _the_promotion_refusal(box: str, tmp_path, monkeypatch) -> str:
    """What `_run_promotion` raises on `box` — run, not quoted."""
    from temporalio.exceptions import ApplicationError

    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal import activities

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    (tmp_path / "repo").mkdir(exist_ok=True)
    ProjectRegistry().add(Project(name="demo", repo_path=str(tmp_path / "repo"),
                                  tracker=ProviderRef(kind="github", repo="acme/demo")))
    with pytest.raises(ApplicationError) as raised:
        activities._run_promotion("demo", "1", "staging", {}, "run-1", sandbox=box)
    assert raised.value.non_retryable
    return raised.value.message


# ── 1. the doctor fails it, before any card ─────────────────────────────────────────────────────

@pytest.mark.parametrize("box", LOCAL_BOXES)
def test_the_doctor_fails_a_promotion_chain_on_a_local_box(box):
    found = _post_merge(_manifest(**CHAIN), box)
    assert not found.ok, (f"a chain the {box!r} box cannot walk was reported ok — the job it "
                          f"lets through fails after its merge: {found.message}")
    assert found.remedy, "a failing finding with no remedy is a symptom, not a diagnosis"
    assert "staging, prod" in found.message and repr(box) in found.message


@pytest.mark.parametrize("box", LOCAL_BOXES)
def test_a_deploy_watch_does_not_hide_the_chain_it_is_declared_beside(box):
    """The workflow promotes on `environments` whether or not a deploy is watched, so the watch's
    `ok` branch must not be where this check stops."""
    found = _post_merge(_manifest(**CHAIN, **WATCH), box)
    assert not found.ok, found.message


def test_the_verdict_is_not_ready_on_that_manifest():
    probes = a_fully_pinned_probe_set(manifest=lambda: _manifest(**CHAIN),
                                      sandbox=lambda: "worktree")
    report = doctor.diagnose(probes)
    assert not report.ok
    assert [f.check for f in report.findings if not f.ok] == ["post_merge"]


# ── 2. one sentence, two speakers ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("box", LOCAL_BOXES)
def test_the_doctor_says_what_the_promotion_would_have_raised(box, tmp_path, monkeypatch):
    """Two copies of one sentence drift by next month. Both speakers are RUN here: the doctor's
    cause and its remedy must each appear, verbatim, in what the promotion raises after a merge."""
    found = _post_merge(_manifest(**CHAIN), box)
    raised = _the_promotion_refusal(box, tmp_path, monkeypatch)
    cause = found.message.split(" — ", 1)[1]
    assert cause in raised, f"the doctor says {cause!r}; the promotion raises {raised!r}"
    assert found.remedy in raised, f"the doctor says {found.remedy!r}; the promotion {raised!r}"


# ── 3. what did not change ──────────────────────────────────────────────────────────────────────

def test_a_remote_box_with_the_same_chain_is_still_ok(orbit):
    found = _post_merge(_manifest(**CHAIN), "orbit")
    assert found.ok, found.message
    assert "promotion chain observes staging, prod" in found.message


@pytest.mark.parametrize("box", LOCAL_BOXES)
@pytest.mark.parametrize("over", [{}, WATCH], ids=["nothing", "a-watch-only"])
def test_a_local_box_without_environments_is_still_ok(box, over):
    found = _post_merge(_manifest(**over), box)
    assert found.ok, found.message


@pytest.mark.parametrize("box", [None, "no-such-box"], ids=["no-box-probe", "an-unknown-box"])
def test_a_box_nothing_can_name_reads_as_it_did_before(box):
    """`_traits` answers None for these, and every check then reads as it did before the box probe
    existed — a guess in either direction would be a finding about a box nobody identified."""
    found = _post_merge(_manifest(**CHAIN), box)
    assert found.ok, found.message


# ── 4. the remedy's advice loads ────────────────────────────────────────────────────────────────

def test_following_the_remedy_gives_a_manifest_that_loads_and_passes():
    found = _post_merge(_manifest(**CHAIN), "worktree")
    assert "`environments:`" in found.remedy and "`promote:`" in found.remedy, found.remedy
    with pytest.raises(ValueError, match="promote: names"):
        _manifest(promote=CHAIN["promote"])  # `environments:` dropped, `promote:` left behind
    assert _post_merge(_manifest(), "worktree").ok
