"""#384, proven by breaking it — a card nobody has started is closed, or removed, from the card.

WHAT WAS MEASURED, on v0.4.1, local board, a card the product role opened from a request, in
Backlog: the product view had no card to act on; the floor board's `card_close` refused it
(`_product_owned_refusal`: "only the product owner closes it … ask for it in the conversation");
nothing anywhere deleted a card. The person who asked for the card could not drop it without
opening a conversation and finding the right sentence.

SIX CLAIMS:

  1. **A close of a product-opened card goes THROUGH the product role**, from either surface —
     never refused, never around the role (`_by_the_product_role` → `withdraw_card`).
  2. **Removal is only before pickup.** `has_started` refuses it, with the close's own sentence
     where a job may be on the card; no engine is asked.
  3. **The person who asked, a product admin, or a vouched operator — nobody else.**
  4. **The conversation is told** (`events.card_withdrawn`).
  5. **What "remove" means is the row's.** The local board deletes and keeps an audit line; a row
     with no removal closes as NOT delivered and says so.
  6. **A removed card's number is never handed out again** (`next_ref`).

The guard is `tests/test_a_card_nobody_started_can_be_closed_and_removed.py`.
"""

TEST = "tests/test_a_card_nobody_started_can_be_closed_and_removed.py"

CATALOG = "openfactory/actions/catalog.py"
MODULE = "openfactory/product/module.py"
BASE = "openfactory/adapters/tracker/base.py"
LOCAL = "openfactory/adapters/tracker/local.py"
DB = "openfactory/adapters/board_db.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    # ── 1. through the product role ────────────────────────────────────────────────────────────
    ("THE FIX ITSELF: the board's close of a card the product role opened goes around the role, "
     "so the conversation is never told and the requirement and the card can drift", CATALOG,
     "    delivered = has_finished(stage.key)\n    if kind:\n",
     "    delivered = has_finished(stage.key)\n    if False:\n"),

    # ── 2. only before pickup ──────────────────────────────────────────────────────────────────
    ("a card the factory has taken up is removed, erasing what was done and said on it", CATALOG,
     "        if has_started(key) and not may_be_running(key):\n",
     "        if False:\n"),

    ("a removal is judged by the close's gate, so a card under a running job is removed from "
     "under it", CATALOG,
     '        return stage, _stage_refusal(proj, board, issue, act="remove", stage=stage)',
     '        return stage, ""'),

    # ── 3. who may ─────────────────────────────────────────────────────────────────────────────
    ("anybody who reaches the product view drops anybody's card", MODULE,
     "        if not (vouched or may_act(self.project, actor, via=self._via)\n",
     "        if not (True or may_act(self.project, actor, via=self._via)\n"),

    ("the person who asked for the card cannot drop it — the product view's control refuses the "
     "one person the issue is about", MODULE,
     "                or (actor and not is_guest(actor) and self._asked_by(number) == actor)):",
     "                or False):"),

    ("an operator on the product view is refused the drop the floor lets them make", CATALOG,
     "    operator = bool(by.admin) and by.may_enter(FLOOR)\n",
     "    operator = False\n"),

    ("any admin of the product area is taken for an operator, so a business analyst drops "
     "anybody's card", CATALOG,
     "    operator = bool(by.admin) and by.may_enter(FLOOR)\n",
     "    operator = bool(by.admin)\n"),

    # ── 4. the conversation is told ────────────────────────────────────────────────────────────
    ("a dropped card vanishes with nothing said where it was asked for", MODULE,
     "            events.card_withdrawn(self.project, card=number, title=title,\n"
     "                                  removed=bool(remove), key=now_iso())\n",
     "            pass\n"),

    # ── 5. the row decides ─────────────────────────────────────────────────────────────────────
    ("a row with no removal is called anyway, so the tracker that can only close raises instead "
     "of closing and saying so", BASE,
     "    if removes(tracker):\n        tracker.remove_ticket(ref, reason, by=by)",
     "    if True:\n        tracker.remove_ticket(ref, reason, by=by)"),

    ("the close a row falls back to records the removed card as DELIVERED work", BASE,
     "    close_ticket(tracker, ref, note, delivered=False)\n    return False",
     "    close_ticket(tracker, ref, note, delivered=True)\n    return False"),

    ("the local removal leaves no audit line, so nobody can say who removed the card or why", LOCAL,
     '            conn.execute(\n                "INSERT OR REPLACE INTO removed_cards(',
     '            (lambda *_a: None)(\n                "INSERT OR REPLACE INTO removed_cards('),

    # ── 6. the number ──────────────────────────────────────────────────────────────────────────
    ("a removed card's number is handed to the next card, so every mention of it points at "
     "somebody else's work", DB,
     '        "  UNION ALL SELECT MAX(ref) AS top FROM removed_cards WHERE project = ?)",',
     '        "  UNION ALL SELECT NULL WHERE ? IS NULL)",'),

    # ── 7. the product role sees the removal (found live on #384) ─────────────────────────────
    ("the product role's refresh never asks what was removed, so a removed card stays in its "
     "board for good", "openfactory/product/board.py",
     "    if gone_refs:\n        known = [t for t in known if t.number not in gone_refs]\n",
     ""),

    ("a row that cannot say what it removed is refreshed blind instead of swept", BASE,
     "    except AttributeError:\n        return None\n    try:\n        found = ask(since=since)",
     "    except AttributeError:\n        return []\n    try:\n        found = ask(since=since)"),

    # ── the page ───────────────────────────────────────────────────────────────────────────────
    ("the product view draws its own controls instead of the card's, so the two surfaces drift",
     PANEL,
     '      ${_bcontrols(c,"product")}${said}`;',
     '      ${said}`;'),
]
