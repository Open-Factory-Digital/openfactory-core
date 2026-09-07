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


def forge_identity_for(project, chat_id: str) -> str:
    """The forge login the deployment declared for `chat_id`, or "" when it declared none.

    `Project.people` maps forge login → channel id; this walks it the other way. Exact match on
    the channel id after trimming — a mention token (`<@U04ABC>`) is stripped to its id first, since
    that is how a Slack requester arrives on the card. Two logins declared for one id is a
    configuration mistake and resolves to nobody: guessing between them would write one person's
    name on a question meant for another."""
    who = (chat_id or "").strip().strip("<@>").strip()
    if not who:
        return ""
    people = getattr(project, "people", None) or {}
    hits = [login.strip() for login, cid in people.items()
            if str(cid or "").strip().strip("<@>") == who and login.strip()]
    return hits[0] if len(hits) == 1 else ""
