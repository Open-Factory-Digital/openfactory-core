"""ADR-0049 slice 3e, proven by breaking it — the last two composed vendor URLs retire.

THREE CLAIMS:

  1. **The GitHub row answers on every shape the healing path hands it** — bare, `#`-decorated,
     qualified with its own repository — and honours `GH_HOST`, which the literal never did.
  2. **The composed fallback was not merely redundant.** It resolved a bare ref through
     `_ref_repo`, whose default is the FORGE's repository and only then the tracker's, so on a
     project that declares both it addressed an issue in the repository the issue is not in.
  3. **Where the port cannot say, the answer is nothing** — not a guess. An empty `issue_url` is a
     shape the boards already meet (`conformance/adapters.py` probes with it) and the Projects
     board's own scan is the authority on whether a card is there.

WHAT THIS PLAN CANNOT SEE, said rather than left to survive quietly: nothing here proves that a
GitHub Enterprise deployment's card actually gets added to the board, because that needs the
vendor. The claim proven is about the URL the platform hands it.

The guard under test is `tests/test_the_ticket_url_is_the_trackers_own.py`.
"""

TEST = "tests/test_the_ticket_url_is_the_trackers_own.py"

SLICE = "tests/test_the_ticket_url_is_the_trackers_own.py"
#: the helper's own property — the card moves whatever the tracker says about links —
#: is held by the guard that has always owned it, so those rows are aimed there.
MOVES = "tests/test_the_card_moves_even_when_the_link_cannot_be_built.py"

ACT = "openfactory/runtime/temporal/activities.py"
GH = "openfactory/adapters/tracker/github.py"

MUTATIONS = [
    # ── 1. the row answers ─────────────────────────────────────────────────────────────────────
    ("the row stops honouring the host, so a GitHub Enterprise deployment links to public "
     "github.com where a same-named repository may belong to somebody else", GH,
     '        host = (os.environ.get("GH_HOST") or os.environ.get("GITHUB_HOST") '
     'or "github.com").strip()',
     '        host = "github.com"', SLICE),

    ("the row ignores the ref's own repository, so on a multi-repo board every card links into "
     "the default one", GH,
     "        repo, num = self._locate(ref)\n"
     '        host = (os.environ.get("GH_HOST") or os.environ.get("GITHUB_HOST") '
     'or "github.com").strip()',
     "        repo, num = self.repo, ref.lstrip('#')\n"
     '        host = (os.environ.get("GH_HOST") or os.environ.get("GITHUB_HOST") '
     'or "github.com").strip()', SLICE),

    ("the `#` a person types is left in the URL", GH,
     '        return f"https://{host}/{repo}/issues/{num}"',
     '        return f"https://{host}/{repo}/issues/{ref}"', SLICE),

    # ── 2. the guess comes back ────────────────────────────────────────────────────────────────
    ("the composed literal comes back at the split-child call site", ACT,
     "            issue_url=_ticket_url(tracker, num),",
     '            issue_url=(_ticket_url(tracker, num)\n'
     '                       or f"https://github.com/{repo}/issues/{num}"),', SLICE),

    ("the composed literal comes back on the healing path, resolved through the FORGE's "
     "repository — the defect this slice closed", ACT,
     "            healed_url = _ticket_url(tracker, ref)",
     "            heal_repo, heal_bare = _ref_repo(project, ref)\n"
     '            healed_url = (_ticket_url(tracker, ref)\n'
     '                          or f"https://github.com/{heal_repo}/issues/{heal_bare}")', SLICE),

    # ── 3. the helper ──────────────────────────────────────────────────────────────────────────
    ("a tracker without the method is answered with a guess instead of nothing", ACT,
     '    ask = getattr(tracker, "ticket_url", None)\n    if not callable(ask):\n        return ""',
     '    ask = getattr(tracker, "ticket_url", None)\n    if not callable(ask):\n'
     '        return f"https://github.com/{getattr(tracker, \'repo\', \'\')}/issues/{ref}"', MOVES),

    ("a tracker that RAISES takes the board move down with it — a link is never worth that", ACT,
     "    except Exception as exc:  # noqa: BLE001 — a link is never worth failing a board move "
     "for",
     "    except Exception as exc:  # noqa: BLE001\n        raise RuntimeError(exc) from exc\n"
     "    if False:", MOVES),

    ("the port's answer is taken unstripped, so a row that pads its URL hands the board a value "
     "it cannot resolve", ACT,
     '        return (ask(ref) or "").strip()',
     '        return ask(ref) or ""', MOVES),
]
