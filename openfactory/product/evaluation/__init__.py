"""The product role's evaluation battery (#266 slice 0, ADR-0051).

"BETTER" HAS TO BE A NUMBER. #266 rebuilds how the product role is reached and how it takes turns,
and every slice after this one changes what a person gets back. Without a measurement taken before
the first of them, an improvement is a belief and a regression is invisible until a client meets
it. So the battery comes first: real product-owner questions about one fixture product, asked of
the role through its one door, each answer judged three ways —

    correct                 the facts a right answer carries are there, and nothing it must not say
    cited                   the source a right answer rests on is named
    abstained correctly     it said "I do not know" exactly when nothing it can read answers it

— and a dated record of the run, carrying the commit and the model, beside the ones before it.

WHO WRITES WHAT is decision 9: the questions are the product owner's, the expected answers and
this automation the implementer's. The question file ships empty, and a run over it refuses with
the sentence that says whose move it is.

    battery.py    the question file: its format, and its validation against the fixture
    score.py      the three verdicts on one answer, each saying who decided it, and the totals
    run.py        the battery through `engine.turn` over the fixture, and the record it writes
    __main__.py   `make eval-product`

A LIVE MODEL ANSWERS IT, so it spends tokens and never runs inside `make test`; the suite drives the
same runner with the model scripted at the harness boundary.
"""
