"""#146: the floor's schedule read is paid on a clock, not on every frame.

Six cuts, each one a way the memo could be present and useless — or present and harmful. The two
that go the OTHER way matter most here, because a cache is the kind of change whose failures are
invisible from inside the run that causes them: a window that never expires reads a paused poller
as running for ever, and a memo that stores an unread answer keeps a transient engine blip on
screen after the thing recovered.

The last cut is not about the memo at all. It grows the per-`intake` describe count, which is the
number this whole change is justified by — a caching change is exactly where a cost growing
underneath it would go unnoticed.
"""

TEST = "tests/test_the_floor_is_not_re_read_on_every_frame.py"
READING = "openfactory/floor/reading.py"
APP = "openfactory/api/app.py"
VIEW = "openfactory/runtime/temporal/view.py"

MUTATIONS = [
    # ── the memo is not there at all ────────────────────────────────────────────────────────────
    ("the memo is never consulted, so every frame describes every schedule again", READING,
     "    if _intake_memo and stamp - _intake_memo[0] < INTAKE_TTL_S:",
     "    if False:"),

    # ── …or it is there and never lets go ───────────────────────────────────────────────────────
    ("the window never expires, so a paused poller reads as running for ever", READING,
     "    if _intake_memo and stamp - _intake_memo[0] < INTAKE_TTL_S:",
     "    if _intake_memo and stamp - _intake_memo[0] < float('inf'):"),

    # ── …or it holds an answer nobody read ──────────────────────────────────────────────────────
    # RE-PINNED 2026-09-17 (#146, second pass): `intake_cached` wraps the RAW read now, so the
    # `got is not None` half of this condition went with the inversion — a read that broke raises
    # out of here and stores nothing, and `known: False` is the one unread shape left to refuse.
    ("an unread answer is cached, so a transient engine blip stays on screen for the window",
     READING,
     '    if got.get("known") is not False:\n'
     "        _intake_memo = (stamp, got)",
     "    _intake_memo = (stamp, got)"),

    # ── …or it answers somebody who did not pay for it ──────────────────────────────────────────
    # RE-PINNED 2026-09-17 (#146, second pass): `gather` now calls `_intake`, the catching wrapper,
    # and the memo is the public `intake_cached` underneath it. The cut is the same one — consult
    # the memo outside the `want` gate.
    ("the memo answers a caller that did not ask for intake", READING,
     '    if "intake" in want and got.connected:\n'
     "        got.intake = await _intake(client, now=got.now)",
     "    if got.connected:\n"
     "        got.intake = await _intake(client, now=got.now)"),

    # ── …or the two surfaces drift apart again, which is how #146 was written ───────────────────
    ("the route and the stream drift apart", APP,
     "_STREAM_SLOW_S = _INTAKE_TTL_S", "_STREAM_SLOW_S = 12.0"),

    # ── …or one of the three readers goes round it, which is what the first pass left ───────────
    # THE DEFECT THE REVIEW FOUND. `/api/floor` had the memo and the other two readers of
    # `tv.intake` did not, under a panel comment saying the schedule read was memoized
    # process-wide. Each cut puts one reader back on the raw read; §8 counts at `tv.intake`, so
    # either one takes the count from 1 to 2.
    ("a reader bypasses the memo — /api/temporal/jobs describes them all again", APP,
     '            "intake": await _floor_reading.intake_cached(client),',
     '            "intake": await tv.intake(client),'),

    ("a reader bypasses the memo — the stream keeps its own copy per connection", APP,
     '                    slow = {"intake": await _floor_reading.intake_cached(client),\n'
     '                            "build": _build_report()}',
     '                    slow = {"intake": await tv.intake(client),\n'
     '                            "build": _build_report()}'),

    # ── …or the inversion collapses and one caller inherits the other's failure semantics ───────
    # The public wrapper must RAISE: `/api/temporal/jobs` and the stream each have an `except` that
    # answers `connected: False`, and a helper that swallowed the failure would hand them
    # `"intake": None` on a `connected: True` frame instead. This cut restores the shape the memo
    # had on `507c715`, when it wrapped the catching `_intake`.
    ("the public wrapper swallows the failure instead of raising", READING,
     "    got = await tv.intake(client)\n",
     "    try:\n"
     "        got = await tv.intake(client)\n"
     "    except Exception:\n"
     "        return None\n"),

    # ── …or the floor stops catching, and a read that broke takes the surface down ───────────────
    ("the floor's own wrapper stops catching, so an unreadable schedule takes the floor down",
     READING,
     "    try:\n"
     "        return await intake_cached(client, now=now)\n"
     "    except Exception as exc:  # noqa: BLE001 — `intake` already answers `known: False` "
     "itself, so\n"
     "        # reaching here means something below it broke; unread is the honest report either "
     "way.\n"
     '        log.warning("floor: could not read the poller schedule (%s)", str(exc)[:160])\n'
     "        return None",
     "    return await intake_cached(client, now=now)"),

    # ── …or the read the memo throttles quietly gets more expensive ─────────────────────────────
    ("the describe count grows", VIEW,
     '            ids.append(f"{WATCH_SCHEDULE_PREFIX}-{p.name}")',
     '            ids.append(f"{WATCH_SCHEDULE_PREFIX}-{p.name}")\n'
     '            ids.append(f"{WATCH_SCHEDULE_PREFIX}-{p.name}-b")'),
]
