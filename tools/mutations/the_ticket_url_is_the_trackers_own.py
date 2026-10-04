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

GH = "openfactory/adapters/tracker/github.py"
PORTS = "openfactory/lifecycle/ports.py"

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
    # RETIRED 2026-10-04 (#414): "the composed literal comes back at the split-child call site".
    # A split's children are filed through the card's door, which places them by the board's own
    # write and asks the link where every placement asks it (`Ports._url`, the row below): the
    # call site composes nothing and hands nothing, so there is no line left to cut there.

    # RE-PINNED 2026-10-02 (#414): the healer hands the card's door an observed close, whose column
    # is the tracker's own `set_state` — no URL is handed on that path any more. The place the door
    # still asks for a link is its board placement (`Ports._url`), and the guess is cut there.
    # re-pinned 2026-10-04: the port strips the answer since the helper it replaced went (#414)
    ("the composed literal comes back where the card's door places a card, resolved through the "
     "FORGE's repository — the defect this slice closed", PORTS,
     '            return str(self.tracker.ticket_url(card) or "").strip()\n',
     '            return str(self.tracker.ticket_url(card) or "").strip() or '
     'f"https://github.com/{self.name}/issues/{card}"\n', MOVES),

    # ── 3. the helper — the door's port since the last call site that shared it went (#414) ─────
    # re-pinned 2026-10-04: `activities._ticket_url` went with `_child_to_todo`; the port that
    # every placement asks is where a missing, raising or padded link is answered now
    ("a tracker without the method is answered with a guess instead of nothing", PORTS,
     '            log.info("the tracker could not name a URL for #%s", card, exc_info=True)\n'
     '            return ""\n',
     '            return f"https://github.com/{self.name}/issues/{card}"\n', MOVES),

    ("a tracker that RAISES takes the board move down with it — a link is never worth that", PORTS,
     "        except Exception:  # noqa: BLE001 — a link is a courtesy; the placement is not\n",
     "        except AttributeError:  # noqa: BLE001\n", MOVES),

    ("the port's answer is taken unstripped, so a row that pads its URL hands the board a value "
     "it cannot resolve", PORTS,
     '            return str(self.tracker.ticket_url(card) or "").strip()\n',
     '            return str(self.tracker.ticket_url(card) or "")\n', MOVES),
]
