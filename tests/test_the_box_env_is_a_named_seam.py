"""`box.env` — a project names which environment variables its box may receive (the harness axis).

WHY. The box passed through exactly two hard-coded credentials (CLAUDE_CODE_OAUTH_TOKEN /
ANTHROPIC_API_KEY), which quietly assumes every deployment authenticates the harness the same
way. The first enterprise client does not: Claude reaches them through Bedrock
(`CLAUDE_CODE_USE_BEDROCK`, `AWS_REGION`, the AWS credential set) or through an LLM gateway
(`ANTHROPIC_BASE_URL`, a gateway key). The same seam is what lets a client's security scanners
authenticate inside the box (`BLACKDUCK_URL`, …) without the platform learning any vendor's name.

THE REGISTRY NAMES VARIABLES, IT NEVER HOLDS VALUES — the same rule as `tracker.options.token_env`
and ADR-0015's `bot_token_env`, for the same reason: the registry is baked into the worker image.
"""

from __future__ import annotations

import pytest

from openfactory.adapters.sandbox.container import ContainerSandbox


def test_declared_and_present_variables_cross_into_the_box(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("AWS_REGION", "eu-west-2")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    box = ContainerSandbox(image="img",
                           extra_env=("CLAUDE_CODE_USE_BEDROCK", "AWS_REGION",
                                      "AWS_SESSION_TOKEN"))

    names = box._passthrough_env()

    assert "CLAUDE_CODE_USE_BEDROCK" in names and "AWS_REGION" in names
    assert "AWS_SESSION_TOKEN" not in names, (
        "an ABSENT variable must not be passed — docker would create it empty inside the box, "
        "and an empty credential fails differently from a missing one everywhere that matters")


def test_the_harness_defaults_still_cross_without_any_declaration(monkeypatch):
    """Every project that exists today declares nothing — byte-for-byte behaviour."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    box = ContainerSandbox(image="img")

    assert box._passthrough_env() == ["ANTHROPIC_API_KEY"]


def test_presence_is_rechecked_per_call_because_the_pool_rotates(monkeypatch):
    """The audit that made run() re-read _AUTH_ENV_VARS applies here too: a snapshot taken at
    prepare() would keep exec'ing with a dead credential after a rotation."""
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    box = ContainerSandbox(image="img", extra_env=("AWS_BEARER_TOKEN_BEDROCK",))

    assert "AWS_BEARER_TOKEN_BEDROCK" not in box._passthrough_env()
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "later")
    assert "AWS_BEARER_TOKEN_BEDROCK" in box._passthrough_env()


def test_a_name_that_is_not_a_name_is_refused_at_construction():
    """Each entry becomes a `docker` argument. A 'name' carrying a value or an option would ride
    straight into the command line — and this list is configuration, not code review."""
    for bad in ("AWS_REGION=eu-west-2", "-e", "A B", "", "então"):
        with pytest.raises(ValueError, match="box.env"):
            ContainerSandbox(image="img", extra_env=(bad,))


def test_duplicates_collapse_so_docker_gets_each_flag_once(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    box = ContainerSandbox(image="img", extra_env=("ANTHROPIC_API_KEY",))

    assert box._passthrough_env().count("ANTHROPIC_API_KEY") == 1


def test_the_registry_declaration_reaches_the_container_builder():
    """The knob is forwarded like its siblings — a declared `box.env` must not be a setting that
    looks configured and is ignored (C-13's defect, one knob over)."""
    from openfactory.adapters.sandbox.registry import build_sandbox

    box = build_sandbox("container", image="img", extra_env=("AWS_REGION",))

    assert box.extra_env == ("AWS_REGION",)


def test_the_project_contract_carries_the_names():
    from openfactory.contracts.project import BoxConfig, Project, ProviderRef

    p = Project(name="dsk", repo_path="u", tracker=ProviderRef(kind="github", repo="a/b"),
                box=BoxConfig(image="mcr.microsoft.com/dotnet/sdk:8.0",
                              env=["CLAUDE_CODE_USE_BEDROCK", "AWS_REGION"]))

    assert p.box.env == ["CLAUDE_CODE_USE_BEDROCK", "AWS_REGION"]
