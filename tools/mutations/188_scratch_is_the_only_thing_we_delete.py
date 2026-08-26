"""#188: only a directory this platform named is ever deleted recursively.

The defect these cuts restore called `shutil.rmtree("/tmp")` three times per suite run. It was
invisible on macOS and destroyed pytest's own temp root on Linux, failing 898 tests with an error
that named nothing. So the only question worth asking of the new guard is whether it goes red when
each half of the check is removed.
"""

TEST = "tests/test_a_scratch_directory_is_the_only_thing_we_delete.py"
S = "openfactory/util/scratch.py"
C = "openfactory/techlead/conversation.py"

MUTATIONS = [
    # THE EXACT DEFECT: the temp root itself passes, because "inside the temp dir" is the half of
    # the question that says yes to `/tmp`.
    ("the temp root itself becomes deletable again", S,
     "    if resolved == root or not resolved.is_relative_to(root):",
     "    if not resolved.is_relative_to(root):"),

    ("the prefix stops being checked, so any temp path is ours", S,
     "    return top.startswith(PREFIX)", "    return True"),

    ("the containment check goes, so any path with our prefix anywhere is ours", S,
     "    if resolved == root or not resolved.is_relative_to(root):\n        return False",
     "    if False:\n        return False"),

    # A prefix test against the RAW string accepts `<tmp>/openfactory-x/../..`, which resolves to
    # the temp root — the escape the resolve() exists to close.
    ("the path is judged before it is resolved", S,
     "        resolved = p.resolve()", "        resolved = p"),

    ("a refusal deletes anyway", S,
     "        log.error(\"refusing to delete %s — not a scratch directory this platform created\","
     " path)\n        return False",
     "        shutil.rmtree(path, ignore_errors=True)\n        return True"),

    ("the refusal stops being findable in the log", S,
     "        log.error(\"refusing to delete %s — not a scratch directory this platform created\","
     " path)",
     "        pass"),

    # And the call site: importing `scratch` while keeping the bare delete is the shape a
    # half-applied fix takes.
    ("the call site goes back to a bare recursive delete", C,
     "        scratch.discard(tmp)",
     "        import shutil as _s\n        _s.rmtree(tmp, ignore_errors=True)"),
]
