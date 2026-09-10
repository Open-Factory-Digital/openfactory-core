"""ADR-0049 slice 4b, proven by breaking it — `init` defaults to the machine in front of you.

THREE CLAIMS:

  1. **Both first questions default to `local`**, and the bare `Answers()` a test builds is the
     same default a person meets at the prompt. The two drifting is how a suite comes to prove a
     path nobody walks.
  2. **A local axis renders a NAMED, row-less section.** Silence and "that section has not been
     written yet" read identically in an `.env` file, and this one was silent — `local` is a
     shipped row, so it never reached the add-on placeholder, and it needs no credential, so it
     reached no block at all.
  3. **The hosted answers lose nothing.** The flip is a default, never a removal.

WHAT THE OLD GUARD COULD NOT SEE, and why this slice has a guard of its own:
`test_every_shipped_kind_NAMES_itself_in_the_file_rendered_for_it` searched the rendered text for
the kind's name, and `OPENFACTORY_BOT_EMAIL=bot@openfactory.local` contains "local" — so the whole
subject of this slice could have been missing with the suite green. That row is dropped from the
search now and the kind is asked for as a WORD; the row below proves the tightening.

The guards under test are `tests/test_init_asks_for_one_machine.py` and the doors-derive suite.
"""

TEST = "tests/test_init_asks_for_one_machine.py"

SLICE = "tests/test_init_asks_for_one_machine.py"
DOORS_TEST = "tests/test_the_doors_derive_from_the_registries.py"

DEP = "openfactory/onboarding/deployment.py"

MUTATIONS = [
    # ── 1. the default ─────────────────────────────────────────────────────────────────────────
    ("the forge question sends a person to a vendor again before they have run anything", DEP,
     '             "Any other answer decides which credential this file asks you for", _forges, '
     '"local"),',
     '             "Any other answer decides which credential this file asks you for", _forges, '
     '"github"),', SLICE),

    ("the tracker question does the same", DEP,
     '             "can differ: tickets in Jira with code on GitHub is ordinary", _trackers, '
     '"local"),',
     '             "can differ: tickets in Jira with code on GitHub is ordinary", _trackers, '
     '"github"),', SLICE),

    ("the model default drifts from the prompt's, so a test proves a path nobody walks", DEP,
     '    forge: str = "local"\n    tracker: str = "local"',
     '    forge: str = "github"\n    tracker: str = "github"', SLICE),

    ("the question offers `local` and never says what answering it does", DEP,
     '             "`local` is this machine: your own repository, no account and no credential. "\n'
     '             "Any other answer decides which credential this file asks you for", _forges, '
     '"local"),',
     '             "decides which credential this file asks you for", _forges, "local"),', SLICE),

    # ── 2. the named, row-less section ─────────────────────────────────────────────────────────
    ("a local axis renders nothing again, so the file is silent about where the code lives", DEP,
     '    for axis in ("forge", "tracker"):\n'
     '        if getattr(answers, axis) == "local":\n'
     '            parts.append(_local_block(axis, out))\n',
     "", SLICE),

    ("only the forge gets a section, so a local tracker is the silent one", DEP,
     '    for axis in ("forge", "tracker"):', '    for axis in ("forge",):', SLICE),

    ("the section stops saying what the axis IS and says only that it is free", DEP,
     '    "forge": "your own repository is the forge: job branches are pushed into it and a merge '
     'is a "\n'
     '             "fast-forward into your base, refused in git\'s own words when your tree is in '
     'the "\n             "way",',
     '    "forge": "nothing to fill in",', SLICE),

    ("the section grows a row nobody can fill", DEP,
     '# Nothing to fill in here: that is what `local` means.',
     'OPENFACTORY_LOCAL_TOKEN=\n# Nothing to fill in here: that is what `local` means.', SLICE),

    # ── 3. the guard that passed by luck ───────────────────────────────────────────────────────
    #
    # THE TIGHTENING CANNOT BE CUT DIRECTLY. Loosening the search back to a substring passes while
    # the section is there, because the section names `local` for real — the luck only mattered
    # when there was nothing else to find. So the row that proves it is the SILENCE it must catch:
    # delete what the render says about a local axis and point the cut at the tightened guard. A
    # loose search is satisfied by `bot@openfactory.local` and stays green; the tightened one goes
    # red, which is the whole claim.
    ("the local sections vanish and the doors-derive guard must SEE the silence — it did not, for "
     "a year, because the bot's email carries the word", DEP,
     '    for axis in ("forge", "tracker"):\n'
     '        if getattr(answers, axis) == "local":\n'
     '            parts.append(_local_block(axis, out))\n',
     "", DOORS_TEST),

    # ── 4. the hosted answers ──────────────────────────────────────────────────────────────────
    ("a GitHub deployment gets the local section too, in a file that has a credential to fill",
     DEP, '        if getattr(answers, axis) == "local":', "        if True:", SLICE),
]
