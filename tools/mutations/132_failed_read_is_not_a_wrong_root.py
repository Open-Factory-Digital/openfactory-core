"""#132: a 503 must not buy the hundredfold board read. Each cut restores a way to pay for it."""

TEST = "tests/test_a_failed_board_read_is_not_a_wrong_root.py"
GP = "openfactory/adapters/tracker/github_project.py"

MUTATIONS = [
    ("a failed call is read as a wrong root again — the whole defect", GP,
     "                if not _is_wrong_root(str(exc)):\n"
     "                    raise BoardUnreadable(\n"
     '                        f"could not read board {self.owner}/{self.number} under {root}: "\n'
     '                        f"{str(exc)[:200]}") from exc\n',
     ""),

    ("unrecognised forge text is guessed as a wrong root", GP,
     "    return any(marker in said for marker in _WRONG_ROOT)",
     "    return True"),

    ("a genuine wrong root stops being recognised, so the other is never tried", GP,
     '_WRONG_ROOT = ("not_found", "could not resolve to an organization",\n'
     '               "could not resolve to a user", "type_mismatch")',
     '_WRONG_ROOT = ("nothing-matches-this",)'),

    ("the caller catches the failure back into the fallback", GP,
     "        for root in (\"organization\", \"user\"):\n"
     "            items = self._board_items_via_graphql(root)\n"
     "            if items is not None:\n                return items",
     "        try:\n"
     "            for root in (\"organization\", \"user\"):\n"
     "                items = self._board_items_via_graphql(root)\n"
     "                if items is not None:\n                    return items\n"
     "        except BoardUnreadable:\n            pass"),

    ("an unreadable board becomes an empty one", GP,
     "                    raise BoardUnreadable(\n"
     '                        f"could not read board {self.owner}/{self.number} under {root}: "\n'
     '                        f"{str(exc)[:200]}") from exc',
     "                    return []"),

    ("BoardUnreadable stops being its own type", GP,
     "class BoardUnreadable(RuntimeError):",
     "BoardUnreadable = RuntimeError\n\n\nclass _WasBoardUnreadable(RuntimeError):"),
]
