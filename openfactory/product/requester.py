"""Who asked, in the namespace the tracker can name (ADR-0048 §5).

A card the factory opens is asked for by a CHAT identity — a Slack user id, a panel principal,
`cli` — and no tracker can mention or match one: a comment on GitHub is signed by a login, on Azure
DevOps by a `uniqueName`, on Jira by a display name. The deployment already declares the bridge for
the opposite direction (`Project.people`: forge login → channel id, written so a question in the
channel can reach the person behind a pull request). Read backwards, it is the only honest answer to
"who is this person on the tracker" — WHAT SOMEBODY DECLARES BEATS WHAT THE MACHINE INFERS, and a
requester the map does not list resolves to nobody rather than to a guess. The factory then does
not ask (§5) instead of addressing a question to a name the tracker will not deliver.
"""

from __future__ import annotations

import logging

log = logging.getLogger("openfactory.product.requester")


def forge_identity_for(project, chat_id: str, tracker=None) -> str:
    """The tracker-namespace identity for `chat_id`: what the deployment DECLARED, else what the
    row can say for itself, else "".

    `Project.people` maps forge login → channel id; this walks it the other way. Exact match on
    the channel id after trimming — a mention token (`<@U04ABC>`) is stripped to its id first, since
    that is how a Slack requester arrives on the card. Two logins declared for one id is a
    configuration mistake and resolves to nobody: guessing between them would write one person's
    name on a question meant for another.

    THE ROW IS ASKED SECOND, AND ONLY WHEN THE MAP HELD NOBODY (ADR-0049 D7). The order is the
    module's own rule — what somebody declares beats what a machine infers — and the row is not
    consulted after an AMBIGUOUS declaration either: two logins for one id is a mistake somebody
    has to fix, and a row answering over it would hide the mistake behind a plausible name.

    A row answers non-empty only where its namespace IS the platform's, which is true of a board
    the platform itself holds and false of every hosted vendor (`TrackerAdapter.identity_of`), so
    on a GitHub, Jira or Azure deployment this returns exactly what it returned before the
    parameter existed — including for a caller that passes no tracker at all."""
    who = (chat_id or "").strip().strip("<@>").strip()
    if not who:
        return ""
    people = getattr(project, "people", None) or {}
    hits = [login.strip() for login, cid in people.items()
            if str(cid or "").strip().strip("<@>") == who and login.strip()]
    if hits:
        return hits[0] if len(hits) == 1 else ""
    fn = getattr(tracker, "identity_of", None)
    if not fn:
        return ""
    try:
        return (fn(who) or "").strip()
    except Exception:  # noqa: BLE001 — a row that cannot say leaves the factory not asking
        log.info("the tracker could not spell %r in its own namespace — the factory will not ask",
                 who, exc_info=True)
        return ""
