"""What this platform's own reviewer concluded, and what that means to somebody deciding (#149).

The verdict was computed by the REVIEW station, published by a workflow query, and rendered in
exactly one place: a dense line for the tech-lead's prompt. The one surface where a person is
actually deciding — the merge gate — showed none of it, so a review that REJECTED a pull request
and one that approved it produced byte-identical screens (measured on the pilot: grepped the gate
payload for `score`, `review`, `reject` — all absent).

One definition, renderers. `line()` is the model's; `headline()` is a person's; neither derives a
judgement the other cannot see.
"""
