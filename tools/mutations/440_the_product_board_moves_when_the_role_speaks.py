"""The product page's Board is read again when the role speaks and when it is opened (#440)."""

TEST = "tests/test_events_and_the_agenda.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    ("the role's reply re-reads the agenda only, as before", PANEL,
     "  loadAgenda();\n  pvBoardLoad();\n",
     "  loadAgenda();\n"),
    ("opening the Board tab shows what the page read when it opened", PANEL,
     '  if(k==="board")pvBoardLoad();\n',
     "\n"),
]
