"""A local deployment's panel must not reach AWS — on ANY endpoint (ADR-0037 audit, 2026-08-02).

`_boxes_are_remote()` exists and is correct, and `_events()` uses it. A cloud-independence audit
then found two paths that do not, and both were reproduced against the running compose panel:

1. **`_token_pool_meta()` calls SSM with no gate at all** — not on the sandbox kind, not on
   credential presence, not on any flag. It is called unconditionally by
   `GET /api/factory/{project}`, which the panel fetches every time an operator selects a project.
   The parameter path (`<ssm-prefix>/agent-tokens`) and the default region (`eu-west-2`) are
   baked-in defaults of whichever deployment built the image, so an operator with their own AWS
   credentials queries a path that does not exist in their account, and an operator with none pays
   a credential-chain stall on every click.

2. **The SSE stream builds a `CloudWatchEventTail` whenever the journal file is absent** — the
   `else` of a bare `path.exists()`, missing the guard its sibling reader received. And because
   journals are written beside the client's repository while the panel reads a mounted volume
   (#67), `path.exists()` is False for every job on a stock install: the CloudWatch branch is not a
   fallback, it is the only path the stream ever takes. The loop runs up to 86400 iterations at 3s,
   so an open job card is ~28,800 CloudWatch calls a day against a log group the operator does not
   have.

WHY THE EXISTING TEST DID NOT CATCH EITHER. `test_panel_reads_events_without_aws.py` proves the
guard on `_events` — one reader, by name. Nothing asserted the PROPERTY, which is that no endpoint
reaches AWS when the deployment is local. A guard that names one caller cannot see the second one.
That is the same shape as every other miss in this codebase: the negative was pinned, the positive
was not.

THE TEST IS THE PROPERTY. Block `boto3` and `botocore` at `sys.meta_path`, drive every GET endpoint
the panel exposes, and assert nothing tried to import them.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _a_local_deployment(monkeypatch, tmp_path):
    """No Fargate cluster, no remote sandbox: `_boxes_are_remote()` is False, which is what every
    `docker compose` install looks like."""
    for var in ("OPENFACTORY_FARGATE_CLUSTER", "OPENFACTORY_WORKER_LOG_GROUP", "OPENFACTORY_METRICS_TABLE",
                "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "container")
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))


@pytest.fixture
def no_boto(monkeypatch):
    """Records every attempt to import an AWS library, and refuses it."""
    import sys

    tried: list[str] = []

    class _Block:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in ("boto3", "botocore"):
                tried.append(name)
                raise ImportError(f"an AWS library was reached for: {name}")
            return None

    blocker = _Block()
    for mod in [m for m in sys.modules if m.split(".")[0] in ("boto3", "botocore")]:
        monkeypatch.delitem(sys.modules, mod, raising=False)
    sys.meta_path.insert(0, blocker)
    yield tried
    sys.meta_path.remove(blocker)


@pytest.fixture
def client(monkeypatch):
    from openfactory.api.app import app

    return TestClient(app, raise_server_exceptions=False)


def _register(name="demo", repo=None):
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    ProjectRegistry().add(Project(
        name=name, repo_path=str(repo or "/tmp/demo"),
        tracker=ProviderRef(kind="github", repo="acme/demo"),
    ))


# ── the endpoint that was reaching ──────────────────────────────────────────────────────────────

def test_the_project_view_does_not_reach_ssm(client, no_boto):
    """THE defect. `_token_pool_meta` asked SSM for `<ssm-prefix>/agent-tokens` in `eu-west-2` on
    every project view, ungated — the image's baked-in parameter path, in the operator's account."""
    _register()

    response = client.get("/api/factory/demo")

    assert response.status_code < 500, response.text
    assert not no_boto, f"the panel reached for AWS: {sorted(set(no_boto))}"


def test_the_token_pool_still_reports_what_the_env_has(monkeypatch, no_boto):
    """The feature must not be deleted with the reach. A deployment that lists its pool in the
    environment still gets a count — that is the degraded path the SSM call already had."""
    import json

    from openfactory.api.app import _token_pool_meta

    # WITH `token` keys: an entry without one is malformed and the loader degrades to the single
    # `CLAUDE_CODE_OAUTH_TOKEN`, which is correct behaviour and was my test being wrong.
    monkeypatch.setenv("OPENFACTORY_AGENT_TOKENS", json.dumps([
        {"id": "a", "token": "sk-ant-a"}, {"id": "b", "token": "sk-ant-b"},
    ]))
    meta = _token_pool_meta()

    assert meta.get("count") == 2, meta
    assert not no_boto


def test_a_remote_deployment_may_still_read_ssm(monkeypatch, no_boto):
    """The guard is about WHAT THE DEPLOYMENT DECLARES, not about removing cloud support. A
    deployment whose pool lives in SSM says so (`OPENFACTORY_TOKEN_POOL_SOURCE=ssm`, the add-on's
    row) and the panel shows it. It used to be inferred from a vendor's cluster variable."""
    from vendor_addons import install

    install(monkeypatch, "token_pool.ssm")
    monkeypatch.setenv("OPENFACTORY_TOKEN_POOL_SOURCE", "ssm")
    # AND IT SAYS WHERE ITS OWN PARAMETERS ARE (#163). Both of these were literals in the panel —
    # `/openfactory/agent-tokens` and `eu-west-2` — and both were the FIRST deployment's, while
    # the terraform beside them builds the path from `var.ssm_prefix`. A remote deployment that
    # declares neither now reads the pool it can see instead of another account's tree.
    monkeypatch.setenv("OPENFACTORY_SSM_PREFIX", "/acme-factory")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-central-1")
    from openfactory.api.app import _token_pool_meta

    _token_pool_meta()

    assert no_boto, "a remote deployment must still consult the authoritative pool"


def test_but_NOT_a_tree_it_never_declared(monkeypatch, no_boto):
    """The half the literal hid. A remote deployment that never said where its parameters live has
    no authoritative pool to read — and reading the path this repository's own terraform builds
    from a variable means reading whichever installation last set that variable in source."""
    from vendor_addons import install

    install(monkeypatch, "token_pool.ssm")
    monkeypatch.setenv("OPENFACTORY_TOKEN_POOL_SOURCE", "ssm")
    monkeypatch.delenv("OPENFACTORY_SSM_PREFIX", raising=False)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-central-1")
    from openfactory.api.app import _token_pool_meta

    _token_pool_meta()

    assert not no_boto, "the panel queried a parameter tree this deployment never declared"


# ── the property, over every endpoint ───────────────────────────────────────────────────────────

ENDPOINTS = [
    "/api/projects",
    "/api/factory/demo",
    "/api/jobs/demo/1/events",
    "/api/costs",
    "/healthz",
]


@pytest.mark.parametrize("path", ENDPOINTS)
def test_no_endpoint_reaches_aws_on_a_local_deployment(client, no_boto, path):
    """The positive twin of the old test, which named one reader. The property is that NOTHING
    reaches AWS when the boxes are local — so a new endpoint is covered the day it is written."""
    _register()

    client.get(path)

    assert not no_boto, f"{path} reached for AWS: {sorted(set(no_boto))}"


def test_the_event_stream_is_guarded_like_its_sibling():
    """`_events` got `_boxes_are_remote()` in C-11c and the SSE stream did not — one reader fixed,
    one left, with nothing asserting they agree. Structural, because driving the SSE loop in a test
    means racing an 86400-iteration generator."""
    import ast
    import pathlib

    src = (pathlib.Path(__file__).resolve().parent.parent / "openfactory/api/app.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef) and n.name == "job_stream")
    body = ast.unparse(fn)

    # the stream tails the remote box through `_StreamTail` (once per stream, bounded retry —
    # `test_the_cloud_is_a_directory_delete` drives it), which is what reaches `_remote_tail`
    assert "_StreamTail" in body, "test is stale — the stream no longer tails the remote box"
    assert "_boxes_are_remote" in body, (
        "the SSE stream builds a remote tail without asking whether the boxes are even remote; "
        "on a local install the journal is absent, so this is not a fallback but the only path"
    )
