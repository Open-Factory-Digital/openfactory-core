"""The product page shows buttons only for the proposal the server says is waiting (#443)."""

TEST = "tests/test_the_page_shows_only_what_the_server_says_is_pending.py"
WAITING = "openfactory/product/waiting.py"
CHAT = "openfactory/api/product_chat.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    # RE-PINNED 2026-10-02 (#452): the three rows below moved with the read into
    # `waiting.in_conversation`, the one reader of what waits, which `staging.waiting_in` projects
    ("the server reads its own copy instead of the store, so a typed yes stays pending", WAITING,
     '    proposals = {q.token.partition("|")[0]: q for q in messages.pending(name)}\n',
     '    from openfactory.product.staging import _PENDING, proposal_token\n'
     '    proposals = {k: messages.Pending(token=proposal_token(k, e), text="",'
     ' ts=datetime.now().isoformat()) for k, e in _PENDING.items()}\n'),
    ("an expired proposal is still named", WAITING,
     "        if q is not None and (asked_at is None or clock - asked_at <= PROPOSAL_TTL_SECONDS):\n",
     "        if q is not None:\n"),
    ("another person's proposal is offered to this one", WAITING,
     "    for key in dict.fromkeys((key_for(conversation, person), conversation)):\n",
     "    for key in dict.fromkeys(proposals):\n"),
    # RE-PINNED 2026-10-10 (#566): the frame also carries the cursor of the page before it
    ("the history frame names nothing, so a stale token survives the catch-up", CHAT,
     '        fan.release(sub, {"kind": "history", "turns": turns, "staged": sub.staged,\n',
     '        fan.release(sub, {"kind": "history", "turns": turns,\n'),
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
