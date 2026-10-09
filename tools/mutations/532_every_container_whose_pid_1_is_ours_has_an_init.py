"""Every container whose PID 1 is one of our processes has an init that reaps orphans (#532),
proven by breaking it.

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/532_every_container_whose_pid_1_is_ours_has_an_init.py

Measured on v0.5.0-rc.1: the worker's and the panel's PID 1 were our Python processes, with
`HostConfig.Init` unset, and every orphan — git's detached auto-maintenance, about 7 a minute —
stayed a zombie; a panel ran out of processes after 39 hours. The claims, each a row:

  1. every compose service that runs one of our images declares `init: true` — the worker, the
     panel, and the build-only services alike (rows 1-3);
  2. the panel runs under the worker image's init, never an entrypoint of its own (row 4);
  3. the box is started with `docker run --init` (row 5);
  4. the worker and sandbox images start `tini -s --`, and install it (rows 6-9).
"""

TEST = "tests/test_every_container_whose_pid_1_is_ours_has_an_init.py"

COMPOSE = "docker-compose.yml"
CONTAINER = "openfactory/adapters/sandbox/container.py"
WORKER = "docker/worker.Dockerfile"
SANDBOX = "docker/sandbox.Dockerfile"
BASE = "docker/base-python.Dockerfile"

_WORKER_ENTRYPOINT = ('ENTRYPOINT ["tini", "-s", "--"]\n'
                      'CMD ["python", "-m", "openfactory.runtime.temporal.worker"]\n')

MUTATIONS = [
    ("TODAY'S DEFECT, ON THE WORKER: its PID 1 is our process and reaps nothing", COMPOSE,
     "    # carries `tini -s` as well, for a runtime that starts it with no init at all.\n"
     "    init: true\n",
     "    # carries `tini -s` as well, for a runtime that starts it with no init at all.\n"),
    ("the panel runs with no init", COMPOSE,
     "    # An init as PID 1, as on the worker (#532): the panel's git work orphans the same "
     "children.\n    init: true\n",
     ""),
    ("a build-only service of ours runs with no init", COMPOSE,
     "    image: ghcr.io/open-factory-digital/openfactory-base:${OPENFACTORY_VERSION:-main}\n"
     "    init: true  # one of our images, so an init as PID 1 (#532), as on the worker\n",
     "    image: ghcr.io/open-factory-digital/openfactory-base:${OPENFACTORY_VERSION:-main}\n"),
    ("the panel brings an entrypoint of its own, past the image's init", COMPOSE,
     '    command: ["python", "-m", "openfactory.cli", "serve", "--host", "0.0.0.0", "--port", '
     '"8787"]\n',
     '    command: ["python", "-m", "openfactory.cli", "serve", "--host", "0.0.0.0", "--port", '
     '"8787"]\n    entrypoint: []\n'),

    ("the box's PID 1 is `sleep`, with no init", CONTAINER,
     '            "--init",\n',
     ""),

    ("the worker image starts with no init", WORKER,
     _WORKER_ENTRYPOINT,
     'CMD ["python", "-m", "openfactory.runtime.temporal.worker"]\n'),
    ("the worker image's tini is no subreaper, so under the daemon's init it reaps nothing it "
     "inherits", WORKER,
     _WORKER_ENTRYPOINT,
     'ENTRYPOINT ["tini", "--"]\n'
     'CMD ["python", "-m", "openfactory.runtime.temporal.worker"]\n'),
    ("the worker image names a tini it does not install", WORKER,
     "poppler-utils tini \\\n",
     "poppler-utils \\\n"),
    ("the sandbox image starts a job with no init", SANDBOX,
     'ENTRYPOINT ["tini", "-s", "--"]\n',
     "ENTRYPOINT []\n"),
    ("the base the sandbox is built from does not install tini", BASE,
     "make build-essential tini \\\n",
     "make build-essential \\\n"),
]
