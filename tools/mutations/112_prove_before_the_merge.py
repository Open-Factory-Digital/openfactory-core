"""#112: a manifest on a branch can be measured, and measuring it never authorises anything.

The dangerous reverse is the first cut. A branch proof written where the poller looks satisfies
the gate that holds pickup on the BASE branch — work would then run against a manifest nobody
merged, and the deployment would look correct while doing it. The other reverses: the base
branch's own proof must keep recording, and the base branch's checkout must not be replaced by
whatever branch was last measured.
"""

TEST = "tests/test_a_manifest_can_be_proven_before_it_is_merged.py"
CLI = "openfactory/cli.py"
FACTORY = "openfactory/factory.py"

MUTATIONS = [
    ("a branch proof is recorded where the poller looks, unlocking an unmerged manifest", CLI,
     "    where = None if ref else save(proof)",
     "    where = save(proof)"),

    ("…and the reverse: the base branch's proof stops being recorded at all", CLI,
     "    where = None if ref else save(proof)",
     "    where = None if not ref else save(proof)"),

    ("the ref shares the base branch's checkout key and replaces its tree", CLI,
     '            ref_root = resolve_repo_path(view, cache_key=f"{proof_key}@{safe}", ref=ref)',
     "            ref_root = resolve_repo_path(view, cache_key=proof_key, ref=ref)"),

    ("the ref is never handed down, so a branch proof silently measures the base branch", CLI,
     '            ref_root = resolve_repo_path(view, cache_key=f"{proof_key}@{safe}", ref=ref)',
     '            ref_root = resolve_repo_path(view, cache_key=f"{proof_key}@{safe}")'),

    ("a ref's slash reaches the directory name", CLI,
     '        safe = _re.sub(r"[^A-Za-z0-9._-]", "-", ref)',
     "        safe = ref"),

    ("the measurement is announced in the word the recorded verdict uses", CLI,
     '        typer.echo(f"{\'WOULD PROVE\' if proof.ok else \'WOULD NOT PROVE\'} — measured on {ref!r}, "',
     '        typer.echo(f"{\'PROVEN\' if proof.ok else \'NOT PROVEN\'} — measured on {ref!r}, "'),

    ("a failing branch exits 0, so a script proposing a manifest reads it as fine", CLI,
     "        raise typer.Exit(0 if proof.ok else 1)",
     "        raise typer.Exit(0)"),

    ("an unreadable ref raises instead of refusing by name", CLI,
     '            typer.echo(f"✗ could not read {namespace.MANIFEST} on {ref!r} ({str(exc)[:200]}) — "\n'
     '                       f"check that the branch exists on the forge and carries the file. "\n'
     '                       f"Nothing was changed.")\n'
     "            raise typer.Exit(2) from None",
     "            raise"),

    # ── the local-path half (review of #119) ────────────────────────────────────────────────────
    ("a locally-registered project ignores the ref and measures the working tree", FACTORY,
     "        return _worktree_at(local, ref, cache_key or project.name) if ref else local",
     "        return local"),

    ("…and the reverse: a project with NO ref gets a worktree instead of its own tree", FACTORY,
     "        return _worktree_at(local, ref, cache_key or project.name) if ref else local",
     "        return _worktree_at(local, ref, cache_key or project.name)"),

    ("the second checkout claims the branch, so measuring the branch you are on fails", FACTORY,
     '    rc, out = _git(["-C", str(repo), "worktree", "add", "--detach", str(dest), ref])',
     '    rc, out = _git(["-C", str(repo), "worktree", "add", str(dest), ref])'),

    ("a stale worktree is left registered, so measuring one ref twice fails the second time",
     FACTORY,
     '        _git(["-C", str(repo), "worktree", "remove", "--force", str(dest)])\n'
     "        if dest.exists():\n"
     "            shutil.rmtree(dest, ignore_errors=True)",
     "        pass"),

    ("a path that is not a repository reaches git instead of a sentence", FACTORY,
     '    if not (repo / ".git").exists():', "    if False:"),

    ("a ref nobody fetched reaches git instead of a sentence naming `git fetch`", FACTORY,
     '    if _git(["-C", str(repo), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"])[0] != 0:',
     "    if False:"),

    ("the seam ignores the ref and syncs the base branch whatever the caller asked for", FACTORY,
     '                                ref or load_manifest_base_branch(project, default=""))',
     '                                load_manifest_base_branch(project, default=""))'),
]
