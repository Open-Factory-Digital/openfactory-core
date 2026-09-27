"""The off-argv channel, and the six ways it would be worse than not having one (#326).

THE ROW THAT MATTERS MOST IS 1. A prompt staged INSIDE the workspace is committed into the
ticket's own pull request by the job's `git add -A` — every ticket's diff would then carry the
prompt that produced it, in every job, for ever, and the suite would still be green because the
channel "works". That is this repository's signature defect shape applied to a fix for it.

ROWS 2-3 ARE THE DEGRADE AND THE MODE. A box that cannot stage must answer None and let the caller
keep the command line it has; a box that raises takes a job with it. And the text is a prompt, so
the file is the ticket — on a worktree box that is a machine other people have processes on.

ROWS 4-5 ARE THE CONTAINER'S TWO HALVES: where the file lands (under `/tmp`, never under the
mounted clone, for row 1's reason) and what a refused `docker cp` answers.

ROWS 6-7 ARE THE CONTRACT AROUND IT. The capability is deliberately off the `@runtime_checkable`
Protocol, so nothing forces a box to have it — which means the only protection against a box
having it in a shape the caller cannot call is the conformance shape check, and the only
protection against an ADAPTER's conformance going silent when it uses the channel is the
recorder keeping what it was handed.
"""

TEST = "tests/test_the_box_takes_text_the_command_line_never_carries.py"

MUTATIONS = [
    ("the worktree box stages the prompt INSIDE the workspace, so the job's own `git add -A` "
     "commits it into the ticket's pull request — the channel works and every diff carries the "
     "prompt that produced it",
     "openfactory/adapters/sandbox/worktree.py",
     "            root = self.root / _INPUT_DIRNAME",
     "            root = workspace.path / _INPUT_DIRNAME"),

    ("a box that cannot stage raises instead of answering None, so a directory it may not write "
     "ends the job rather than leaving the caller the command line it already had",
     # RE-PINNED (review of #349): the clause now catches `(OSError, ValueError)` and carries a
     # comment, so the anchor is the two lines that end it — "command line it has" is unique here.
     "openfactory/adapters/sandbox/worktree.py",
     "                        \"command line it has\", len(text or \"\"), exc)\n"
     "            return None",
     "                        \"command line it has\", len(text or \"\"), exc)\n"
     "            raise"),

    ("the staged prompt is world-readable, on a box whose machine has other people's processes "
     "on it — and the text is the ticket",
     "openfactory/adapters/sandbox/worktree.py",
     "            os.chmod(name, 0o600)",
     "            os.chmod(name, 0o644)"),

    ("the container stages into the mounted clone instead of `/tmp`, which is row 1 again by "
     "another road: the workspace is the bind-mounted checkout",
     "openfactory/adapters/sandbox/container.py",
     '_INPUT_DIR = "/tmp/openfactory-input"',
     '_INPUT_DIR = "/workspace/.openfactory-input"'),

    ("a refused `docker cp` still answers with a path, so the caller builds a command that reads "
     "a file the box does not have — and the harness is handed an empty prompt",
     "openfactory/adapters/sandbox/container.py",
     "        if rc != 0:\n"
     "            log.warning(\"could not stage %d characters into the box %s (%s)\",\n"
     "                        len(text or \"\"), self._container, (out or \"\").strip()[:160])\n"
     "            return None\n"
     "        return target",
     "        return target"),

    ("the conformance shape check goes away, so a box may offer the capability with a signature "
     "the caller cannot call — a TypeError inside a job instead of a finding at the door",
     "openfactory/conformance/adapters.py",
     "    stage = getattr(box, \"stage_input\", None)\n    if stage is not None:",
     "    stage = None\n    if stage is not None:"),

    # ── the review of #349: three promises the code did not keep, and one the suite could not test
    ("the check judges the SPELLING of the signature again instead of asking whether the caller's "
     "call binds, so an add-on box written the ordinary way — `def stage_input(self, workspace, "
     "text)` — gets a red line at the door for a call that works perfectly",
     "openfactory/conformance/adapters.py",
     "            inspect.signature(stage).bind(workspace=None, text=\"\")",
     "            _p = inspect.signature(stage).parameters\n"
     "            if any(_p[n].kind is not inspect.Parameter.KEYWORD_ONLY\n"
     "                   for n in _p if n != \"self\"):\n"
     "                raise TypeError(\"not keyword-only\")"),

    ("a text that cannot be ENCODED escapes the degradation again: `UnicodeEncodeError` is a "
     "ValueError, a lone surrogate is what a surrogateescape-decoded file becomes, and the "
     "docstring promises None whenever the text cannot be staged",
     "openfactory/adapters/sandbox/worktree.py",
     "        except (OSError, ValueError) as exc:",
     "        except OSError as exc:"),

    ("the staged prompt outlives the box again, so every ticket's prompt stays on the machine for "
     "good — the docstring's own claim that the directory 'already removes' it, unkept",
     "openfactory/adapters/sandbox/worktree.py",
     "        for staged in self._staged:\n"
     "            try:\n"
     "                staged.unlink(missing_ok=True)",
     "        for staged in []:\n"
     "            try:\n"
     "                staged.unlink(missing_ok=True)"),

    ("cleanup sweeps the whole directory instead of what THIS box staged, so a second job's "
     "prompt is deleted mid-pass on a deployment that raised its concurrency",
     "openfactory/adapters/sandbox/worktree.py",
     "        for staged in self._staged:",
     "        for staged in list((self.root / _INPUT_DIRNAME).glob(\"*\")) if "
     "(self.root / _INPUT_DIRNAME).is_dir() else self._staged:"),

    ("the conformance recorder drops the text, so an adapter that moves its prompt off the "
     "command line reads as an adapter that said nothing",
     "openfactory/conformance/adapters.py",
     "        self.staged.append(text)",
     "        pass"),
]
