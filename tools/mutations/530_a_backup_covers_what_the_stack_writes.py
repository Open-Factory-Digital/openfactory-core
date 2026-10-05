"""The backup before a candidate covers everything the stack writes (review of #530), proven by
breaking it.

Run:  .venv/bin/python tools/mutate.py tools/mutations/530_a_backup_covers_what_the_stack_writes.py

docs/RELEASING.md said "an installation is two files and five Docker volumes", and the stack also
writes two directories of the host. Each row puts the gap back, or opens a new one in the compose
file the section is held to.
"""

TEST = "tests/test_a_backup_covers_everything_the_stack_writes.py"
PAGE = "docs/RELEASING.md"
COMPOSE = "docker-compose.yml"

MUTATIONS = [
    ("THE DEFECT: the backup leaves the working clones in the candidate's state", PAGE,
     'tar czf backup-repos-dir.tgz -C "$REPOS" .\n',
     ""),

    ("the restore never puts the work directory back", PAGE,
     '(cd "$WORK" && find . -mindepth 1 -delete) && tar xzf backup-work-dir.tgz -C "$WORK"\n',
     ""),

    ("the backup loop forgets a volume", PAGE,
     'for v in temporal_db openfactory_state openfactory_toolbox openfactory_repos openfactory_logs; do\n'
     '  docker run --rm -v "openfactory_$v:/v:ro"',
     'for v in temporal_db openfactory_state openfactory_toolbox openfactory_repos; do\n'
     '  docker run --rm -v "openfactory_$v:/v:ro"'),

    ("the page counts the volumes again, and the count goes stale", PAGE,
     "- **the Docker volumes**, which Compose names",
     "- **the five Docker volumes**, which Compose names"),

    ("a new writable host directory is mounted, and the page does not know it", COMPOSE,
     "      - /var/run/docker.sock:/var/run/docker.sock\n",
     "      - /var/run/docker.sock:/var/run/docker.sock\n"
     "      - ${OPENFACTORY_CACHE_DIR:-/var/cache/openfactory}:/var/cache/openfactory\n"),

    ("the guidelines mount becomes writable, and the page still says it needs no backup", COMPOSE,
     "${OPENFACTORY_GUIDELINES_DIR:-${HOME}/openfactory/guidelines}:ro",
     "${OPENFACTORY_GUIDELINES_DIR:-${HOME}/openfactory/guidelines}"),

    ("a host path is written into the compose file itself, outside every setting", COMPOSE,
     "      - /var/run/docker.sock:/var/run/docker.sock\n",
     "      - /var/run/docker.sock:/var/run/docker.sock\n      - ./data:/var/lib/data\n"),
]
