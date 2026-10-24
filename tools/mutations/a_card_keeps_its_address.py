"""Exercise card addresses, history, and route callbacks against the panel's actual functions."""

TEST = "tests/test_a_card_keeps_its_address.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    ("opening the board replaces a card deep link", PANEL,
     "  if(!route || route.project!==name){",
     '  if(location.pathname!==`/p/${encodeURIComponent(name)}/board`){'),
    ("selecting a card writes no address", PANEL,
     '    if(location.pathname !== path) history.pushState({}, "", path);',
     '    if(false) history.pushState({}, "", path);'),
    ("closing the drawer leaves its card address", PANEL,
     "  if(route && (route.card || route.preview)){", "  if(false){"),
    ("a preview address is replaced by its card address", PANEL,
     "  if(route && route.project===_bd.project && route.preview && route.card===ref)",
     "  if(false)"),
    ("opening a board retains the previous selection and form", PANEL,
     "  closeBoard(false);\n  _bd.project = name;", "  _bd.project = name;"),
    ("an old callback reopens a card after route navigation", PANEL,
     "if(location.pathname!==path || _bd!==board)return;", "if(false)return;"),
    ("an old callback clears a draft after returning to the same path", PANEL,
     "if(location.pathname!==path || _bd!==board)return;",
     "if(location.pathname!==path)return;"),
]
