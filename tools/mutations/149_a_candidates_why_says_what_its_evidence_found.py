"""#149, proven by breaking it — a reverse-engineered candidate's Why says what its evidence found.

THREE CLAIMS:

  1. **Each tier writes its own Why.** It was one sentence for all three, true only for `code`: an
     `asked` candidate said "a person asked for this" in its Evidence line and "nobody asked for
     this — no request for it was found" in its Why (measured on `506317a`, and written that way
     by a real first pass).
  2. **What each Why says is what the pass found, and where to look.** `asked` says a request was
     found and points at the citations under `## Affects`; `tested` says a test asserts it without
     claiming that nobody asked; `code` keeps its wording.
  3. **`Asked by` stays `UNRECORDED` on every tier.** A request found by a first pass is a citation,
     not a person, and a sentence in that field once made every candidate impossible to accept
     (#70).

The guard is `tests/test_product_brownfield.py`: one case per tier reads the rendered `## Why`, and
one per tier reads `Asked by` back through the corpus parser.
"""

TEST = "tests/test_product_brownfield.py"

BROWNFIELD = "openfactory/product/brownfield.py"

MUTATIONS = [
    # ── 1. each tier writes its own Why ────────────────────────────────────────────────────────
    ("THE DEFECT ITSELF: every tier gets the `code` Why again, so an `asked` candidate says nobody "
     "asked for it", BROWNFIELD,
     "        _WHY[obs.evidence],",
     "        _WHY[CODE],"),

    # ── 2. what each Why says ──────────────────────────────────────────────────────────────────
    ("the `asked` Why says nobody asked and no request was found, a few lines under an Evidence "
     "line that says a person asked", BROWNFIELD,
     '    ASKED: "A request for this was found: this pass read it as something a person asked for, "',
     '    ASKED: "Unknown: nobody asked for this, and no request for it was found; "'),

    ("the `asked` Why no longer says where the request is, so the reviewer is told to read a "
     "request nobody located", BROWNFIELD,
     '           "`## Affects`, next to the code it touched. The reason is not recorded here: read "',
     '           "the history, next to the code it touched. The reason is not recorded here: read "'),

    ("the `tested` Why says nobody asked, under a note that says somebody made it a promise on "
     "purpose", BROWNFIELD,
     '    TESTED: "No request for this was found, but a test asserts it: somebody made it a promise '
     'on "',
     '    TESTED: "Unknown: nobody asked for this, but a test asserts it: somebody made it a promise '
     'on "'),

    ("the `code` Why loses the wording the provenance test pins", BROWNFIELD,
     '    CODE: "Unknown: nobody asked for this — it was reverse-engineered from the code, and no "',
     '    CODE: "Unknown: it was reverse-engineered from the code, and no "'),

    # ── 3. Asked by stays the placeholder ──────────────────────────────────────────────────────
    ("an `asked` candidate names its request in `Asked by`, a sentence the second-yes gate reads as "
     "a person no actor can ever be", BROWNFIELD,
     '        f"- **Asked by:** {UNRECORDED}",\n',
     "        f\"- **Asked by:** {'the request under Affects' if obs.evidence == ASKED "
     "else UNRECORDED}\",\n"),
]
