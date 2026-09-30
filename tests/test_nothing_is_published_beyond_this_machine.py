"""The compose file publishes nothing on a network interface unless the operator says so.

THE ADVISORY. Every release up to 0.4.1 published the engine (7233), its UI (8080) and the panel
(8787) as `"PORT:PORT"` — no host address, which Docker binds on 0.0.0.0 and `::`, ahead of most
host firewall rules. The engine and its UI have no authentication at all: anybody who reached
them could read every job, terminate any of them, and signal the human gates directly.

Held here: every published port names the address it binds; the engine's two are loopback and
not configurable; the panel's is loopback unless PANEL_BIND says otherwise.
"""

from __future__ import annotations

import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"

_VAR = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)(?::-([^}]*))?\}")


def _ports() -> dict[str, list[str]]:
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    return {name: [str(p) for p in (service.get("ports") or [])]
            for name, service in services.items()}


def _as_shipped(mapping: str) -> str:
    return _VAR.sub(lambda m: m.group(2) or "", mapping)


def test_every_published_port_names_the_address_it_binds():
    bare = {name: mapping for name, mappings in _ports().items() for mapping in mappings
            if len(_as_shipped(mapping).split(":")) != 3}
    assert not bare, (f"published with no host address, so on every interface: {bare}. Write "
                      f"`127.0.0.1:` in front, or a variable whose default is loopback.")


def test_as_shipped_nothing_is_published_beyond_loopback():
    exposed = {name: _as_shipped(mapping) for name, mappings in _ports().items()
               for mapping in mappings if not _as_shipped(mapping).startswith("127.0.0.1:")}
    assert not exposed, exposed


def test_the_engine_and_its_ui_are_loopback_whatever_the_env_file_says():
    """No variable decides the engine's bind address: it has no sign-in, and there is no
    deployment of this file for which opening it is the right answer."""
    ports = _ports()
    for service in ("temporal", "temporal-ui"):
        assert ports[service], f"{service} publishes nothing — then say so in this test"
        for mapping in ports[service]:
            assert mapping.startswith("127.0.0.1:"), (service, mapping)


def test_the_panel_is_opened_only_by_its_own_variable():
    (mapping,) = _ports()["panel"]
    assert mapping.startswith("${PANEL_BIND:-127.0.0.1}:"), mapping


def test_the_operator_is_told_where_to_open_the_panel():
    example = (ROOT / ".env.compose.example").read_text()
    assert re.search(r"^PANEL_BIND=", example, re.M), "the example env file has no PANEL_BIND row"
