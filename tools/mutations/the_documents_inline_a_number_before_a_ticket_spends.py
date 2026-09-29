"""#7: doctor and box prove say how many BYTES a project's documents would inline, before spending.

The size of the prompt is knowable from the manifest and the checkout alone — before a ticket
spends anything — and two facts survive #360's staging fix that make it worth saying: the refusal
path is real but invisible (a box with no staging channel, or `kimi-code`, still delivers the prompt
as one argv element, capped at 128 KiB), and nothing can argue the prompt's size (#364) without a
number an operator can read per project.

Four cuts, one per acceptance edge, each turning a true report into a plausible-but-wrong one:

  * the COUNT going back to characters — the whole point is bytes, because `_MAX_DOC_CHARS`
    truncates in characters and the limit it must clear is bytes (this repo's own ADRs run 8,066
    bytes for 8,000 characters);
  * the per-role SPLIT collapsing into one total — a single number cannot point at the setting that
    changes it, and the ticket asks for one line per declared role;
  * the NOTE firing for a deployment that HAS a channel — the note is for a box that cannot hand the
    prompt over off argv; a staging box with a stdin-capable harness is unaffected and must not be
    told it has a problem;
  * the CALLER dropping the profile (review of #370) — the number is only the one the job will pay
    when it is measured under the profile the job will run under. A profile that waives a baseline
    document makes the unprofiled read OVER-report, which is the false-alarm direction the note's
    exemption exists to prevent; one that adds guidelines makes it UNDER-report and stay silent on
    a real overflow.
"""

TEST = "tests/test_the_inlined_document_bytes_are_reported.py"

MUTATIONS = [
    ("the count goes back to CHARACTERS, so a multibyte corpus is under-reported against a byte "
     "limit — the exact confusion the ticket names, `→` counted as one where it costs three",
     "openfactory/orchestrator/context.py",
     '    return sum(len(t.encode("utf-8")) for t in texts)',
     "    return sum(len(t) for t in texts)"),

    ("the per-role split collapses into one total, so the report is a single number that cannot "
     "point at the role — `docs.constraints` vs the framework baseline vs `docs.guidelines` — an "
     "operator would change to shrink it",
     "openfactory/orchestrator/context.py",
     '        "docs.constraints": _inlined_bytes(constraints),\n'
     '        "framework baseline": _inlined_bytes(framework),\n'
     '        "operator guidelines": _inlined_bytes(operator_tier),\n'
     '        "docs.guidelines": _inlined_bytes(project_docs),',
     '        "documents": _inlined_bytes(\n'
     "            constraints + framework + operator_tier + project_docs),"),

    ("the note fires for a deployment that CAN hand the prompt over off argv, so a working staging "
     "box with a stdin-capable harness is told it has a problem it does not have — the false alarm "
     "the note's one exemption exists to prevent",
     "openfactory/orchestrator/context.py",
     '    if stages_input and reads_staged:\n        return ""',
     '    if False:\n        return ""'),

    ("doctor sizes the corpus with NO profile, so a profiled project is measured against a "
     "baseline no pass will ever inline — `prototype` waives `tdd.md`, and the report keeps its "
     "bytes: the over-reporting direction, silent and plausible, on the one number an operator "
     "trusts to decide whether their documents fit",
     "openfactory/doctor.py",
     "        per_role = inlined_document_bytes(manifest, pathlib.Path(root), profile=profile)",
     "        per_role = inlined_document_bytes(manifest, pathlib.Path(root))"),
]
