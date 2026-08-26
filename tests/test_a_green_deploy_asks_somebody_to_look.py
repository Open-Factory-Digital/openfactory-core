"""A deploy that went green is an invitation, not a receipt (#122, pilot 2026-08-16).

The operator asked, the evening before his first merge:

    "when the merge is done a deploy to staging happens — I have not seen anywhere that picks up
     the staging domain so the tech-lead (or the PO) can ask for validation."

He was right twice over. The outcome was reported as a **CI run URL**, which tells a reviewer
whether the pipeline was green and nothing about whether the product is right; and the one place in
the whole product that names a human-visitable address — `ProductConfig.staging_url` — sat on the
deployment's registry with no writer, no document, and a single reader behind the PRODUCTION gate,
so a shop whose flow ends at staging was never asked to validate anything at all.

TWO DECISIONS SHAPE THIS FILE, both the operator's, both on the card:

  * **the address belongs to the environment**, declared by the client in their own manifest, and
    it must be on `post_merge_deploy` as well as on `Environment` — observing an `Environment`
    requires the provider to have RECORDED a deployment, and a repository that simply deploys from
    a workflow records none (measured on his: 0 deployments, 0 environments, a working staging
    site). Putting the address only where the chain lives offers it to the shops that need it least.
  * **both surfaces are told** — *"os 2 podem comunicar isso… se a empresa não estiver usando [o
    PO], continua sendo relevante independente do canal"* — so the operator's half must not depend
    on the product module being switched on, which is the failure this card was opened for.

And the silence rule, which is what stops this becoming its own defect: with no address declared,
nobody is invited anywhere. The previous shape of this idea told a client the change was "in the
test environment, go and have a look" with no address, which costs the reader a reply to find out
where — worse than saying nothing.
"""

from __future__ import annotations

import pytest

from openfactory.contracts.manifest import Environment, PostMergeDeploy
from openfactory.runtime.temporal import activities
from openfactory.runtime.temporal.io import DeployNotifyInput

# ── 1. the address has a home, and it is not the health probe ───────────────────────────────────

def test_both_levers_can_carry_an_address():
    assert "url" in PostMergeDeploy.model_fields, (
        "the lever most repositories can actually use cannot say where a person looks")
    assert "url" in Environment.model_fields


def test_the_human_address_is_not_the_health_probe():
    """A health endpoint is a probe target — a 200 and a JSON body. Sending somebody there to
    confirm a feature is sending them to the wrong page, and the pilot's own deploy has both:
    it smoke-tests `/api/v1/health` and the thing to open is the site."""
    env = Environment(health_url="https://stg.example.com/api/v1/health",
                      url="https://stg.example.com")
    assert env.url != env.health_url
    assert Environment().url is None, "a project that declares no address must not get a guess"


def test_a_watch_with_no_address_is_still_valid():
    """The address is an addition, never a new requirement — an existing manifest keeps working."""
    assert PostMergeDeploy(workflow="deploy.yml").url == ""


# ── 2. the message ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def sent(monkeypatch):
    """Capture what each surface was told, without a registry, a channel or a notifier."""
    out: dict = {"operator": [], "client": []}

    class _Notifier:
        def notify(self, *, message: str, level: str = "info", about: str = "") -> None:
            out["operator"].append((level, message))

    # PATCHED WHERE THE ACTIVITY RESOLVES THEM. `notifier_for_project` is imported inside the
    # function body (the import graph is a feature here — the panel serves without temporalio), so
    # the seam is the module it comes FROM, not this one.
    monkeypatch.setattr("openfactory.factory.notifier_for_project", lambda project: _Notifier())
    monkeypatch.setattr(activities, "ProjectRegistry",
                        lambda: type("R", (), {"get": staticmethod(lambda name: object())})())
    monkeypatch.setattr(activities, "_invite_the_client_to_look",
                        lambda project, inp: out["client"].append(inp.url))
    return out


async def test_a_green_deploy_with_an_address_ASKS(sent):
    await activities.notify_deploy(DeployNotifyInput(
        project="podbeam", issue="87", status="success", env="staging",
        run_url="https://github.com/o/r/actions/runs/1", url="https://stg.podbeam.example"))

    level, message = sent["operator"][0]
    assert "https://stg.podbeam.example" in message, "the address never reached the person asked to look"
    assert "look" in message.lower(), "it reports a deploy without asking anybody anything"
    assert level == "action_required", (
        "an invitation to validate is filed as news — it is a thing somebody must do")
    assert sent["client"] == ["https://stg.podbeam.example"], "the second surface was never told"


async def test_a_green_deploy_with_NO_address_invents_no_place(sent):
    await activities.notify_deploy(DeployNotifyInput(
        project="podbeam", issue="87", status="success", env="staging",
        run_url="https://github.com/o/r/actions/runs/1"))

    level, message = sent["operator"][0]
    assert "look" not in message.lower(), (
        "somebody is being sent to look at a place this deployment never named")
    assert level == "info"
    assert sent["client"] == [], "a client was messaged about an address that does not exist"


@pytest.mark.parametrize("status", ["failure", "timeout"])
async def test_a_deploy_that_did_not_go_green_asks_nobody_to_validate_it(status, sent):
    await activities.notify_deploy(DeployNotifyInput(
        project="podbeam", issue="87", status=status, env="staging",
        url="https://stg.podbeam.example"))

    level, message = sent["operator"][0]
    assert "look" not in message.lower(), f"a {status} deploy is inviting somebody to validate it"
    assert level == "error"
    assert sent["client"] == []


def test_the_OPERATOR_half_does_not_go_through_the_product_module():
    """The failure this card was opened for, one layer up: a capability that only exists when an
    optional module is switched on. Derived from the source, because the whole point is that the
    operator's path must not reach `product/` at all."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(activities.notify_deploy).lstrip())
    operator_calls = [n for n in ast.walk(tree)
                      if isinstance(n, ast.Call)
                      and getattr(n.func, "id", "") == "notifier_for_project"]
    assert operator_calls, "the operator is no longer notified at all"
    src = inspect.getsource(activities.notify_deploy)
    assert src.index("notifier_for_project") < src.index("_invite_the_client_to_look"), (
        "the client is told first — a failure there would cost the operator their notification")


def test_the_client_half_is_silent_when_there_is_nobody_to_tell(monkeypatch):
    """No product module, no channel, no client — no message, and no exception either. The
    operator has already been told by the time this runs."""
    posted: list[str] = []
    monkeypatch.setattr(activities, "channel_destination", lambda project, configured: "")
    monkeypatch.setattr(activities, "_product_post",
                        lambda channel, project, cfg, text: posted.append(text))

    class _Cfg:
        enabled, channel_id = True, ""

    class _P:
        product, language, name = _Cfg(), "pt-BR", "podbeam"

    activities._invite_the_client_to_look(
        _P(), DeployNotifyInput(project="podbeam", issue="87", status="success",
                                url="https://stg.podbeam.example"))
    assert posted == []

    class _NoProduct:
        product, language, name = None, "en", "x"

    activities._invite_the_client_to_look(
        _NoProduct(), DeployNotifyInput(project="x", issue="1", status="success", url="https://x"))
    assert posted == []
