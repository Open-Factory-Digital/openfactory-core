"""Mutation plan for the public SHAPE: nothing the export ships executes against a path it removes.

The blocker this proves (pre-launch audit, 2026-08-26): both images did `COPY addons ./addons`
while `addons/` is a row of docs/STATUS.md's excluded-paths table, so the published tree died at
`failed to compute cache key: "/addons": not found` on README.md's first command — and four of
the Makefile's ten advertised targets were dead there, one announcing "created …" over a failed
`cp`. Every guard that could have seen it skipped itself where `addons/` is absent.

Each row below is either the defect exactly as it stood, or a way of satisfying the new guards
with nothing behind them. Point-in-time proof; anchors rot as code moves and fail loudly on rerun.
"""

CUT = "tests/test_the_public_cut_is_written_down.py"

TEST = CUT

MUTATIONS = [
    # ── the two Dockerfiles, back to the shape that could not build ─────────────────────────────
    ("the worker copies addons/ literally again — the blocker itself",
     "docker/worker.Dockerfile",
     "COPY addon[s] ./addons",
     "COPY addons ./addons"),
    ("the sandbox copies addons/ literally again",
     "docker/sandbox.Dockerfile",
     "COPY addon[s] ./addons",
     "COPY addons ./addons"),
    ("the worker installs the two packages by name again, so the RUN dies where the COPY would not",
     "docker/worker.Dockerfile",
     "RUN pip install --no-cache-dir '.[runtime]' \\\n"
     " && for p in ./addons/openfactory-*; do \\\n"
     '      if [ -d "$p" ]; then pip install --no-cache-dir "$p" || exit 1; fi; \\\n'
     "    done",
     "RUN pip install --no-cache-dir '.[runtime]' ./addons/openfactory-aws "
     "./addons/openfactory-slack"),
    ("the sandbox installs the two packages by name again",
     "docker/sandbox.Dockerfile",
     "RUN pip install --no-cache-dir . \\\n"
     " && for p in ./addons/openfactory-*; do \\\n"
     '      if [ -d "$p" ]; then pip install --no-cache-dir "$p" || exit 1; fi; \\\n'
     "    done",
     "RUN pip install --no-cache-dir . ./addons/openfactory-aws ./addons/openfactory-slack"),
    # ── the other way of passing: carry nothing at all ──────────────────────────────────────────
    ("the worker stops copying the packages entirely — green in both trees, and the private "
     "worker ships without its add-ons",
     "docker/worker.Dockerfile",
     "COPY addon[s] ./addons\n",
     ""),
    ("the worker's install loop drops the -d test, so a glob that matched nothing is installed",
     "docker/worker.Dockerfile",
     'if [ -d "$p" ]; then pip install --no-cache-dir "$p" || exit 1; fi;',
     'pip install --no-cache-dir "$p" || exit 1;'),
    # ── the Makefile ────────────────────────────────────────────────────────────────────────────
    ("make tfvars runs at the template with nothing testing that it is there",
     "Makefile",
     "\t@$(call cloud-or-refuse,$(CLOUD_TFVARS_EXAMPLE))\n",
     ""),
    ("make deploy runs the deploy script with nothing testing that it is there",
     "Makefile",
     "\t@$(call cloud-or-refuse,$(CLOUD_DEPLOY))\n",
     ""),
    ("make panel-url names the add-on's guide, which a reader without the add-on cannot open",
     "Makefile",
     "the $(CLOUD_PACKAGE) walkthrough §1 lists what a deploy needs.",
     "$(CLOUD_GUIDE) §1 lists what a deploy needs."),
    ("the refusal exits 0, so a target announces nothing and succeeds at doing nothing",
     "Makefile",
     "\t  exit 1; fi",
     "\t  exit 0; fi"),
    ("the refusal names the package but no longer the command that gets it",
     "Makefile",
     '\t  echo "  pip install $(CLOUD_PACKAGE)   (or use a checkout that carries $(1))" >&2; \\\n',
     '\t  echo "  it is published under that name." >&2; \\\n'),
    ("the refusal refuses, but names neither the path it wanted nor the package that has it",
     "Makefile",
     'cloud-or-refuse = if [ ! -e "$(1)" ]; then \\\n'
     '\t  echo "make $@: $(1) is not in this tree." >&2; \\\n'
     '\t  echo "  The reference deployment on one cloud — its terraform, its deploy script and its" >&2; \\\n'
     '\t  echo "  walkthrough — ships in the $(CLOUD_PACKAGE) add-on package." >&2; \\\n'
     '\t  echo "  pip install $(CLOUD_PACKAGE)   (or use a checkout that carries $(1))" >&2; \\\n'
     "\t  exit 1; fi",
     'cloud-or-refuse = if [ ! -e "$(1)" ]; then echo "a required path is missing" >&2; exit 1; fi'),
    ("make tfvars announces the file again over a cp that failed — the original defect",
     "Makefile",
     '\telse cp "$(CLOUD_TFVARS_EXAMPLE)" "$(TFVARS)" \\\n'
     '\t     && echo "created $(TFVARS) — fill it in (app id, installation, temporal, brand)."; fi',
     '\telse cp "$(CLOUD_TFVARS_EXAMPLE)" "$(TFVARS)"; \\\n'
     '\t     echo "created $(TFVARS) — fill it in (app id, installation, temporal, brand)."; fi'),
    # ── the judge itself, so the twins are not reading a broken ruler ───────────────────────────
    ("the judge stops seeing a path nested under an excluded directory",
     CUT,
     'return ("/" + path.strip("/") + "/") in _path_key(token)',
     'return ("/" + path.strip("/") + "/") == _path_key(token)'),
    ("any existence test anywhere in the unit reads as a guard, whatever path it names",
     CUT,
     "if not any(_path_key(token).startswith(op) for op in operands)",
     "if not operands"),
    ("the Dockerfile reader stops joining continuations, so a multi-line RUN is invisible",
     CUT,
     'for chunk in body.replace("\\\\\\n", " ").splitlines():',
     "for chunk in body.splitlines():"),
    ("the comment stripper eats the code as well as the comment",
     CUT,
     'cut = re.search(r"(?:^|\\s)#", line)',
     'cut = re.search(r"(?:^|\\s)?", line)'),
]
