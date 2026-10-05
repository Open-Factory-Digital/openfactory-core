"""A card the product filed in another of its repositories is seen delivered, so the requirement it
belongs to is announced (#492).

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/492_a_card_in_another_repository_is_seen_delivered.py

Row 1 is the defect as it shipped: the delivered set a loop is checked against is the board's
alone, one repository's list, so `acme/web#1` is never in it. Row 2 puts back the early return
that let an empty board answer decide before the other repository was asked. Rows 3-4 break what
is read: a loop with work still open in its own repository is read anyway, and the tracker's own
cards are read one by one instead of taken from the board. Rows 5-7 break what counts as delivered:
every card read (open, or closed as not planned), a card that could not be read, and a read with
no `stateReason`. Rows 8-10 break the failure: an unread card said nothing about, a raise inside
the other repository's read reaching the round, and a row that raises reaching it at the port.
Rows 11-12 break the GitHub row's read: the card read in the tracker's own repository instead of
the one its ref names, and the ref answered bare. Row 13 breaks the board's per-ref read: the ref
answered, not the ref asked, so a row answering `1` makes `acme/web#1` the tracker's own `#1`.
"""

TEST = "tests/test_a_card_in_another_repository_is_seen_delivered.py"

EVENTS = "openfactory/product/events.py"
LOOPS = "openfactory/lifecycle/loops.py"
BOARD = "openfactory/product/board.py"
BASE = "openfactory/adapters/tracker/base.py"
GITHUB = "openfactory/adapters/tracker/github.py"

MUTATIONS = [
    # re-pinned 2026-10-05: integration of slices 4/5 with the door stack — `events.deliver`
    # became the card door's `loops.announce` (#414), which asks the other repository now
    ("TODAY'S DEFECT: the delivered set is the board's, one repository's list", LOOPS,
     "    delivered = set(delivered or ()) | events._delivered_elsewhere(project, "
     "set(delivered or ()))\n",
     "    delivered = set(delivered or ())\n"),

    # re-pinned 2026-10-05: integration of slices 4/5 with the door stack (#414)
    ("an empty board answer returns before the other repository is asked", LOOPS,
     "    if not events._speaks(project):\n        return [], 0\n"
     "    delivered = set(delivered or ()) | events._delivered_elsewhere(",
     "    if not events._speaks(project) or not delivered:\n        return [], 0\n"
     "    delivered = set(delivered or ()) | events._delivered_elsewhere("),

    ("a loop with work still open in its own repository is read anyway", EVENTS,
     "            if elsewhere and cards - elsewhere <= delivered:\n",
     "            if elsewhere:\n"),

    ("the tracker's own cards are read one by one, not taken from the board", EVENTS,
     "            elsewhere = {c for c in cards if split_repo_ref(c)[0] and c not in delivered}\n",
     "            elsewhere = {c for c in cards if c not in delivered}\n"),

    ("every card read counts as delivered, open or closed as not planned", EVENTS,
     "    return {t.number for t in read if t.delivered}\n",
     "    return {t.number for t in read}\n"),

    ("a card of another repository that could not be read counts as delivered", EVENTS,
     "    return {t.number for t in read if t.delivered}\n",
     "    return {t.number for t in read if t.delivered} | set(unread)\n"),

    ("the card is read without why it was closed", GITHUB,
     '        p = self._gh(["issue", "view", num, "--repo", repo, "--json", _LIST_FIELDS])\n',
     '        p = self._gh(["issue", "view", num, "--repo", repo, "--json",\n'
     '                      "number,title,body,state,labels,assignees,updatedAt"])\n'),

    ("a card that could not be read is said nothing about", EVENTS,
     "    if unread:\n        log.warning(\"OPENFACTORY_DELIVERY_UNREAD",
     "    if False:\n        log.warning(\"OPENFACTORY_DELIVERY_UNREAD"),

    ("a raise inside the other repository's read reaches the round", EVENTS,
     "    except Exception:  # noqa: BLE001 — not seen is not delivered; the board's answer "
     "stands\n",
     "    except ImportError:  # noqa: BLE001\n"),

    ("a row that raises reading a card by its ref raises at the port", BASE,
     "    except Exception:  # noqa: BLE001 — \"could not read\" is an answer: the card is not "
     "delivered\n",
     "    except ImportError:  # noqa: BLE001\n"),

    ("the card is read in the tracker's own repository, not the one its ref names", GITHUB,
     '        p = self._gh(["issue", "view", num, "--repo", repo, "--json", _LIST_FIELDS])\n',
     '        p = self._gh(["issue", "view", num, "--repo", self.repo, "--json", _LIST_FIELDS])\n'),

    ("the GitHub row answers a card of another repository by its bare number", GITHUB,
     "        return _summary(row, ref=qualify_ref(repo, row.get(\"number\") or num, self.repo))\n",
     "        return _summary(row, ref=canonical_ref(row.get(\"number\") or num))\n"),

    ("the board's per-ref read keeps the ref answered, not the ref asked", BOARD,
     "            read.append(_ticket(summary, {}).model_copy(update={\"number\": ref}))\n",
     "            read.append(_ticket(summary, {}))\n"),
]
