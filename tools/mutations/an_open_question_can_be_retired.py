"""An open question can be retired — the cuts that make the gather ask for ever again
(2026-09-06, the slice-2 design critique).

ROW 1 IS THE GATE NAMING AN ANSWERED QUESTION AGAIN — shown on every change, holding the file
when graded high, asking the person who answered to answer again.
ROWS 2-3 ARE THE TWO MERGES: the covering and the renewal appending the re-derivation beside the
record, so the answered question has an open twin next round.
ROW 4 IS THE IDENTITY: a key that differs between constructions can never be matched, retired or
deduplicated.
ROW 5 IS THE RECORD DELETED: a retirement that removes the question makes "somebody answered"
indistinguishable from "nobody asked".
ROWS 6-8 ARE THE AUTHOR: not told what was answered (by the covering, or by the prompt), or told
and the repeat minted anyway.
"""

TEST = "tests/test_an_open_question_can_be_retired.py"

MUTATIONS = [
    ("a retired question comes back next round — the gate names it again",
     "openfactory/knowledge/gate.py",
     "    return [g for where, rows in gaps.items() if where in prefixes for g in rows\n"
     "            if g.status != ANSWERED]\n",
     "    return [g for where, rows in gaps.items() if where in prefixes for g in rows]\n"),

    ("cover appends a duplicate key — the answered question gets an open twin",
     "openfactory/onboarding/cover.py",
     '        "gaps": merge_gaps(manifest.gaps, authored.gaps)})\n',
     '        "gaps": list(manifest.gaps) + list(authored.gaps)})\n'),

    ("the renewal appends a duplicate key — the same twin, one round later",
     "openfactory/onboarding/renew.py",
     "    gaps = merge_gaps(kept, list(new_gaps or []) + list(stale_gaps or [])\n"
     "                      + inventory_gaps(inventory))\n",
     "    gaps = kept + list(new_gaps or []) + list(stale_gaps or [])\n"
     "    gaps = gaps + inventory_gaps(inventory)\n"),

    ("the key changes between constructions — nothing can ever be matched to it",
     "openfactory/knowledge/contracts.py",
     "            self.key = gap_key(self.kind, self.path, self.detail)\n",
     '            self.key = f"{id(self):024x}"[-12:]\n'),

    ("the retirement deletes the question instead of keeping it as the record",
     "openfactory/knowledge/gaps.py",
     '    gaps = [\n'
     '        gap.model_copy(update={"status": ANSWERED, "answer": (answer or "").strip(),\n'
     '                               "answered_by": (by or "").strip(), "answered_at": at or ""})\n'
     '        if gap.key == wanted else gap\n'
     '        for gap in manifest.gaps\n'
     '    ]\n',
     '    gaps = [gap for gap in manifest.gaps if gap.key != wanted]\n'),

    ("the covering authors without telling what was answered",
     "openfactory/onboarding/cover.py",
     "generated_at=generated_at, answered=answered_gaps(previous))\n",
     "generated_at=generated_at, answered=[])\n"),

    ("the prompt drops what was answered — the same caveat comes back in new words",
     "openfactory/onboarding/concepts.py",
     "        *_already_answered(answered or []),\n",
     "        *_already_answered([]),\n"),

    ("a caveat asked again in the same words is minted as a new gap",
     "openfactory/onboarding/concepts.py",
     "            if question.key in closed:\n                continue",
     "            if False:\n                continue"),

    # review of #73: a dropped question mark was a new key
    ("trailing punctuation makes a new key again",
     "openfactory/knowledge/contracts.py",
     '    words = " ".join(str(detail).casefold().split()).rstrip("?.!…:;")\n',
     '    words = " ".join(str(detail).casefold().split())\n'),
]
