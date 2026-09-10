"""ADR-0049 slice 4a, proven by breaking it — a path registers as `local`, at every door.

FOUR CLAIMS:

  1. **The kind is read from the address**, in D2's four readings: a named kind is the operator's,
     Azure coordinates name Azure, any other URL takes its host's kind, and a filesystem path is
     `local` unless coordinates came with it.
  2. **`local` is written on EVERY axis.** An axis left unwritten inherits `ProviderRef`'s
     `github` default and takes the deployment's GitHub credential with it.
  3. **A path with coordinates keeps the hosted kind** — a mounted checkout of a hosted repository
     is a shape that runs today and must keep running (`tests/test_api.py` is its pin, unedited).
  4. **Every registering door asks the same two questions.** `project add` and `POST /api/projects`
     asked neither; the third refused a foreign host by name. Two doors into one registry,
     disagreeing about the same address.

WHAT THE FIRST RUN FOUND, and it was a line of mine: `kind_for` read the Azure DevOps coordinates
out of the URL before reading its host, and DELETING THAT LINE CHANGED NO ANSWER — all three
shapes ADO hands out live on hosts `shipped_hosts` already names. It bought one wrong answer,
though: an ADO address pasted without its `_git` segment reads as no coordinates at all and fell
through to `github`, so a project on somebody's Azure organisation was written as a GitHub row.
Removing it made two more cuts visible — the URL reading itself, and the subdomain match the
legacy `*.visualstudio.com` hosts need — which had been hidden behind it.

The guards under test are `tests/test_a_path_registers_itself.py` and the doors-derive suite.
"""

TEST = "tests/test_a_path_registers_itself.py"

SLICE = "tests/test_a_path_registers_itself.py"
DOORS_TEST = "tests/test_the_doors_derive_from_the_registries.py"

DOORS = "openfactory/doors.py"
CLI = "openfactory/cli.py"
API = "openfactory/api/app.py"

MUTATIONS = [
    # ── 1. the reading ─────────────────────────────────────────────────────────────────────────
    ("a bare path falls back to GitHub again — the person's own repository registered as one on "
     "a host they have no account on", DOORS,
     '    return "github" if (repo or "").strip() else "local"',
     '    return "github"', SLICE),

    ("a path WITH coordinates is taken as local, so a mounted checkout of a hosted repository "
     "stops being registerable", DOORS,
     '    return "github" if (repo or "").strip() else "local"',
     '    return "local"', SLICE),

    ("a URL is typed by its shape rather than by its host, so every URL is GitHub", DOORS,
     '    if "://" in raw or raw.startswith("git@"):\n        return host_owner(raw) or "github"',
     '    if "://" in raw or raw.startswith("git@"):\n        return "github"', SLICE),

    ("the kind the operator NAMED is overridden by the address", DOORS,
     '    chosen = (provider or "").strip().lower()\n    if chosen:\n        return chosen',
     '    chosen = ""', SLICE),

    ("the host reading loses its subdomains, so a GitHub Enterprise host reads as nobody's",
     DOORS,
     '    return next((kind for kind, owned in shipped_hosts().items()\n'
     '                 if any(host == o or host.endswith("." + o) for o in owned)), "")',
     '    return next((kind for kind, owned in shipped_hosts().items()\n'
     '                 if host in owned), "")', SLICE),

    # ── 2. every axis ──────────────────────────────────────────────────────────────────────────
    ("`project add` writes the tracker alone for a local project, so the forge inherits GitHub",
     CLI,
     '        local = {"kind": "local", "repo": name, "options": {}}\n'
     '        kwargs["tracker"] = ProviderRef(**local)\n'
     '        kwargs["forge"] = ProviderRef(**local)\n'
     '        kwargs["ci"] = ProviderRef(kind="none", repo=name, options={})',
     '        kwargs["tracker"] = ProviderRef(kind="local", repo=name, options={})', SLICE),

    ("the local row carries no repo, and four consumers need it non-empty", CLI,
     '        local = {"kind": "local", "repo": name, "options": {}}',
     '        local = {"kind": "local", "repo": None, "options": {}}', SLICE),

    ("the API door writes the tracker alone again", API,
     '        axes = {"tracker": ProviderRef(kind="local", repo=body.name),\n'
     '                "forge": ProviderRef(kind="local", repo=body.name),\n'
     '                "ci": ProviderRef(kind="none", repo=body.name)}',
     '        axes = {"tracker": ProviderRef(kind="local", repo=body.name)}', SLICE),

    ("`project init` leaves the ci axis unwritten for a local project", CLI,
     '            kwargs["ci"] = ProviderRef(kind="none", repo=inferred, options={})', "",
     DOORS_TEST),

    # ── 3. the doors stop asking ───────────────────────────────────────────────────────────────
    ("the API model carries a vendor default again, so the panel registers every project as "
     "GitHub", API, '    provider: str = ""', '    provider: str = "github"', SLICE),

    ("`project add` stops asking whose host it is — the #162 door, reopened at the door beside "
     "the one that closed it", CLI,
     "    try:\n        foreign = doors.foreign_host(repo_path, provider=provider or \"\")\n"
     "    except ValueError as exc:\n        typer.echo(f\"✗ {exc}\")\n"
     "        raise typer.Exit(2) from None\n    if foreign:\n"
     "        typer.echo(_foreign_refusal(foreign, provider))\n        raise typer.Exit(2)\n",
     "", SLICE),

    # RE-PINNED 2026-09-10 (slice 4c): this door's copy of the sentence became
    # `doors.foreign_refusal(foreign)`, so the cut is the refusal itself going quiet — the row
    # is then written as GitHub, which is the claim this line has always been about.
    ("the API door stops asking whose host it is", API,
     "        raise HTTPException(status_code=422, detail=doors.foreign_refusal(foreign))",
     "        pass", SLICE),

    ("the refusal goes back to being written twice, and the copies drift", CLI,
     "            typer.echo(_foreign_refusal(foreign, provider))\n"
     "            raise typer.Exit(2) from None",
     '            typer.echo(f"✗ {foreign} is not supported")\n'
     "            raise typer.Exit(2) from None", DOORS_TEST),
]
