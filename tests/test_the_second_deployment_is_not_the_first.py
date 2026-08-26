"""What a second installation cannot change without editing source (#163).

A second deployment exists — it is not hypothetical — and the sweep measured what it would inherit:
the first one's region in four modules, the first one's SSM parameter tree in the panel, and a
durable engine that falls back to `localhost:7233` when nobody says otherwise.

THE RULE: a deployment-varying value has exactly one home (env or registry), is read at CALL time,
and its absence fails out loud. Never a localhost, never `eu-west-2`, never the first deployment's
parameter path.

WHY ABSENCE MUST BE LOUD, and not merely defaulted well. The two failures look identical from
inside the process and opposite from outside it: a worker pointed at nothing does nothing, and a
worker pointed at somebody else's account does something. The house memory records the first one
costing a debugging day (`temporal-cloud-not-localhost`), and this file is the guard that memory
asked for.
"""

from __future__ import annotations

import ast
import pathlib

import add_ons
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: The literal that started this: the first deployment's region, and the value four modules used
#: when nobody had said anything.
FIRST_DEPLOYMENTS_REGION = "eu-west-2"


def _terraform() -> str:
    """Every `.tf` in this repository, WITHOUT its comments — read through the one shared stripper
    (`tests/terraform_text.py`), and skipping by name where the reference deployment is absent.

    The eighth guard in a fortnight to break on the comment explaining the rule it protects: the
    note above the fixed start command names `sdlc.api.app` as the thing that was wrong, and a
    raw substring search reads that as the defect still being there.
    """
    import terraform_text

    terraform_text.require()
    return terraform_text.whole()


# ── 1. the durable engine ───────────────────────────────────────────────────────────────────────

def test_an_engine_nobody_declared_is_an_ERROR_not_a_localhost(monkeypatch):
    from openfactory.runtime.temporal import connection

    for var in ("TEMPORAL_ADDRESS", "TEMPORAL_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(connection.EngineNotDeclared) as caught:
        connection.address()

    said = str(caught.value)
    assert "TEMPORAL_ADDRESS" in said and "TEMPORAL_ENDPOINT" in said, said
    assert connection.LOCAL_DEV_ADDRESS in said, (
        "the refusal does not say how to ask for a local dev server — a rule with no way to obey "
        "it is a rule somebody deletes")


@pytest.mark.parametrize("var", ["TEMPORAL_ADDRESS", "TEMPORAL_ENDPOINT"])
def test_and_either_NAME_still_declares_one(monkeypatch, var):
    """Both spellings are live: the compose stack sets one, the terraform in this repository sets
    the other, and Temporal Cloud's console calls it the second."""
    from openfactory.runtime.temporal import connection

    for name in ("TEMPORAL_ADDRESS", "TEMPORAL_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(var, "acme.eu-central-1.aws.api.temporal.io:7233")

    assert connection.address() == "acme.eu-central-1.aws.api.temporal.io:7233"


def test_the_panel_asks_connection_rather_than_reading_the_variables_itself(monkeypatch):
    """Two readers, opposite precedence, and each with its own localhost default — so a deployment
    that set both had the panel linking to one engine while the worker connected to the other."""
    from openfactory.runtime.temporal import view

    monkeypatch.setenv("TEMPORAL_ADDRESS", "declared:7233")
    monkeypatch.setenv("TEMPORAL_ENDPOINT", "other:7233")
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "acme.abc12")

    from openfactory.runtime.temporal import connection

    assert view.temporal_config() == (connection.address(), connection.namespace())


@pytest.mark.parametrize("endpoint,expected", [
    ("acme.tmprl.cloud:7233", "https://cloud.temporal.io"),
    # THE FORM THIS MISSED. `connection.py`'s own header documents it, one module over, while
    # `ui_base` read it as "not the cloud" and deep-linked a production panel at localhost.
    ("acme.eu-central-1.aws.api.temporal.io:7233", "https://cloud.temporal.io"),
    ("temporal:7233", "http://localhost:8233"),
    ("", "http://localhost:8233"),
])
def test_the_ui_link_knows_BOTH_cloud_endpoint_forms(monkeypatch, endpoint, expected):
    from openfactory.runtime.temporal import view

    monkeypatch.delenv("TEMPORAL_UI_URL", raising=False)
    monkeypatch.setenv("TEMPORAL_ENDPOINT", endpoint)
    monkeypatch.delenv("TEMPORAL_ADDRESS", raising=False)

    assert view.ui_base() == expected


# ── 2. the region ───────────────────────────────────────────────────────────────────────────────

def test_a_region_nobody_declared_is_EMPTY_where_it_decides_a_link(monkeypatch):
    """This product's default shape has no cloud at all, and that is not a degraded state."""
    from openfactory import environ

    # BOTH NAMES, because both are read. Deleting one and asserting emptiness would make this
    # guard depend on whether the machine running it happens to export the other.
    for var in environ.REGION_VARS:
        monkeypatch.delenv(var, raising=False)

    assert environ.cloud_region() == ""


def test_and_an_ERROR_where_it_decides_which_ACCOUNT_is_read(monkeypatch):
    from openfactory import environ

    for var in environ.REGION_VARS:
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(environ.NotDeclared, match="AWS_DEFAULT_REGION"):
        environ.cloud_region(required=True)


@pytest.mark.parametrize("var", ["AWS_DEFAULT_REGION", "AWS_REGION"])
def test_and_either_of_AWSs_OWN_names_declares_one(monkeypatch, var):
    """boto3 honours both. One of the five welded sites read the second as a fallback and the
    other four did not — so a deployment that set only `AWS_REGION` was read by four of them as
    having declared nothing, and answered with the first deployment's region."""
    from openfactory import environ

    for name in environ.REGION_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(var, "sa-east-1")

    assert environ.cloud_region(required=True) == "sa-east-1"


def test_no_module_carries_the_first_deployments_region_as_a_fallback():
    """The measurement, over the package. Four modules had it; a fifth is one grep away.

    THE STRING MAY APPEAR — a docstring explaining this rule needs to name the thing it forbids,
    and a test fixture needs a region to be about. What may not appear is a `.get(…, "eu-west-2")`
    or an `or "eu-west-2"`: the shapes that answer with it when nobody asked.
    """
    offenders = []
    for path in sorted((ROOT / "openfactory").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or node.value != FIRST_DEPLOYMENTS_REGION:
                continue
            offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")

    assert not offenders, (
        f"the first deployment's region is a value in neutral code: {offenders} — a second "
        f"install would read that account's resources, or none")


def test_the_fargate_config_requires_a_region_like_any_other_coordinate():
    fargate_config_from_env = add_ons.module(
        "openfactory.runtime.fargate.launcher").fargate_config_from_env

    complete = {"OPENFACTORY_FARGATE_CLUSTER": "c", "OPENFACTORY_FARGATE_SUBNETS": "s",
                "OPENFACTORY_FARGATE_SG": "sg", "OPENFACTORY_FARGATE_TASKDEF": "t",
                "OPENFACTORY_FARGATE_LOG_GROUP": "/g", "AWS_DEFAULT_REGION": "ap-south-1"}

    assert fargate_config_from_env(complete).region == "ap-south-1"

    with pytest.raises(KeyError, match="AWS_DEFAULT_REGION"):
        fargate_config_from_env({k: v for k, v in complete.items()
                                 if k != "AWS_DEFAULT_REGION"})


# ── 3. the parameter tree ───────────────────────────────────────────────────────────────────────

def test_the_ssm_prefix_is_declared_and_normalised(monkeypatch):
    """`/acme/` and `/acme` must name one tree: the code appends `/agent-tokens`, and a trailing
    slash would produce `//agent-tokens` — a path AWS does not answer for."""
    from openfactory import environ

    monkeypatch.setenv(environ.SSM_PREFIX_VAR, "/acme-factory/")
    assert environ.ssm_prefix() == "/acme-factory"

    monkeypatch.delenv(environ.SSM_PREFIX_VAR, raising=False)
    assert environ.ssm_prefix() == ""


def test_the_terraform_DECLARES_what_the_code_now_requires():
    """Reachability, across the language boundary. The code reading an env var nothing sets is the
    same defect facing the other way: every panel would fall back to its own environment pool and
    the SSM read would be dead — green, silent, and exactly what a literal was hiding."""
    tf = _terraform()

    from openfactory import environ

    assert f'"{environ.SSM_PREFIX_VAR}"' in tf or f"{environ.SSM_PREFIX_VAR} " in tf, (
        f"no terraform service passes {environ.SSM_PREFIX_VAR} — the panel cannot find this "
        f"deployment's parameters at all")
    assert "var.ssm_prefix" in tf


def test_the_panel_runs_the_module_this_package_actually_has():
    """Found in passing and left live by the rename: an App Runner panel created from this file
    would crash-loop on `sdlc.api.app`, and only the deployment that turns the optional panel on
    would ever see it — which is the second one."""
    tf = _terraform()

    assert "sdlc.api.app" not in tf, "the terraform starts a module this package no longer has"
    assert tf.count("openfactory.api.app:app") >= 2


def test_the_panel_asks_SSM_for_ITS_OWN_tree(monkeypatch):
    """Which path is queried, not merely that one is. The literal here was
    `/openfactory/agent-tokens` while every parameter in this repository's terraform is built from
    `var.ssm_prefix` — so a guard that only asserts "SSM was consulted" is green either way."""
    from vendor_addons import install

    from openfactory import environ
    from openfactory.api import app

    observe = add_ons.module("openfactory.runtime.fargate.observe")
    asked: list[tuple[str, str]] = []
    monkeypatch.setattr(observe, "token_pool_from_ssm",
                        lambda parameter, region: asked.append((parameter, region)) or {})
    # the pool's source is DECLARED (the add-on's `ssm` row), no longer inferred from a cluster
    install(monkeypatch, "token_pool.ssm")
    monkeypatch.setenv("OPENFACTORY_TOKEN_POOL_SOURCE", "ssm")
    monkeypatch.setenv(environ.SSM_PREFIX_VAR, "/acme-factory")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-central-1")

    app._token_pool_meta()

    assert asked == [("/acme-factory/agent-tokens", "eu-central-1")], asked


def test_and_a_route_to_an_UNDECLARED_engine_answers_503(monkeypatch):
    """Not a 500. Every one of these routes already turns an unreachable engine into a 503 with a
    reason; an engine nobody declared is the same class of answer and a better sentence — it names
    the variable to set instead of sending somebody to look at the network."""
    from fastapi.testclient import TestClient

    from openfactory.api.app import app as panel

    for var in ("TEMPORAL_ADDRESS", "TEMPORAL_ENDPOINT", "OPENFACTORY_PANEL_TOKEN"):
        monkeypatch.delenv(var, raising=False)

    answered = TestClient(panel).get("/api/inbox")

    assert answered.status_code == 503, answered.status_code
    assert "TEMPORAL_ADDRESS" in answered.text, answered.text[:300]
