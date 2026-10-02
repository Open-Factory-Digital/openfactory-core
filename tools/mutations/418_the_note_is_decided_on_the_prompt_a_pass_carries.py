"""The inlined-documents note is decided on the prompt a pass carries, at the line it refuses at (#418).

#370's note measured the declared documents ALONE against the raw `MAX_ARG_STRLEN`, while the pass
refuses on its WHOLE prompt — the documents behind the role's instructions and the brief — quoted,
against that limit less the command's margin. Measured on this tree (no operator tier, ADRs of
8,000 characters): the planner's instructions and the brief add 7,704 bytes once quoted and the
margin 4,096 more, so a corpus from 119,209 to 131,072 bytes read as fitting in `doctor` and
`box prove` and was refused at pickup whatever the card said.

Eleven cuts, in four groups:

  * the LINE — the note goes back to the documents alone against the raw limit (the defect as
    filed), or measures the prompt against the raw limit and forgets the margin the pass holds back;
  * the FLOOR — `prompt_floor_bytes` stops being the prompt the passes build: it drops the role's
    instructions, counts bytes instead of the quoted argument, reads one pass's instructions where
    the larger is the planner's, or invents a card (the issue's own "not the fix");
  * the CALLERS — `doctor` or `box prove` decides the note on the documents' sum again, or measures
    the floor without the profile the job runs under (#416's lesson, on the new measure);
  * the HEADROOM — the half that says how close the floor comes and what the card has left goes
    silent, which is the under-warning the issue is about for every card larger than that.
"""

TEST = "tests/test_the_inlined_document_bytes_are_reported.py"
CONTEXT = "openfactory/orchestrator/context.py"
DOCTOR = "openfactory/doctor.py"
BOX_PROVE = "openfactory/box_prove.py"

MUTATIONS = [
    # ── the line ──────────────────────────────────────────────────────────────────────────────────
    ("the note is decided on the documents ALONE against the raw limit again — #418 as filed: a "
     "corpus the pass refuses at pickup reads as fitting",
     CONTEXT,
     "    if prompt_bytes > ARGV_PROMPT_CEILING:\n",
     "    if total > MAX_ARG_STRLEN:\n"),

    ("the note measures the prompt against the RAW limit, forgetting the 4,096 bytes the pass holds "
     "back for the rest of the command — the note's line and the refusal's drift apart again",
     CONTEXT,
     "    if prompt_bytes > ARGV_PROMPT_CEILING:\n",
     "    if prompt_bytes > MAX_ARG_STRLEN:\n"),

    # ── the floor ─────────────────────────────────────────────────────────────────────────────────
    ("the floor drops the role's instructions, the 6,073 bytes the planner's prompt opens with",
     CONTEXT,
     '    return max(_argv_bytes(f"{role_prompt(role)}\\n\\n{brief}")',
     "    return max(_argv_bytes(brief)"),

    ("the floor counts the prompt's bytes instead of the quoted argument the shell carries, so "
     "every apostrophe in the documents is four bytes short",
     CONTEXT,
     '    return max(_argv_bytes(f"{role_prompt(role)}\\n\\n{brief}")',
     '    return max(len(f"{role_prompt(role)}\\n\\n{brief}".encode())'),

    ("the floor reads the executor's instructions only, while the planner's — the first pass a "
     "pickup starts — are longer",
     CONTEXT,
     '_PASSES_THAT_INLINE_THE_DOCUMENTS = ("planner", "executor")',
     '_PASSES_THAT_INLINE_THE_DOCUMENTS = ("executor",)'),

    ("the floor INVENTS a card — the issue's own 'not the fix': a number for a ticket that does "
     "not exist, past the floor every real one stands on",
     CONTEXT,
     '_BLANK_CARD = Ticket(id="", title="", objective="", repo="")',
     '_BLANK_CARD = Ticket(id="#0", title="a typical card", objective="change one thing and test '
     'it", repo="")'),

    # ── the callers ───────────────────────────────────────────────────────────────────────────────
    ("doctor decides the note on the documents' sum again, so its probe calls fitting what the "
     "pass refuses",
     DOCTOR,
     "        note = inlined_document_overflow(sum(per_role.values()), prompt_bytes=floor,",
     "        note = inlined_document_overflow(sum(per_role.values()),\n"
     "                                         prompt_bytes=sum(per_role.values()),"),

    ("box prove decides the note on the documents' sum again — the same, on the other caller",
     BOX_PROVE,
     "        note = inlined_document_overflow(sum(per_role.values()), prompt_bytes=floor,",
     "        note = inlined_document_overflow(sum(per_role.values()),\n"
     "                                         prompt_bytes=sum(per_role.values()),"),

    ("doctor measures the floor with NO profile, so a profiled project's prompt is sized on a "
     "corpus no pass inlines",
     DOCTOR,
     "        floor = prompt_floor_bytes(manifest, pathlib.Path(root), profile=profile)",
     "        floor = prompt_floor_bytes(manifest, pathlib.Path(root))"),

    ("box prove measures the floor with NO profile — the same, on the other caller",
     BOX_PROVE,
     "            floor = prompt_floor_bytes(manifest, repo, profile=profile)",
     "            floor = prompt_floor_bytes(manifest, repo)"),

    # ── the headroom ──────────────────────────────────────────────────────────────────────────────
    ("the note goes silent when the floor fits, so a deployment whose prompt rides the command "
     "line is never told how close it is or how many bytes the card has left",
     CONTEXT,
     "    left = ARGV_PROMPT_CEILING - prompt_bytes\n",
     '    return ""\n    left = ARGV_PROMPT_CEILING - prompt_bytes\n'),
]
