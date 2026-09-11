"""#162 (cli.py:408): a project is not registered as a vendor nobody asked for."""

TEST = "tests/test_a_project_is_not_registered_as_the_wrong_vendor.py"
CLI = "openfactory/cli.py"
#: RE-PINNED 2026-09-10 (ADR-0049 slice 4a). The door helpers moved to `openfactory/doors.py` so
#: the API could reach the same answers the command line had — `POST /api/projects` is a door too,
#: and while it could not reach them it asked no host at all. Every claim below is unchanged; six
#: cut it one file along, and three cut a shape that moved: the refusal has one definition
#: (`_foreign_refusal`), the host is read once (`_host_in`), and the kind comes from `kind_for`.
DOORS = "openfactory/doors.py"

MUTATIONS = [
    # six rows re-pinned 2026-09-07: `foreign_host` takes the operator's `--provider`, answers
    # through `shipped_hosts`/`host_owner`, and the known kinds come from the plugin loader
    ("every non-Azure URL is labelled GitHub again", CLI,
     "        if foreign:\n            typer.echo(_foreign_refusal(foreign, provider))",
     "        if False:\n            typer.echo(_foreign_refusal(foreign, provider))"),

    ("…and the reverse: a GitHub URL is refused too, so nothing registers", DOORS,
     '    return next((kind for kind, owned in shipped_hosts().items()\n'
     '                 if any(host == o or host.endswith("." + o) for o in owned)), "")',
     '    return ""'),

    # NOT "delete the `if not host` early return" — with no host the `ours` check answers `""`
    # anyway, so the cut changes nothing. The claim worth making is that a path never reaches the
    # refusal at all, which this does:
    ("a LOCAL path is treated as a foreign host", DOORS,
     '    host = _host_in(raw)\n    if not host:\n        return ""',
     '    host = _host_in(raw)\n    if not host:\n        return "unknown"'),

    ("an ssh remote's host stops being read", DOORS,
     '    elif raw.startswith("git@") and ":" in raw:\n'
     '        host = raw.split("@", 1)[1].split(":", 1)[0]',
     '    elif False:\n        host = ""'),

    ("a GitHub ENTERPRISE host stays foreign however the deployment declares it", DOORS,
     '    github = {(os.environ.get("GH_HOST") or os.environ.get("GITHUB_HOST") or "github.com")\n'
     '              .strip().lower(), "github.com"}',
     '    github = {"github.com"}'),

    ("the known-forge list is hand-written instead of read", DOORS,
     '    return plugins.known("forge", FORGES)',
     '    return ["github"]'),

    # MOVED 2026-09-10 (ADR-0049 slice 4c): the CLAIM left `cli.py` for `doors.foreign_refusal`,
    # because the panel's door needs the same sentence and a browser form has no flags to offer.
    # The ways out stayed behind, which is why the row below still cuts `cli.py`.
    ("the refusal stops naming the host it saw", DOORS,
     '    return (f"{foreign} is not a forge this build implements — known: "',
     '    return (f"that is not a forge this build implements — known: "'),

    ("…and stops offering the Enterprise remedy", CLI,
     '            + f"  · a GitHub ENTERPRISE host: set GH_HOST={foreign} and re-run — this "\n'
     '            f"platform honours it everywhere it builds a URL\\n"\n', ""),

    ("the row is written BEFORE the refusal", CLI,
     '        try:\n            foreign = doors.foreign_host(repo_path, provider=provider or "")\n',
     "        reg.add(Project(name=name, repo_path=repo_path,\n"
     '                        tracker=ProviderRef(kind="github", repo="o/r", options={})))\n'
     '        try:\n            foreign = doors.foreign_host(repo_path, provider=provider or "")\n'),

    ("the Azure refusal is replaced by the generic one", CLI,
     '            typer.echo(f"✗ that is an Azure DevOps URL — register with `openfactory project '
     'add "', '            typer.echo(f"✗ unsupported vendor — see docs. `openfactory project '
     'add "'),
]
