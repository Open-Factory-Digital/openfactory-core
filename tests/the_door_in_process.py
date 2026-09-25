"""The durable engine behind the door, stood in for IN PROCESS — for a test about a ROW, not a queue.

WHY THIS EXISTS (#266 slice 3). The panel's row (`product_say`) sends its message through the door
(`product/door.py`) and reads the answer back from the conversation: a signal-with-start, then a
query. The tests that drive the row are about what reaches the engine and what comes back — the
transport a message carries into every gate, the token of what the turn staged, the triage a typed
sentence runs — and they pass a module double the real engine's worker could never see. So this
client answers the door's two calls itself: `start_workflow` runs the message through the worker's
OWN turn function (`activities._conversation_turn`, or `_conversation_fast` for what the door read
as read-only) in this process, and `query` hands back what that turn replied, as the conversation's
`where` would.

WHAT IT IS NOT: a conversation. There is no queue, no debounce, no bound here — one message, one
turn, answered at once. The queue is driven on an engine of its own in `tests/test_the_one_door.py`.
"""

from __future__ import annotations

import asyncio


class DoorInProcess:
    """A durable-engine client the door can talk to, answering each message in process.

    `arrivals` is every message the door enqueued, as it enqueued it (the `Arrival`), in order —
    what a test reads to see what crossed the door. `executed` is every workflow a row ran the
    old way (`execute_workflow`), for the rows that still do, with `answers` giving what each
    workflow type returns."""

    def __init__(self, project, *, answers: dict | None = None) -> None:
        self.project = project
        self.arrivals: list = []
        self.started: list[str] = []
        self.executed: list[tuple[str, object]] = []
        self.answers = dict(answers or {})
        self._replies: dict[str, list[dict]] = {}

    async def start_workflow(self, workflow, arg, *, id, task_queue, start_signal=None,
                             start_signal_args=(), **_kw):
        from openfactory.runtime.temporal.activities import _conversation_fast, _conversation_turn
        from openfactory.runtime.temporal.io import TurnInput

        self.started.append(workflow)
        arrival = start_signal_args[0]
        self.arrivals.append(arrival)
        if arrival.replies:
            self._replies[arrival.in_reply_to or arrival.id] = list(arrival.replies)
            return None
        work = TurnInput(product=arg.product, project=arrival.project,
                         conversation=arg.conversation, room=arrival.room,
                         speaker=arrival.speaker, text=arrival.text, id=arrival.id,
                         ids=[arrival.id], in_reply_to=arrival.in_reply_to,
                         source=arrival.source, fingerprint=arrival.fingerprint,
                         via=arrival.via, language=arrival.language)
        run = _conversation_fast if arrival.fast else _conversation_turn
        replies = await asyncio.to_thread(run, self.project, work)
        self._replies[arrival.id] = [r.model_dump(mode="json") for r in replies
                                     if r.kind != "receipt"]
        return None

    def get_workflow_handle(self, workflow_id):
        door = self

        class _Handle:
            async def query(self, name, message_id, **_kw):
                assert name == "where", name
                replies = door._replies.get(message_id)
                return {"state": "answered" if replies is not None else "unknown", "ahead": 0,
                        "coalesced": False, "duplicate": False, "replies": list(replies or [])}

        return _Handle()

    async def execute_workflow(self, name, inp, **_kw):
        self.executed.append((name, inp))
        return self.answers.get(name, {"ok": True})
