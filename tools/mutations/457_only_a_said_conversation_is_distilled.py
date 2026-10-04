"""Only a conversation that SAID something becomes a distillate (#457).

Each cut breaks one thing the guards claim: a platform sentence is handed to the model; the marked
tree stops advancing the cursor or stops being hidden; a nothing-to-keep reading becomes a
distillate; an unmarked crash goes unrecognised; the once-per-span compare-and-swap looks in one
tree only. Every row must go red — a surviving cut is a guard that was decoration.
"""

TEST = "tests/test_the_memory_writes.py"

DISTIL = "openfactory/product/distil.py"
RECORD = "openfactory/product/documents/record.py"
AUTHORING = "openfactory/product/authoring.py"

_MARKED = "tests/test_the_memory_writes.py::test_a_marked_span_is_not_a_document"
_FINDS_NOTHING = ("tests/test_the_memory_writes.py::"
                  "test_a_span_a_model_finds_nothing_in_is_marked_read_not_distilled")
_PROMPT = ("tests/test_the_memory_writes.py::"
           "test_the_prompt_offers_nothing_to_keep_and_tells_a_question_from_a_request")
_CRASH = "tests/test_the_memory_writes.py::test_an_unmarked_crash_reply_reaches_no_model"
_CROSS_TREE = ("tests/test_the_memory_writes.py::"
               "test_a_span_marked_in_one_tree_is_not_distilled_in_the_other")
_AGREEMENT = ("tests/test_the_memory_writes.py::"
              "test_a_real_agreement_beside_a_platform_sentence_is_still_distilled_without_it")

MUTATIONS = [
    ("a platform sentence is handed to the model, not left out of the span", DISTIL,
     "        spoken = [s for s in addressed if not _is_platform(s)]\n",
     "        spoken = list(addressed)\n",
     _AGREEMENT),
    ("distilled_in stops reading the marked tree, so a marked span is read again", DISTIL,
     "    for top in (DISTILLATES, MARKED):\n",
     "    for top in (DISTILLATES,):\n",
     _FINDS_NOTHING),
    ("the marked tree is no longer hidden, so ingestion reads the mark as a document", RECORD,
     'MARKED = ".distilled"\n',
     'MARKED = "distilled"\n',
     _MARKED),
    ("a nothing-to-keep reading is ignored, so it becomes a distillate", DISTIL,
     "        return not self.nothing and any(getattr(self, name) for name, _title in SECTIONS)\n",
     "        return any(getattr(self, name) for name, _title in SECTIONS)\n",
     _PROMPT),
    ("an all-empty reading is counted as kept, so it becomes a distillate", DISTIL,
     "        return not self.nothing and any(getattr(self, name) for name, _title in SECTIONS)\n",
     "        return not self.nothing and True\n",
     _PROMPT),
    ("an unmarked crash reply is no longer recognised, so it reaches the model", DISTIL,
     '    return bool(voice.own_voice_kind(str(getattr(line, "text", "") or "")))\n',
     "    return False\n",
     _CRASH),
    ("the compare-and-swap reads one tree only, so a marked span is distilled too", AUTHORING,
     "        latest = _distilled_until_across_trees(tmp, path)\n",
     "        latest = distilled_until(target.parent)\n",
     _CROSS_TREE),
]
