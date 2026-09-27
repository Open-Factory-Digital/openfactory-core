"""A card that names its base starts from that base, or does not start at all (#354).

ROWS 1-4 ARE THE WORKTREE BOX: the card's base never reached (the placeholder gone, so `worktree
add` dies on "invalid reference"), the worktree cut but never reset onto the forge's base, the
forge's "no such branch" said as a network failure, and a project with no forge starting from its
own HEAD instead of the base it was handed.

ROWS 5-7 ARE THE CONTAINER BOX: the forge never asked, the forge's "no such branch" said as a
network failure, and a project with no forge starting from its own HEAD.
"""

TEST = "tests/test_a_card_s_base_is_the_base_the_job_starts_from.py"

WORKTREE = "openfactory/adapters/sandbox/worktree.py"
CONTAINER = "openfactory/adapters/sandbox/container.py"

MUTATIONS = [
    ("the worktree box never reaches a base its clone does not hold", WORKTREE,
     "        if not keep and start == base_branch and not _resolves(repo_path, base_branch):",
     "        if False:"),

    ("the worktree is cut from a placeholder and never reset onto the card's base", WORKTREE,
     "                remote_url=remote_url, from_base=start == base_branch or placeholder)",
     "                remote_url=remote_url, from_base=start == base_branch)"),

    ("the worktree box says a missing base as a network failure", WORKTREE,
     "            if _remote_has_no_such_branch(out):\n"
     "                raise RuntimeError(no_such_base(base_branch, \"the forge\"))\n"
     "            raise RuntimeError(\n"
     "                f\"could not read {base_branch!r} from the forge, so this job would start",
     "            raise RuntimeError(\n"
     "                f\"could not read {base_branch!r} from the forge, so this job would start"),

    ("a project with no forge starts from its own HEAD instead of the base it was handed", WORKTREE,
     "            if not remote_url or _is_this_repo(remote_url, repo_path):\n"
     "                raise RuntimeError(no_such_base(base_branch, str(repo_path)))\n"
     "            start, placeholder = \"HEAD\", True",
     "            start, placeholder = \"HEAD\", True"),

    ("the container box never asks the forge for the card's base", CONTAINER,
     "    rc, out = _host([\"git\", \"-C\", str(host_clone), \"fetch\", remote_url,",
     "    return base_branch\n    rc, out = _host([\"git\", \"-C\", str(host_clone), \"fetch\", remote_url,"),

    ("the container box says a missing base as a network failure", CONTAINER,
     "        if _remote_has_no_such_branch(out):\n"
     "            raise RuntimeError(no_such_base(base_branch, \"the forge\"))",
     "        if False:\n"
     "            raise RuntimeError(no_such_base(base_branch, \"the forge\"))"),

    ("a container job with no forge starts from the clone's HEAD", CONTAINER,
     "    if not remote_url or _is_this_repo(remote_url, repo_path):\n"
     "        raise RuntimeError(no_such_base(base_branch, str(repo_path)))",
     "    if not remote_url or _is_this_repo(remote_url, repo_path):\n"
     "        return \"HEAD\""),
]
