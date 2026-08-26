"""Install the add-ons the packages under `addons/` declare, for the duration of one test.

THE PLATFORM'S OWN CONNECTORS ARE ADD-ONS NOW. The `fargate` runner, the DynamoDB metrics sink,
the S3 session store and the SSM token-pool source are rows `addons/openfactory-aws` declares in
the `openfactory.adapters` entry-point group; the chat channel, its notifier and the Telegram
fallback are rows `addons/openfactory-slack` declares. None is a row in the core's tables — so a
test that needs one has to INSTALL it, the way `pip install` would.

WHY NOT SIMPLY LET `importlib.metadata` FIND THEM. An editable install writes `entry_points.txt`
once, at install time; a checkout that adds a row to a package's `pyproject.toml` is invisible to
the running interpreter until somebody reinstalls that package. A suite that depended on that
would be green on a fresh CI box and red on the machine the row was written on — or, worse, the
other way round after a stale reinstall. So the fixture reads the declarations from the packages'
own `pyproject.toml` files and serves exactly those rows through the same `entry_points()` call
the loader makes, loading the REAL target objects. What is proven is the whole declared chain:
name → `module:attr` → a callable that builds the right thing. What is not proven here, and is
checked by its own test, is that the installed metadata agrees with the files.

IN THE PUBLIC TREE THERE ARE NO PACKAGES. `addons/` leaves the export, so `declared()` answers an
empty table there and every test that needs one of the platform's own rows skips by name
(`require()`), the way the terraform guards skip where `infra/` is absent.
"""

from __future__ import annotations

import importlib
import pathlib
import tomllib

import add_ons
import pytest

from openfactory import plugins

ROOT = pathlib.Path(__file__).resolve().parents[1]
#: The packages' directory IS the public-tree signal (`add_ons.public_tree_signal`), spelled once.
ADDONS = ROOT / add_ons.public_tree_signal()


def packages() -> dict[str, pathlib.Path]:
    """`{"openfactory-aws": <addons/openfactory-aws>, …}` — every package under `addons/` that
    has a pyproject, by the name its pyproject declares."""
    found: dict[str, pathlib.Path] = {}
    for pyproject in sorted(ADDONS.glob("*/pyproject.toml")):
        data = tomllib.loads(pyproject.read_text())
        found[data["project"]["name"]] = pyproject.parent
    return found


def declared_by(package_dir: pathlib.Path) -> dict[str, str]:
    """One package's rows: `{"metrics.dynamodb": "openfactory.observability.dynamo:build", …}`."""
    data = tomllib.loads((package_dir / "pyproject.toml").read_text())
    return dict(data["project"].get("entry-points", {}).get(plugins.GROUP, {}))


def declared() -> dict[str, str]:
    """Every row the platform's own packages declare, across `addons/`. A name declared by two
    packages would be two answers for one kind and is refused here, by name."""
    rows: dict[str, str] = {}
    owners: dict[str, str] = {}
    for name, package_dir in packages().items():
        for point, target in declared_by(package_dir).items():
            assert point not in rows, (
                f"{point} is declared by both {owners[point]} and {name} — one kind, one package")
            rows[point], owners[point] = target, name
    return rows


def require(*names: str) -> None:
    """Skip, by name, when the platform's own packages are not in this tree (the public export)
    or do not declare `names` — never read an absent declaration as a passing test."""
    if add_ons.is_public_tree():
        pytest.skip(f"this is the public tree (no {add_ons.public_tree_signal()}) — the platform's "
                    f"own rows live in the private one")
    if not packages():
        pytest.skip(f"no add-on package under {ADDONS.relative_to(ROOT)} — the platform's own "
                    f"rows live in the private tree")
    rows = declared()
    missing = [n for n in names if n not in rows]
    if missing:
        pytest.skip(f"{missing} are not declared by any package under addons/")


class Point:
    """One entry point, as `importlib.metadata` hands them over — loading the real target."""

    def __init__(self, name: str, value: str) -> None:
        self.name, self.value = name, value

    def load(self):
        module, _, attr = self.value.partition(":")
        return getattr(importlib.import_module(module), attr)


def install(monkeypatch, *names: str, declared_rows: bool = True, extra: tuple = ()) -> None:
    """Serve the declared rows named (all of them when none are named and `declared_rows`), plus
    `extra` points — objects with `.name` and `.load()`. `declared_rows=False` with no names
    serves only `extra`, which is how a test pins "the add-on is NOT installed".

    Patched at `importlib.metadata.entry_points` rather than at our own loader, because patching
    the loader would prove that our function returns what we told it to — and the claim is about
    the PACKAGING mechanism, which is the part a stranger actually uses. The loader's cache is
    handed to `monkeypatch` too, so the rows leave with the test."""
    if names or declared_rows:
        require(*names)  # the public tree has no rows to serve: skip by name, never serve none
    rows = declared()
    chosen = names or (tuple(rows) if declared_rows else ())
    missing = [n for n in chosen if n not in rows]
    assert not missing, (f"{missing} are not declared by any package under addons/ in the "
                         f"{plugins.GROUP} group")
    points = [Point(n, rows[n]) for n in chosen] + list(extra)
    monkeypatch.setattr("importlib.metadata.entry_points",
                        lambda group=None: list(points) if group == plugins.GROUP else [])
    monkeypatch.setattr(plugins, "_cache", None)


def not_ours(points, ours: dict[str, str]) -> list:
    """`points` minus the rows the packages under `addons/` declare — matched on BOTH the name
    and the target, so a stranger who declares the same kind pointing at its own module is left
    alone. Pure, so it can be fed a case that must fail; the autouse firewall in
    `tests/conftest.py` is the only caller."""
    return [p for p in points if ours.get(p.name) != p.value]
