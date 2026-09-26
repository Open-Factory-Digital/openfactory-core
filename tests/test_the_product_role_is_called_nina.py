"""The product role is called Nina unless a deployment names it otherwise (#335).

The product owner's decision (2026-09-25): a product whose registry names nobody still has a
colleague with a name. The name was configurable only by editing the live registry by hand;
`openfactory product name` reads and sets it.
"""
from __future__ import annotations

from typer.testing import CliRunner

from openfactory.cli import app
from openfactory.contracts.product import ProductConfig


def test_a_product_nobody_named_is_called_nina():
    assert ProductConfig(docs_repo="acme/docs").agent_name == "Nina"
    # an explicit empty name is still a choice: the role introduces itself by function
    assert ProductConfig(docs_repo="acme/docs", agent_name="").agent_name == ""


def _registered(tmp_path, monkeypatch, *, product: bool = True) -> None:
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    assert CliRunner().invoke(
        app, ["project", "add", "demo", "https://github.com/acme/demo.git"]).exit_code == 0
    if product:
        ProjectRegistry().set_docs_repo("demo", "acme/demo-docs")


def test_the_name_is_read_and_set_from_the_command_line(tmp_path, monkeypatch):
    from openfactory.registry import ProjectRegistry

    _registered(tmp_path, monkeypatch)
    shown = CliRunner().invoke(app, ["product", "name", "demo"])
    assert shown.exit_code == 0 and "'Nina'" in shown.output

    named = CliRunner().invoke(app, ["product", "name", "demo", "  Bruno\n"])
    assert named.exit_code == 0, named.output
    assert ProjectRegistry().get("demo").product.agent_name == "Bruno"

    cleared = CliRunner().invoke(app, ["product", "name", "demo", ""])
    assert cleared.exit_code == 0 and "by function" in cleared.output
    assert ProjectRegistry().get("demo").product.agent_name == ""


def test_a_project_with_no_product_module_is_not_given_a_name(tmp_path, monkeypatch):
    _registered(tmp_path, monkeypatch, product=False)
    out = CliRunner().invoke(app, ["product", "name", "demo", "Nina"])
    assert out.exit_code == 2 and "no product module" in out.output
