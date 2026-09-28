"""How many BYTES a project's declared documents would inline, said before a ticket spends (#7).

`openfactory doctor` and `openfactory box prove` both say, per declared document role, the total
bytes it would inline into every pass — AFTER `_MAX_DOC_CHARS` truncation, because that is what
reaches the prompt, and in BYTES, because the argv ceiling it must clear is a byte limit. A note
SAYS SO when the total would not fit a box that cannot hand the prompt over off the command line;
it is a note, never a refusal, and a staging box with a stdin-capable harness is left alone.

Reporting only: no cap is added (PR #359, a summed cap, was closed as superseded; #364 decides
whether a bound should exist).
"""

from __future__ import annotations

from pathlib import Path

from openfactory.adapters.agent.base import MAX_ARG_STRLEN
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


# ── the note: only when it would not fit a box that cannot get it off argv ────────────────────────

_OVER = MAX_ARG_STRLEN + 1
_UNDER = MAX_ARG_STRLEN - 1


def test_the_note_appears_for_a_no_channel_box():
    note = inlined_document_overflow(_OVER, stages_input=False, harness="claude_code")
    assert note
    assert f"{_OVER:,}" in note                    # the byte count
    assert "per-argument limit" in note            # the limit
    assert "kimi" in note                          # which harnesses cannot read a staged prompt


def test_the_note_does_not_appear_for_a_staging_box_with_a_stdin_harness():
    assert inlined_document_overflow(_OVER, stages_input=True, harness="claude_code") == ""


def test_a_staging_box_with_a_harness_that_cannot_read_a_staged_prompt_still_gets_the_note():
    """The one exemption is a staging box AND a stdin-capable harness. `kimi-code` keeps its prompt
    on argv, so even on a staging box a corpus past the ceiling is undeliverable — the note says
    so."""
    note = inlined_document_overflow(_OVER, stages_input=True, harness="kimi")
    assert note and "kimi" in note


def test_a_total_that_fits_the_limit_is_never_a_note():
    assert inlined_document_overflow(_UNDER, stages_input=False, harness="kimi") == ""


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
    note = inlined_document_overflow(_OVER, stages_input=False, harness="claude_code")
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
    note = inlined_document_overflow(_OVER, stages_input=False, harness="claude_code")
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
    the bug was invisible in the output for an unprofiled project and silent for a profiled one."""
    import openfactory.loader as loader_mod
    import openfactory.orchestrator.context as ctx
    from openfactory import doctor as doctor_mod

    seen: dict[str, object] = {}
    real = ctx.inlined_document_bytes
    monkeypatch.setattr(ctx, "inlined_document_bytes",
                        lambda m, r, **kw: seen.update(kw) or real(m, r, **kw))
    # `probes_for` imports these at call time, so the module attribute is the seam.
    monkeypatch.setattr(loader_mod, "load_manifest", lambda _p, **_kw: Manifest(profile="prototype"))
    monkeypatch.setattr("openfactory.factory.resolve_repo_path", lambda _p: str(tmp_path))

    from openfactory.contracts.project import Project

    probes = doctor_mod.probes_for(Project(name="acme", repo_path=str(tmp_path)))
    assert probes.inlined_documents is not None
    probes.inlined_documents()

    assert seen.get("profile") is not None, "doctor sized the corpus with no profile"
    assert seen["profile"].name == "prototype"
