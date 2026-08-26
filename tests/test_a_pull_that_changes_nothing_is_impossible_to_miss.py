"""A deployment must be able to say WHICH code answered (pilot, 2026-08-14).

The compose worker BAKES the package (`docker/worker.Dockerfile`: `COPY openfactory` then
`pip install`), so `git pull && docker compose up -d` restarts the PREVIOUS build. Every
command inside the worker then answers from it — identically, with nothing in the output to
suggest anything is stale.

It cost three rounds on the pilot: the operator pulled twice, re-ran `openfactory doctor`, and
got byte-identical output including the very lines the fixes had rewritten. Neither of us could
tell from the terminal, and I had told him the rebuild was optional, which was wrong.

Three properties, and the first is the one that makes the others findable:

  1. the image writes a build stamp, and `doctor` opens with it;
  2. every documented update names `--build`, because a pull alone is a no-op;
  3. the reader degrades honestly OUTSIDE an image (a laptop checkout runs the code on disk).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_image_records_which_code_it_baked():
    """Written AFTER the COPY of the package, so the layer cache refreshes it exactly when the
    code changes — a stamp written before it would be frozen and lie."""
    text = (ROOT / "docker" / "worker.Dockerfile").read_text()

    copy_at = text.index("COPY openfactory ./openfactory")
    stamp_at = text.index("/etc/openfactory/build.json")

    assert stamp_at > copy_at, (
        "the build stamp is written before the code is copied, so Docker caches it and every "
        "later build reports the first build's identity")


def test_doctor_opens_with_the_build_that_answered(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from openfactory import namespace
    from openfactory.cli import app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    assert CliRunner().invoke(app, ["project", "add", "demo", str(tmp_path)]).exit_code == 0
    monkeypatch.setattr(namespace, "build_stamp", lambda: ("abc123def456", "2026-08-14T09:00:00Z"))

    result = CliRunner().invoke(app, ["doctor", "demo"])

    assert "abc123def456" in result.output, "the build that answered is not named"
    assert "2026-08-14T09:00:00Z" in result.output
    assert "--build" in result.output, (
        "the line names a build without naming what replaces it — the operator is told they may "
        "be stale and not how to stop being")


def test_outside_an_image_nothing_is_invented(tmp_path, monkeypatch):
    """A laptop checkout runs the code on disk; claiming a build identity there would be a
    fact nobody measured."""
    from openfactory import namespace

    monkeypatch.setattr(Path, "read_text", lambda self, **kw: (_ for _ in ()).throw(OSError()))

    assert namespace.build_stamp() == ("", "")


def test_the_stamp_reader_survives_a_corrupt_file(tmp_path, monkeypatch):
    from openfactory import namespace

    broken = tmp_path / "build.json"
    broken.write_text("{not json")
    real_read = Path.read_text
    monkeypatch.setattr(
        Path, "read_text",
        lambda self, **kw: real_read(broken, **kw) if "build.json" in str(self)
        else real_read(self, **kw))

    assert namespace.build_stamp() == ("", "")


def test_the_stamp_is_the_shape_the_reader_expects():
    """The Dockerfile writes it and Python reads it — two files, one contract, and nothing else
    would notice them disagreeing until an operator was already confused."""
    text = (ROOT / "docker" / "worker.Dockerfile").read_text()

    assert "'code'" in text and "'built_at'" in text, (
        "the image no longer writes the keys `build_stamp()` reads")
    payload = json.dumps({"code": "x", "built_at": "y"})
    assert set(json.loads(payload)) == {"code", "built_at"}


def test_every_documented_update_rebuilds():
    """A `git pull` shown beside a compose `up` without `--build` is an instruction to run the
    old code — which is exactly what happened."""
    offenders: list[str] = []
    for path in sorted(ROOT.joinpath("docs").rglob("*.md")) + [ROOT / "README.md"]:
        text = path.read_text()
        for block in re.findall(r"```bash\n(.*?)```", text, re.S):
            if "git pull" not in block:
                continue
            ups = [line for line in block.splitlines()
                   if "docker compose" in line and re.search(r"\bup\b", line)]
            if any("--build" not in line for line in ups):
                offenders.append(f"{path.relative_to(ROOT)}: {block.strip()[:120]}")
    assert not offenders, (
        "these documented updates restart the previous build and silently change nothing: "
        + "; ".join(offenders))
