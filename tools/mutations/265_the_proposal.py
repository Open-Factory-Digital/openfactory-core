"""Mutation plan for #265 slice 4 — a repository that cannot say how it runs gets a preview drafted
from what it says, proposed on a pull request of its own, never built or run before a person
merges it (ADR-0050 D12; the design's §4).

Each row takes away one rule the proposal's safety or honesty rests on; every row must turn
`tests/test_a_preview_is_proposed_from_what_the_repository_says.py` red.
"""

TEST = "tests/test_a_preview_is_proposed_from_what_the_repository_says.py"
INFER = "openfactory/onboarding/preview_infer.py"
PROPOSE = "openfactory/onboarding/preview_propose.py"
CLI = "openfactory/cli.py"
READER = "openfactory/onboarding/infer.py"
COMPOSE = "openfactory/adapters/preview/compose.py"
MACHINE = "openfactory/orchestrator/machine.py"

MUTATIONS = [
    # ── nothing is built where the verb runs, and no job opens one ──
    ("the verb proves — builds — the draft whether or not anybody asked", CLI,
     "    if prove and not as_card:",
     "    if not as_card:"),
    ("a job opens a proposal on its own", MACHINE,
     "",
     "\n\ndef _offer_a_proposal(project):\n"
     "    from openfactory.onboarding.preview_propose import propose_preview\n\n"
     "    return propose_preview(project)\n"),
    ("a proof writes a drafted path outside the fresh checkout", COMPOSE,
     "                if not target.startswith(root + os.sep):",
     "                if False:"),

    # ── the tiers: an unknown is never written, an inferred line waits for --accept ──
    ("an inferred line is written without --accept", PROPOSE,
     "    return tier in (OBSERVED, ANSWERED) or (tier == INFERRED and accept)",
     "    return tier in (OBSERVED, ANSWERED, INFERRED)"),
    ("a port nobody stated is guessed and written as observed", INFER,
     '                field=f"preview.expose.{name}", value=None, confidence=UNKNOWN,\n'
     "                evidence=[Evidence(path=df.path)],",
     '                field=f"preview.expose.{name}", value=8000, confidence=OBSERVED,\n'
     "                evidence=[Evidence(path=df.path)],"),
    ("a framework's conventional port is claimed as read", INFER,
     "            port, port_tier, port_ev = conv, INFERRED, command_ev",
     "            port, port_tier, port_ev = conv, OBSERVED, command_ev"),
    ("an answer's port stays the string a person typed", PROPOSE,
     '        if re.fullmatch(r"\\d+", value):',
     "        if False:"),

    # ── a secret's value never reaches a draft ──
    ("a literal credential in the team's compose file is not flagged", INFER,
     "                out.flags.append(Flag(path=rel, line=at, service=name, name=key, why=why))",
     "                pass"),
    ("a password inside an address is not seen", INFER,
     '    if m and "$" not in m.group(1):',
     "    if False:"),
    ("a secret an example file names is copied into the draft", INFER,
     "        why = credential(entry.name, entry.value)",
     '        why = ""'),
    ("the excerpt of an example file's line carries its value", INFER,
     '        where = Evidence(path=entry.path, line=entry.line, excerpt=f"{entry.name}=…")',
     '        where = Evidence(path=entry.path, line=entry.line,\n'
     '                         excerpt=f"{entry.name}={entry.value}")'),
    ("the pull request says nothing of the flagged literals", PROPOSE,
     "    if proposal.flags:",
     "    if False:"),
    ("a Dockerfile line holding a secret is quoted in the pull request", INFER,
     "        line = quoted(raw.strip())",
     "        line = raw.strip()"),
    ("a start command holding a secret is copied into a drafted CMD", INFER,
     "    if carries_credential(_shown_command(command)):",
     "    if False:"),

    # ── a Dockerfile only when its start is anchored, and never `COPY . .` ──
    ("a start command nothing anchors is guessed", INFER,
     '                Evidence(path="manage.py", excerpt="manage.py"), "python")\n'
     "    return None",
     '                Evidence(path="manage.py", excerpt="manage.py"), "python")\n'
     '    return ["python", "app.py"], INFERRED, Evidence(path="."), "python"'),
    ("the drafted image copies the whole repository", PROPOSE,
     '    lines += [f"COPY {d} ./{d}" for d in df.copy_dirs]',
     '    lines += ["COPY . ."]'),
    ("the drafted image's ignore file lets `.git` in", PROPOSE,
     '        ".git",\n',
     ""),

    # ── the depth, two-files, store and wiring rules ──
    ("a Dockerfile two directories deep is drafted as a service", INFER,
     "        if depth > 1:",
     "        if depth > 9:"),
    ("one of two Dockerfiles in a directory is picked", INFER,
     "        if len(files) > 1:",
     "        if len(files) > 9:"),
    ("a store is drafted without its healthcheck", PROPOSE,
     "        if svc.healthcheck:",
     "        if False:"),
    ("a service only waits for a store to start, not to be healthy", PROPOSE,
     '                lines.append("        condition: service_healthy")',
     '                lines.append("        condition: service_started")'),
    ("the server-side address is written with nothing saying the service renders on its server",
     INFER,
     "            elif ssr is not None:",
     "            elif True:"),
    ("an override's paths resolve against its own directory", INFER,
     '    return posixpath.relpath(directory or ".", compose_dir or ".")',
     '    return posixpath.relpath(directory or ".", ".openfactory")'),
    ("a Dockerfile a service already builds is handed to an image-only one", INFER,
     "              if path.count(\"/\") <= 1 and posixpath.normpath(path) not in owned}",
     "              if path.count(\"/\") <= 1}"),
    ("a managed database gets no stand-in", INFER,
     "                store = next((s for s in STORES.values() if scheme in s.schemes), None)",
     "                store = None"),

    # ── the manifest keeps its comments; a person's files are theirs ──
    ("the manifest is re-dumped even when an append means the same file", PROPOSE,
     "        if yaml.safe_load(appended) == wanted:",
     "        if False:"),
    ("a block the manifest already declares is overwritten", PROPOSE,
     "    if key in current:",
     "    if False:"),
    ("a drafted file overwrites one of the team's", PROPOSE,
     "    clash = sorted(p for p in out.files if (checkout / p).exists())",
     "    clash: list[str] = []"),
    ("an open proposal is not asked about before drafting", PROPOSE,
     "        found = already_proposed(forge, repo, BRANCH)",
     '        found = ""'),

    # ── `env read` reports it; `env apply` never writes it ──
    ("the preview is no longer attempted by the repository reader", READER,
     '_ATTEMPTED = ("base_branch", "setup", "validation", "components", "preview")',
     '_ATTEMPTED = ("base_branch", "setup", "validation", "components")'),
    ("the preview rides the manifest's fields, where `env apply` writes them", READER,
     '    preview = _preview_reading(root, tree, fields["setup"])',
     '    preview = _preview_reading(root, tree, fields["setup"])\n'
     '    fields["preview.compose"] = Proposal(field="preview.compose", value=["x"],\n'
     "                                         confidence=OBSERVED)"),

    # ── the card: the forge's answer when it is read ──
    ("the card names the proposal the record froze, not the forge's answer now", PROPOSE,
     "    url = open_proposal(project, shape.repo, forge=forge, now=now)",
     "    url = None"),
    ("the forge is asked once and never again", PROPOSE,
     "    if cached is not None and now - cached[0] < _ASK_FOR:",
     "    if cached is not None:"),
    ("could not ask is read as none open", PROPOSE,
     "    if url is None:\n"
     '        url = getattr(record, "proposal_url", "") or ""',
     "    if url is None:\n"
     '        url = ""'),
]
