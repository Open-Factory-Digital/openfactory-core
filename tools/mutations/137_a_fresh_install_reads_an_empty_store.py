"""#137, proven by breaking it — a fresh install's metrics store is empty, not unreadable.

The schema was applied only on a write, and nothing writes a metric until a job runs, so every read
on a deployment that had run nothing yet failed with `no such table: metrics`. The panel reads the
people store on every request, so it logged that on essentially every request (442 lines for 240
board reads on the e2e bed) and nobody registered by invitation could be identified.

TWO CLAIMS:

  1. **The first read makes the table**, once per file per process, including when the directory
     does not exist yet — and a file removed under a running process is made again, rather than
     failing every read for the rest of its life.
  2. **A store that cannot be read still says so.** A file that is not a database is
     `StoreUnreadable`, never `[]` (#126).

The guard is `tests/test_a_fresh_install_reads_an_empty_store.py`.
"""

TEST = "tests/test_a_fresh_install_reads_an_empty_store.py"

SINK = "openfactory/observability/sqlite_metrics.py"

MUTATIONS = [
    ("THE DEFECT ITSELF: a read never makes the table, so a fresh install fails every read",
     SINK,
     "        ensure = write or key not in _SCHEMA_ENSURED\n",
     "        ensure = write\n"),

    ("a read that should make the table skips it", SINK,
     "            elif ensure:\n                try:\n"
     "                    conn.executescript(_SCHEMA)",
     "            elif False:\n                try:\n"
     "                    conn.executescript(_SCHEMA)"),

    ("a read before the state directory exists fails instead of reading an empty store", SINK,
     "        elif ensure:\n            try:\n                self.path.parent.mkdir(",
     "        elif False:\n            try:\n                self.path.parent.mkdir("),

    ("a store removed under a running process fails every read for the rest of its life", SINK,
     "            _SCHEMA_ENSURED.discard(str(self.path))\n",
     "            pass\n"),

    ("#126 UNDONE: a store that cannot be read answers as an empty one", SINK,
     '            log.warning("metrics read failed on %s: %s", self.path, exc)\n',
     '            return []\n'),
]
