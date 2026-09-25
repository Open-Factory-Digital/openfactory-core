"""Mutation plan for #266 slice 2 — one turn engine, and nobody named across conversations
(ADR-0051 D9, D12).

Each row takes away one rule; every row must turn tests/test_one_turn_engine.py red.
"""

TEST = "tests/test_one_turn_engine.py"
ENGINE = "openfactory/product/engine.py"
RECALL = "openfactory/memory/recall.py"

MUTATIONS = [
    # RE-PINNED 2026-09-25: without names became render_recall's DEFAULT (review of #279), so
    # dropping the argument no longer names anybody; the cut is the engine asking for names.
    ("the conversation hands the model the names of people in other conversations", ENGINE,
     "        elsewhere = render_recall(hits, agent_name=agent_name, name_people=False)",
     "        elsewhere = render_recall(hits, agent_name=agent_name, name_people=True)"),
    ("a private conversation's key is printed beside the withheld speaker", RECALL,
     "        elif not name_people and is_private(s.where):",
     "        elif False:"),
    ("the anonymous rendering still names the person", RECALL,
     "            who = (s.actor or \"somebody\") if name_people else \"someone\"",
     "            who = s.actor or \"somebody\""),
]
