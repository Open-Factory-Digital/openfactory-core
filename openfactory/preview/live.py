"""A preview that starts itself, and says where it is once it is up (ADR-0050 D6 as amended on
2026-09-29; #404, #405).

THE CLICK WAS A WAIT, NOT A BOUND. D6 made a preview start on demand because a whole product per
pull request is not free. What bounds that cost is the cap on previews at once, the per-unit budget
and the expiry — all enforced by the steps whoever starts them. The click bounded nothing; it made
the person the preview is for find a button after they heard the change was ready, press it, and
come back minutes later. Measured live on 2026-09-29: the click was pressed, the start failed, and
the card showed nothing at all (#403, #404). So on a project that declared `preview:`, on a
deployment that names a runtime, the job's own activity starts the preview when the pull request
is handed to a person (`should_start`), and the operator can turn that off per project
(`preview.auto_start: false`, the registry's).

NOBODY WAS TOLD WHEN ONE WAS UP. The card's thread says "PR ready for review: <url>" and then
nothing; the product role had a sentence for it (`product/events.py::preview_up`) and no producer.
`comment` is what the card is told, and `link_for` is what anything that speaks to a person — the
product role's "your card's PR is ready" message (#401) among them — asks for the link.

THE LINK CARRIES NO CREDENTIAL. A preview's own URL carries a key minted for minutes (D7); written
into a tracker comment it would be readable by everybody who can read the board and dead by the
time most of them clicked. The link is the panel's route `/p/<project>/preview/<card>`, which
opens the card and, the preview being up, walks into it with a key minted at that moment — for
whoever the panel lets in.
"""

from __future__ import annotations

import logging
import time
from urllib.parse import quote

from openfactory import preview

log = logging.getLogger("openfactory.preview.live")

#: `started_by` of a preview the factory started itself. A name where a person's would be, so the
#: `stopped by …` and `started by …` the steps already write stay true; the card says it in the
#: project's language (`techlead/voice.py`, `preview.on-its-own`).
AUTO_STARTER = "openfactory"

#: The panel's route that opens a card's preview (`api/app.py::project_page`).
ROUTE = "/p/{project}/preview/{card}"


def route(project: str, card: str, *, base: str | None = None) -> str:
    """The panel's link that opens `card`'s preview — absolute when the deployment says where its
    panel is, else the route alone, which is what every link the local board writes already is
    (`adapters/tracker/local.py::panel_url`)."""
    if base is None:
        from openfactory.listeners import PANEL

        base = PANEL.declared()
    path = ROUTE.format(project=quote(str(project), safe=""), card=quote(str(card), safe=""))
    return f"{(base or '').rstrip('/')}{path}"


def is_up(found: preview.Preview | None, *, now: float | None = None) -> bool:
    return found is not None and found.live and not found.expired(now)


def link_for(project, card: str, *, latest=None, now: float | None = None) -> str:
    """THE HOOK (#405): the link that opens `card`'s preview while it is up, `""` while it is not.

    For whatever tells a person their card's change is ready — the product role's message (#401)
    passes it as `preview_url` — so the sentence can say "try it here" instead of "open the card
    and start one". Never raises: a message is never lost over a preview store that cannot be
    read.

    THE PROJECT OR ITS NAME. Both callers — the merge watch's `tell_the_requester` and the round's
    `_pull_requests_waiting` — hand it the registry's project, and it compared that object to the
    record's project NAME: never equal, so every "ready for you" said "start the preview from the
    card" while one was up (measured building #413, 2026-10-02)."""
    project = str(getattr(project, "name", project) or "")
    number = preview.card_of(card)
    if not number:
        return ""
    try:
        token = preview.unit_of_card(project, number)
        found = (latest or preview.latest)(project, token)
    except Exception as exc:  # noqa: BLE001 — no link is said as no link, never as a crash
        log.info("could not read the preview of %s %s (%s)", project, number, str(exc)[:160])
        return ""
    if found is None or found.project != project or not is_up(found, now=now):
        return ""
    return route(project, number)


def until_said(expires_at: int) -> str:
    """When a preview ends, as a person reads it in a comment that outlives the page: UTC,
    to the minute, because a card is read in more than one timezone."""
    if not expires_at:
        return "?"
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(int(expires_at)))


def _say(key: str, language: str | None, **params: object) -> str:
    from openfactory.techlead import voice

    return voice.say(voice.PREVIEW, key, language, **params)


def headline(found: preview.Preview | None, *, can_start: bool, language: str | None,
             now: float | None = None) -> str:
    """The card's first line about its preview, in the project's language (#404) — what state it
    is in, never why: the reason is the step's own sentence, drawn under it."""
    if found is not None and found.state == preview.STARTING:
        return _say("preview.starting", language)
    if is_up(found, now=now):
        return _say("preview.live", language, until=until_said(found.expires_at))
    if found is not None and found.state == preview.FAILED:
        return _say("preview.failed", language)
    if found is not None and (found.state == preview.ENDED or found.live):
        return _say("preview.ended", language)
    if can_start:
        return _say("preview.can-start", language)
    return ""


def started_by_said(found: preview.Preview | None, language: str | None) -> str:
    """Who started it, as the card says it — `""` when nobody is recorded, and the factory's own
    start in the project's words rather than as a name nobody pressed anything under."""
    who = str(getattr(found, "started_by", "") or "")
    if not who:
        return ""
    if who == AUTO_STARTER:
        return _say("preview.on-its-own", language)
    return _say("preview.started-by", language, who=who)


def comment(found: preview.Preview, *, link: str, language: str | None) -> str:
    """What the card is told when its preview comes up (#405)."""
    return _say("preview.comment.live", language, link=link,
                until=until_said(found.expires_at))


def held(why: str, language: str | None) -> str:
    """What the card says when the deployment's limits held an automatic start back."""
    return _say("preview.held", language, why=why)


def should_start(project, found: preview.Preview | None, *, kind: str, running=(),
                 cap: int | None = None) -> tuple[bool, str]:
    """`(start, why not)` — whether the factory starts this unit's preview itself, now that the
    job handed its pull request to a person. `why` is said on the card when the answer is a LIMIT
    (the cap); every other "no" is silent, because it is the project's own choice or a record the
    job did not write.

    ONLY WHAT THE OFFER JUDGED STARTABLE: a record the job wrote at this gate (`offered`), for a
    project that DECLARES a shape (no `shape` — the proposal case starts nothing until a person
    merges one, D3/D12), on a deployment that names a runtime (the offer's `why` is empty and the
    kind is not `none`). A unit that is already starting or up is never started again — the
    offer relabels nothing live, and a sibling that joins a live unit makes it stale, not rebuilt.
    THE OPERATOR MAY SAY NO per project (`preview.auto_start: false`), and then the card offers
    the button exactly as before.

    THE CAP IS ASKED BEFORE STARTING, not left to the plan step's refusal: that one records the
    preview `failed`, and a preview nobody asked for must not greet the person as a failure.
    Everything else the steps enforce whoever starts them — the budget, the expiry, the egress
    network, the env tiers.

    AND IT IS ASKED LAST, BECAUSE IT IS THE ONE QUESTION THAT COSTS (review of #408). `running` is
    the previews up on the deployment, or A CALLABLE THAT READS THEM — which is what the job's
    activity hands over, because reading them is a `docker ps -a` on the daemon. Handed over as a
    value it was read before any of the refusals above was decided: a project whose operator had
    said `preview.auto_start: false` paid one docker call on every job that opened a pull
    request, and so did a record nobody could start. The callable is called once, here, only when
    everything cheaper said yes."""
    from openfactory.contracts.project import PreviewPolicy
    from openfactory.preview import demand

    policy = getattr(project, "preview", None) or PreviewPolicy()
    if not getattr(policy, "auto_start", True):
        return False, ""
    if not kind or kind == "none":
        return False, ""
    if found is None or found.state != preview.OFFERED or found.shape or found.why \
            or not found.pr_urls:
        return False, ""
    mine = preview.compose_project(project.name, found.unit)
    up = running() if callable(running) else running
    why = demand.over_cap(up or (), mine=mine,
                          cap=cap if cap is not None else demand.max_previews())
    if why:
        return False, why
    return True, ""
