"""Mutation plan for #266 slice 2 — one turn engine, and nobody named across conversations
(ADR-0051 D9, D12).

Each row takes away one rule; every row must turn tests/test_one_turn_engine.py red.
"""

TEST = "tests/test_one_turn_engine.py"
ENGINE = "openfactory/product/engine.py"
RECALL = "openfactory/memory/recall.py"

MUTATIONS = [
    ("the conversation hands the model the names of people in other conversations", ENGINE,
     "        elsewhere = render_recall(hits, agent_name=agent_name, name_people=False)",
     "        elsewhere = render_recall(hits, agent_name=agent_name)"),
    ("the anonymous rendering still names the person", RECALL,
     "            who = (s.actor or \"somebody\") if name_people else \"someone\"",
     "            who = s.actor or \"somebody\""),
]
