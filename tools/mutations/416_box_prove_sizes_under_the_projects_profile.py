"""`box prove` sizes the inlined documents under the profile the job will run under (#416).

#370 made BOTH callers of `inlined_document_bytes` resolve `manifest.profile` the way the executor
does, and guarded only one of them: `the_documents_inline_a_number_before_a_ticket_spends` row 4
drops the doctor's `profile=`, and nothing dropped the box prove one. Measured in the re-review of
#370: that cut left `test_the_inlined_document_bytes_are_reported.py` and `test_box_prove.py` green
(57 passed) — so `box prove` could lose the profile again and nothing would notice, which is how
the original defect lived in both callers unseen.

Two cuts, the two ways the box prove closure can stop handing the sizer the resolved profile. The
reported NUMBER is no guard here: for an unprofiled project it is identical with or without the
profile, so the test watches what the sizer is handed.
"""

TEST = "tests/test_the_inlined_document_bytes_are_reported.py"
BOX_PROVE = "openfactory/box_prove.py"

MUTATIONS = [
    ("box prove sizes the corpus with NO profile — the cut #370's re-review measured green: a "
     "`prototype` project is reported with `tdd.md`'s bytes it will never inline",
     BOX_PROVE,
     "            per_role = inlined_document_bytes(manifest, repo, profile=profile)",
     "            per_role = inlined_document_bytes(manifest, repo)"),

    ("box prove resolves no profile at all, so the sizer is handed None for a project that "
     "declares one — the same wrong number reached one line earlier",
     BOX_PROVE,
     "            profile = resolve_profile(manifest.profile, project_dir=repo)",
     "            profile = resolve_profile(None, project_dir=repo)"),
]
