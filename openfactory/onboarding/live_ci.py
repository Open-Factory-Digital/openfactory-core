"""A command read from a RETIRED pipeline is not this client's gate (#117).

Found live on the pilot (2026-08-14). The proposed manifest carried

    uv run bandit -c pyproject.toml -r src

read verbatim from `.github/workflows/ci.yml` — a workflow whose forge state is
`disabled_manually`. The box proof then failed on a gate the client had deliberately switched off
months earlier, under a report that said, with full confidence, *"observed from ci.yml"*.

ON DISK A RETIRED WORKFLOW IS BYTE-IDENTICAL TO A LIVING ONE. That is not a bug in `infer`: it is
offline and vendor-neutral on purpose — it reads files, and no file says whether the forge is
ignoring it. The state lives at the provider, and `onboard` has a provider.

THE NEXT DEPLOYMENT MAKES IT WORSE. An enterprise arrives with years of retired Azure Pipelines
sitting in the same directory as the living ones, under the same extension, written by people who
have left. Reading all of them equally is how a first-day onboarding proposes a gate nobody has
run since 2023 and then fails its own proof on it.

WHAT THIS MODULE DOES, AND THE ORDER MATTERS:

    1. a proposal whose evidence is ALL from disabled files, when a live alternative exists, is
       re-pointed at the living one and says so;
    2. one with no live alternative is DEMOTED to a question naming the state — never dropped
       silently, because a client who deliberately disabled a workflow may deliberately want it
       back, and that is their call and not ours;
    3. a forge that cannot answer changes nothing at all.

THAT THIRD RULE IS THE LOAD-BEARING ONE. `disabled_ci_paths` returning None means "I could not
find out", and treating it as "nothing is disabled" would be this codebase's most expensive
recurring shape — an absence read as an answer — applied to the one decision that removes a
client's real gate from their manifest.
"""

from __future__ import annotations

import logging

from openfactory.onboarding.infer import UNKNOWN, Candidate, ManifestProposal, Proposal

log = logging.getLogger("openfactory.onboarding.live_ci")


def _norm(path: str) -> str:
    """One spelling for a repo-relative path, so the forge's answer and the evidence's citation
    can be compared as strings.

    `lstrip("./")` IS NOT THIS, and it was the first thing written here. `lstrip` takes a SET of
    characters, so `.github/workflows/ci.yml` came back as `github/workflows/ci.yml` — a file the
    client does not have, printed to them in a question about their own repository. The matching
    still worked, because both sides were corrupted identically, which is exactly why it would
    have survived every test that did not read the sentence."""
    out = str(path or "").strip().replace("\\", "/")
    while out.startswith("./"):
        out = out[2:]
    return out.lstrip("/")


def _evidence_paths(items) -> set[str]:
    return {_norm(getattr(e, "path", "")) for e in (items or [])
            if str(getattr(e, "path", "") or "")}


def _is_dead(candidate_or_proposal, dead: set[str]) -> bool:
    """Does every piece of evidence for this claim live in a file the forge is ignoring?

    ALL, NOT ANY. A command corroborated by a live `Makefile` and a dead `ci.yml` is still a
    command this repository runs; demoting it because one of its two witnesses retired would take
    a working gate away from the client, which is the more expensive error of the two."""
    paths = _evidence_paths(getattr(candidate_or_proposal, "evidence", None))
    return bool(paths) and paths <= dead


def _live_alternative(proposal: Proposal, dead: set[str]) -> Candidate | None:
    """The best candidate whose evidence is NOT entirely from disabled files.

    Candidates are already best-first, so the first survivor is the one the same ranking would
    have chosen had the retired file never been read."""
    for candidate in proposal.candidates or []:
        if candidate.value is None:
            continue
        if not _is_dead(candidate, dead):
            return candidate
    return None


def _question(field: str, where: set[str], *, taken: str = "") -> str:
    """What the client is asked. It names the FILE and the STATE, because "we ignored this" is not
    an answer somebody can act on — and it never tells them what to decide."""
    files = ", ".join(sorted(where))
    if taken:
        return (f"`{field}`: the strongest reading came from {files}, which the forge reports as "
                f"DISABLED — so `{taken}` was taken from a pipeline that still runs. If the "
                f"disabled one is the gate you want, re-enable it and re-run the onboarding.")
    return (f"`{field}`: the only command found for this came from {files}, which the forge "
            f"reports as DISABLED — a retired pipeline is not a gate, so nothing is proposed "
            f"here. Re-enable it if it should run, or tell us what does.")


def demote_disabled(proposal: ManifestProposal, disabled: list[str] | None) -> ManifestProposal:
    """Re-point or demote every field whose evidence lives only in switched-off CI. Mutates and
    returns `proposal`.

    `disabled is None` — the forge could not say — returns it UNTOUCHED. Not "assume nothing is
    disabled": the two answers are different and only one of them is knowledge.
    """
    if disabled is None:
        log.info("the forge could not say which pipelines are disabled — every command is being "
                 "taken at face value, which is what happened before this check existed")
        return proposal
    dead = {_norm(p) for p in disabled if str(p or "").strip()}
    if not dead:
        return proposal

    for name, field in proposal.fields.items():
        if not field.known or not _is_dead(field, dead):
            continue
        where = _evidence_paths(field.evidence) & dead
        alternative = _live_alternative(field, dead)
        if alternative is not None:
            field.value = alternative.value
            field.confidence = alternative.confidence
            field.evidence = list(alternative.evidence)
            field.candidates = [alternative] + [c for c in field.candidates if c is not alternative]
            question = _question(name, where, taken=str(alternative.value))
            log.info("OPENFACTORY_DISABLED_CI field=%s dropped=%s taken=%r",
                     name, sorted(where), alternative.value)
        else:
            field.value = None
            field.confidence = UNKNOWN
            field.candidates = []
            question = _question(name, where)
            log.info("OPENFACTORY_DISABLED_CI field=%s dropped=%s taken=none", name, sorted(where))
        # THE NOTE IS THE QUESTION for an unknown field — `onboard` reads `unknown.note` into the
        # pull request's question list, so writing it anywhere else would lose it. It is added to
        # `questions` too for the re-pointed case, which stays `known` and is therefore never
        # walked by `unknowns()`.
        field.note = question
        if question not in proposal.questions:
            proposal.questions.append(question)
    return proposal


def ask_the_forge(forge, repo: str) -> list[str] | None:
    """`disabled_ci_paths` if this forge implements it, else None. Never raises.

    A PROVIDER THAT DOES NOT IMPLEMENT IT IS NOT A FAILURE. The port declares the method and two
    adapters answer it; a third — or a test double, or a future one — simply cannot say, which is
    the honest `None` the caller already handles. Raising here would make a capability that exists
    to improve a proposal able to stop the onboarding that carries it."""
    ask = getattr(forge, "disabled_ci_paths", None)
    if not callable(ask):
        return None
    try:
        got = ask(repo)
    except Exception as exc:  # noqa: BLE001 — an unanswerable question is not a failed onboarding
        log.warning("could not ask %s which pipelines are disabled (%s) — proceeding without it",
                    type(forge).__name__, str(exc)[:160])
        return None
    if got is None:
        return None
    return [str(p) for p in got if str(p or "").strip()]
