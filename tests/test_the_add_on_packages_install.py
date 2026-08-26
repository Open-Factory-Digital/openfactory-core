"""The public core plus the two add-on packages, installed the way a stranger installs them.

Every other guard of the cut runs in THIS interpreter, with the leaving modules still in the tree
and the packages' rows served by a patched metadata reader. That proves the registries and the
declarations; it says nothing about the artefacts — a wheel built from the public tree, a wheel
built from `addons/<package>`, `pip install` of both into an environment that has neither. So
this file does exactly that, once, in a scratch virtual environment:

  1. the PUBLIC tree's core — `openfactory/` minus the paths `docs/STATUS.md` excludes — built into
     a wheel and installed: the chat modules and the cloud modules are absent; `channel: slack`
     and `remote_box("fargate")` are refused BY NAME, each naming the package to install;
  2. `openfactory-aws` installed from `addons/`: `plugins.known("box")` lists `fargate`, its
     runner resolves through `remote_box`, the metrics sink, the session store and the token-pool
     source resolve through their registries;
  3. `openfactory-slack` installed from `addons/`: `build_channel` builds the chat adapter, the
     notifier builds the chat notifier, the declared Telegram fallback builds, the console entry
     exists, and `openfactory conformance-adapter channel` passes the adapter.

SKIPPED BY NAME, AT RUN TIME, where it cannot run: no `addons/` (the public tree), no route to the
package index (pip has to resolve the core's dependencies), or a venv that cannot be created.
Never at collection — a suite that cannot be collected reports nothing.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import textwrap
import venv

import add_ons
import pytest
from vendor_addons import packages, require

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: What a scratch box needs to build the cloud runner without a cloud: the launcher raises by
#: name on a missing coordinate, so the probe supplies each one with a placeholder.
CLOUD_COORDINATES = {
    "OPENFACTORY_FARGATE_CLUSTER": "probe", "OPENFACTORY_FARGATE_SUBNETS": "subnet-probe",
    "OPENFACTORY_FARGATE_SG": "sg-probe", "OPENFACTORY_FARGATE_TASKDEF": "probe:1",
    "OPENFACTORY_FARGATE_LOG_GROUP": "/probe", "AWS_DEFAULT_REGION": "eu-west-2",
    "AWS_ACCESS_KEY_ID": "probe", "AWS_SECRET_ACCESS_KEY": "probe",
}

PROBE = textwrap.dedent('''
    import importlib.util, json, logging, os
    from openfactory import plugins
    from openfactory.adapters.channel.registry import build_channel
    from openfactory.adapters.notify.registry import build_notifier
    from openfactory.adapters.sandbox.registry import BOXES, installed_box_traits, remote_box
    from openfactory.contracts.project import Project

    logging.disable(logging.CRITICAL)
    facts = {}

    def refusal(fn, *args, **kw):
        try:
            return {"built": type(fn(*args, **kw)).__name__}
        except Exception as exc:  # the refusal IS the answer
            return {"refused": f"{type(exc).__name__}: {exc}"}

    facts["chat_module_present"] = importlib.util.find_spec("openfactory.runtime.slack") is not None
    facts["cloud_module_present"] = importlib.util.find_spec("openfactory.runtime.fargate") is not None
    facts["channel_slack"] = refusal(build_channel, Project(name="p", repo_path="/tmp/p", channel="slack"))
    facts["channel_coordinates"] = refusal(build_channel, Project(name="c", repo_path="/tmp/c", channel_id="C1"))
    facts["known_box"] = plugins.known("box", BOXES)
    facts["fargate_remote"] = installed_box_traits("fargate").remote
    facts["remote_box_fargate"] = refusal(remote_box, "fargate")
    facts["is_remote_box"] = False
    try:
        from openfactory.adapters.sandbox.registry import RemoteBox
        facts["is_remote_box"] = isinstance(remote_box("fargate"), RemoteBox)
    except Exception:
        pass
    from openfactory.observability.registry import build_metrics_sink
    from openfactory.adapters.agent.session_store import build_session_store
    facts["metrics_dynamodb"] = refusal(build_metrics_sink, "dynamodb", table="t", path=None)
    facts["session_store_s3"] = refusal(build_session_store, "s3", bucket="b")
    facts["token_pool_ssm"] = plugins.builder("token_pool", "ssm", builtin={}) is not None
    facts["notifier_slack"] = type(build_notifier(Project(name="s", repo_path="/tmp/s", channel_id="C1"))).__name__
    facts["notifier_fallback"] = type(build_notifier(Project(name="x", repo_path="/tmp/x"))).__name__
    print(json.dumps(facts))
''')


def _network() -> bool:
    try:
        socket.create_connection(("pypi.org", 443), timeout=3).close()
        return True
    except OSError:
        return False


def _run(*cmd: str, env: dict | None = None, cwd: pathlib.Path | None = None) -> str:
    proc = subprocess.run(list(cmd), capture_output=True, text=True, timeout=900,
                          env={**os.environ, **(env or {})}, cwd=cwd)
    assert proc.returncode == 0, f"{' '.join(cmd[:3])} …:\n{proc.stdout[-2000:]}\n{proc.stderr[-3000:]}"
    return proc.stdout


def _public_core(into: pathlib.Path) -> pathlib.Path:
    """The public tree's core, as the build backend reads it: `openfactory/` minus every path
    `docs/STATUS.md` excludes, plus the four files a wheel is built from."""
    excluded = add_ons.excluded_paths()
    src = into / "public"

    def leaves(directory: str, names: list[str]) -> list[str]:
        rel = pathlib.Path(directory).relative_to(into / "public-src").as_posix()
        out = ["__pycache__"]
        for name in names:
            path = f"{rel}/{name}"
            if any(path == p.rstrip("/") or path.startswith(p) for p in excluded):
                out.append(name)
        return out

    staged = into / "public-src" / "openfactory"
    shutil.copytree(ROOT / "openfactory", staged, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(staged, src / "openfactory", ignore=leaves)
    for f in ("pyproject.toml", "LICENSE", "NOTICE", "README.md"):
        shutil.copy2(ROOT / f, src / f)
    for p in excluded:
        if p.startswith("openfactory/"):
            assert not (src / p).exists(), f"{p} survived the export"
    return src


def _probe(py: pathlib.Path, env: dict) -> dict:
    """`cwd` is the scratch directory ON PURPOSE: `python -c` puts the working directory first on
    `sys.path`, and run from the repository root the scratch interpreter imported THIS tree's
    `openfactory/` — chat and cloud modules included — instead of what it had installed
    (measured 2026-08-26: every 'absent' assertion failed in 6 seconds)."""
    return json.loads(_run(str(py), "-c", PROBE, env=env, cwd=py.parents[1]))


@pytest.mark.slow
def test_the_public_core_refuses_by_name_and_the_packages_supply_the_rows(tmp_path):
    require()
    if not _network():
        pytest.skip("no route to pypi.org — pip cannot resolve the core's dependencies here")
    core_src = _public_core(tmp_path)
    dist = tmp_path / "dist"
    pip = [sys.executable, "-m", "pip", "--disable-pip-version-check", "-q"]
    _run(*pip, "wheel", "--no-cache-dir", "--no-deps", "-w", str(dist), str(core_src))
    core_wheel = next(dist.glob("openfactory-*.whl"))

    try:
        venv.EnvBuilder(with_pip=True, clear=True).create(tmp_path / "venv")
    except Exception as exc:  # noqa: BLE001 — a box that cannot make a venv cannot run this
        pytest.skip(f"cannot create a scratch venv here: {exc}")
    py = tmp_path / "venv" / "bin" / "python"
    vpip = [str(py), "-m", "pip", "--disable-pip-version-check", "-q"]
    _run(*vpip, "install", str(core_wheel))
    env = {**CLOUD_COORDINATES, "SLACK_BOT_TOKEN": "xoxb-probe", "OPENFACTORY_NOTIFIER_FALLBACK": "telegram",
           "OPENFACTORY_TELEGRAM_BOT_TOKEN": "t", "OPENFACTORY_TELEGRAM_CHAT_ID": "c"}

    # 1. the public core alone
    bare = _probe(py, env)
    assert not bare["chat_module_present"] and not bare["cloud_module_present"], bare
    # The clause each refusal must carry is `install_hint`'s own answer, asked here rather than
    # spelled: the remedy's wording lives in one place and this guard follows it there.
    from openfactory import plugins

    for key in ("channel_slack", "channel_coordinates"):
        message = bare[key].get("refused", "")
        assert "'slack'" in message, (key, bare[key])
        assert plugins.install_hint("channel", "slack") in message, (key, bare[key])
        assert "ModuleNotFoundError" not in message, (key, bare[key])
    assert "fargate" in bare["known_box"] and bare["fargate_remote"] is True
    for key, axis, kind in (("remote_box_fargate", "box_runner", "fargate"),
                            ("metrics_dynamodb", "metrics", "dynamodb"),
                            ("session_store_s3", "session_store", "s3")):
        assert plugins.install_hint(axis, kind) in bare[key].get("refused", ""), (key, bare)
    assert bare["token_pool_ssm"] is False
    assert bare["notifier_slack"] == "PanelNotifier" and bare["notifier_fallback"] == "PanelNotifier"

    # 2. the cloud package
    _run(*vpip, "install", "--no-cache-dir", str(packages()["openfactory-aws"]))
    cloud = _probe(py, env)
    assert cloud["cloud_module_present"] and not cloud["chat_module_present"]
    assert "fargate" in cloud["known_box"]
    assert cloud["remote_box_fargate"] == {"built": "FargateLauncher"}, cloud["remote_box_fargate"]
    assert cloud["is_remote_box"] is True
    assert cloud["metrics_dynamodb"] == {"built": "DynamoMetricsSink"}, cloud["metrics_dynamodb"]
    assert cloud["session_store_s3"] == {"built": "S3SessionStore"}, cloud["session_store_s3"]
    assert cloud["token_pool_ssm"] is True
    assert plugins.install_hint("channel", "slack") in cloud["channel_slack"].get("refused", ""), cloud

    # 3. the chat package
    _run(*vpip, "install", "--no-cache-dir", str(packages()["openfactory-slack"]))
    chat = _probe(py, env)
    assert chat["chat_module_present"]
    assert chat["channel_slack"] == {"built": "SlackChannel"} == chat["channel_coordinates"], chat
    assert chat["notifier_slack"] == "SlackNotifier", chat
    assert chat["notifier_fallback"] == "TelegramNotifier", chat
    assert (tmp_path / "venv" / "bin" / "openfactory-slack").exists(), "the console entry was not installed"
    conformance = subprocess.run(
        [str(tmp_path / "venv" / "bin" / "openfactory"), "conformance-adapter", "channel",
         "openfactory.adapters.channel.slack:SlackChannel"],
        capture_output=True, text=True, timeout=300, env={**os.environ, **env}, cwd=tmp_path)
    assert conformance.returncode == 0, conformance.stdout + conformance.stderr
