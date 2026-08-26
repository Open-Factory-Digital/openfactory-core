"""The two pages wave 3 read but did not rewrite — architecture.md's seam table and the links that
dangle at export — have guards, and every one goes red on the cut a later editor would make.

Ported onto main from 3724056 (2026-08-26) after the fix round (65a0522) had re-pointed the same
links and moved the two cloud documents under `addons/openfactory-aws/docs/`: the link cuts aim
at that path (the `addons/` row of STATUS's table), and the notifier row carries the
`notifier.telegram` add-on row the fallback became.

The cuts are on DOCUMENTS: a registry row dropped from the seam table, a kind promised that no
registry ships, an add-on row a package declares that the table stops naming, a cloud row that
stops naming its add-on package, a wrong entry-point axis, the group name gone, Telegram
described as switched on by its variables again, a row deleted whole, a link put back to a
document that leaves the public tree — and one on the metadata reader, which must read ONE
distribution's rows and not the group's union.
"""

TEST = "tests/test_the_docs_do_not_drift.py"
CUT = "tests/test_the_public_cut_is_written_down.py"
CLOUD = "tests/test_the_cloud_is_a_directory_delete.py"

MUTATIONS = [
    ("the tracker row loses Azure DevOps, which the registry ships",
     "docs/architecture.md",
     "TrackerAdapter        github · jira · azure_devops",
     "TrackerAdapter        github · jira               "),
    ("the forge row promises a kind no registry ships",
     "docs/architecture.md",
     "ForgeAdapter          github · azure_devops        ",
     "ForgeAdapter          github · azure_devops · gitlab"),
    ("the harness row loses OpenCode",
     "docs/architecture.md",
     "claude_code · codex · kimi · opencode",
     "claude_code · codex · kimi           "),
    ("the CI row names one alias of a builder and drops the other builder entirely",
     "docs/architecture.md",
     "github_actions · azure_pipelines",
     "github_actions · github         "),
    ("the sandbox row stops framing the cloud box as an add-on package",
     "docs/architecture.md",
     "container · worktree · a cloud box (an add-on package: openfactory-aws)",
     "container · worktree · a cloud box                                     "),
    ("the notifier row drops the telegram row the chat package declares",
     "docs/architecture.md",
     "panel · slack · telegram (an add-on package: openfactory-slack)",
     "panel · slack (an add-on package: openfactory-slack)           "),
    ("the notifier row names its add-on rows under a package STATUS does not know",
     "docs/architecture.md",
     "panel · slack · telegram (an add-on package: openfactory-slack)",
     "panel · slack · telegram (an add-on package: openfactory-chat) "),
    ("the CI row tells a stranger the axis is called `environment`",
     "docs/architecture.md",
     "azure_pipelines                           ci.<kind>",
     "azure_pipelines                           environment.<kind>"),
    ("§6 stops naming the entry-point group",
     "docs/architecture.md",
     "the `openfactory.adapters` entry-point group; its rows join",
     "the entry-point group; its rows join"),
    ("the notifier row is deleted whole",
     "docs/architecture.md",
     "   notifier    Notifier              panel · slack · telegram (an add-on package: "
     "openfactory-slack)   notifier.<kind>\n",
     ""),
    ("Telegram is called a stub again while STATUS still lists its row",
     "docs/architecture.md",
     "reached only as the deployment-wide fallback — the row",
     "reached only as a stub — the row"),
    ("the sentence stops naming the variable that declares the fallback",
     "docs/architecture.md",
     "`OPENFACTORY_NOTIFIER_FALLBACK=telegram` declares for a caller",
     "the deployment declares for a caller"),
    ("the sentence stops naming the package that declares the row",
     "docs/architecture.md",
     "`openfactory-slack` add-on package declares, reached",
     "chat add-on package declares, reached"),
    ("the sentence stops saying Telegram's module leaves while STATUS still excludes it",
     "docs/architecture.md",
     "and its module leaves the public tree with the",
     "and its module ships in the public tree with the"),
    ("the glossary links the runtime document that left with the cloud package",
     "docs/glossary.md",
     "See [`architecture.md`](architecture.md) for how they fit",
     "See [`runtime-architecture.md`](../addons/openfactory-aws/docs/runtime-architecture.md) "
     "for how they fit",
     CUT),
    ("the reader's map links the deployment document that left, under an anchor",
     "docs/README.md",
     "| the `openfactory-aws` add-on package | putting this on a cloud:",
     "| [DEPLOYMENT.md](../addons/openfactory-aws/docs/DEPLOYMENT.md#compose) | putting this on a cloud:",
     CUT),
    ("the metadata reader reads the group's union instead of one distribution's rows",
     CLOUD,
     "    return {p.name: p.value for p in dist.entry_points if p.group == plugins.GROUP}",
     "    from importlib.metadata import entry_points\n\n"
     "    return {p.name: p.value for p in entry_points(group=plugins.GROUP)}",
     CLOUD),
    ("the metadata reader stops filtering by group, so a console script is a row",
     CLOUD,
     "    return {p.name: p.value for p in dist.entry_points if p.group == plugins.GROUP}",
     "    return {p.name: p.value for p in dist.entry_points}",
     CLOUD),
]
