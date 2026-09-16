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
    ("an unread answer is cached, so a transient engine blip stays on screen for the window",
     READING,
     '    if got is not None and got.get("known") is not False:\n'
     "        _intake_memo = (stamp, got)",
     "    _intake_memo = (stamp, got)"),

    # ── …or it answers somebody who did not pay for it ──────────────────────────────────────────
    ("the memo answers a caller that did not ask for intake", READING,
     '    if "intake" in want and got.connected:\n'
     "        got.intake = await _intake_cached(client, now=got.now)",
     "    if got.connected:\n"
     "        got.intake = await _intake_cached(client, now=got.now)"),

    # ── …or the two surfaces drift apart again, which is how #146 was written ───────────────────
    ("the route and the stream drift apart", APP,
     "_STREAM_SLOW_S = _INTAKE_TTL_S", "_STREAM_SLOW_S = 12.0"),

    # ── …or the read the memo throttles quietly gets more expensive ─────────────────────────────
    ("the describe count grows", VIEW,
     '            ids.append(f"{WATCH_SCHEDULE_PREFIX}-{p.name}")',
     '            ids.append(f"{WATCH_SCHEDULE_PREFIX}-{p.name}")\n'
     '            ids.append(f"{WATCH_SCHEDULE_PREFIX}-{p.name}-b")'),
]
