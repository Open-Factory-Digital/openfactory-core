"""A breakdown's outcome says what did not land, on every surface it is told on (#564, the
catalog's two doors), proven by breaking it.

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/564_a_breakdown_says_what_did_not_land_on_every_surface.py

An acceptance from the panel answered "Work filed: …" about the fronts that landed, and the front
the vet refused was named only in a log line. The claims, each a row:

  1. the acceptance and the `product_break_down` row render every row, not only the landed ones
     (rows 1-2);
  2. the catalog's text is plain, and the conversation keeps its emphasis (rows 3-4).
"""

TEST = "tests/test_a_breakdown_says_what_did_not_land_on_every_surface.py"

CATALOG = "openfactory/actions/catalog.py"
CONFIRM = "openfactory/product/confirm.py"

MUTATIONS = [
    # RE-PINNED 2026-10-10 (review of #580): the board is asked in a thread, with the project the
    # door already holds
    ("TODAY'S DEFECT, ON THE ACCEPTANCE: only what landed is said", CATALOG,
     "        said = await asyncio.to_thread(_breakdown_said, proj, number, filed)\n",
     "        said = await asyncio.to_thread(_breakdown_said, proj, number, made)\n"),
    ("the break-down row says only what landed", CATALOG,
     "        return done(await asyncio.to_thread(_breakdown_said, proj, num, filed), **data)\n",
     "        return done(await asyncio.to_thread(_breakdown_said, proj, num, made), **data)\n"),
    # review of #580: with two fronts refused, the second was named nowhere
    ("a second front not filed is named nowhere", CONFIRM,
     '        out += said["not_registered_some"].format(n=len(failed)) + " ".join(told)\n',
     '        out += said["not_registered_some"].format(n=len(failed)) + told[0]\n'),
    ("the board's name is read on the event loop", CATALOG,
     "        return done(await asyncio.to_thread(_breakdown_said, proj, num, filed), **data)\n",
     "        return done(_breakdown_said(proj, num, filed), **data)\n"),
    ("the conversation's emphasis reaches the action layer", CONFIRM,
     "                            project=project, backlog=backlog, marked=False)\n",
     "                            project=project, backlog=backlog, marked=True)\n"),
    ("the conversation loses its emphasis", CONFIRM,
     '    count = f"**{len(landed)}**" if marked else str(len(landed))\n',
     "    count = str(len(landed))\n"),
]
