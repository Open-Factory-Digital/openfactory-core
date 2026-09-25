"""#180: the GitHub row's Done path closes the issue as completed — the tracker writes its card's
state, whatever forge it is paired with."""

TEST = "tests/test_a_delivered_card_is_closed_by_its_tracker.py"
TRACKER = "openfactory/adapters/tracker/github.py"

MUTATIONS = [
    ("THE DEFECT ITSELF: Done moves the column and leaves the issue open", TRACKER,
     "        if state is JobState.DONE:\n",
     "        if False:\n"),

    ("every state closes the issue, so a card is closed at its first transition", TRACKER,
     "        if state is JobState.DONE:\n",
     "        if True:\n"),

    ("a delivered card is closed as NOT planned, and drops out of what was delivered", TRACKER,
     '            self._write(["issue", "close", num, "--repo", repo, "--reason", "completed"])',
     '            self._write(["issue", "close", num, "--repo", repo, "--reason", "not planned"])'),

    ("the close goes to the adapter's default repository, not the card's — the pairing this "
     "issue is about", TRACKER,
     '            self._write(["issue", "close", num, "--repo", repo, "--reason", "completed"])',
     '            self._write(["issue", "close", num, "--repo", self.repo, "--reason", '
     '"completed"])'),

    ("a refused close raises out of `set_state`, failing a delivery that already landed", TRACKER,
     "        except Exception as exc:  # noqa: BLE001 — a delivery is never failed by its record\n"
     "            why = str(exc) or type(exc).__name__",
     "        except ZeroDivisionError as exc:\n"
     "            why = str(exc) or type(exc).__name__"),

    ("a refused close is swallowed: no log names the card", TRACKER,
     '        log.error("OPENFACTORY_DELIVERED_CARD_NOT_CLOSED %s#%s was delivered',
     '        log.debug("OPENFACTORY_DELIVERED_CARD_NOT_CLOSED %s#%s was delivered'),

    ("the row tells the card itself, in a language it was never told", TRACKER,
     '        log.error("OPENFACTORY_DELIVERED_CARD_NOT_CLOSED %s#%s was delivered',
     '        self.comment(ref, why)\n'
     '        log.error("OPENFACTORY_DELIVERED_CARD_NOT_CLOSED %s#%s was delivered'),

    ("the forge's own words are dropped from the log, so nobody can act on it", TRACKER,
     '                  "%s (triage reports it as done-but-open): %s", repo, num, repo, why)',
     '                  "%s (triage reports it as done-but-open): %s", repo, num, repo, "")'),

    # Re-pinned by #180's second half: the state is read in `_reads_closed`, before the close too.
    ("a state that cannot be read raises out of the delivery", TRACKER,
     "        except Exception as exc:  # noqa: BLE001 — an unread state is one still to close",
     "        except ZeroDivisionError as exc:"),

    # Re-pinned by #180's second half: the read is `_reads_closed`, asked before and after.
    ("an issue that is ALREADY closed is reported as one that could not be", TRACKER,
     '            return seen.returncode == 0 and (seen.stdout or "").strip().upper() == "CLOSED"\n',
     "            return False\n"),

    ("the issue is closed BEFORE the card moves, so a failed move leaves a closed card in its old "
     "column", TRACKER,
     "        repo, bare = self._locate(ref)\n        num = int(bare)\n        moved = True\n",
     "        repo, bare = self._locate(ref)\n        num = int(bare)\n        moved = True\n"
     "        if state is JobState.DONE:\n            self._close_as_delivered(ref)\n"),
]
