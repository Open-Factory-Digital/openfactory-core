"""The split announcement is actionable: which card, how many, and a reason that ends."""

TEST = "tests/test_the_split_says_which_card_to_drag.py"
V = "openfactory/techlead/voice.py"
ACT = "openfactory/runtime/temporal/activities.py"
SPLIT = "tests/test_sweep_records_only_what_posted.py"
LANG = "tests/test_no_gesture_exists_in_one_language_only.py"

MUTATIONS = [
    # ── one stuck card is not "them" ─────────────────────────────────────────────────────────────
    ("a single straggler is addressed in the plural again", ACT,
     '                "split.straggler-one" if len(stragglers) == 1 else "split.stragglers",',
     '                "split.stragglers",', SPLIT),

    ("…and the singular row loses its own words", V,
     '        "en": " I created all {n}, but could not move {stuck} to TO-DO — drag that one '
     'onto the "\n'
     '              "board, after the others, or it will never run:\\n{children}",',
     '        "en": " I created all {n}, but could not move {stuck} to TO-DO — drag those onto '
     'the "\n'
     '              "board, in order, or they will never run:\\n{children}",'),

    ("the plural row is written in the singular, so several read as one", V,
     '        "en": " I created all {n}, but could not move {stuck} to TO-DO — drag those onto '
     'the "\n'
     '              "board, in order, or they will never run:\\n{children}",',
     '        "en": " I created all {n}, but could not move {stuck} to TO-DO — drag that one '
     'onto the "\n'
     '              "board, after the others, or it will never run:\\n{children}",'),

    # ── the list marks the stuck child ───────────────────────────────────────────────────────────
    ("the stuck child stops being marked in the list", ACT,
     '            + (f"  ← {stuck_note}" if r in stragglers else "")\n', "", SPLIT),

    ("…and every child is marked instead, so the marker says nothing", ACT,
     '            f"  {\'⚠\' if r in stragglers else \'•\'} {r} — "',
     '            f"  ⚠ {r} — "', SPLIT),

    ("the marker is welded English", V,
     '    "split.not-queued": {"en": "NOT QUEUED — drag this one",\n'
     '                         "pt-BR": "FORA DA FILA — arrasta este"},',
     '    "split.not-queued": {"en": "NOT QUEUED — drag this one"},', LANG),

    # ── the reason ends where a reader can follow it ─────────────────────────────────────────────
    ("the reason is hard-sliced mid-word again", ACT,
     "why=_clipped(inp.reasons, 160))", "why=inp.reasons[:160])", SPLIT),

    ("…and the clip stops cutting at a word boundary", ACT,
     '    cut = clean[:limit].rsplit(" ", 1)[0].rstrip(" ,;:([{-")',
     "    cut = clean[:limit]"),

    ("…and stops trimming the punctuation it lands on", ACT,
     '.rsplit(" ", 1)[0].rstrip(" ,;:([{-")', '.rsplit(" ", 1)[0]'),

    ("a reason that FITS is marked as cut anyway", ACT,
     "    if len(clean) <= limit:\n        return clean", "    if False:\n        return clean"),

    # The `or clean[:limit]` fallback this row used to cut is GONE: `rsplit` with no
    # separator returns the whole string, so the branch could never be reached. The
    # mutation surviving is what proved it dead, and the code was deleted rather than
    # guarded.

    ("whitespace stops being collapsed, so the cap counts what nobody sees", ACT,
     '    clean = " ".join((text or "").split())', "    clean = text or \"\""),

    # ── and the announcement still goes out at all ───────────────────────────────────────────────
    ("the split stops announcing the stragglers", ACT,
     "            body = tl_voice.say(\n                tl_voice.NARRATION,\n"
     '                "split.straggler-one" if len(stragglers) == 1 else "split.stragglers",\n'
     "                lang, n=n, stuck=\", \".join(stragglers), children=kids)",
     '            body = ""', SPLIT),
]
