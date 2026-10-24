"""Late reads must not take ownership of a newer card drawer."""

TEST = "tests/test_the_card_drawer_keeps_its_selection.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    ("a slow response paints over the current card", PANEL,
     "  if(_bd !== board || board.acceptedRead > read || board.project !== project ||\n"
     "     board.card !== card || board.pr !== pr || board.selection !== selection) return;",
     "  if(false) return;"),
    ("an older refresh of the same selection replaces the latest read", PANEL,
     "board.acceptedRead > read || board.project !== project",
     "board.project !== project"),
    ("a read from an earlier opening of the same card paints the new drawer", PANEL,
     "board.card !== card || board.pr !== pr || board.selection !== selection",
     "board.card !== card || board.pr !== pr"),
    ("the previous card's controls remain live while another card loads", PANEL,
     '  if(old) old.innerHTML = `<header><span class="ref">${esc(ref)}</span>',
     '  if(false) old.innerHTML = `<header><span class="ref">${esc(ref)}</span>'),
    ("reopening an unchanged card leaves its drawer loading forever", PANEL,
     "  board.selection = selection;\n"
     '  _bd.card = ref; _bd.pr = null; _bd.draft = ""; _bd.form = null; '
     '_bd.ask = null; _bd.said = null;\n'
     "  _bd.sig = null;",
     "  board.selection = selection;\n"
     '  _bd.card = ref; _bd.pr = null; _bd.draft = ""; _bd.form = null; '
     '_bd.ask = null; _bd.said = null;'),
    ("an old open reopens a drawer after its selection was closed", PANEL,
     "  if(_bd !== board || board.selection !== selection || board.card !== ref) return;",
     "  if(false) return;"),
    ("an earlier open of the same card completes the newer open", PANEL,
     "board.selection !== selection || board.card !== ref",
     "board.card !== ref"),
    ("an explicit repaint displays a card that is not the action target", PANEL,
     "  if(!drawer || !c || String(c.ref) !== String(_bd.card)) return;",
     "  if(!drawer || !c) return;"),
]
