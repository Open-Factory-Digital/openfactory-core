"""Routing the prompt off the command line, and the six ways a cut used to survive (#326, #5).

THE PLAN THE REVIEW ASKED FOR. The routing landed with no plan, and the reviewer cut nineteen
guards by hand: thirteen went red and six survived — the `shlex.quote` around the staged path in
each of the five builders, and counting bytes rather than the quoted length at the ceiling. Every
row below either is one of those six or protects a property the review verified per CLI.

WHY THE QUOTE MATTERS, since a reader will ask why five near-identical rows are worth keeping: the
worktree box stages under the operator's own root, and that path can contain a space
(`~/Library/Application Support/…` is where a Mac puts it). Unquoted, `cat` is handed two arguments
and reads neither, so the harness is given an EMPTY prompt and answers about nothing — the failure
mode this whole change exists to remove, arriving by a different road.

AND WHY KIMI IS THE ROW THAT MUST NOT STAGE: `kimi-code`'s `-p` takes a value and enqueues it
verbatim, so `-p -` sent the model the one-character task `-` on every staged run. Read in 0.31.1,
the pinned version, and 0.32.0.
"""

TEST = "tests/test_a_large_prompt_travels_off_the_command_line.py"

MUTATIONS = [
    # ── the quote around the staged path: five builders, one property ────────────────────────────
    ("claude's builder stops quoting the staged path, so a path with a space becomes two arguments "
     "and `cat` reads neither — the harness is handed an empty prompt and answers about nothing",
     "openfactory/adapters/agent/claude_code.py",
     "shlex.quote(prompt_path)", "prompt_path"),

    ("codex's builder stops quoting it, same consequence",
     "openfactory/adapters/agent/codex.py",
     "shlex.quote(prompt_path)", "prompt_path"),

    ("opencode's builder stops quoting it, same consequence",
     "openfactory/adapters/agent/opencode.py",
     "shlex.quote(prompt_path)", "prompt_path"),

    ("the reviewer's builder stops quoting it, same consequence — and a review that reads nothing "
     "rejects a change nobody looked at",
     "openfactory/adapters/reviewer/claude_code.py",
     "shlex.quote(prompt_path)", "prompt_path"),

    # ── the ceiling measures what the shell will carry ───────────────────────────────────────────
    ("the ceiling counts the prompt's bytes again instead of the quoted argument's, so the window "
     "the review measured reopens: 131,000 bytes of ADR prose pass the check and raise "
     "`OSError: Argument list too long` out of Popen as a 131,886-byte argument",
     "openfactory/adapters/agent/base.py",
     "    return len(shlex.quote(prompt).encode(\"utf-8\", \"surrogatepass\"))",
     "    return len(prompt.encode(\"utf-8\", \"surrogatepass\"))"),

    ("the margin for the rest of the command goes, so a prompt just under the cap overflows it "
     "once the harness path, the flags and the model are added",
     "openfactory/adapters/agent/base.py",
     "    if _argv_bytes(prompt) > MAX_ARG_STRLEN - _COMMAND_MARGIN:",
     "    if _argv_bytes(prompt) > MAX_ARG_STRLEN:"),

    # ── kimi: the row whose CLI cannot read a staged prompt ──────────────────────────────────────
    ("kimi asks for the channel again, so `-p -` hands the model the one-character task `-` on "
     "every staged run — the blocking finding of the review, which no behavioural test caught "
     "because the assertion only checked the prompt was OFF the command line",
     "openfactory/adapters/agent/kimi.py",
     "            prompt_path = stage_prompt(sandbox, workspace, prompt, phase=phase, "
     "project=project,\n                                       channel=False)",
     "            prompt_path = stage_prompt(sandbox, workspace, prompt, phase=phase, "
     "project=project)"),

    ("the no-channel caller stops being able to say so, so `channel=False` is ignored and every "
     "row stages whatever its CLI can read",
     "openfactory/adapters/agent/base.py",
     "    stage = getattr(sandbox, \"stage_input\", None) if channel else None",
     "    stage = getattr(sandbox, \"stage_input\", None)"),

    # ── the refusal itself ───────────────────────────────────────────────────────────────────────
    ("a prompt nothing can carry is delivered anyway instead of refused by name, which is the "
     "`OSError` out of Popen this change exists to replace",
     "openfactory/adapters/agent/base.py",
     "        raise PromptTooLarge(_prompt_too_large_finding(prompt, phase=phase, project=project))",
     "        pass"),
]
