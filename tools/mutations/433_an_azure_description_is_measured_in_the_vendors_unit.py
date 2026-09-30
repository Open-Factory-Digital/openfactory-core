"""Azure DevOps measures a PR description in UTF-16 code units, and so does the cut (#433)."""

TEST = "tests/test_the_pull_request_says_what_the_card_says.py"
FORGE = "openfactory/adapters/forge/azure_devops.py"

MUTATIONS = [
    ("the vendor's length is Python's code-point count again", FORGE,
     '    return len(text.encode("utf-16-le")) // 2\n',
     "    return len(text)\n"),
    ("the ceiling is checked in the vendor's unit but the cut keeps counting code points", FORGE,
     "            used += _vendor_length(ch)\n",
     "            used += 1\n"),
    ("the cut note's own length is left out of the room", FORGE,
     "        room = cls._DESCRIPTION_MAX - _vendor_length(cls._CUT_NOTE)\n",
     "        room = cls._DESCRIPTION_MAX\n"),
    ("a pictograph on the boundary is kept though it does not fit", FORGE,
     "            if used > room:\n",
     "            if used > room + 1:\n"),
]
