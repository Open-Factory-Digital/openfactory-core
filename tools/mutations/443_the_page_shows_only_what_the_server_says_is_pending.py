"""The product page shows buttons only for the proposal the server says is waiting (#443)."""

TEST = "tests/test_the_page_shows_only_what_the_server_says_is_pending.py"
STAGING = "openfactory/product/staging.py"
CHAT = "openfactory/api/product_chat.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    ("the server reads its own copy instead of the store, so a typed yes stays pending", STAGING,
     '        rows = {q.token.partition("|")[0]: q for q in _panel_store.pending(name)}\n',
     '        rows = {k: _panel_store.Pending(token=proposal_token(k, e), text="",'
     ' ts=datetime.now().isoformat()) for k, e in _PENDING.items()}\n'),
    ("an expired proposal is still named", STAGING,
     "                if clock - datetime.fromisoformat(q.ts).timestamp() > PROPOSAL_TTL_SECONDS:\n",
     "                if False:\n"),
    ("another person's proposal is offered to this one", STAGING,
     "        for key in dict.fromkeys((key_for(conversation, person), conversation)):\n",
     "        for key in dict.fromkeys(rows):\n"),
    ("the history frame names nothing, so a stale token survives the catch-up", CHAT,
     '        fan.release(sub, {"kind": "history", "turns": turns, "staged": sub.staged})\n',
     '        fan.release(sub, {"kind": "history", "turns": turns})\n'),
    ("the watch never asks the store again after a batch", CHAT,
     "                await self.hub.restage(self.product, self.conversation)\n",
     "                pass\n"),
    ("the hub says the same answer on every read", CHAT,
     "            if now != sub.staged:\n",
     "            if True:\n"),
    ("the page ignores the staged frame", PANEL,
     '  else if(m.kind==="staged"){pchatStaged(m.staged)}',
     '  else if(m.kind==="staged"){}'),
    ("the page merges instead of replacing, keeping a token the server did not name", PANEL,
     '  _pc.staged=(s&&s.token)?{token:s.token,approve:s.approve||"approve",reject:s.reject||"reject"}:null;\n',
     '  if(s&&s.token)_pc.staged={token:s.token,approve:s.approve||"approve",reject:s.reject||"reject"};\n'),
    ("the history frame's answer is not applied by the page", PANEL,
     '    if("staged" in m)pchatStaged(m.staged);\n',
     "\n"),
]
