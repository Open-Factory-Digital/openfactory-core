"""P0.6 — adding a decision record moves every count that claims to know how many there are.

Run:  .venv/bin/python tools/mutate.py tools/mutations/installer_adr_counts_move_together.py

NO NEW GUARD IS ADDED BY P0.6, which is exactly why this plan exists. The task ships ADR-0043 and
the numbers that move with it, and the guards that judge those numbers were already here
(`test_the_adr_count_the_docs_CLAIM_is_the_number_of_ADRs_there_are` and
`test_the_adr_index_status_column_is_the_ADRs_own_status`). A guard nobody re-ran against the
change it was supposed to catch is a guard nobody has checked — #113's whole lesson is that four
documents said "42 decision records" over 41 ADRs for as long as they did, because
`docs/adr/` also holds its own README and somebody counted files.

So each of the three documents that types the count is cut separately: three homes, three chances
to update two of them and ship the third stale, which is the failure that actually happens.
"""

TEST = "tests/test_the_docs_do_not_drift.py"

INDEX = "docs/adr/README.md"

MUTATIONS = [
    ("the README keeps the old count while a 43rd record ships",
     "README.md",
     "| [docs/adr/](docs/adr/) | why it is built this way (43 decision records) |",
     "| [docs/adr/](docs/adr/) | why it is built this way (42 decision records) |"),

    ("CONTRIBUTING keeps the old count — the page a contributor reads first",
     "CONTRIBUTING.md",
     "**why** — 43 decision records.",
     "**why** — 42 decision records."),

    ("the documentation map keeps the old count",
     "docs/README.md",
     "why it is built this way — 43 decision records",
     "why it is built this way — 42 decision records"),

    ("the index says Proposed about a record whose own Status line says Accepted",
     INDEX,
     "| [0043](0043-the-distribution-is-a-published-image.md) | The distribution is a published "
     "image, and one compose file both installs and builds | Accepted for the shape; the images "
     "are published by a workflow that has not been run |",
     "| [0043](0043-the-distribution-is-a-published-image.md) | The distribution is a published "
     "image, and one compose file both installs and builds | Proposed (design only) |"),
]
