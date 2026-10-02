"""How many BYTES a project's declared documents would inline, said before a ticket spends (#7).

`openfactory doctor` and `openfactory box prove` both say, per declared document role, the total
bytes it would inline into every pass — AFTER `_MAX_DOC_CHARS` truncation, because that is what
reaches the prompt, and in BYTES, because the argv ceiling it must clear is a byte limit. Where the
prompt cannot be handed over off the command line, a note says whether every pass would refuse it
— decided on the prompt a pass carries, at the line the pass refuses at (#418) — or how close it
comes; it is a note, never a refusal, and a staging box with a stdin-capable harness is left alone.

Reporting only: no cap is added (PR #359, a summed cap, was closed as superseded; #364 decides
whether a bound should exist).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openfactory.adapters.agent.base import ARGV_PROMPT_CEILING, MAX_ARG_STRLEN
from openfactory.contracts import Manifest
from openfactory.orchestrator import operator_guidelines as og
from openfactory.orchestrator.context import (
    _MAX_DOC_CHARS,
    inlined_document_bytes,
    inlined_document_overflow,
)

# ── the count is bytes, per role, after truncation ───────────────────────────────────────────────

def test_the_count_is_bytes_not_characters_for_a_multibyte_document(tmp_path: Path):
    """A constraint doc written in multibyte characters is reported by the bytes it costs the
    prompt, not the characters it has — the two differ, and the limit is bytes."""
    (tmp_path / "adr").mkdir()
    # `→` is three UTF-8 bytes; the arrow-heavy line is longer encoded than counted.
    body = "A decision → another → a third\n"
    (tmp_path / "adr" / "0001.md").write_text(body)

    per_role = inlined_document_bytes(Manifest(docs={"constraints": "adr/*.md"}), tmp_path)

    assert per_role["docs.constraints"] == len(body.encode("utf-8"))
    assert per_role["docs.constraints"] > len(body), "bytes must exceed characters for `→`"


def test_truncation_happens_in_characters_and_the_bytes_are_counted_after(tmp_path: Path):
    """`_MAX_DOC_CHARS` cuts at a CHARACTER boundary, and the bytes are counted on what survives —
    so a doc padded past the cap with ASCII reports exactly `_MAX_DOC_CHARS` bytes, and the
    multibyte tail beyond the cut is not paid for."""
    (tmp_path / "adr").mkdir()
    (tmp_path / "adr" / "0001.md").write_text("a" * _MAX_DOC_CHARS + "→" * 500)

    per_role = inlined_document_bytes(Manifest(docs={"constraints": "adr/*.md"}), tmp_path)

    assert per_role["docs.constraints"] == _MAX_DOC_CHARS


def test_each_role_is_its_own_line_and_they_do_not_collapse(tmp_path: Path, monkeypatch):
    """The split is per role: `docs.constraints`, the framework baseline, the operator tier and
    `docs.guidelines`. Each is its own number, and a project that names one role does not have its
    bytes attributed to another."""
    monkeypatch.delenv(og.ENV_VAR, raising=False)  # no operator tier configured
    (tmp_path / "adr").mkdir()
    (tmp_path / "adr" / "0001.md").write_text("x" * 100)
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "house.md").write_text("y" * 40)

    per_role = inlined_document_bytes(
        Manifest(docs={"constraints": "adr/*.md", "guidelines": ["rules/house.md"]}), tmp_path)

    assert per_role["docs.constraints"] == 100
    assert per_role["docs.guidelines"] == 40
    assert per_role["operator guidelines"] == 0            # none configured
    assert per_role["framework baseline"] > 0              # org_defaults are always inlined
    # four distinct roles, so the sum is a derived total and not the only number there is
    assert set(per_role) == {"docs.constraints", "framework baseline",
                             "operator guidelines", "docs.guidelines"}


def test_a_components_guidelines_are_reported_under_the_component_that_names_them(
        tmp_path: Path, monkeypatch):
    """A component's own `guidelines` are their own line, `components.<name>.guidelines` (#417).

    They were counted under `docs.guidelines`: the total was right and the split pointed an
    operator whose large file was the component's at the project-wide list. Each guideline is
    reported under the key that names it, a component that names none has no line (it has no
    setting to change), and the total is still exactly what `build_context` inlines."""
    from openfactory.contracts import Ticket
    from openfactory.orchestrator.context import _inlined_bytes, build_context

    monkeypatch.delenv(og.ENV_VAR, raising=False)
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "house.md").write_text("y" * 40)
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "rules.md").write_text("z" * 25)
    manifest = Manifest(
        docs={"guidelines": ["rules/house.md"]},
        components={"api": {"path": "api/**", "stack": "python", "guidelines": ["api/rules.md"]},
                    "web": {"path": "web/**", "stack": "node"}})

    per_role = inlined_document_bytes(manifest, tmp_path)

    assert per_role["docs.guidelines"] == 40, "the component's bytes were folded into the project's"
    assert per_role["components.api.guidelines"] == 25
    assert "components.web.guidelines" not in per_role, "a 0 line for a setting nobody wrote"
    job = build_context(manifest, tmp_path, Ticket(id="#1", title="t", objective="o", repo="o/x"),
                        knowledge_map="")
    assert sum(per_role.values()) == _inlined_bytes(job.constraints) + _inlined_bytes(
        job.guidelines), "the split moved the total away from what the job inlines"


# ── the note: only where the prompt rides the command line, on the line the pass refuses at ──────

#: A prompt just past the line `stage_prompt` refuses at, and one comfortably within it.
_OVER = ARGV_PROMPT_CEILING + 1
_WITHIN = ARGV_PROMPT_CEILING - 20_000
#: What the note says when no card can save the pass — the sentence the tests tell apart from the
#: headroom one.
_EVERY_PASS_REFUSES = "EVERY pass would refuse"


def _note(prompt_bytes: int, *, stages_input: bool, harness: str, total: int = 100_000) -> str:
    return inlined_document_overflow(total, prompt_bytes=prompt_bytes, stages_input=stages_input,
                                     harness=harness)


def test_the_note_says_every_pass_refuses_a_prompt_past_the_line_on_a_no_channel_box():
    note = _note(_OVER, stages_input=False, harness="claude_code")
    assert _EVERY_PASS_REFUSES in note
    assert f"{_OVER:,}" in note                    # the prompt's byte count
    assert f"{ARGV_PROMPT_CEILING:,}" in note      # the line the pass refuses at
    assert "per-argument limit" in note            # the limit that line comes from
    assert "kimi" in note                          # which harnesses cannot read a staged prompt


def test_the_note_does_not_appear_for_a_staging_box_with_a_stdin_harness():
    for prompt in (_OVER, _WITHIN):
        assert _note(prompt, stages_input=True, harness="claude_code") == ""


def test_a_staging_box_with_a_harness_that_cannot_read_a_staged_prompt_still_gets_the_note():
    """The one exemption is a staging box AND a stdin-capable harness. `kimi-code` keeps its prompt
    on argv, so even on a staging box a corpus past the ceiling is undeliverable — the note says
    so."""
    note = _note(_OVER, stages_input=True, harness="kimi")
    assert _EVERY_PASS_REFUSES in note and "kimi" in note


def test_a_prompt_within_the_line_on_an_argv_deployment_is_told_how_close_it_comes():
    """The other half of #418. The card, its plan and the knowledge map are unknown before a ticket
    exists, so where the prompt rides the command line the note says how close the floor comes, as
    a percentage, and how many bytes those have left — the number to judge them by, never a
    verdict on them."""
    note = _note(_WITHIN, stages_input=False, harness="kimi")
    assert _EVERY_PASS_REFUSES not in note
    assert f"{_WITHIN * 100 // ARGV_PROMPT_CEILING}% of the {ARGV_PROMPT_CEILING:,} bytes" in note
    assert f"the {ARGV_PROMPT_CEILING - _WITHIN:,} bytes left" in note


# ── the note is decided on the prompt a pass carries, not on the documents alone (#418) ──────────

class _Captured(Exception):
    """Raised by `_CapturesThePrompt` once it holds the prompt, so the pass stops before running."""


class _CapturesThePrompt:
    """A box with the staging channel that records what a pass hands it, then stops the pass —
    the exact prompt the adapter built, and nothing run."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def stage_input(self, *, workspace, text: str):  # noqa: ARG002
        self.prompts.append(text)
        raise _Captured


def _corpus(tmp_path: Path, monkeypatch, *, documents: int) -> Manifest:
    """A project whose declared documents inline exactly `documents` bytes, framework baseline
    included — ADRs of plain ASCII, each under the truncation cap, so bytes are characters."""
    monkeypatch.delenv(og.ENV_VAR, raising=False)
    remaining = documents - sum(inlined_document_bytes(Manifest(), tmp_path).values())
    (tmp_path / "adr").mkdir()
    for i in range(0, remaining, 7_000):
        (tmp_path / "adr" / f"{i:06d}.md").write_text("x" * min(7_000, remaining - i))
    manifest = Manifest(docs={"constraints": "adr/*.md"})
    assert sum(inlined_document_bytes(manifest, tmp_path).values()) == documents
    return manifest


#: Documents that fit the line on their own — the old note's measure called them fitting even
#: against the stricter line — and whose prompt does not.
_FITS_ALONE = ARGV_PROMPT_CEILING - 2_000


def test_the_floor_is_the_prompt_the_planner_and_executor_passes_hand_their_cli(tmp_path: Path,
                                                                                monkeypatch):
    """`prompt_floor_bytes` is the prompt the job's own passes build, measured as `stage_prompt`
    measures it — captured from the real adapter, with apostrophes in the documents so the shell's
    quoting is part of the number — and not a second estimate of it."""
    from openfactory.adapters.agent.base import _argv_bytes
    from openfactory.adapters.agent.claude_code import ClaudeCodeAdapter
    from openfactory.contracts import Ticket
    from openfactory.orchestrator.context import build_context, prompt_floor_bytes

    monkeypatch.delenv(og.ENV_VAR, raising=False)
    (tmp_path / "adr").mkdir()
    (tmp_path / "adr" / "0001.md").write_text("Don't import FastAPI in the domain; it's the "
                                              "adapter's job.\n" * 40)
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "house.md").write_text("100% coverage is enforced — no exceptions.\n")
    manifest = Manifest(docs={"constraints": "adr/*.md", "guidelines": ["rules/house.md"]})

    blank = Ticket(id="", title="", objective="", repo="")
    context = build_context(manifest, tmp_path, blank, knowledge_map="")
    box, agent = _CapturesThePrompt(), ClaudeCodeAdapter(model="opus")
    for run in (agent.plan, agent.execute):
        with pytest.raises(_Captured):
            run(sandbox=box, workspace=None, context=context)

    assert len(box.prompts) == 2, "the planner and the executor each hand over one prompt"
    assert prompt_floor_bytes(manifest, tmp_path) == max(_argv_bytes(p) for p in box.prompts)


def test_a_corpus_the_documents_alone_call_fitting_but_the_pass_refuses_is_reported(
        tmp_path: Path, monkeypatch):
    """The test #418 asks for. Documents under the raw limit — under the pass's own line, even —
    whose prompt is past that line once the role's instructions and the brief are around them. The
    pass refuses it at pickup with an ordinary card, read from the real planner pass on a box with
    no staging channel; the note says so, where it used to say nothing."""
    from openfactory.adapters.agent.claude_code import ClaudeCodeAdapter
    from openfactory.contracts import Ticket
    from openfactory.orchestrator.context import build_context, prompt_floor_bytes

    manifest = _corpus(tmp_path, monkeypatch, documents=_FITS_ALONE)
    assert _FITS_ALONE <= MAX_ARG_STRLEN, "the documents alone read as fitting the raw limit"

    card = Ticket(id="#7", title="add health check", objective="expose /health", repo="o/r")
    refused = ClaudeCodeAdapter(model="opus").plan(
        sandbox=object(), workspace=None,
        context=build_context(manifest, tmp_path, card, knowledge_map=""))
    assert not refused.ok and "per-argument limit" in refused.summary, refused.summary

    note = _note(prompt_floor_bytes(manifest, tmp_path), total=_FITS_ALONE, stages_input=False,
                 harness="claude_code")
    assert _EVERY_PASS_REFUSES in note, note
    assert f"{_FITS_ALONE:,}" in note, "the documents' own bytes are still said"


def test_doctor_reports_the_refusal_the_pass_will_make(tmp_path: Path, monkeypatch):
    """The caller, watched on its output: `doctor`'s probe decides the note on the prompt a pass
    carries, so a corpus whose documents fit and whose prompt does not reads as refused."""
    import openfactory.loader as loader_mod
    from openfactory import doctor as doctor_mod
    from openfactory.contracts.project import Project

    manifest = _corpus(tmp_path, monkeypatch, documents=_FITS_ALONE)
    monkeypatch.setattr(loader_mod, "load_manifest", lambda _p, **_kw: manifest)
    monkeypatch.setattr("openfactory.factory.resolve_repo_path", lambda _p: str(tmp_path))
    monkeypatch.setattr(doctor_mod, "_box_stages_input", lambda _kind: False)  # no channel

    probes = doctor_mod.probes_for(Project(name="acme", repo_path=str(tmp_path)))
    assert probes.inlined_documents is not None
    per_role, note = probes.inlined_documents()

    assert sum(per_role.values()) == _FITS_ALONE
    assert _EVERY_PASS_REFUSES in note, note


def test_box_prove_reports_the_refusal_the_pass_will_make(tmp_path: Path, monkeypatch):
    """The same, on `box prove`'s closure, over a box that offers no staging channel."""
    from types import SimpleNamespace

    from openfactory import box_prove
    from openfactory.adapters.sandbox import registry as sandboxes

    class _NoChannelBox:
        def prepare(self, **_kw):
            return SimpleNamespace(path=str(tmp_path))

        def cleanup(self, **_kw):
            pass

    manifest = _corpus(tmp_path, monkeypatch, documents=_FITS_ALONE)
    monkeypatch.setattr(sandboxes, "installed_box_traits",
                        lambda _kind: SimpleNamespace(honours_image=True))
    monkeypatch.setattr(sandboxes, "build_sandbox", lambda *_a, **_kw: _NoChannelBox())

    with box_prove.box_probes(SimpleNamespace(name="acme", box=None), "img", repo_path=tmp_path,
                              manifest=manifest, key="acme", sandbox="container") as probes:
        assert probes.inlined_documents is not None
        measured = probes.inlined_documents()

    assert measured is not None, "box prove could not measure a readable checkout"
    per_role, note = measured
    assert sum(per_role.values()) == _FITS_ALONE
    assert _EVERY_PASS_REFUSES in note, note


# ── doctor says the number, before the first ticket ──────────────────────────────────────────────

def _doctor_documents(measured):
    from openfactory import doctor
    from tests.pinned_probes import a_fully_pinned_probe_set

    report = doctor.diagnose(a_fully_pinned_probe_set(inlined_documents=lambda: measured))
    return next(f for f in report.findings if f.check == "documents")


def test_doctor_reports_the_per_role_bytes_and_never_fails_on_them():
    per_role = {"docs.constraints": 30_000, "framework baseline": 8_066,
                "operator guidelines": 0, "docs.guidelines": 2_000}
    f = _doctor_documents((per_role, ""))
    assert f.ok, "a size report is never a FAIL — it reports what is"
    assert "40,066 bytes" in f.message           # the derived total, in bytes
    assert "docs.constraints: 30,000 B" in f.message and "framework baseline: 8,066 B" in f.message
    assert f.note == ""                           # it fits: nothing to warn about


def test_doctor_notes_a_corpus_that_would_not_fit_a_no_channel_box():
    per_role = {"docs.constraints": _OVER, "framework baseline": 0,
                "operator guidelines": 0, "docs.guidelines": 0}
    note = _note(_OVER, total=_OVER, stages_input=False, harness="claude_code")
    f = _doctor_documents((per_role, note))
    assert f.ok and f.note and "per-argument limit" in f.note


# ── box prove says the same number, where a project is proven before pickup ───────────────────────

def _box_prove_documents(measured):
    from openfactory.box_prove import Probes, prove

    probes = Probes(
        resolve_digest=lambda image: "sha256:" + "a" * 64,
        image_platform=lambda image: ("linux", "arm64", "glibc"),
        toolbox_stamp=lambda: {"variant": "linux-arm64-glibc", "harnesses": ["claude"]},
        contract=lambda image: {},
        run_in_box=lambda cmd: (0, ""),
        harness_reachable=lambda: (True, ""),
        setup_commands=lambda: [],
        validate_commands=lambda: {},
        harness_name=lambda: "claude",
        inlined_documents=lambda: measured,
    )
    proof = prove("acme", "mycorp/ci:1", probes)
    return next(f for f in proof.findings if f.check == "documents")


def test_box_prove_carries_the_same_per_role_bytes():
    per_role = {"docs.constraints": 30_000, "framework baseline": 8_066,
                "operator guidelines": 0, "docs.guidelines": 2_000}
    f = _box_prove_documents((per_role, ""))
    assert f.ok
    assert "40,066 bytes" in f.message
    assert "docs.constraints: 30,000 B" in f.message


def test_box_prove_notes_an_overflow_for_a_no_channel_box():
    note = _note(_OVER, total=_OVER, stages_input=False, harness="claude_code")
    f = _box_prove_documents(({"docs.constraints": _OVER, "framework baseline": 0,
                               "operator guidelines": 0, "docs.guidelines": 0}, note))
    assert f.ok, "a note holds no pickup — it is not a failure"
    assert "per-argument limit" in f.message and f"{_OVER:,}" in f.message


# ── the profile the job will run under is the profile the number is measured under ───────────────

def test_a_waiving_profile_shrinks_the_baseline_by_exactly_the_waived_document(tmp_path: Path,
                                                                               monkeypatch):
    """The number is measured under the profile the job will run under (review of #370).

    `prototype` waives `tdd.md`, so the framework baseline it inlines is the unprofiled baseline
    MINUS that file, to the byte. Measuring the same project with `profile=None` reports a corpus
    no pass will ever inline — the over-reporting direction, which is the false alarm the note's
    exemption exists to prevent."""
    from openfactory.orchestrator.context import ORG_DEFAULTS_DIR
    from openfactory.policy.profiles import resolve_profile

    monkeypatch.delenv(og.ENV_VAR, raising=False)  # no operator tier: the baseline is the subject
    manifest = Manifest(profile="prototype")

    unprofiled = inlined_document_bytes(manifest, tmp_path)["framework baseline"]
    profiled = inlined_document_bytes(
        manifest, tmp_path, profile=resolve_profile("prototype"))["framework baseline"]

    tdd = (ORG_DEFAULTS_DIR / "tdd.md").read_text()[:_MAX_DOC_CHARS]
    assert profiled == unprofiled - len(tdd.encode("utf-8")), (
        "the waived document's bytes, and only those, come off the baseline")
    assert profiled < unprofiled, "a waiving profile must not report the unprofiled size"


def test_the_reported_baseline_is_the_one_build_context_inlines_for_that_profile(tmp_path: Path,
                                                                                 monkeypatch):
    """The claim the docstring stakes, pinned: for the SAME profile, what this reports and what
    `build_context` actually inlines are the same bytes — not a second estimate of them."""
    from openfactory.orchestrator.context import _org_defaults
    from openfactory.policy.profiles import resolve_profile

    monkeypatch.delenv(og.ENV_VAR, raising=False)
    for name in ("prototype", "regulated"):
        profile = resolve_profile(name)
        reported = inlined_document_bytes(
            Manifest(profile=name), tmp_path, profile=profile)["framework baseline"]
        inlined = _inlined_bytes_of(_org_defaults(profile, tmp_path, set()))
        assert reported == inlined, f"{name}: reported {reported} B, job inlines {inlined} B"


def _inlined_bytes_of(texts: list[str]) -> int:
    from openfactory.orchestrator.context import _inlined_bytes

    return _inlined_bytes([t[:_MAX_DOC_CHARS] for t in texts])


def test_doctor_hands_the_sizer_the_projects_resolved_profile(tmp_path: Path, monkeypatch):
    """The regression guard on the CALLER, which is where the defect was: `doctor`'s probe must
    resolve `manifest.profile` and pass it. Asserted by watching what the sizer is handed, because
    the bug was invisible in the output for an unprofiled project and silent for a profiled one.
    The floor of the prompt a pass carries (#418) reads the same documents and is watched too."""
    import openfactory.loader as loader_mod
    from openfactory import doctor as doctor_mod

    seen = _watch_both_measures(monkeypatch)
    # `probes_for` imports these at call time, so the module attribute is the seam.
    monkeypatch.setattr(loader_mod, "load_manifest", lambda _p, **_kw: Manifest(profile="prototype"))
    monkeypatch.setattr("openfactory.factory.resolve_repo_path", lambda _p: str(tmp_path))

    from openfactory.contracts.project import Project

    probes = doctor_mod.probes_for(Project(name="acme", repo_path=str(tmp_path)))
    assert probes.inlined_documents is not None
    probes.inlined_documents()

    assert set(seen) == {"inlined_document_bytes", "prompt_floor_bytes"}, seen
    for measure, kw in seen.items():
        assert kw.get("profile") is not None, f"doctor ran {measure} with no profile"
        assert kw["profile"].name == "prototype", measure


def _watch_both_measures(monkeypatch) -> dict[str, dict]:
    """What each measure a caller runs is HANDED — the per-source bytes and, since #418, the floor
    of the prompt a pass carries. Both read the documents, so both are owed the profile."""
    import openfactory.orchestrator.context as ctx

    seen: dict[str, dict] = {}
    for measure in ("inlined_document_bytes", "prompt_floor_bytes"):
        real = getattr(ctx, measure)
        monkeypatch.setattr(ctx, measure, lambda m, r, _name=measure, _real=real, **kw: (
            seen.__setitem__(_name, kw) or _real(m, r, **kw)))
    return seen


def test_box_prove_hands_the_sizer_the_projects_resolved_profile(tmp_path: Path, monkeypatch):
    """The doctor guard's twin, on the OTHER caller (#416). #370 made both `doctor` and `box prove`
    resolve the project's profile before sizing, and only the doctor side was watched: dropping
    `profile=` in `box_prove.py` left this file and `test_box_prove.py` green (57 passed), which is
    how the original defect lived in both callers unseen.

    Driven through the real `box_probes`, with a box that starts and runs nothing, because the
    claim is that closure's wiring. Watched on what the sizer is HANDED, not on the number: for an
    unprofiled project the number is identical with or without the profile. The floor of the
    prompt a pass carries (#418) reads the same documents and is watched too."""
    from types import SimpleNamespace

    from openfactory import box_prove
    from openfactory.adapters.sandbox import registry as sandboxes

    class _Box:
        def prepare(self, **_kw):
            return SimpleNamespace(path=str(tmp_path))

        def cleanup(self, **_kw):
            pass

    seen = _watch_both_measures(monkeypatch)
    monkeypatch.setattr(sandboxes, "installed_box_traits",
                        lambda _kind: SimpleNamespace(honours_image=True))
    monkeypatch.setattr(sandboxes, "build_sandbox", lambda *_a, **_kw: _Box())
    monkeypatch.delenv(og.ENV_VAR, raising=False)

    with box_prove.box_probes(SimpleNamespace(name="acme", box=None), "img", repo_path=tmp_path,
                              manifest=Manifest(profile="prototype"), key="acme",
                              sandbox="container") as probes:
        assert probes.inlined_documents is not None
        measured = probes.inlined_documents()

    assert measured is not None, "box prove could not measure a readable checkout"
    assert set(seen) == {"inlined_document_bytes", "prompt_floor_bytes"}, seen
    for measure, kw in seen.items():
        assert kw.get("profile") is not None, f"box prove ran {measure} with no profile"
        assert kw["profile"].name == "prototype", measure
