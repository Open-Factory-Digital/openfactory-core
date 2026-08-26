"""A deploy observed for somebody else's commit is not evidence about yours (2026-08-16).

`PromotionRunner` asks `deploy_status(env=…, ref=base_branch)` for every stage of the client's
chain, posts *"✅ staging verified"* on the ticket when it comes back green, and — if the chain has
a production stage — parks the job asking a human to approve the release. The whole gate rests on
that one answer being about the change in front of them.

`GitHubActionsObserver.deploy_status` took `ref` and never used it. It read the newest Deployment
to the environment, whoever made it and from whatever branch. A colleague deploying a hotfix to
staging while a ticket was promoting made the platform verify the ticket's change with the
hotfix's deploy.

THE AZURE TWIN HAS ALWAYS BEEN RIGHT, and its docstring names this precise failure:
*"Skipping that correlation would answer 'staging is green' using somebody else's commit."* It is
the second-vendor lesson again — the port that came later was written carefully, and the one on
the vendor this repository develops against carried the defect.

So this file holds the two implementations to ONE contract, in the four answers the callers
distinguish. `pending` and `unknown` are not interchangeable: one is "wait", the other is "your
manifest names an environment that does not exist".
"""

from __future__ import annotations

import pytest

from openfactory.adapters.environment.github_actions import GitHubActionsObserver


class _Api:
    """A GitHub API that answers by PATH, so what the code asked for is part of the assertion."""

    def __init__(self, answers: dict[str, object]) -> None:
        self.answers, self.asked = answers, []

    def __call__(self, path: str) -> object:
        self.asked.append(path)
        for key, value in self.answers.items():
            if key in path:
                return value
        return []


def _observer(answers: dict[str, object]) -> tuple[GitHubActionsObserver, _Api]:
    obs = GitHubActionsObserver("o/r")
    api = _Api(answers)
    obs._api = api  # the only seam: everything else is the real method under test
    return obs, api


def test_the_deployment_read_is_SCOPED_to_the_ref():
    """The regression itself. Without the ref in the query the answer is about the environment,
    not about the change."""
    obs, api = _observer({
        "deployments?environment=staging&ref=main": [{"id": 7}],
        "deployments/7/statuses": [{"state": "success"}],
    })
    assert obs.deploy_status(env="staging", ref="main") == "success"
    assert any("ref=main" in p for p in api.asked), (
        f"the observer never told GitHub which ref it is asking about: {api.asked}")


def test_a_deploy_of_ANOTHER_ref_does_not_verify_this_one():
    """The failure in one test: staging has been deployed — from a branch that is not ours."""
    obs, _ = _observer({
        "deployments?environment=staging&ref=main": [],          # nothing from OUR ref
        "deployments?environment=staging&per_page": [{"id": 9}],  # …but the env is in use
        "deployments/9/statuses": [{"state": "success"}],
    })
    assert obs.deploy_status(env="staging", ref="main") == "pending", (
        "somebody else's green deploy is being reported as this change's — the ticket would say "
        "'staging verified' and a human would be asked to approve production on that basis")


def test_an_environment_nobody_has_ever_deployed_to_is_UNKNOWN_not_pending():
    """A manifest naming an environment that does not exist is a configuration mistake worth
    reporting; 'pending' would tell the operator to wait for something that will never arrive."""
    obs, _ = _observer({})
    assert obs.deploy_status(env="stagng", ref="main") == "unknown"


@pytest.mark.parametrize("state,expected", [
    ("success", "success"),
    ("failure", "failure"),
    ("error", "failure"),
    ("in_progress", "pending"),
    ("queued", "pending"),
    ("wat", "unknown"),
])
def test_every_deployment_state_maps_to_one_of_the_four_answers(state, expected):
    obs, _ = _observer({
        "deployments?environment=staging&ref=main": [{"id": 1}],
        "deployments/1/statuses": [{"state": state}],
    })
    assert obs.deploy_status(env="staging", ref="main") == expected


def test_a_deployment_with_no_status_yet_is_pending():
    obs, _ = _observer({"deployments?environment=staging&ref=main": [{"id": 1}]})
    assert obs.deploy_status(env="staging", ref="main") == "pending"


def test_NO_observer_accepts_a_contract_parameter_and_ignores_it():
    """The class of defect, not this instance of it.

    A port method that takes an argument and never reads it compiles, type-checks, passes every
    test written against its other argument, and answers a question nobody asked. That is exactly
    what `deploy_status(env, ref)` did on GitHub for as long as it has existed.

    Derived from the port: every method on `EnvironmentObserver` is walked in every implementation,
    and each declared parameter must appear somewhere in the body. It cannot false-positive on
    delegation — passing `ref` to a helper still reads the name.

    (The first version of this guard scanned each implementation's source for the four answer
    strings, and accused the Azure observer of never returning "success" — which it does, through
    a helper. A guard that measures the wrong thing fails on correct code, and gets deleted.)"""
    import ast
    import inspect

    from openfactory.adapters.environment.azure_pipelines import AzurePipelinesObserver
    from openfactory.adapters.environment.base import EnvironmentObserver

    contract = {name: [p for p in inspect.signature(fn).parameters if p != "self"]
                for name, fn in vars(EnvironmentObserver).items()
                if callable(fn) and not name.startswith("_")}
    assert contract, "the observer port declares no methods — this guard is measuring nothing"

    offenders = []
    for impl in (GitHubActionsObserver, AzurePipelinesObserver):
        for name, params in contract.items():
            fn = getattr(impl, name, None)
            if fn is None or fn is vars(EnvironmentObserver).get(name):
                continue  # inherited, not implemented here
            used = {n.id for n in ast.walk(ast.parse(inspect.getsource(fn).lstrip()))
                    if isinstance(n, ast.Name)}
            used |= {n.arg for n in ast.walk(ast.parse(inspect.getsource(fn).lstrip()))
                     if isinstance(n, ast.keyword) and n.arg}
            for p in params:
                if p not in used and p != "timeout":
                    offenders.append(f"{impl.__name__}.{name} ignores `{p}`")
    assert not offenders, (
        "these implementations take a parameter the contract defines and never read it — the "
        "answer is then about something the caller did not ask about:\n  " + "\n  ".join(offenders))
