"""A component's own guidelines are reported under the component that names them (#417).

`inlined_document_bytes` reports the bytes per source so an operator can see WHICH setting to
shrink (#370). A component's `guidelines` were counted under `docs.guidelines`: the total was right
and the split pointed at the project-wide list when the large file was the component's. Found in
the review of #370 and agreed there as its own change.

Five cuts, each a plausible way to lose the split again or to buy it with a wrong number:

  * the component's bytes go back under `docs.guidelines` — the defect as filed;
  * every guideline folds into one "guidelines" line — the issue's own "not the fix": it hides the
    split this report exists to show;
  * the component's guidelines stop being counted at all — a split bought by under-reporting;
  * a component that names no guideline gets a 0 line — a number for a setting nobody wrote;
  * the job stops inlining what the report counts — the total must stay what `build_context`
    inlines, and only the test's total assertion can see a drift that leaves every key right.
"""

TEST = "tests/test_the_inlined_document_bytes_are_reported.py"
CONTEXT = "openfactory/orchestrator/context.py"

MUTATIONS = [
    ("a component's guidelines are counted under `docs.guidelines` again, so the split sends the "
     "operator to the project-wide list when the large file is the component's",
     CONTEXT,
     "        texts = by_source.setdefault(named_by, [])",
     '        texts = by_source["docs.guidelines"]'),

    ("every guideline folds into one `guidelines` line — the total is right and the split the "
     "report exists to show is gone",
     CONTEXT,
     "        **{source: _inlined_bytes(texts) for source, texts in by_source.items()},",
     '        "guidelines": _inlined_bytes([t for texts in by_source.values() for t in texts]),'),

    ("the component's guidelines are no longer counted — its line reads 0 while the job still "
     "inlines the file, so the split is bought by under-reporting",
     CONTEXT,
     "        texts = by_source.setdefault(named_by, [])\n",
     "        texts = by_source.setdefault(named_by, [])\n"
     '        if named_by != "docs.guidelines":\n'
     "            continue\n"),

    ("every component gets a line whether or not it names a guideline, so the report shows a 0 "
     "for a setting nobody wrote",
     CONTEXT,
     '    by_source: dict[str, list[str]] = {"docs.guidelines": []}',
     '    by_source: dict[str, list[str]] = {"docs.guidelines": [], **{\n'
     '        f"components.{n}.guidelines": [] for n in manifest.components}}'),

    ("the JOB stops inlining a component's guidelines while the report still counts them, so the "
     "total no longer is what a pass pays — caught by the total, the one assertion every per-key "
     "line above can leave standing",
     CONTEXT,
     "    guideline_paths = declared_guidelines(manifest)\n",
     '    guideline_paths = [("docs.guidelines", g) for g in manifest.docs.guidelines]\n'),
]
