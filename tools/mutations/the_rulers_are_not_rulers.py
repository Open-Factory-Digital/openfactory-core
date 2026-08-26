"""The guards two reviewers walked through by hand, and the cuts that now stop them.

TWO REVIEWERS BROKE THIS ROUND'S PREDECESSORS WITHOUT TOUCHING THE TREE'S BEHAVIOUR (2026-08-26).
The worst left the launch blocker live under 23 green guards: `if [ -d "$p" ]` became
`if [ -f README.md ]` in `docker/worker.Dockerfile` — README.md is COPYied into that WORKDIR, so
the test is always true — and the public build went back to `pip install ./addons/openfactory-*`
and exit 1 on the first command README.md gives a stranger. The guard was reading the SHAPE of an
install loop. Shapes cannot be judged, so the loop is a script now and its guards RUN it.

The rest are the same failure in smaller shapes: a walk that knew one spelling of a thing with
three, an existence test that read as compliance, a word standing in for a claim, a count typed
beside a table that derives, a prefix exemption over a directory that ships.

EVERY ROW HERE IS A CUT A REVIEWER WOULD WRITE, not a revert. Where the old text would do, the
mutation keeps the vocabulary and inverts the meaning, or reaches the same defect through another
spelling the guard did not know.

Run: .venv/bin/python tools/mutate.py tools/mutations/the_rulers_are_not_rulers.py
"""

CUT = "tests/test_the_public_cut_is_written_down.py"
EXAMPLES = "tests/test_the_examples_a_reader_copies_load_on_the_core.py"
REMEDY = "tests/test_the_remedy_a_refusal_hands_you_can_be_followed.py"
OPERATOR = "tests/test_the_operator_path_names_what_the_code_mints.py"

TEST = CUT

MUTATIONS = [
    # ── the blocker, and the reviewer's own cut of it ───────────────────────────────────────────
    ("THE CUT THAT SHIPPED THE BLOCKER: the package test becomes a test of a file the COPY above "
     "always lands, and the directory test above it goes — the public build is handed a glob "
     "that matched nothing",
     "docker/install-addons.sh",
     '# NOT AN ERROR, AND THAT IS THE WHOLE POINT: this is what the public export looks like.\n'
     'if [ ! -d "$packages" ]; then\n'
     '    echo "install-addons: no \'$packages\' directory in this build context — the core alone" >&2\n'
     '    exit 0\n'
     'fi\n'
     '\n'
     'count=0\n'
     'for package in "$packages"/openfactory-*; do\n'
     '    # A glob that matched nothing leaves the pattern itself in "$package"; a README or a note\n'
     '    # beside the packages is not one. Either way there is nothing to install here.\n'
     '    [ -d "$package" ] || continue\n',
     'count=0\n'
     'for package in "$packages"/openfactory-*; do\n'
     '    [ -f README.md ] || continue\n'),

    ("the same cut with the directory test left standing: the public tree survives and the "
     "PRIVATE one installs the notes file beside the packages",
     "docker/install-addons.sh",
     '    [ -d "$package" ] || continue\n',
     '    [ -f README.md ] || continue\n'),

    ("a failing package install is swallowed and the image ships without it — the `|| exit 1` "
     "the old comment described and nothing measured",
     "docker/install-addons.sh",
     "set -eu\n",
     "set -u\n"),

    ("the install step stops installing the packages at all: green in both trees, and a private "
     "worker that refuses `channel: slack` by name",
     "docker/install-addons.sh",
     '    pip install --no-cache-dir "$package"\n',
     '    :\n'),

    # ── the same COPY in another spelling ───────────────────────────────────────────────────────
    ("the aborting COPY comes back in Docker's OTHER form, whose leading `[` read as an optional "
     "glob",
     "docker/worker.Dockerfile",
     "COPY addon[s] ./addons\n",
     'COPY ["addons", "./addons"]\n'),

    ("and in the plain form the blocker was first found in",
     "docker/sandbox.Dockerfile",
     "COPY addon[s] ./addons\n",
     "COPY addons ./addons\n"),

    ("an image stops copying the packages' directory: the script then finds nothing to install "
     "in the tree that has them",
     "docker/worker.Dockerfile",
     "COPY addon[s] ./addons\nRUN sh docker/install-addons.sh '.[runtime]'\n",
     "RUN sh docker/install-addons.sh '.[runtime]'\n"),

    ("the RUN throws the script's exit status away one word later: the script still decides "
     "correctly and the layer no longer cares",
     "docker/worker.Dockerfile",
     "RUN sh docker/install-addons.sh '.[runtime]'\n",
     "RUN sh docker/install-addons.sh '.[runtime]' || true\n"),

    ("the RUN points the script at a directory the build context does not have — every package "
     "is skipped in the tree that carries them",
     "docker/sandbox.Dockerfile",
     "RUN sh docker/install-addons.sh .\n",
     "RUN sh docker/install-addons.sh . ./vendor\n"),

    ("the exec form reads as an optional glob again — the parser goes back to word-splitting",
     CUT,
     '    rest = " ".join(words).strip()\n'
     '    if rest.startswith("["):\n',
     '    rest = " ".join(words).strip()\n'
     '    if False:\n'),

    ("the Dockerfile walk forgets `Dockerfile.worker`, the third name Docker builds",
     CUT,
     '    return name == "Dockerfile" or name.startswith("Dockerfile.") or name.endswith(".Dockerfile")',
     '    return name == "Dockerfile" or name.endswith(".Dockerfile")'),

    ("the compose walk knows one of Compose's four file names again",
     CUT,
     '_COMPOSE_NAMES = frozenset(f"{stem}{part}{ext}"\n'
     '                           for stem in ("compose", "docker-compose")\n'
     '                           for part in ("", ".override")\n'
     '                           for ext in (".yaml", ".yml"))',
     '_COMPOSE_NAMES = frozenset({"docker-compose.yml"})'),

    # ── the banner: a word is not a claim ───────────────────────────────────────────────────────
    ("THE REVIEWER'S INVERSION: the banner keeps every word — the package, the add-on framing, "
     "the link to STATUS — and says the directory SHIPS here",
     "docs/configuration.md",
     "> **It drives `infra/`, which is not in this tree.**",
     "> **It drives `infra/`, which SHIPS in this tree.**"),

    ("THE REVIEWER'S DELETION: the whole banner goes and a sentence carrying one of the three "
     "framing words stays behind",
     "docs/configuration.md",
     "> **It drives `infra/`, which is not in this tree.** That directory and the deployment it stands\n"
     "> up ship with the `openfactory-aws` **add-on package** — one cloud realisation, never the\n"
     "> platform ([STATUS.md](STATUS.md) lists what leaves with it). Every `infra/…` path below is a\n"
     "> path inside that package's checkout, and every parameter store, region and console name with\n"
     "> it; a deployment on your own machines has none of them and configures itself through\n"
     "> `.env.compose` and the registry.\n",
     "> A cloud is an adapter on the box axis, like any other.\n"),

    ("MY OWN CUT AT THE INVERSION: the banner denies something ELSE and then says the directory "
     "ships here — a negation and a claim about different things, in one sentence",
     "docs/configuration.md",
     "> **It drives `infra/`, which is not in this tree.**",
     "> **It drives `infra/`, which is not the platform, and ships in this tree.**"),

    # ── the templates: a commented instruction is an instruction ────────────────────────────────
    ("a chat variable comes back as a COMMENTED row of the core's own template — the shape the "
     "active-row scan could not see",
     ".env.example",
     "",
     "\n# --- restored by hand ---\n# SLACK_BOT_TOKEN=xoxb-000\n",
     EXAMPLES),

    ("MY OWN CUT AT THAT ONE: the same row in the spelling a reader pastes into a shell, which "
     "the keyword `export` hid from the first version of the widened scan",
     ".env.example",
     "",
     "\n# --- restored by hand ---\n# export SLACK_APP_TOKEN=xapp-000\n",
     EXAMPLES),

    ("the row scan goes back to reading only what is uncommented",
     EXAMPLES,
     r'    return set(re.findall(r"^\s*(?:#\s*)*(?:export\s+)?([A-Z][A-Z0-9_]*)=", text, re.M))',
     r'    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, re.M))',
     EXAMPLES),

    # ── the markdown table nothing read ─────────────────────────────────────────────────────────
    ("the reference page's environment table declares an add-on package's variable again",
     "docs/reference/configuration.md",
     "",
     "\n| `OPENFACTORY_TELEGRAM_BOT_TOKEN` | the bot token the fallback posts with |\n",
     EXAMPLES),

    ("the table scan stops seeing a declaring cell",
     EXAMPLES,
     r'_VARIABLE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")',
     r'_VARIABLE = re.compile(r"\b(NOTHING_AT_ALL)\b")',
     EXAMPLES),

    # ── the registry block a reader pastes ──────────────────────────────────────────────────────
    ("the product section ships the retired chat spellings again — pasted on a panel deployment, "
     "`channel_destination` answers with a chat id where the project's name belongs",
     "docs/configuration.md",
     "  admins: [ana]                                       # who may make it WRITE — panel identities\n",
     "  slack_channel: C0ABCDEF                             # the product's own channel\n"
     "  slack_admins: [U0123ABCD]                           # who may make it WRITE\n",
     EXAMPLES),

    ("the walk over shipped files goes back to the two-item list that missed it",
     EXAMPLES,
     "    return sorted(rel for rel in _tracked()\n"
     "                  if rel.endswith(_COPYABLE) and _stays_in_the_public_tree(rel)\n"
     "                  and _registry_settings(rel, (ROOT / rel).read_text()))",
     "    return [REGISTRY_EXAMPLE, REGISTRY_REFERENCE]",
     EXAMPLES),

    ("the alias rule's count is typed beside the table that derives it, and typed wrong",
     "deploy/registry.yaml.example",
     "`.app_token_env` — all of them",
     "`.app_token_env` — the first two",
     EXAMPLES),

    # ── the remedy a stuck operator is handed ───────────────────────────────────────────────────
    ("the refusal promises an index while nothing here publishes — unfollowable and "
     "self-contradictory, in the sentence that exists to unstick somebody",
     "openfactory/plugins.py",
     'which is on no public index: "',
     'which is on PyPI: "',
     REMEDY),

    ("`pip install <our name>` comes back under another installer's verb",
     "docs/configuration.md",
     "",
     "\nInstall the chat rows with `pip3 install openfactory-slack`.\n",
     REMEDY),

    ("MY OWN CUT AT THAT ONE: the same unfollowable name under a third package manager's verb",
     "docs/configuration.md",
     "",
     "\nOr, on a poetry project: `poetry add openfactory-slack`.\n",
     REMEDY),

    ("the installer scan knows one verb again",
     REMEDY,
     '_INSTALLER = (r"(?:pip[0-9.]*|pipx|uv[ \\t]+pip|conda|mamba)[ \\t]+install"\n'
     '              r"|(?:uv|poetry|pdm|rye|hatch)[ \\t]+add")',
     '_INSTALLER = r"pip[ \\t]+install"',
     REMEDY),

    # ── the exemption that covered a directory that ships ───────────────────────────────────────
    ("the prefix exemption comes back over the whole dossier's directory",
     OPERATOR,
     'HISTORY = ("docs/adr/", "addons/", "infra/")',
     'HISTORY = ("docs/adr/", "docs/core/", "addons/", "infra/")',
     OPERATOR),

    ("a dossier page loses its entry and the walk reads it as an ordinary operator page — the "
     "proof that docs/core/ is really inside the scan now",
     OPERATOR,
     '    "docs/core/01-reality-check.md": "the per-module import listing of that day",\n',
     "",
     OPERATOR),
]
