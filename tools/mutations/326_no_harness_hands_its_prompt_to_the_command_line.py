"""No harness hands its prompt to the command line, at any door, on any platform (#326).

The guard runs every door of every shipped harness on the real worktree box (and one on the real
container box) against a stand-in CLI that writes down its own argv, stdin and environment, with a
corpus sized past this platform's `ARG_MAX`. Each cut below puts the prompt back where the kernel
refuses it, takes the channel away, or changes what the staged command hands the process — and
the last two cut the guard's own premise and its ceiling from the other side.

Where a row says "on argv", the measured failure is the incident's: `OSError: [Errno 7] Argument
list too long`, which the guard turns into a sentence naming the door.
"""

TEST = "tests/test_no_harness_hands_its_prompt_to_the_command_line.py"
GUARD = TEST

MUTATIONS = [
    # ── each builder, putting the prompt back on argv while the box staged it ────────────────────
    ("claude's builder ignores the staged path and puts the prompt on argv",
     "openfactory/adapters/agent/claude_code.py",
     '        head = ([f"cat {shlex.quote(prompt_path)} |", harness, "-p"] if prompt_path\n'
     '                else [harness, "-p", shlex.quote(prompt)])\n',
     '        head = [harness, "-p", shlex.quote(prompt)]\n'),

    ("claude's lap stages the prompt and then forgets the path it was given",
     "openfactory/adapters/agent/claude_code.py",
     "                                    prompt_path=prompt_path)\n",
     "                                    prompt_path=None)\n"),

    ("codex appends the prompt as its positional argument even when it was staged",
     "openfactory/adapters/agent/codex.py",
     '        if not prompt_path:\n            cmd += ["--", shlex.quote(prompt)]',
     '        if True:\n            cmd += ["--", shlex.quote(prompt)]'),

    ("opencode appends the prompt as its positional argument even when it was staged",
     "openfactory/adapters/agent/opencode.py",
     '        if not prompt_path:\n            cmd += ["--", shlex.quote(prompt)]',
     '        if True:\n            cmd += ["--", shlex.quote(prompt)]'),

    ("the Claude reviewer ignores the staged path, so a large diff is on argv",
     "openfactory/adapters/reviewer/claude_code.py",
     '        head = ([f"cat {shlex.quote(prompt_path)} |", harness, "-p"] if prompt_path\n'
     '                else [harness, "-p", shlex.quote(prompt)])\n',
     '        head = [harness, "-p", shlex.quote(prompt)]\n'),

    # ── the channel itself ───────────────────────────────────────────────────────────────────────
    ("the seam stops asking the box for its channel, so every staging harness refuses a corpus "
     "it could have delivered",
     "openfactory/adapters/agent/base.py",
     '    stage = getattr(sandbox, "stage_input", None) if channel else None\n',
     "    stage = None\n"),

    ("the worktree box can no longer stage, so no harness runs on it",
     "openfactory/adapters/sandbox/worktree.py",
     "            return name\n",
     "            return None\n"),

    ("the container box can no longer stage, so the half of the fix that lives across the docker "
     "hop is gone while the worktree half stays green",
     "openfactory/adapters/sandbox/container.py",
     "        return target\n",
     "        return None\n"),

    # ── what the staged command must keep ────────────────────────────────────────────────────────
    ("opencode's read-only profile and project-config lock bind to `cat` instead of opencode, so "
     "a judging pass honours the client's own opencode.json — with every word still in the string",
     "openfactory/adapters/agent/opencode.py",
     '        cmd = [*pipe, *env, harness, "run", "--format", "json"]\n',
     '        cmd = [*env, *pipe, harness, "run", "--format", "json"]\n'),

    # ── the argument-only row ────────────────────────────────────────────────────────────────────
    ("a prompt no argument can carry is handed to the argument-only harness anyway, instead of "
     "refused by name",
     "openfactory/adapters/agent/base.py",
     "        raise PromptTooLarge(_prompt_too_large_finding(prompt, phase=phase, project=project))\n",
     "        pass\n"),

    ("the ceiling counts characters, so a multibyte prompt three times its length in bytes is put "
     "on argv (the approval's note on #360)",
     "openfactory/adapters/agent/base.py",
     '    return len(shlex.quote(prompt).encode("utf-8", "surrogatepass"))\n',
     "    return len(shlex.quote(prompt))\n"),

    ("the ceiling over-counts — four bytes a character — so a prompt that fits is refused",
     "openfactory/adapters/agent/base.py",
     '    return len(shlex.quote(prompt).encode("utf-8", "surrogatepass"))\n',
     '    return len(shlex.quote(prompt).encode("utf-32"))\n'),

    # ── the guard's own premise ──────────────────────────────────────────────────────────────────
    ("the corpus shrinks under every platform's limit, so the proof would pass with the prompt on "
     "argv — the control is what says so",
     GUARD,
     '_PAST_ARG_MAX = min(os.sysconf("SC_ARG_MAX"), 4 * 1024 * 1024) + 64 * 1024\n',
     "_PAST_ARG_MAX = 64 * 1024\n"),
]
