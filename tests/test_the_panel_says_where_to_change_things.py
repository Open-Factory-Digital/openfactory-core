"""A read-only surface must still say where each decision LIVES (pilot, 2026-08-14).

The project bar showed six facts — harness, auth, models, review, token pool, region — and no
way to reach any of them. The operator had chosen none of them, could not tell whether the
factory was spending his Claude subscription or an API key, and could not find where TDD or the
coding agents' prompts are configured. His verdict on an onboarding that had otherwise just gone
green: *"very black box… it may well be, but it has to offer the option to know and to
change things if you want."*

No editing UI was invented. Each line names the command or the FILE that owns the decision,
because that is where it is changed, reviewed and versioned.

  1. every fact on the bar has a stated way to change it, by its real name;
  2. the credential KIND is shown beside the route — two very different bills;
  3. "I cannot see which credential" is said, never guessed;
  4. the role prompts are named WITH the rebuild trap, since editing them changes nothing until
     the image is rebuilt.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = (ROOT / "openfactory" / "api" / "panel.html").read_text()


def test_every_fact_on_the_bar_names_the_way_to_change_it():
    for owed in (
        "openfactory project set-model",        # models
        "--role executor|reviewer|techlead|product",
        "org_defaults/roles",                   # the agents themselves
        "merge_policy:",                        # what review actually gates on
        ".env.compose",                         # harness auth, token pool, region
    ):
        assert owed in PANEL, f"the panel shows a decision it never says how to change: {owed}"


def test_the_how_to_covers_the_capabilities_the_LOCAL_deployment_hides():
    """The half-fix, caught by the pilot the same day (2026-08-15).

    Dropping the AWS console buttons from a free deployment left the operator with no logs,
    no parameters and no tasks — *"I don't want to lose any of it, I just want to see it in
    a free option — logs, for example: I do want to see the logs"*. A capability with no button
    is exactly the one
    the panel must explain, because there is nothing on screen to click and guess from.

    Driven by what the API can render — a new cloud button cannot be added without teaching its
    free counterpart here.
    """
    import inspect

    from openfactory.api import app

    keys = set(re.findall(r'links\["(\w+)"\]', inspect.getsource(app._links)))
    keys |= set(re.findall(r'"(\w+)":', inspect.getsource(app._links)))
    taught = {  # the paragraph in the how-to that owes each button an answer
        "board": "board &amp; tracker",
        "temporal": "Temporal",
        "cloudwatch": "logs — where the work's output is",
        "ssm": "parameters &amp; secrets",
        "ecs": "where the work actually runs",
    }
    assert keys <= set(taught), f"the panel can render a button it never explains: {keys - set(taught)}"
    for key, heading in taught.items():
        assert heading in PANEL, f"nothing in the how-to tells an operator about {key}"


def test_the_free_answer_comes_FIRST_for_every_capability():
    """A free deployment reading its own panel must not have to shop for an account. Where a
    capability exists both ways, the local answer is stated before the cloud one."""
    block = PANEL[PANEL.index('<summary>how to change any of this'):]
    block = block[:block.index("</details>")]
    for free, vendor in (
        ("docker compose --env-file .env.compose logs", "OPENFACTORY_SANDBOX=fargate"),
        (".env.compose</code> (keep it <code>chmod 600", "AWS SSM"),
        ("OPENFACTORY_SANDBOX=container", "run them in AWS"),
    ):
        assert free in block, f"the free way to reach this is not on the panel: {free}"
        assert block.index(free) < block.index(vendor), (
            f"the panel offers {vendor} before the free option an open-source install already has")


def test_the_rebuild_trap_is_named_beside_the_prompts():
    """Editing a role prompt changes nothing until the worker image is rebuilt — the trap §11
    documents and the panel is now the first place somebody reads about the files."""
    where = PANEL[PANEL.index("org_defaults/roles"):][:900]
    assert "baked into the worker image" in where
    assert "up -d --build" in where


def test_the_reviewer_is_named_as_the_one_prompt_a_deployment_may_not_soften():
    where = PANEL[PANEL.index("org_defaults/roles"):][:900]
    assert "REVIEWER has no file" in where, (
        "the panel points at the prompts folder without saying why one voice is missing from it")


def test_the_credential_KIND_is_reported_and_never_guessed(monkeypatch):
    from openfactory.api.app import _auth_credential

    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert _auth_credential() == "", "a guess about somebody's billing is worse than a blank"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    assert _auth_credential() == "api key"

    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-x")
    assert _auth_credential() == "subscription", (
        "the subscription is what pays when both are present — the harness prefers it")


def test_the_bar_renders_the_credential_beside_the_route():
    assert "f.auth_credential" in PANEL, (
        "the API reports which credential pays and the bar still shows only the route")


def test_what_the_panel_REPORTS_is_what_the_harness_will_USE(monkeypatch):
    """The panel's answer and the adapter's choice are two readings of one fact, and a surface
    that disagrees with the code is worse than one that says nothing: it tells an operator his
    subscription is paying while the API key is billed. Pinned against the adapter's own
    resolution order rather than against a comment about it."""
    import inspect

    from openfactory.adapters.agent import claude_code
    from openfactory.api.app import _auth_credential

    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")

    src = inspect.getsource(claude_code)
    oauth_at = src.index('os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")')
    apikey_at = src.index('os.environ.get("ANTHROPIC_API_KEY")')

    assert oauth_at < apikey_at, (
        "the adapter no longer prefers the subscription — the panel's answer is now wrong")
    assert _auth_credential() == "subscription"
