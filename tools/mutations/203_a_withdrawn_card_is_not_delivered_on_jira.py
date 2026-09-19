"""#203: on Jira a withdrawn card carries the site's own resolution, and generic code closes through
one seam that knows no vendor."""

TEST = "tests/test_a_withdrawn_card_is_not_delivered_on_jira.py"
CLOSED_AS_DELIVERED = "tests/test_a_finished_card_is_closed_as_delivered.py"
JIRA = "openfactory/adapters/tracker/jira.py"
PORT = "openfactory/adapters/tracker/base.py"
REGISTRY = "openfactory/adapters/tracker/registry.py"
CONFORMANCE = "openfactory/conformance/adapters.py"
CATALOG = "openfactory/actions/catalog.py"
MODULE = "openfactory/product/module.py"
LOCAL_FLOW = "openfactory/testing/local_flow.py"
VOICE = "openfactory/product/voice.py"

MUTATIONS = [
    # ── the row ─────────────────────────────────────────────────────────────────────────────────
    ("THE DEFECT ITSELF: a withdrawn card is sent the bare transition, and lands in Done beside "
     "the work that shipped", JIRA,
     # re-pinned 2026-09-19: the post moved into `_refusal_of` when the status joined it
     "            refused = self._refusal_of(ref, {**move, \"fields\": {\"resolution\": "
     "{\"name\": wanted}}})",
     "            refused = self._refusal_of(ref, move)"),

    ("the row takes the word and ignores it", JIRA,
     "        if delivered:\n            self.set_state(ref, JobState.DONE)",
     "        if True:\n            self.set_state(ref, JobState.DONE)"),

    ("a literal default pretends every site has a `Won't Do`", JIRA,
     "str(not_delivered_resolution or \"\").strip()",
     "str(not_delivered_resolution or \"Won't Do\").strip()"),

    ("`resolution` is not asked of `search/jql`, so it is never answered", JIRA,
     "    _LIST_FIELDS = [\"summary\", \"description\", \"status\", \"resolution\", \"labels\", "
     "\"assignee\",",
     "    _LIST_FIELDS = [\"summary\", \"description\", \"status\", \"labels\", \"assignee\","),

    ("the read side never says not_planned: what the close wrote does not come back", JIRA,
     # re-pinned 2026-09-19: the answer is `said`, which the status can give as well
     "        return \"not_planned\" if said else \"\"",
     "        return \"\""),

    ("delivery is decided from a resolution name nobody configured", JIRA,
     # re-pinned 2026-09-19: the resolution is one half of `said` now
     "        said = (wanted and got == wanted) or",
     "        said = (got and got != \"done\") or"),

    ("the configured name is compared by case, and a person's `WON'T DO` reads as delivered", JIRA,
     "        got = str((fields.get(\"resolution\") or {}).get(\"name\") or \"\").strip().lower()",
     "        got = str((fields.get(\"resolution\") or {}).get(\"name\") or \"\").strip()"),

    ("a site that refuses the field leaves the card open: the 400 is not degraded", JIRA,
     # re-pinned 2026-09-19: the 400 rule lives in `_refusal_of`, for both words
     "            if exc.code != 400:\n                raise\n",
     "            raise\n"),

    ("an expired credential is read as a refused field, and the close is retried and noted", JIRA,
     "            if exc.code != 400:\n",
     "            if False:\n"),

    ("the status code is lost on the way out of `_call`", JIRA,
     "                              code=int(exc.code)) from exc",
     "                              code=0) from exc"),

    ("the degraded close leaves no word on the card that the work was not done", JIRA,
     "        self.comment(ref, closed_not_delivered_note(status=landed, language=self.language))",
     "        closed_not_delivered_note(status=landed, language=self.language)"),

    ("the note no longer says the work was NOT delivered", VOICE,
     "    \"en\": (\"Closed as NOT delivered: the work was withdrawn, not done. The board shows ",
     "    \"en\": (\"Closed. The board shows "),

    ("the row says its one sentence in English whatever the project speaks", JIRA,
     "closed_not_delivered_note(status=landed, language=self.language))",
     "closed_not_delivered_note(status=landed, language=None))"),

    ("the registry row never tells the tracker which language the project speaks", REGISTRY,
     "        language=getattr(project, \"language\", None),\n    )\n\n\ndef _azure_devops",
     "        language=None,\n    )\n\n\ndef _azure_devops"),

    ("the note does not name the status the card landed in", JIRA,
     "        landed = str((match.get(\"to\") or {}).get(\"name\") or match.get(\"name\") or \"\")",
     "        landed = \"\""),

    ("the degraded close is silent: no log line names the option", JIRA,
     "        log.warning(\"OPENFACTORY_JIRA_WITHDRAWN_READS_AS_DELIVERED issue=%s",
     "        log.debug(\"OPENFACTORY_JIRA_WITHDRAWN_READS_AS_DELIVERED issue=%s"),

    ("a card with no way into Done is not left alone by the withdrawn close", JIRA,
     "        if match is None:\n            return  # `set_state`'s own contract",
     "        if False:\n            return  # `set_state`'s own contract"),

    ("`set_state` says a card moved that stayed where it was", JIRA,
     "        if match is None:\n            return False\n",
     "        if match is None:\n            return True\n"),

    # ── the option ──────────────────────────────────────────────────────────────────────────────
    ("the registry row never hands the option to the tracker", REGISTRY,
     "        not_delivered_resolution=options.get(\"not_delivered_resolution\", \"\"),",
     "        not_delivered_resolution=\"\","),

    ("the registry row invents the default the adapter refused", REGISTRY,
     "        not_delivered_resolution=options.get(\"not_delivered_resolution\", \"\"),",
     "        not_delivered_resolution=options.get(\"not_delivered_resolution\", \"Won't Do\"),"),

    # ── the seam ────────────────────────────────────────────────────────────────────────────────
    ("THE OLD FALLBACK, IN THE NEW PLACE: a row without the keyword is closed with the word "
     "dropped, and withdrawn work is recorded as delivered", PORT,
     "    if delivered:\n        tracker.close_ticket(ref, reason)\n        return\n",
     "    if True:\n        tracker.close_ticket(ref, reason)\n        return\n"),

    ("a row from before the keyword can no longer close delivered work either", PORT,
     "    if delivered:\n        tracker.close_ticket(ref, reason)\n        return\n",
     "    if False:\n        tracker.close_ticket(ref, reason)\n        return\n"),

    ("every row is taken to declare the keyword, so an old one answers a raw TypeError", PORT,
     "    return \"delivered\" in params or any(p.kind is inspect.Parameter.VAR_KEYWORD\n",
     "    return True or any(p.kind is inspect.Parameter.VAR_KEYWORD\n"),

    ("a row that takes the word through **kwargs is refused it", PORT,
     "    return \"delivered\" in params or any(p.kind is inspect.Parameter.VAR_KEYWORD\n"
     "                                        for p in params.values())",
     "    return \"delivered\" in params"),

    ("the product owner's watched tracker hides what the row takes", MODULE,
     "        watched.__wrapped__ = attr\n",
     ""),

    ("the conformance suite lets a row without the keyword through", CONFORMANCE,
     "    if not says_delivered(tracker):\n",
     "    if False:\n"),

    ("the in-memory tracker the flow harness ships falls behind the port", LOCAL_FLOW,
     "    def close_ticket(self, ref: str, reason: str, *, delivered: bool = True) -> None:",
     "    def close_ticket(self, ref: str, reason: str) -> None:"),

    # ── the callers ─────────────────────────────────────────────────────────────────────────────
    ("the catalog walks around the seam, and an old row answers a TypeError the operator reads",
     CATALOG,
     "        close_ticket(tracker, issue, note, delivered=delivered)",
     "        tracker.close_ticket(issue, note, delivered=delivered)",
     CLOSED_AS_DELIVERED),

    ("the catalog walks around the seam — seen from the code, not from a run", CATALOG,
     "        close_ticket(tracker, issue, note, delivered=delivered)",
     "        tracker.close_ticket(issue, note, delivered=delivered)"),

    ("the product owner's close walks around the seam", MODULE,
     "            close_ticket(tracker, f\"#{number}\",\n",
     "            tracker.close_ticket(f\"#{number}\",\n"),
]
