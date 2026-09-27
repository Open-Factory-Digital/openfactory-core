"""A card that names its base starts from that base, or does not start at all (#354).

ROWS 1-4 ARE THE WORKTREE BOX: the card's base never reached (the placeholder gone, so `worktree
add` dies on "invalid reference"), the worktree cut but never reset onto the forge's base, the
forge's "no such branch" said as a network failure, and a project with no forge starting from its
own HEAD instead of the base it was handed.

ROWS 5-7 ARE THE CONTAINER BOX: the forge never asked, the forge's "no such branch" said as a
network failure, and a project with no forge starting from its own HEAD.

ROWS 8-13 ARE THE REVIEW OF #355: the container box trusting the cache's stale copy of the card's
base over the forge; its fresh job saying nothing of the commit it started from, its `Workspace`
dropping that commit, and its diff spelled from the base's name, which the clone does not hold; a
reopened pull request measured from the name too; and the worktree box's failed reset said as a
failed read of the forge.
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
     "    _read_the_forges_base(host_clone, base_branch, remote_url)\n"
     "    return \"FETCH_HEAD\"",
     "    return base_branch"),

    ("the container box says a missing base as a network failure", CONTAINER,
     "        if _remote_has_no_such_branch(out):\n"
     "            raise RuntimeError(no_such_base(base_branch, \"the forge\"))",
     "        if False:\n"
     "            raise RuntimeError(no_such_base(base_branch, \"the forge\"))"),

    ("a container job with no forge starts from the clone's HEAD", CONTAINER,
     "                return rev\n"
     "        raise RuntimeError(no_such_base(base_branch, str(repo_path)))",
     "                return rev\n"
     "        return \"HEAD\""),

    ("the container box trusts the cache's stale copy of the card's base over the forge",
     CONTAINER,
     "    if not remote_url or _is_this_repo(remote_url, repo_path):\n"
     "        # THROUGH `_host`, like every other git step of this box, so there is one door to the host\n",
     "    for rev in (base_branch, f\"origin/{base_branch}\"):\n"
     "        if _host([\"git\", \"-C\", str(host_clone), \"rev-parse\", \"--verify\", \"--quiet\",\n"
     "                  f\"{rev}^{{commit}}\"])[0] == 0:\n"
     "            return rev\n"
     "    if not remote_url or _is_this_repo(remote_url, repo_path):\n"),

    ("a fresh container job says nothing of the commit it started from", CONTAINER,
     "    rc, out = _host([\"git\", \"-C\", str(host_clone), \"rev-parse\", \"HEAD\"])\n"
     "    return out.strip() if rc == 0 else None",
     "    return None"),

    ("the container box's workspace drops the commit its job started from", CONTAINER,
     "branch=branch, base_branch=base_branch, base_commit=base_commit)",
     "branch=branch, base_branch=base_branch)"),

    ("the container box's diff is spelled from the base's name, which its clone does not hold",
     CONTAINER,
     "            command=f\"git diff --name-only {workspace.diff_base}..HEAD\",",
     "            command=f\"git diff --name-only {workspace.base_branch}..HEAD\","),

    ("a reopened pull request on the container box is measured from the base's name", CONTAINER,
     "        if not remote_url or _is_this_repo(remote_url, repo_path):\n"
     "            return None\n"
     "        _read_the_forges_base(host_clone, base_branch, remote_url)",
     "        return None\n"
     "        _read_the_forges_base(host_clone, base_branch, remote_url)"),

    ("the worktree box says a failed reset as a failed read of the forge", WORKTREE,
     "            if read:\n"
     "                raise RuntimeError(\n"
     "                    f\"read {base_branch!r} from the forge, but could not reset",
     "            if False:\n"
     "                raise RuntimeError(\n"
     "                    f\"read {base_branch!r} from the forge, but could not reset"),
]
