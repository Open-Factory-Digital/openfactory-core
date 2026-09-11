"""ADR-0049 slice 7, proven by breaking it — the roles run on the local rows.

FOUR CLAIMS:

  1. **The context repository is a bare one the installation owns**, created idempotently — and a
     context name never resolves to the person's own repository.
  2. **The factory's own board on this row is the project's own tracker, labelled `fabrica`** —
     and a deployment that declared one still gets what it declared, on every row.
  3. **`project init` switches the product role on for a path** and leaves a hosted registration
     alone, where naming a requirements repository is an operator's decision about somebody
     else's organisation.
  4. **The manifest is scaffolded with the branch this checkout is on**, and the closing lines
     name the one thing no command can do — which is not the same thing on both doors.

The guard under test is `tests/test_the_roles_run_on_the_local_rows.py`.
"""

TEST = "tests/test_the_roles_run_on_the_local_rows.py"

FORGE = "openfactory/adapters/forge/local.py"
OPS = "openfactory/ops/impediment.py"
CLI = "openfactory/cli.py"

MUTATIONS = [
    # ── 1. the context repository ──────────────────────────────────────────────────────────────
    ("the context repository is created with a working tree, so the first push is refused",
     FORGE,
     '        made = subprocess.run(["git", "init", "--bare", "-b", "main", str(where)],',
     '        made = subprocess.run(["git", "init", "-b", "main", str(where)],', TEST),

    ("creating it twice reports a fresh one, so a retry tells a client we made them a repository",
     FORGE,
     '        if (where / "HEAD").exists():\n            return name, False',
     '        if False:\n            return name, False', TEST),

    ("a context name resolves to the person's OWN repository, where their code lives", FORGE,
     '        name = (repo or "").strip()\n        if not name or name == self.project:',
     '        name = (repo or "").strip()\n        if True:', TEST),

    ("a refused `git init` reads as success, so the role fails an hour later writing a "
     "requirement", FORGE,
     '        if made.returncode != 0 or not (where / "HEAD").exists():', '        if False:',
     TEST),

    # ── 2. the factory's own board ─────────────────────────────────────────────────────────────
    ("the impediment has nowhere to go again on the one deployment with no second board", OPS,
     '    if (getattr(tracker, "kind", "") or "").strip().lower() != "local":\n        return None',
     '    return None', TEST),

    ("the factory's cards stop being marked as its own, on the person's own board", OPS,
     '    return FactoryBoard(tracker=tracker)',
     '    return FactoryBoard(tracker=tracker, label="")', TEST),

    ("a declared board is overridden by the derived one", OPS,
     '    declared = getattr(project, "factory_board", None)\n    if declared is not None:\n'
     '        return declared',
     '    declared = getattr(project, "factory_board", None)\n    if False:\n'
     '        return declared', TEST),

    # ── 3. the product section ─────────────────────────────────────────────────────────────────
    ("the product role stays off on the runtime that can host it", CLI,
     '            kwargs["product"] = ProductConfig(docs_repo=f"{name}-context")\n', "", TEST),

    ("every hosted registration is switched on too, naming a repository nobody decided on", CLI,
     '        if kind == "local":\n'
     '            # `ci: none` is a row any forge may declare (slice 3b) and the only honest '
     'answer for', '        if True:\n'
     '            # `ci: none` is a row any forge may declare (slice 3b) and the only honest '
     'answer for', TEST),

    # ── 4. the branch, and the last sentence ───────────────────────────────────────────────────
    # RE-PINNED 2026-09-11: the scaffold gained the `docs_repo:` line for a local project, so the
    # branch substitution is now a statement of its own rather than an argument to `write_text`.
    ("the manifest names a branch this repository does not have", CLI,
     '                scaffold = _MANIFEST_TEMPLATE.replace("base_branch: main",\n'
     '                                                      f"base_branch: {base_branch}")',
     '                scaffold = _MANIFEST_TEMPLATE', TEST),

    ("the last sentence sends somebody to configure access to a repository they own", CLI,
     '    if registered_local:\n'
     '        typer.echo(f"two things no command can do for you — commit '
     '`.openfactory/project.yaml` on "',
     '    if False:\n'
     '        typer.echo(f"two things no command can do for you — commit '
     '`.openfactory/project.yaml` on "', TEST),
]
