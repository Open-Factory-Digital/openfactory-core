"""Mutation plan for SECURITY.md's credential-reach paragraph and the guard that measures it
(2026-08-26).

THE CUTS ARE HOSTILE ON PURPOSE. The passage had already been wrong twice, and the second wording
was written by someone who did not run it — so restoring the old text proves nothing anybody
needed proving. What is cut here is the meaning while the VOCABULARY stays: the deny list keeps a
name spelled `OPENFACTORY_TRACKER_TOKEN…` that nothing reads, the document keeps the word
`AZURE_DEVOPS_PAT` while moving it out of the claim, the anchors are renamed rather than deleted,
and the same defect arrives under a spelling nobody has seen (`OPENFACTORY_BOARD_TOKEN`). A guard
that survives any of those is a guard a reviewer walks through.

Point-in-time proof; anchors rot as code moves and fail loudly on rerun.
"""

TEST = "tests/test_the_environment_carries_the_products_name.py"

WORKTREE = "openfactory/adapters/sandbox/worktree.py"
CONTAINER = "openfactory/adapters/sandbox/container.py"
CREDENTIALS = "openfactory/credentials.py"
SECURITY = "SECURITY.md"
ENVIRON = "openfactory/environ.py"

MUTATIONS = [
    # ── the defect itself, and the same defect wearing the right word ───────────────────────────
    ("the tracker spelling leaves the deny list again",
     WORKTREE,
     '    "OPENFACTORY_TRACKER_TOKEN",\n',
     ""),
    ("the deny list keeps the vocabulary and denies a name nothing serves",
     WORKTREE,
     '    "OPENFACTORY_TRACKER_TOKEN",\n',
     '    "OPENFACTORY_TRACKER_TOKEN_LEGACY",\n'),
    ("a deny list names a retired spelling as a precaution",
     WORKTREE,
     '    "OPENFACTORY_GH_APP_ID",\n',
     '    "OPENFACTORY_GH_APP_ID",\n    "OPENFACTORY_RETIRED_BOT_TOKEN",\n'),
    # ── the same hole through a spelling nobody has seen ────────────────────────────────────────
    ("one credential grows a third override that no list carries",
     CREDENTIALS,
     '    return (os.environ.get("OPENFACTORY_TRACKER_TOKEN")\n',
     '    return (os.environ.get("OPENFACTORY_BOARD_TOKEN")\n'
     '            or os.environ.get("OPENFACTORY_TRACKER_TOKEN")\n'),
    ("a new credential the platform reads reaches the agent unannounced",
     CREDENTIALS,
     "",
     '\n\nVAULT = os.environ.get("OPENFACTORY_VAULT_TOKEN")\n'),
    # ── the scrub stops scrubbing, in the two ways that still read as a scrub ───────────────────
    ("the scrub drops a whole credential family",
     WORKTREE,
     "    for var in _AWS_CRED_VARS + _FORGE_CRED_VARS + _AGENT_CRED_VARS:",
     "    for var in _AWS_CRED_VARS + _AGENT_CRED_VARS:"),
    ("the scrub removes exactly what the project asked to keep",
     WORKTREE,
     "        if var not in kept:",
     "        if var in kept:"),
    ("the box.env seam widens until it keeps everything",
     WORKTREE,
     "    kept = {v for v in keep if v}",
     "    kept = set(os.environ)"),
    # ── the second vendor, which is how the last table went stale ───────────────────────────────
    ("a third vendor ships a credential and the table does not hear of it",
     "openfactory/adapters/credential/registry.py",
     'SHIPPED_ENV: dict[str, str] = {\n    "jira": "JIRA_API_TOKEN",',
     'SHIPPED_ENV: dict[str, str] = {\n    "gitlab": "GITLAB_TOKEN",\n'
     '    "jira": "JIRA_API_TOKEN",'),
    # ── the allow-list box, which is why the paragraph is not alarmist ──────────────────────────
    ("the container box's allow list grows and the document does not",
     CONTAINER,
     '_AUTH_ENV_VARS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")',
     '_AUTH_ENV_VARS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")'),
    ("the container box passes the worker's whole environment",
     CONTAINER,
     "        for var in (*_AUTH_ENV_VARS, *self.extra_env):",
     "        for var in (*_AUTH_ENV_VARS, *self.extra_env, *os.environ):"),
    # ── the document, cut the way a reviewer cuts a document ────────────────────────────────────
    ("the table keeps the name and moves it out of the claim",
     SECURITY,
     "| `AZURE_DEVOPS_PAT`, `JIRA_API_TOKEN` | the shipped default credential for the two "
     "non-GitHub vendors.",
     "| `JIRA_API_TOKEN` | the shipped default credential for the two non-GitHub vendors, "
     "`AZURE_DEVOPS_PAT` among them."),
    ("the table drops a row that is still true",
     SECURITY,
     "  | `TEMPORAL_API_KEY`, `TEMPORAL_TLS_KEY` | the orchestrator connection's API key, and "
     "the path to its client key. |\n",
     ""),
    ("the anchors are renamed and the table left standing",
     SECURITY,
     "  <!-- reaches-the-agent -->",
     "  <!-- the credentials below -->"),
    ("the sentence keeps its shape and loses its count",
     SECURITY,
     "<!-- reach-count -->13<!-- /reach-count -->",
     "<!-- reach-count -->14<!-- /reach-count -->"),
    ("the prose reassures about a credential the table says reaches the agent",
     SECURITY,
     "  Anything that lets workload code reach a credential outside that set is a vulnerability",
     "  `AZURE_DEVOPS_PAT` never leaves the framework's own process.\n\n"
     "  Anything that lets workload code reach a credential outside that set is a vulnerability"),
    ("the sentence that carries the count is rewritten away",
     SECURITY,
     "these\n  <!-- reach-count -->13<!-- /reach-count --> are the ones a worktree workload can "
     "read today:",
     "these are the credentials a worktree workload can read today:"),
    # ── and the derivation itself, since every row above trusts it ──────────────────────────────
    ("the AST scan stops finding what the platform reads",
     ENVIRON,
     "    base = root if root is not None else Path(__file__).resolve().parent",
     "    return frozenset()\n"
     "    base = root if root is not None else Path(__file__).resolve().parent"),
]
