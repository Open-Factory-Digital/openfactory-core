"""The preview and card links the product role sends open for the person they are sent to (#444)."""

TEST = "tests/test_a_link_the_role_sends_opens_for_the_requester.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    ("the product page ignores the link, as before", PANEL,
     "  const linked=(name===null)?curBoard():null;\n",
     "  const linked=null;\n"),
    ("a preview link opens the card and never the preview", PANEL,
     "    if(linked.preview)openPreviewNow(linked.project,linked.card);\n",
     "\n"),
    ("a card link lands on the product page without its card", PANEL,
     '    pvTab("board");pvCardOpen(linked.card);\n',
     "\n"),
]
MUTATIONS += [
    ("the parser reads a preview link as a pull request with no ref again", PANEL,
     r"(board|card|pr|preview)(?=\/|$)(?:",
     r"(board|card|pr|preview)(?:"),
]
