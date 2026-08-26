"""#162 (cli.py:408): a project is not registered as a vendor nobody asked for."""

TEST = "tests/test_a_project_is_not_registered_as_the_wrong_vendor.py"
CLI = "openfactory/cli.py"

MUTATIONS = [
    ("every non-Azure URL is labelled GitHub again", CLI,
     "        foreign = _foreign_host(repo_path)\n        if foreign:", "        if False:"),

    ("…and the reverse: a GitHub URL is refused too, so nothing registers", CLI,
     '    return "" if any(host == o or host.endswith("." + o) for o in ours) else host',
     "    return host"),

    # NOT "delete the `if not host` early return" — with no host the `ours` check answers `""`
    # anyway, so the cut changes nothing. The claim worth making is that a path never reaches the
    # refusal at all, which this does:
    ("a LOCAL path is treated as a foreign host", CLI,
     '    if not host:\n        return ""', '    if not host:\n        return "unknown"'),

    ("an ssh remote's host stops being read", CLI,
     '    elif raw.startswith("git@") and ":" in raw:\n'
     '        host = raw.split("@", 1)[1].split(":", 1)[0]',
     '    elif False:\n        host = ""'),

    ("a GitHub ENTERPRISE host stays foreign however the deployment declares it", CLI,
     '    ours = {(os.environ.get("GH_HOST") or os.environ.get("GITHUB_HOST")\n'
     '             or "github.com").strip().lower(), "github.com", "dev.azure.com", '
     '"ssh.dev.azure.com",\n'
     '            "visualstudio.com"}',
     '    ours = {"github.com", "dev.azure.com", "ssh.dev.azure.com", "visualstudio.com"}'),

    ("the known-forge list is hand-written instead of read", CLI,
     "    from openfactory.adapters.forge.registry import FORGES\n\n    return sorted(FORGES)",
     '    return ["github"]'),

    ("the refusal stops naming the host it saw", CLI,
     '            typer.echo(f"✗ {foreign} is not a forge this build implements — known: "',
     '            typer.echo(f"✗ that is not a forge this build implements — known: "'),

    ("…and stops offering the Enterprise remedy", CLI,
     '                       f"  · a GitHub ENTERPRISE host: set GH_HOST={foreign} and re-run — '
     'this "\n                       f"platform honours it everywhere it builds a URL\\n"', ""),

    ("the row is written BEFORE the refusal", CLI,
     "        foreign = _foreign_host(repo_path)\n        if foreign:",
     "        reg.add(Project(name=name, repo_path=repo_path,\n"
     '                        tracker=ProviderRef(kind="github", repo="o/r", options={})))\n'
     "        foreign = _foreign_host(repo_path)\n        if foreign:"),

    ("the Azure refusal is replaced by the generic one", CLI,
     '            typer.echo(f"✗ that is an Azure DevOps URL — register with `openfactory project '
     'add "', '            typer.echo(f"✗ unsupported vendor — see docs. `openfactory project '
     'add "'),
]
