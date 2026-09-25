"""The product's search and reading work out of the box, and `openfactory doctor` says how (#337).

ROWS 1-2 ARE OCR'S LANGUAGES: tesseract asked for no language reads a Portuguese scan as English,
and a language this machine does not have makes it fail outright.

ROWS 3-6 ARE THE DOCTOR'S TWO LINES: a degraded search sent to the FAIL column (a deployment that
works told to fix itself), a model the row would refuse said to be on because its digest went
unchecked or its library missing, and a missing language pack said as nothing.

ROW 7 IS THE MEASUREMENT `store.py` NAMES: a slow search never logged by name, so the trigger to
revisit the index's design exists only in a comment again.
"""

TEST = "tests/test_the_doctor_says_how_the_product_reads.py"
DOCUMENTS_TEST = "tests/test_the_documents_are_read.py"
INDEX_TEST = "tests/test_the_hybrid_index.py"

PDF = "openfactory/adapters/extract/pdf.py"
LOCAL = "openfactory/adapters/embed/local.py"
DOCTOR = "openfactory/doctor.py"
SEARCH = "openfactory/product/index/search.py"

MUTATIONS = [
    ("OCR is asked for no language: a Portuguese scan is read as English", PDF,
     '                                      *(["-l", langs] if langs else [])], capture_output=True,',
     "                                      *([])], capture_output=True,",
     DOCUMENTS_TEST),

    ("OCR is asked for a language this machine does not have", PDF,
     '        return "+".join(dict.fromkeys(w for w in wanted if w in have))',
     '        return "+".join(dict.fromkeys(w for w in wanted))',
     DOCUMENTS_TEST),

    ("a search by words is a FAIL: a deployment that answers is told to fix itself", DOCTOR,
     '    return Finding("product_search", True, f"{words} — {state.search_detail}",\n'
     '                   note=f"the product\'s search is by words only',
     '    return Finding("product_search", False, f"{words} — {state.search_detail}",\n'
     '                   note=f"the product\'s search is by words only'),

    ("a model nobody pinned or declared is said to be on", LOCAL,
     "        if digest not in PINNED and digest != declared:",
     "        if False:"),

    ("a verified model whose library is missing is said to be on", LOCAL,
     "        if not _installed():",
     "        if False:"),

    ("a wanted OCR language that is not installed is said as nothing", DOCTOR,
     "        missing = tuple(w for w in wanted_languages() if w not in langs.split(\"+\"))",
     "        missing = ()"),

    ("a slow search is never named in the log", SEARCH,
     "    if took > SLOW_MS:",
     "    if False:",
     INDEX_TEST),
]
