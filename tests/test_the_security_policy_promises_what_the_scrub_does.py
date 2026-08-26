"""`SECURITY.md`'s first technical claim must be true of `_scrubbed_env` — measured, not read.

THE SENTENCE WAS FALSE, in the first document a security researcher opens (found in the
pre-launch audit, 2026-08-26). It promised the workspace scrub covered *"both current and legacy
spellings of every name"*. Measured: a name under the platform's retired prefix survives the
scrub untouched, because the deny lists spell one name per secret — deliberately, and a guard in
`test_the_environment_carries_the_products_name.py` REFUSES a second spelling on those lists
("a list that named a second spelling would be the side door coming back"). So the code was
right and the promise was wrong, which is the worse direction: a reader who believed it would
not look for the hole the document told them was closed.

What the code can actually promise is narrower and holds: the listed names are removed, and no
second spelling exists to carry the same secret because the retired prefix is served by nothing
and reserved against every add-on. This file pins the three halves of that:

  1. the promise, on the real deny lists — every name they hold is gone from the workspace env;
  2. the boundary, measured — the retired twin of each of those names SURVIVES, which is the
     fact that made the old sentence false;
  3. the document, held to the code's OWN words for why (2) is safe — `environ.reserved`'s
     reason, quoted rather than paraphrased, so that a day when the prefix IS served turns this
     guard red instead of leaving a promise nobody re-measured.
"""

from __future__ import annotations

import pathlib
import re

from openfactory import environ
from openfactory.adapters.sandbox.worktree import (
    _AGENT_CRED_VARS,
    _AWS_CRED_VARS,
    _FORGE_CRED_VARS,
    _scrubbed_env,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICY = ROOT / "SECURITY.md"

#: Every name the scrub's deny lists hold, in one place — the three families the bullet names.
DENIED = (*_AWS_CRED_VARS, *_FORGE_CRED_VARS, *_AGENT_CRED_VARS)


def _credential_reach_bullet() -> str:
    """The bullet `SECURITY.md` opens its threat model with, from its marker to the next one.

    Whitespace-normalised, because a sentence in a wrapped document is broken by newlines
    wherever the column ran out, and a guard that could be satisfied by re-wrapping a paragraph
    would be measuring the line width."""
    text = POLICY.read_text()
    start = text.index("- **Credential reach.**")
    nxt = text.find("\n- **", start + 1)
    return re.sub(r"\s+", " ", text[start:] if nxt < 0 else text[start:nxt])


def _retired_twin(name: str) -> str | None:
    """`OPENFACTORY_FORGE_TOKEN` → `SDLC_FORGE_TOKEN`, from the code's own two prefixes; None for
    a name that is not ours to re-spell (`GH_TOKEN`, `AWS_*` — those belong to other tools)."""
    if not name.startswith(environ.ENV_PREFIX):
        return None
    return environ.RETIRED_ENV_PREFIX + name[len(environ.ENV_PREFIX):]


# ── 1. the promise, on the real lists ───────────────────────────────────────────────────────────

def test_every_name_the_deny_lists_hold_is_gone_from_the_workspace_environment(monkeypatch):
    """The bullet's actual guarantee, measured on the shipped lists rather than a sample."""
    assert len(DENIED) >= 12, f"the deny lists have shrunk to {len(DENIED)} — this measures little"
    for name in DENIED:
        monkeypatch.setenv(name, f"secret-for-{name}")
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "worktree")  # not a secret; must survive

    env = _scrubbed_env()

    assert [n for n in DENIED if n in env] == [], "the scrub left a name its own lists hold"
    assert env.get("OPENFACTORY_SANDBOX") == "worktree", "the scrub took more than the secrets"


# ── 2. the boundary, measured ───────────────────────────────────────────────────────────────────

def test_a_retired_spelling_survives_the_scrub_which_is_why_the_document_may_not_promise_it(
        monkeypatch):
    """The negative half, and the measurement the old sentence contradicted.

    This is not a wish: the twins are BUILT from the code's two prefixes, so the day a name is
    added to a deny list its twin is measured here too."""
    twins = {t: name for name in DENIED if (t := _retired_twin(name))}
    assert len(twins) >= 5, f"only {len(twins)} of our own names on the lists — no subject here"
    for twin in twins:
        monkeypatch.setenv(twin, "same-secret-other-spelling")

    env = _scrubbed_env()

    assert sorted(t for t in twins if t in env) == sorted(twins), (
        "a retired-prefix name is being scrubbed — the deny lists have grown a second spelling, "
        "which is the side door `test_the_environment_carries_the_products_name.py` refuses; if "
        "that changed on purpose, SECURITY.md's credential-reach bullet has to change with it")


# ── 3. the document sends a reader to the function it describes ────────────────────────────────

def test_the_policy_points_at_the_function_it_describes():
    """WHAT THIS NO LONGER ASSERTS, and why. Until 2026-08-26 this section held SECURITY.md to
    the platform's own sentence that ONE SPELLING IS ENOUGH. That premise was measured and found
    false: `OPENFACTORY_TRACKER_TOKEN` was a served third spelling of the forge push credential
    while the two beside it were denied. The document now states the guarantee in the one
    direction it holds and PUBLISHES the credentials a worktree workload can read, and those
    claims are held to the code — name for name, count and all — by
    `tests/test_the_environment_carries_the_products_name.py`
    (`test_SECURITY_names_every_credential_a_worktree_workload_can_read`,
    `test_SECURITY_names_the_container_boxs_allow_list`, and the rule that any credential named
    anywhere else in the document must be one the scrub removes). Those are derived; the sentence
    check that stood here was a phrase.

    What survives is the half that is still a property and not a wording: a reader of the
    security policy is sent to the code that implements it."""
    bullet = _credential_reach_bullet()
    assert "`_scrubbed_env`" in bullet, (
        "the credential-reach bullet no longer names the function it describes — a security "
        "reader is left to find it")
