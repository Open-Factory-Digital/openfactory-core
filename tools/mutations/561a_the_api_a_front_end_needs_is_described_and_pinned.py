"""The API a front end needs is described and pinned as an API (#561, slice 1), proven by
breaking it.

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/561a_the_api_a_front_end_needs_is_described_and_pinned.py

The contract is `docs/reference/the-front-end-api.md`. The claims, each a row:

  1. every route is a row in its area, and every row a route — the document and the code each cut;
  2. the default front end calls nothing the contract does not list;
  3. the credential is read three ways, and the 401 and 403 are the ones the contract names;
  4. the streams' frames and endings are the ones the code sends.
"""

TEST = "tests/test_the_front_end_api_is_a_contract.py"
CONTRACT = "docs/reference/the-front-end-api.md"
APP = "openfactory/api/app.py"
PAGE = "openfactory/api/panel.html"
CHAT = "openfactory/api/product_chat.py"

MUTATIONS = [
    # 1. the table
    ("a route the contract forgot goes unseen", CONTRACT,
     "| GET | `/api/v1/whoami` | every credential | who this credential is, and which areas it may "
     "act in |\n", ""),
    ("a row for a route that is gone stays", CONTRACT,
     "| GET | `/api/budget` | floor |", "| GET | `/api/budgets` | floor |"),
    ("a row states another area than the gate reads", CONTRACT,
     # RE-PINNED 2026-10-11 (#562): the board row names the product owner's read beside the floor
     "| GET | `/api/board/{project}` | floor;", "| GET | `/api/board/{project}` | product;"),
    ("the gate's area moves and the contract is not told", APP,
     '_UNSCOPED_ROUTES = ("/api/whoami",)', "_UNSCOPED_ROUTES = ()"),

    # 2. the page
    ("the default front end calls an address the contract does not list", PAGE,
     'let fresh=null;try{fresh=await api("/api/whoami")}catch(e){}',
     'let fresh=null;try{fresh=await api("/api/whoami/private")}catch(e){}'),

    # 3. credentials and refusals
    ("the cookie is not read", APP,
     "        else (_one_credential_cookie(request)\n              or request.query_params",
     "        else (\n              request.query_params"),
    ("the 401 says something else", APP,
     'if login else {"detail": "unauthorized"}', 'if login else {"detail": "denied"}'),
    ("the 403 says something else", APP,
     '            "detail": f"this credential is scoped to "',
     '            "detail": f"scoped to "'),

    # 4. the streams
    ("the product chat sends a frame the contract does not name", CHAT,
     '            sub.frames.put_nowait((sub.generation, {"kind": "resync"}))',
     '            sub.frames.put_nowait((sub.generation, {"kind": "refresh"}))', TEST),
    ("a stream ends with a word the contract does not name", APP,
     '_ENDED_WHY = {401: "signed_out", 403: "not_allowed"}',
     '_ENDED_WHY = {401: "logged_out", 403: "not_allowed"}'),
]
