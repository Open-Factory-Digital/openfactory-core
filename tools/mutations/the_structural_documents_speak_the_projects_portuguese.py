"""The structural documents speak the project's Portuguese — the cuts that put Lisbon back in
São Paulo (2026-09-06).

ROW 1 IS THE MEASURED SHAPE: `_words` serves the Brazilian table to every `pt-*`.
ROW 2 IS THE REGION READ AS TYPED: `pt_PT` and `PT-pt` fall through to Brazilian.
ROWS 3-4 ARE ONE OVERRIDE LOST — a shared word (`t_file`) and a sentence (`s_files_read`).
ROW 5 IS THE OVERRIDE TABLE STANDING ALONE, without the base it inherits from.
"""

TEST = "tests/test_the_structural_documents_speak_the_projects_portuguese.py"

MUTATIONS = [
    ("_words serves the Brazilian table to every pt-* — the 2026-09-06 shape",
     "openfactory/onboarding/context.py",
     '        return _HEADINGS["pt-PT"] if lang == "pt-pt" else _HEADINGS["pt"]\n',
     '        return _HEADINGS["pt"]\n'),

    ("the region is read as typed — `pt_PT` and `PT-pt` fall through to Brazilian",
     "openfactory/onboarding/context.py",
     '    lang = str(_lang(language)).lower().replace("_", "-")\n',
     '    lang = str(_lang(language))\n'),

    ("the shared word `t_file` loses its override",
     "openfactory/onboarding/context.py",
     '    "t_file": "ficheiro",\n',
     ''),

    ("the sentence `s_files_read` loses its override",
     "openfactory/onboarding/context.py",
     '    "s_files_read": ("ficheiros-fonte lidos pelo mapa estrutural: {read}; ficheiros que '
     'ele "\n'
     '                     "não lê: {unread}"),\n',
     ''),

    ("the override table stands alone, without the base it inherits from",
     "openfactory/onboarding/context.py",
     '_HEADINGS["pt-PT"] = {**_HEADINGS["pt"], **_PT_PT}\n',
     '_HEADINGS["pt-PT"] = {**_PT_PT}\n'),
]
