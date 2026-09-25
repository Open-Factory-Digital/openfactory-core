"""Mutation plan for #265 slice 5 — a product of several repositories is previewed as one unit, and
nothing outside the product ever reaches it (ADR-0050 D1, D3, D5; the design's §2.2, §6, §8).

Each row takes away one rule the multi-repository preview's safety or honesty rests on — the
`sources:` bound, the exclusion of another product's cards, the downgrade when the product cannot
be read, the refusal of two shapes, the writers that land in the context repository without a
person, and where a card of the back end is filed. Every row must turn
`tests/test_a_product_is_previewed_across_its_repositories.py` red.
"""

TEST = "tests/test_a_product_is_previewed_across_its_repositories.py"

SIBLINGS = "openfactory/preview/siblings.py"
PRODUCT = "openfactory/preview/product.py"
STEPS = "openfactory/preview/steps.py"
UNIT = "openfactory/preview/unit.py"
DEMAND = "openfactory/preview/demand.py"
COMPOSE = "openfactory/adapters/preview/compose.py"
CONTRACT = "openfactory/contracts/product.py"
AUTHORING = "openfactory/product/authoring.py"
MODULE = "openfactory/product/module.py"
WRITES = "openfactory/policy/context_writes.py"
PIPELINE = "openfactory/knowledge/pipeline.py"
TRACKER_BASE = "openfactory/adapters/tracker/base.py"
GITHUB = "openfactory/adapters/tracker/github.py"
AZURE = "openfactory/adapters/tracker/azure_devops.py"

MUTATIONS = [
    # ── a card of another product is never joined ──
    ("a card whose repository is outside `sources:` is a sibling, and its pull request is asked",
     SIBLINGS,
     "        home = member(repo, members)\n",
     "        home = repo\n"),
    ("an offered change in a repository outside the product is fetched and built", STEPS,
     "        if shape is not None and not shape.dir_of(c.repo):",
     "        if False:"),
    ("with the product module off, a change in another repository joins the project's own", STEPS,
     "        elif shape is None and not _own(project, c.repo):",
     "        elif False:"),

    # ── the `sources:` bound on the shape and the layout ──
    ("`preview.compose.repository` may name a repository outside `sources:`", PRODUCT,
     "    if repo and not member(repo, sources):",
     "    if False:"),
    ("`dirs:` may map a directory to a repository outside `sources:`", PRODUCT,
     "        found = member(target, [*sources, context])",
     "        found = target"),
    ("a `../x` that names no member is checked out on a guess", PRODUCT,
     "    found = prescan(texts, layout_dirs=shape.members, of=\"this product\", "
     "remedy=PRODUCT_REMEDY)",
     "    found = prescan(texts, layout_dirs=None, of=\"this product\", remedy=PRODUCT_REMEDY)"),
    ("the plan trusts whatever tree is on disk under a member's name", PRODUCT,
     "        if not expected or not repo_match(tree.repo, expected):",
     "        if False:"),
    ("product.yaml is read through a link out of its checkout", PRODUCT,
     "    text = _read_inside(root, posixpath.join(root, PRODUCT_YAML))",
     "    text = open(posixpath.join(root, PRODUCT_YAML), encoding=\"utf-8\").read()"),

    # ── the siblings: the platform's own pull request, open, in its own repository ──
    ("a sibling's pull request is looked for on a branch the platform never opened", SIBLINGS,
     "        branch = namespace.job_branch(number)",
     "        branch = f\"feature/{number}\""),
    ("a sibling whose pull request merged or closed is built as if it were open", SIBLINGS,
     "        elif state != \"open\":",
     "        elif False:"),
    ("two open pull requests of one repository are checked out over each other", STEPS,
     "        if len(urls) > 1:",
     "        if False:"),
    ("an unreadable board is read as a board, and its siblings guessed", STEPS,
     "        if not error:",
     "        if True:"),
    ("a sibling's branch is fetched from the project's own repository", STEPS,
     "        if _own(project, repo):",
     "        if True:"),
    ("a sibling's head is read in the project's own repository, so `stale` reads another card",
     DEMAND,
     "remote_for(project, forge, repos.get(url, \"\"))",
     "remote_for(project, forge, \"\")"),

    # ── the side-by-side layout ──
    ("the repositories the compose file reaches are never checked out", STEPS,
     "                               more=more, context=shape.context_dir)",
     "                               more=None, context=shape.context_dir)"),
    ("the layout forgets it is a product's, and the plan looks for a manifest's shape", STEPS,
     "                               more=more, context=shape.context_dir)",
     "                               more=more)"),
    ("the plan never reads the product's shape from the context repository's base", COMPOSE,
     "    if layout.context:",
     "    if False:"),

    # ── the downgrade ──
    ("a card of a requirement is previewed as the requirement with the product module off", UNIT,
     "    alone = alone_because(ctx) if cited is not None else \"\"",
     "    alone = \"\""),
    ("the offer never asks the product, so every card of a requirement is alone", DEMAND,
     "    ctx = (product or product_context)(project) if _cited_requirement(body) is not None "
     "else None",
     "    ctx = None"),
    ("a fresh start forgets why its card is alone", STEPS,
     "    alone = (was.alone,) if was is not None and was.alone else ()",
     "    alone = ()"),

    # ── the citation: a defect is a card of its requirement ──
    ("a defect filed before its Source is not a card of its requirement", MODULE,
     "    m = _DEFECT_CITES_RE.search(body or \"\")",
     "    m = None"),
    ("a defect's Source cites no requirement", AUTHORING,
     "            f\"Restores **REQ-{requirement.number:04d}** in",
     "            f\"Restores **the promise** in"),
    ("the orphan repair writes a requirement card's Source over a defect", MODULE,
     "            if filed_by_the_product_role(card.body) == \"defect\":",
     "            if False:"),

    # ── `product.yaml`'s `preview:`, typed ──
    ("a typo in the preview block turns the whole product module off", CONTRACT,
     "        block = data.get(\"preview\") if isinstance(data, dict) else None",
     "        block = None"),

    # ── one shape per product ──
    ("a product whose source also declares a shape is previewed from one of them", COMPOSE,
     "    if two:",
     "    if False:"),

    # ── the writer guard ──
    ("the sweep merges a `req/*` branch whatever it touches", AUTHORING,
     "        if why:\n            log.warning(\"OPENFACTORY_PRODUCT_PROPOSAL_LEFT_OPEN",
     "        if False:\n            log.warning(\"OPENFACTORY_PRODUCT_PROPOSAL_LEFT_OPEN"),
    ("the sweep merges a proposal whose diff it read only in part", AUTHORING,
     "    if len(diff) > _SWEEP_DIFF_CHARS:",
     "    if False:"),
    ("the sweep reads a diff it could not read as one that touches nothing", AUTHORING,
     "    if diff is None:",
     "    if False:"),
    ("a fact's path is never judged before it is written", AUTHORING,
     "    if outside([path], FACTS):",
     "    if False:"),
    ("a direct writer commits whatever its checkout staged", AUTHORING,
     "    if not staged:\n        return None",
     "    if True:\n        return None"),
    ("the platform's own directory is a path any writer may land", WRITES,
     "        if (not norm or norm.startswith(PLATFORM_DIR) or norm + \"/\" == PLATFORM_DIR",
     "        if (not norm"),
    ("the module map is published wherever it is pointed", PIPELINE,
     "    if outside([subpath.as_posix()], KNOWLEDGE):",
     "    if False:"),
    ("the module map commits whatever its checkout staged", PIPELINE,
     "    stray = outside([p for p in staged.split(\"\\0\") if p.strip()], KNOWLEDGE) if rc == 0 \\",
     "    stray = [] if rc == 0 \\"),

    # ── filing: `target_repo` only within `sources:` ──
    ("a card is filed in any repository the role names", MODULE,
     "        home = next((s for s in self._sources() if s and repo_match(target, s)), \"\")",
     "        home = target"),
    ("a retried filing in another repository files the card twice", MODULE,
     "            existing = tracker.find_ticket(title=title) or self._titled_in(where, title)",
     "            existing = tracker.find_ticket(title=title)"),
    ("a row written before `repo` is handed one", TRACKER_BASE,
     "    return \"repo\" in params or any(p.kind is inspect.Parameter.VAR_KEYWORD",
     "    return True or any(p.kind is inspect.Parameter.VAR_KEYWORD"),
    ("GitHub files every card in its own repository whatever it is asked", GITHUB,
     "        target = (repo or \"\").strip().strip(\"/\") or self.repo",
     "        target = self.repo"),
    ("Azure Boards files a card of another repository under no area", AZURE,
     "        area = self._area_for(repo)",
     "        area = \"\""),
]
