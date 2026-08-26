"""The Core kernel names no vendor, and a rename cannot disable a feature in silence (C-08).

`openfactory/contracts/` is the vendor-free kernel — its whole dependency surface is stdlib plus pydantic.
The *names* were not: `slack_channel`, `slack_admins`, `slack_bot_token_env`, `slack_app_token_env`
on both `Project` and `ProductConfig`, plus `ProviderRef.kind` defaulting to `"github"` and the
`handoff_to_github` / `handoff_to_slack` renderers exported from the kernel's own `__init__`.

**THE RENAME IS NOT THE DANGEROUS PART — THE READERS ARE.** Fourteen call sites read these through
`getattr(obj, "slack_…", default)`, so renaming the field does not raise. It returns the default,
and the feature turns itself off:

    factory.py:39           every notification becomes a NullNotifier
    schedule.py:203         zero tech-lead watch schedules are created
    bot.py:73               every Slack admin becomes unauthorized
    bot.py:988-992          zero socket-mode clients, and the skip path logs nothing
    product_channel.py:559  the product agent stops recognising its own channel and answers nobody
    adapters/channel/slack.py:59   sits inside a bare `except Exception: return None` and cannot
                                   fail loud even in principle

A grep-and-replace that misses one produces a green test suite and a mute factory. So the guard
here is not "the kernel is clean" — it is **"no reader still asks for the old name"**, which is the
half that fails silently.

MIGRATION WITHOUT COORDINATION. `deploy/registry.yaml` is gitignored and baked into the worker
image: no test, no CI job and no reviewer can see it. So the old keys keep parsing via
`AliasChoices` and the registry reports them by name at startup. Nobody has to edit a file they
cannot be shown, and nobody finds out from a client's silence.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
KERNEL = [ROOT / "openfactory" / "contracts", ROOT / "openfactory" / "policy"]

#: Vendor tokens that must not appear in an IDENTIFIER inside the kernel. Docstrings and comments
#: are deliberately exempt, and that is a house rule rather than an oversight: a comment here
#: carries the measurement that earned it, and the measurement usually has a vendor's name in it
#: (`adapters/tracker/registry.py:12`, `channel/base.py:3`). What the kernel is held to is what
#: the code NAMES, not what a sentence explains — so this walks identifiers, and a guard that
#: fought the house style is a guard somebody deletes.
VENDORS = ("slack", "github", "gitlab", "jira", "telegram", "teams", "temporal", "fargate",
           "dynamodb", "cloudwatch", "claude", "codex", "kimi", "aws")


def _identifiers(path: pathlib.Path):
    """Every name the code DEFINES or READS, ignoring string content entirely."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            yield node.lineno, node.id
        elif isinstance(node, ast.Attribute):
            yield node.lineno, node.attr
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node.lineno, node.name
        elif isinstance(node, ast.arg):
            yield node.lineno, node.arg
        elif isinstance(node, ast.keyword) and node.arg:
            yield node.lineno, node.arg


def _kernel_files():
    for d in KERNEL:
        yield from sorted(p for p in d.rglob("*.py") if "__pycache__" not in str(p))


def test_the_guard_walks_something():
    """A guard that walks nothing passes for ever."""
    assert len(list(_kernel_files())) >= 10


@pytest.mark.parametrize("path", list(_kernel_files()), ids=lambda p: p.name)
def test_no_kernel_identifier_names_a_vendor(path):
    offenders = [
        f"{path.relative_to(ROOT)}:{line} — {name}"
        for line, name in _identifiers(path)
        if any(v in name.lower() for v in VENDORS)
    ]
    assert not offenders, (
        "the Core kernel must name no vendor (docs/core/02 E5). Docstrings and comments are "
        "exempt; these are identifiers:\n  " + "\n  ".join(offenders)
    )


# ── the half that fails silently ────────────────────────────────────────────────────────────────

def test_no_reader_anywhere_still_asks_for_a_renamed_field():
    """The trap, and the reason this card is not a rename.

    `getattr(project, "slack_channel", None)` does not raise after the rename — it returns None,
    and the factory goes mute with every test still green."""
    gone = ("slack_channel", "slack_admins", "slack_bot_token_env", "slack_app_token_env")
    offenders: list[str] = []
    for path in sorted((ROOT / "openfactory").rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            # getattr(x, "slack_channel", ...) — the silent form
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "getattr" and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value in gone):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} — "
                                 f"getattr(..., {node.args[1].value!r})")
            # x.slack_channel — the loud form, still wrong
            if isinstance(node, ast.Attribute) and node.attr in gone:
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} — .{node.attr}")
    assert not offenders, (
        "these readers still ask for a field that no longer exists. `getattr` returns the default "
        "instead of raising, so the feature turns itself off and every test stays green:\n  "
        + "\n  ".join(offenders)
    )


# ── the migration: an old registry still parses ─────────────────────────────────────────────────

def test_a_registry_written_with_the_old_keys_still_loads():
    """`deploy/registry.yaml` is gitignored and baked into the worker image — no test, no CI job
    and no reviewer can see it. Requiring an edit nobody can be shown is how a deploy goes mute."""
    from openfactory.contracts.project import Project, ProviderRef

    p = Project(name="demo", repo_path="/tmp/x", tracker=ProviderRef(kind="github", repo="a/b"),
                slack_channel="C123",
                slack_admins=["U1"], slack_bot_token_env="SLACK_BOT_TOKEN_FINK")
    assert p.channel_id == "C123"
    assert p.admins == ["U1"]
    assert p.channel_options["bot_token_env"] == "SLACK_BOT_TOKEN_FINK"


def test_the_product_config_migrates_too():
    from openfactory.contracts.product import ProductConfig

    cfg = ProductConfig(docs_repo="a/b", slack_channel="C9", slack_admins=["U2"])
    assert cfg.channel_id == "C9" and cfg.admins == ["U2"]


def test_the_new_names_work_too():
    from openfactory.contracts.project import Project, ProviderRef

    p = Project(name="demo", repo_path="/tmp/x", tracker=ProviderRef(kind="github", repo="a/b"),
                channel_id="C1", admins=["U1"])
    assert p.channel_id == "C1" and p.admins == ["U1"]


def test_a_rewrite_migrates_the_file(tmp_path, monkeypatch):
    """Self-migrating: anything the registry writes back uses the new names, so the old keys drain
    away rather than needing a flag day."""
    import yaml

    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    live = tmp_path / "r.yaml"
    live.write_text(yaml.safe_dump({"projects": {"demo": {
        "name": "demo", "repo_path": "/tmp/x", "tracker": {"kind": "github", "repo": "a/b"},
        "slack_channel": "C123"}}}))
    reg = ProjectRegistry(live)
    reg.add(Project(name="other", repo_path="/tmp/y",
                    tracker=ProviderRef(kind="github", repo="a/c")))
    written = yaml.safe_load(live.read_text())["projects"]["demo"]
    assert written["channel_id"] == "C123"
    assert "slack_channel" not in written


def test_an_unknown_key_is_reported_by_name(tmp_path, caplog):
    """`extra="ignore"` means a typo'd or obsolete key is silently dropped, and the operator finds
    out from a client's silence. It is not made fatal — a worker that will not boot because of one
    stale key is a worse outage than the one it prevents — but it is never quiet."""
    import yaml

    from openfactory.registry import ProjectRegistry

    live = tmp_path / "r.yaml"
    live.write_text(yaml.safe_dump({"projects": {"demo": {
        "name": "demo", "repo_path": "/tmp/x", "tracker": {"kind": "github", "repo": "a/b"},
        "slack_chanel": "C123"}}}))
    with caplog.at_level("WARNING", logger="openfactory.registry"):
        ProjectRegistry(live).list()
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "slack_chanel" in msg and "demo" in msg


def test_a_deprecated_key_is_reported_as_deprecated(tmp_path, caplog):
    import yaml

    from openfactory.registry import ProjectRegistry

    live = tmp_path / "r.yaml"
    live.write_text(yaml.safe_dump({"projects": {"demo": {
        "name": "demo", "repo_path": "/tmp/x", "tracker": {"kind": "github", "repo": "a/b"},
        "slack_channel": "C123"}}}))
    with caplog.at_level("INFO", logger="openfactory.registry"):
        ProjectRegistry(live).list()
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "slack_channel" in msg and "channel_id" in msg


# ── the other leaks ─────────────────────────────────────────────────────────────────────────────

def test_an_unset_kind_is_refused_where_it_MATTERS():
    """A wrong provider does not fail like a missing one (ADR-0022 §1) — but the gate belongs one
    layer down from the model.

    Removing `ProviderRef.kind`'s default was tried and reverted: `Project.tracker` has a
    `default_factory`, so it breaks 320 tests, and three hundred mechanical edits is three hundred
    chances to quietly change what a test asserts. It would also buy nothing. What has to be
    impossible is a DEPLOYMENT silently getting the wrong client, and that is refused here."""
    from openfactory.adapters.forge.registry import build_forge
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.contracts.project import Project, ProviderRef

    blank = Project(name="x", repo_path="/t", tracker=ProviderRef(kind="", repo="a/b"),
                    forge=ProviderRef(kind="", repo="a/b"))
    with pytest.raises(ValueError, match="unknown tracker"):
        build_tracker(blank)
    with pytest.raises(ValueError, match="unknown forge"):
        build_forge(blank)


def test_an_explicit_kind_is_still_fine():
    from openfactory.contracts.project import ProviderRef

    assert ProviderRef(kind="jira").kind == "jira"


def test_the_registries_no_longer_default_to_github_either():
    """Removing the model default does not remove the GitHub default: both provider registries
    ended in `or DEFAULT_KIND == "github"`, so `kind: ""` still resolved to GitHub *after* the
    model change — and the AST guard stayed green because those files are provider registries,
    correctly outside its scope. Both had to land together or the claim would be false."""
    from openfactory.adapters.forge import registry as forge_reg
    from openfactory.adapters.tracker import registry as tracker_reg

    assert getattr(forge_reg, "DEFAULT_KIND", None) is None
    assert getattr(tracker_reg, "DEFAULT_KIND", None) is None


def test_the_kernel_no_longer_exports_provider_renderers():
    import openfactory.contracts as kernel

    assert not [n for n in kernel.__all__ if "github" in n or "slack" in n]


def test_the_renderers_still_exist_somewhere_neutral():
    """Moved, not deleted — `activities.py` renders a HandOff onto a ticket and into a channel."""
    from openfactory.contracts.decision import handoff_to_markdown, handoff_to_plain

    assert callable(handoff_to_markdown) and callable(handoff_to_plain)


def test_the_kernel_reads_no_environment():
    """`contracts/bot.py` read `os.environ` — a domain model reaching for process state. A vendor
    NAME guard would never catch it, so it gets its own rule."""
    offenders = []
    for path in _kernel_files():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv")):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, "the kernel must be handed its configuration:\n  " + "\n  ".join(offenders)
