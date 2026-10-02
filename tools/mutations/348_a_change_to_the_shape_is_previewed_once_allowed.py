"""A change to the product's shape is previewed with its own shape once a person allows it (#348).

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/348_a_change_to_the_shape_is_previewed_once_allowed.py

Row 1 is the defect as it shipped: nothing ever runs the change's shape. Rows 2-3 break the
bound: any allowance runs whatever the change now says, and the change's shape runs unasked. Rows
4-6 break the overlay's walls: a write through a link, into a linked directory, outside the
repository. Rows 7-8 make the digest blind to the block and to an extended file. Row 9 drops the
card's sentence. Rows 10-11 break the record and the row: the digest not recorded, a digest nobody
measured allowed. Row 12 reads the change's manifest through a link out of its checkout, row 13
lets any panel credential allow it, and row 14 leaves the pull request untold.
"""

TEST = "tests/test_a_change_to_the_shape_is_previewed_once_allowed.py"

COMPOSE = "openfactory/adapters/preview/compose.py"
OWN = "openfactory/preview/own.py"
READ = "openfactory/preview/read.py"
ASSEMBLE = "openfactory/preview/assemble.py"
STEPS = "openfactory/preview/steps.py"
CAT = "openfactory/actions/catalog.py"

ALLOWED = "    if allowance and allowance[0] == found.digest:\n"

MUTATIONS = [
    ("TODAY'S DEFECT: a change to the shape is never previewed with its own", COMPOSE,
     ALLOWED, "    if False:\n"),

    ("an allowance runs whatever the change says now, not what was read", COMPOSE,
     ALLOWED, "    if allowance:\n"),

    ("the change's shape runs with nobody having allowed it", COMPOSE,
     ALLOWED, "    if True:\n        allowance = allowance or ('', '')\n"),

    ("the overlay writes through a link the base committed", OWN,
     "        if os.path.lexists(dest):\n"
     "            os.unlink(dest)\n"
     '        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", '
     "0),\n"
     "                     0o644)\n"
     '        with os.fdopen(fd, "w", encoding="utf-8") as fh:\n',
     '        with open(dest, "w", encoding="utf-8") as fh:\n'),

    ("the overlay walks into a directory that is a link out", OWN,
     "            if os.path.islink(here) or (os.path.lexists(here) and not os.path.isdir(here)):",
     "            if os.path.lexists(here) and not os.path.isdir(here):"),

    ("the overlay writes outside the repository the shape lives in", OWN,
     "        if not dest.startswith(root + os.sep):\n",
     "        if False:\n"),

    ("the digest is blind to the block", OWN,
     'json.dumps({"preview": cfg.model_dump(mode="json"), "files": files}, sort_keys=True)',
     'json.dumps({"files": files}, sort_keys=True)'),

    ("the digest is blind to a file only an `extends:` reaches", READ,
     "        texts[rel] = text\n",
     ""),

    ("the card says the base's shape ran when the change's did", ASSEMBLE,
     "            shape_said or \"the preview runs the base branch's version",
     "            \"the preview runs the base branch's version"),

    ("the record forgets the digest and which shape ran", STEPS,
     "            expires_at=int(planned.expires_at), why=\"\", stale=(),\n"
     "            own_shape=planned.own_shape, shape_from=planned.shape_from)",
     "            expires_at=int(planned.expires_at), why=\"\", stale=())"),

    ("the row allows a shape no start ever measured", CAT,
     "    if was is None or not was.own_shape:\n",
     "    if was is None:\n"),

    ("the change's manifest is read through a link out of its checkout", COMPOSE,
     "    if not where.startswith(root + os.sep) or not os.path.isfile(where):\n",
     "    if False:\n"),

    ("any panel credential may allow it, not only the product's admins", CAT,
     "    if not _a_product_admin(found, by):\n",
     "    if False:\n"),

    ("the pull request is not told its own shape was allowed", CAT,
     "        for url in was.pr_urls:\n"
     '            await asyncio.to_thread(forge.review_pr, pr=url, event="comment", body=said)\n',
     "        pass\n"),
]
