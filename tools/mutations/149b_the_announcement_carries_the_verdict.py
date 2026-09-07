"""#149 (the half left standing): the announcement says what our own reviewer found."""

TEST = "tests/test_the_announcement_carries_the_verdict.py"
MACHINE = "openfactory/orchestrator/machine.py"

MUTATIONS = [
    # rows re-pinned 2026-09-07: the sentence is composed once, through the voice, and both the
    # comment and the notification carry it
    ("the ticket comment goes back to announcing nothing", MACHINE,
     '                ready = self._say("job.pr-ready", pr=pr, review=said)',
     '                ready = self._say("job.pr-ready", pr=pr, review="")'),

    ("…and the notification does", MACHINE,
     '                self._notify(f"{ticket.id} {ready}", "info")',
     '                self._notify(f"{ticket.id} PR ready for review: {pr}", "info")'),

    ("an absent review renders as a clean one", MACHINE,
     "    head = headline(verdict if isinstance(verdict, dict) else {})",
     '    head = headline(verdict if verdict else {"decision": "approved"})'),

    ("the verdict is composed here instead of through the shared renderer", MACHINE,
     "    from openfactory.review.verdict import headline",
     "    headline = lambda v, **k: {\"word\": (v or {}).get(\"decision\", \"?\"),  # noqa: E731\n"
     '                               "clause": "", "points": []}'),

    ("every finding is poured into a phone notification", MACHINE,
     '    for point in (head.get("points") or [])[:3]:',
     '    for point in (head.get("points") or []):'),

    ("the findings stop travelling at all", MACHINE,
     '    for point in (head.get("points") or [])[:3]:\n        out += f"\\n· {point}"',
     "    pass"),
]
