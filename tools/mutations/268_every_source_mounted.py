"""#268 slice 1 (every source of the product, mounted for the product role), proven by breaking it.

SIX CLAIMS, each cut here and each required to go red:

  1. **Every declared source is mounted** — brought up, placed, and linked into the turn's own view;
     one mounted source of N is the defect this slice removes.
  2. **Sparse, and on demand** — a partial clone, checked out through a cone that leaves out the
     directories of weight and never code, made on the first turn and brought up to date after.
  3. **A missing source is named, with why** — in the prompt, by the module, by the bring-up and by
     the sentence git's words are read into.
  4. **The confidence bound reads every source's bundle.**
  5. **Nothing outside `sources:`** — not the registry project's own repository when the product
     does not declare it, not a worktree the product stopped declaring, not a host a URL names,
     not an entry that names no repository; and no credential on disk, in a log, in the view.
  6. **The map is checked before it is named, and the onboarding's documents are named** — and the
     team hears of a missing source, as the prompt tells the role it has.

The guard is `tests/test_every_source_is_mounted.py`, on the battery's multi-repository fixture
(`tests/fixtures/evaluation/harbourline/`).
"""

TEST = "tests/test_every_source_is_mounted.py"

MODULE = "openfactory/product/module.py"
SOURCES = "openfactory/product/sources.py"
WORKSPACE = "openfactory/product/workspace.py"
ROLE = "openfactory/product/role.py"
READING = "openfactory/product/reading.py"
CACHE = "openfactory/runtime/repo_cache.py"

MUTATIONS = [
    # ── 1. every declared source is mounted ────────────────────────────────────────────────────
    ("the view is composed from the project's own source alone — the one-of-N mount again",
     MODULE,
     "                ws = compose(docs_checkout=docs, sources=checkouts.placed, root=root)",
     "                ws = compose(docs_checkout=docs, sources={r: p for r, p in "
     "checkouts.placed.items() if r == checkouts.own}, root=root)"),

    ("every source is fetched, and only the project's own is kept", SOURCES,
     "    for (coordinate, _), got in zip(found.sources, results, strict=True):\n"
     "        if got.path is not None:",
     "    for (coordinate, _), got in zip(found.sources, results, strict=True):\n"
     "        if got.path is not None and coordinate == out.own:"),

    ("the turn's own view links the first source and drops the rest", WORKSPACE,
     "        for checkout in sources.values():",
     "        for checkout in list(sources.values())[:1]:"),

    # ── 2. sparse, and on demand ───────────────────────────────────────────────────────────────
    ("every source is cloned whole — history and all", CACHE,
     '                    cloned = _git_out(["clone", "--filter=blob:none", "--no-checkout",',
     '                    cloned = _git_out(["clone", "--no-checkout",'),

    ("the cone is never set, so the pictures and the font are checked out and fetched", CACHE,
     "        if cone is not None:",
     "        if False:"),

    ("a directory of weight alone is taken into the cone", CACHE,
     "        if not child.has_code():\n            left_out.append(where)",
     "        if False:\n            left_out.append(where)"),

    ("a directory's own code is left out with the weight beside it", CACHE,
     "    if not top and not listed and node.own_code():",
     "    if False:"),

    ("the next turn clones every source again instead of bringing it up to date", CACHE,
     '                if branch and (master / ".git").exists():',
     "                if False:"),

    # ── 3. a missing source is named, with why ─────────────────────────────────────────────────
    ("the prompt drops the list of sources that could not be opened", ROLE,
     "            missing += [f\"- `{m.repo}` — {m.why}\" for m in absent]",
     "            missing += []"),

    ("the module forgets the sources that were not mounted", MODULE,
     "        out += [Mount(repo=repo, why=why, own=repo == own)\n"
     '                for repo, why in (getattr(self, "_missing_sources", {}) or {}).items()]',
     "        out += []"),

    ("a source that failed to come up is dropped in silence", SOURCES,
     "            out.missing[coordinate] = got.why or NOT_CHECKED_OUT",
     "            pass"),

    ("every reason collapses into one — not authorised, not found and unreachable read alike",
     SOURCES,
     "            return sentence",
     "            return NOT_CHECKED_OUT"),

    # ── 4. the bound reads every source's bundle ───────────────────────────────────────────────
    ("the answer is bound against the project's own bundle alone", MODULE,
     '        okf = getattr(module, "_okf_dirs", None) or getattr(module, "_okf_dir", None)',
     '        okf = getattr(module, "_okf_dir", None)'),

    ("the other sources' bundles are found and never added", MODULE,
     "            if home is not None and (home / OKF_INDEX_FILE).is_file() and home not in dirs:\n"
     "                dirs.append(home)",
     "            if home is not None and (home / OKF_INDEX_FILE).is_file() and home not in dirs:\n"
     "                pass"),

    ("the bound reads the first bundle it is handed and ignores the rest", READING,
     "    for bundle_dir in bundle_dirs:",
     "    for bundle_dir in bundle_dirs[:1]:"),

    # ── 5. nothing outside `sources:`, and no credential ───────────────────────────────────────
    ("the registry's own repository is mounted though the product does not declare it", SOURCES,
     "    if own_repo and not out.own:\n"
     "        out.missing[normalize_repo(own_repo) or own_repo] = NOT_DECLARED",
     "    if own_repo and not out.own:\n"
     "        out.own = normalize_repo(own_repo)\n"
     "        found = Declared(sources=(*found.sources, (out.own, own_repo)), "
     "refused=found.refused)"),

    ("a worktree the product stopped declaring stays under the shared root", WORKSPACE,
     "        if stale.name in names.values():\n            continue",
     "        if True:\n            continue"),

    ("what `sources:` wrote is handed to the forge as written — a URL's host, a query", SOURCES,
     "        out.append((coordinate, plain if plain.lower() == coordinate else coordinate))",
     "        out.append((coordinate, plain))"),

    ("an entry that names no repository is handed to the forge anyway", SOURCES,
     "        if not coordinate:\n            from openfactory.product.model import "
     "scrub_credentials",
     "        if False:\n            from openfactory.product.model import scrub_credentials"),

    ("the credentialed URL is the one git writes down", CACHE,
     '    public = _USERINFO_URL.sub(r"\\1", clone_url or "", count=1)',
     '    public = clone_url or ""'),

    ("git's own words are kept, and logged, with the credential in them", CACHE,
     '        self.failure = _USERINFO_URL.sub(r"\\1***@", _scrub(said or "")).strip()',
     '        self.failure = (said or "").strip()'),

    ("a link out of its tree reaches the view", WORKSPACE,
     "            if os.path.isabs(target) or os.path.commonpath([base, landed]) != base:",
     "            if False:"),

    ("a source's `.git` — a pointer into the cache — reaches the view", WORKSPACE,
     '    return lambda where, names: outside(where, names) | ({".git"} & set(names))',
     "    return lambda where, names: outside(where, names)"),

    ("a mounted source can be written through", WORKSPACE,
     "                os.chmod(path, mode & ~0o222)",
     "                os.chmod(path, mode)"),

    # ── 6. the map, the onboarding's documents, and the team told ──────────────────────────────
    ("a module map is named without being checked against the code it describes", SOURCES,
     "    if not is_trustworthy(bundle, code):",
     "    if False:"),

    ("the map section never reaches the prompt", ROLE,
     "        parts += self._map_section()",
     "        parts += []"),

    # RE-PINNED 2026-09-24 (#268 slice 3): the role is handed the turn's sight after the documents
    ("the onboarding's documents are never named", MODULE,
     "                           onboarding=self.onboarding(),",
     "                           onboarding=[],"),

    ("a missing source other than the project's own reaches nobody on the team", MODULE,
     "                          ok=bool(code) and n_code > 0 and not missing)",
     "                          ok=bool(code) and n_code > 0)"),
]
