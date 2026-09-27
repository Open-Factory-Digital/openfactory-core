"""Whoever talks to the product role reads everything the product exposes (2026-09-25).

The product owner's decision, replacing #266 decision 8 for what the role reads: the role is the
product's owner, and a co-owner, an engineer or a client talking to it may read every document the
product exposes. What stays private is a PERSON's conversation, which the product does not expose.
Twelve rows of the 269 plans guarded the withholding this removed and were retired, each with a
note naming this plan; these rows put the withholding back, one path at a time:

  1. a client's turn is narrowed to the client's documents again (`turn_audience`);
  2. the panel shows a product credential a count where the floor gets names;
  3. a pack another conversation may read is searched as a client's again;
  4. a view made before the answer is the narrow one again;
  5. the room is not told of an internal document, whoever brought it.
"""

TEST = "tests/test_the_documents_are_read.py"
INDEX_TEST = "tests/test_the_hybrid_index.py"
STEP_TEST = "tests/test_the_retrieval_step.py"
MEMORY_TEST = "tests/test_the_memory_writes.py"

RECORD = "openfactory/product/documents/record.py"
APP = "openfactory/api/app.py"
RETRIEVAL = "openfactory/product/index/retrieval.py"
MODULE = "openfactory/product/module.py"
INGEST = "openfactory/product/documents/ingest.py"

MUTATIONS = [
    ("a client's turn is narrowed to the client's documents again", RECORD,
     "    del person, private\n    return INTERNAL",
     "    from openfactory.product.speaker import ADMIN, ENGINEER\n\n"
     "    return INTERNAL if private and getattr(person, \"role\", \"\") in (ADMIN, ENGINEER) "
     "else CLIENT",
     INDEX_TEST),

    ("the panel shows a product credential a count where the floor gets names", APP,
     "                **overview(product_key(proj), internal=True)}",
     "                **overview(product_key(proj), internal=False)}"),

    ("a pack another conversation may read is searched as a client's again", RETRIEVAL,
     "    query = Query(text=query_of(question, said), audience=audience,",
     "    query = Query(text=query_of(question, said), audience=audience if own else \"client\",",
     STEP_TEST),

    ("a view made before the answer is the narrow one again", MODULE,
     '        audience = str(getattr(self, "_documents_audience", "") or INTERNAL)',
     '        audience = str(getattr(self, "_documents_audience", "") or "client")',
     MEMORY_TEST),

    ("the room is not told of an internal document, whoever brought it", INGEST,
     "    if brought_to or not scheduled:\n        return brought_to",
     "    if record.audience != CLIENT and not brought_to:\n        return None\n"
     "    if brought_to or not scheduled:\n        return brought_to"),
]
