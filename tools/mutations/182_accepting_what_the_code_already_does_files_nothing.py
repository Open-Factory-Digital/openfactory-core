"""#182: accepting a reading of the code records the promise and files nothing.

Three layers, each cut on its own: the corpus can TELL (the two provenance lines are parsed and
the predicate reads them), the acceptance SAYS (`nothing_to_build`, read by both doors), and the
sink ASKS (`break_down` has no default for `asked_for`, and refuses a reading of the code nobody
asked it to break down). The explicit door — `product_break_down`, the chat gesture — is cut from
the other side: it must still file.
"""

TEST = "tests/test_accepting_what_the_code_already_does_files_nothing.py"

CORPUS = "openfactory/product/corpus.py"
MODULE = "openfactory/product/module.py"
CATALOG = "openfactory/actions/catalog.py"
CONFIRM = "openfactory/product/confirm.py"
CHANNEL = "openfactory/product/channel.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
IO = "openfactory/runtime/temporal/io.py"
VOICE = "openfactory/product/voice.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    # ── the corpus can tell ─────────────────────────────────────────────────────────────────────
    ("the Evidence line goes back to being written and never read — the state of `1512d0a`",
     CORPUS, "        evidence=evidence,\n", '        evidence="",\n'),

    ("the commit the behaviour was read at is not parsed",
     CORPUS, '        observed_at=_recorded(observed_at.group("value") if observed_at else ""),\n',
     '        observed_at="",\n'),

    ("the predicate asks the STATUS, which stops being `observed` at the very moment it matters",
     CORPUS, "        return bool(self.evidence or self.observed_at)",
     "        return self.status == OBSERVED"),

    ("the commit alone is not enough, so tidying the Evidence line away makes built work unbuilt",
     CORPUS, "        return bool(self.evidence or self.observed_at)",
     "        return bool(self.evidence)"),

    ("the writers' placeholder is read as a commit called `unrecorded`",
     CORPUS, '    return "" if text.lower() == UNRECORDED else text',
     "    return text"),

    ("a tier this build does not know is DROPPED, turning the entry into a request",
     CORPUS, "    return tier, [Finding(", '    return "", [Finding('),

    # ── the acceptance says it ──────────────────────────────────────────────────────────────────
    ("the acceptance stops saying there is nothing to build",
     MODULE, "                result.nothing_to_build = req.came_from_the_code",
     "                result.nothing_to_build = False"),

    ("a SECOND acceptance forgets, and the retry door files what the first rightly did not",
     MODULE, "                               nothing_to_build=req.came_from_the_code)",
     "                               nothing_to_build=False)"),

    # ── the panel's door ────────────────────────────────────────────────────────────────────────
    ("the catalog row ignores the verdict and starts the breakdown workflow anyway",
     CATALOG, '    if getattr(result, "nothing_to_build", False) is True:', "    if False:"),

    ("the catalog says it in English whatever the project speaks",
     CATALOG,
     '    said = nothing_to_build(number=number, language=getattr(project, "language", None))',
     "    said = nothing_to_build(number=number, language=None)"),

    ("the automatic chain tells the worker a person asked",
     CATALOG, "by=by,\n                                                 asked_for=False)",
     "by=by,\n                                                 asked_for=True)"),

    ("the requirements row stops carrying the server's verdict to the page",
     CATALOG, '             "came_from_the_code": r.came_from_the_code,',
     '             "came_from_the_code": False,'),

    # ── the conversation's door ─────────────────────────────────────────────────────────────────
    ("the chat executor ignores the verdict and goes to the breakdown",
     CONFIRM, '    if getattr(result, "nothing_to_build", False):', "    if False:"),

    ("the executor's second act claims a person asked, so the sink lets it through",
     CONFIRM, "        results = module.break_down(number, actor=user, asked_for=False)",
     "        results = module.break_down(number, actor=user, asked_for=True)"),

    ("the module's refusal is told as a failed breakdown — 'não consegui… tento de novo'",
     CONFIRM, '    if any(getattr(r, "nothing_to_build", False) for r in results):',
     "    if False:"),

    # ── the sink ────────────────────────────────────────────────────────────────────────────────
    ("`asked_for` gains a default, so the next call site can stay silent on the question",
     MODULE, "    def break_down(self, number: int, *, actor: str, asked_for: bool, board=_UNSET):",
     "    def break_down(self, number: int, *, actor: str, asked_for: bool = True, "
     "board=_UNSET):"),

    ("the sink stops refusing: a door that forgets the verdict files built behaviour",
     MODULE, "        if requirement.came_from_the_code and not asked_for:", "        if False:"),

    ("the sink refuses a PERSON too, and an edited reading can never become work",
     MODULE, "        if requirement.came_from_the_code and not asked_for:",
     "        if requirement.came_from_the_code:"),

    ("the refusal comes back `ok`, which an older panel counts as a card: 'Work filed: ?'",
     MODULE, "            return [WriteResult(ok=False, nothing_to_build=True,",
     "            return [WriteResult(ok=True, nothing_to_build=True,"),

    # ── the explicit door ───────────────────────────────────────────────────────────────────────
    ("the chat's own gesture reaches the module as if nobody had asked",
     CHANNEL, "        results = module.break_down(number, actor=user, asked_for=True)",
     "        results = module.break_down(number, actor=user, asked_for=False)"),

    ("`product_break_down` reaches the worker as the automatic chain",
     CATALOG, "by=by,\n                                                 asked_for=True)",
     "by=by,\n                                                 asked_for=False)"),

    ("the dispatch drops the flag on its way into the workflow input",
     CATALOG,
     "        ProductBreakdownInput(project=project, number=number, actor=by.id, "
     "asked_for=asked_for),",
     "        ProductBreakdownInput(project=project, number=number, actor=by.id),"),

    ("the explicit door spends an agent without a yes",
     CATALOG,
     "    if not _said_yes(yes):\n        return refused(\n            INVALID,\n"
     '            f"nothing was filed: breaking requirement',
     "    if False:\n        return refused(\n            INVALID,\n"
     '            f"nothing was filed: breaking requirement'),

    ("…or for somebody who may not act, who then hears no from the worker minutes later",
     CATALOG,
     "    if not await asyncio.to_thread(lambda: may_act(proj, by.id, via=via)):\n"
     "        return refused(DENIED, unauthorized_message(proj), project=proj.name, number=num)",
     "    if False:\n"
     "        return refused(DENIED, unauthorized_message(proj), project=proj.name, number=num)"),

    ("…or for a requirement nobody confirmed, which is not a promise to build from",
     CATALOG, "    if not requirement.is_promise:\n        return refused(INVALID, _not_a_promise(",
     "    if False:\n        return refused(INVALID, _not_a_promise("),

    # ── the process boundary ────────────────────────────────────────────────────────────────────
    ("the activity forgets what the door said",
     ACTIVITIES, "                                      inp.asked_for)",
     "                                      False)"),

    ("the worker tells the module a person asked, whatever arrived",
     ACTIVITIES,
     '    return ProductModule(project, via="api").break_down(number, actor=actor, '
     "asked_for=asked_for)",
     '    return ProductModule(project, via="api").break_down(number, actor=actor, '
     "asked_for=True)"),

    ("a payload with no field — an older panel's — reads as an explicit request",
     IO, "    asked_for: bool = False", "    asked_for: bool = True"),

    # ── what a person reads ─────────────────────────────────────────────────────────────────────
    ("the sentence exists in one language only",
     VOICE, '    "pt-BR": ("O *requisito {number}* descreve o que o produto já faz hoje',
     '    "pt-PT": ("O *requisito {number}* descreve o que o produto já faz hoje'),

    ("the page's dialog promises filed work for every click, as it did",
     PANEL, "  const then=row.came_from_the_code\n", "  const then=false\n"),
]
