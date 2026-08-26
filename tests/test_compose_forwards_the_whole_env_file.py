"""The compose stack forwards EVERY row of `.env.compose` — or `token_env` is decorative there.

The registry's credential rule is "the project's entry NAMES the variable, the env file HOLDS the
value" — which means a client can invent `ACME_ADO_PAT`, and no fixed `environment:` list written
in this repository can ever contain a name a client invents. The funnel review (2026-08-09)
measured the consequence: `AZURE_DEVOPS_PAT`, `OPENFACTORY_FORGE_TOKEN`/`OPENFACTORY_TRACKER_TOKEN`
and the per-person token lists were all documented in `.env.compose.example` and reached nothing —
filled in good faith, silently absent from the worker, failing three layers away as an
authentication error on a credential the operator could see they had set.

`env_file: .env.compose (required: false)` on the worker and the panel is the mechanism. This
guard pins it, with its two load-bearing properties: the file stays OPTIONAL (the stack must boot
for somebody who has not created it yet), and the example file genuinely documents variables the
fixed list does not carry — the positive twin that proves the mechanism is needed, not decoration.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.yml"
_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.compose.example"


def _service(name: str) -> dict:
    return yaml.safe_load(_COMPOSE.read_text())["services"][name]


def _env_file_entries(service: dict) -> list[dict]:
    raw = service.get("env_file") or []
    return [entry if isinstance(entry, dict) else {"path": entry} for entry in raw]


def test_worker_and_panel_read_env_compose_as_an_env_file():
    for name in ("worker", "panel"):
        entries = _env_file_entries(_service(name))
        ours = [e for e in entries if e.get("path") == ".env.compose"]
        assert ours, (f"service {name!r} does not read .env.compose as an env_file — every "
                      f"`token_env` a registry names is unreachable on compose without it")
        assert ours[0].get("required") is False, (
            f"service {name!r} requires .env.compose to exist — the stack must BOOT for "
            f"somebody who has not created the file yet; use `required: false`")


def test_the_example_documents_variables_only_the_env_file_can_deliver():
    """The positive twin. If the fixed `environment:` list ever grows to cover everything the
    example documents, this guard should be re-thought rather than deleted — today it cannot,
    because `token_env` names are the client's to invent."""
    worker_env = set((_service("worker").get("environment") or {}).keys())
    documented = set(re.findall(r"^([A-Z][A-Z0-9_]+)=", _EXAMPLE.read_text(), re.MULTILINE))
    only_via_env_file = documented - worker_env
    assert "AZURE_DEVOPS_PAT" in only_via_env_file
    assert {"OPENFACTORY_FORGE_TOKEN", "OPENFACTORY_TRACKER_TOKEN"} <= only_via_env_file
