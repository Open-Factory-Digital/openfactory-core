"""The preview removes exactly the images its own Compose document built (#265 slice 2)."""

TEST = "tests/test_the_compose_row_runs_what_was_admitted.py"
COMPOSE = "openfactory/adapters/preview/compose.py"

MUTATIONS = [
    ("a preview leaves its tagged build images on the daemon", COMPOSE,
     "        for image in built_images:\n",
     "        for image in []:\n"),
    ("a preview forgets which services it built", COMPOSE,
     '                                    and "build" in spec and "image" not in spec]\n',
     '                                    and False]\n'),
    ("the cleanup also tries to remove an image-only service", COMPOSE,
     '                                    and "build" in spec and "image" not in spec]\n',
     '                                    and ("build" in spec or "image" in spec)]\n'),
]
