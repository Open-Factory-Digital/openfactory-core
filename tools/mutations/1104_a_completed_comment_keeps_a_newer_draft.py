"""A completed comment owns its submitted draft and the drawer that submitted it."""

TEST = "tests/test_a_completed_comment_keeps_a_newer_draft.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    ("a successful comment erases text typed while it was pending", PANEL,
     '  if(board.draft === draft) board.draft = "";',
     '  board.draft = "";'),
    ("a completed comment clears a different drawer's draft", PANEL,
     "  if(_bd !== board || board.project !== project || board.card !== card ||\n"
     "     board.selection !== selection) return;",
     "  if(false) return;"),
    ("leaving and reopening a card keeps an older comment's ownership", PANEL,
     "  board.selection = selection;",
     "  void selection;"),
]
