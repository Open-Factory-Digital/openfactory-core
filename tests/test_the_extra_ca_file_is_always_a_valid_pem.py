"""#122: `NODE_EXTRA_CA_CERTS` points at a file, so that file must always be one.

The images set `ENV NODE_EXTRA_CA_CERTS=/usr/local/share/openfactory/extra-ca.crt` unconditionally,
and the block above it used to create that file EMPTY whenever `docker/extra-ca/` held no
certificate — which is the public build, every time. The comment called it a no-op, on this
measurement:

    node warns on a MISSING extra-certs file on every invocation and says nothing about an
    empty one (measured, both)

True of `node`. The HARNESS ships its own runtime, linked against BoringSSL, and that one refuses
an empty PEM outright — so on the published v0.2.0 images every agent call died with

    warn: ignoring extra certs from …/extra-ca.crt, load failed: error:10000009:SSL routines:
          OPENSSL_internal:PEM routines
    API Error: Unable to connect to API (FailedToOpenSocket)

behind a warning that said it was merely *ignoring* the file. Everything above the agent stayed
green: `doctor` 13/13, `box prove` PROVEN, the poller running — and no ticket could have run.

WHY THIS GUARD EXECUTES THE BLOCK. A guard that read the Dockerfile would have been satisfied by
the very comment asserting the no-op, which is the failure CONTRIBUTING names ("a guard reads the
THING, not text about the thing"). So this extracts the real `RUN` script, runs it under `sh` with
the paths rebased into a sandbox, and reads the file it produced. It needs no Docker: the block is
shell, and shell is runnable.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Every image whose ENV names the file. `cli.Dockerfile` deliberately does NOT set the variable —
#: it only writes pip's config — so it is not in this list and must not be added without its ENV.
DOCKERFILES = ("docker/base-python.Dockerfile", "docker/worker.Dockerfile")

_ENV = re.compile(r"^ENV NODE_EXTRA_CA_CERTS=(\S+)\s*$", re.MULTILINE)


def _blocks(text: str) -> list[str]:
    """Every `RUN` script in the file that writes the extra-ca file, un-continued into one line."""
    out: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("RUN "):
            body = [lines[i][4:]]
            while body[-1].rstrip().endswith("\\"):
                i += 1
                body.append(lines[i])
            # A SPACE, NOT A NEWLINE. `\<newline>` collapses to nothing in sh, so re-joining with
            # a newline turns `foo && \` into a statement ending in `&&` — a syntax error that
            # looks like the block's fault rather than the reader's.
            script = " ".join(b.strip().removesuffix("\\") for b in body)
            if "extra-ca.crt" in script:
                out.append(script)
        i += 1
    return out


def _run_in_sandbox(script: str, tmp_path: pathlib.Path, *, with_extra_cert: bool) -> pathlib.Path:
    """Execute the real block with its absolute paths rebased under `tmp_path`."""
    root = tmp_path / "root"
    (root / "etc/ssl/certs").mkdir(parents=True)
    (root / "usr/local/share/ca-certificates").mkdir(parents=True)
    (root / "tmp/extra-ca").mkdir(parents=True)
    # The system store the image already trusts. Content, not shape, is what the block copies.
    (root / "etc/ssl/certs/ca-certificates.crt").write_text(
        "-----BEGIN CERTIFICATE-----\nc3lzdGVt\n-----END CERTIFICATE-----\n")
    if with_extra_cert:
        (root / "tmp/extra-ca/corp.crt").write_text(
            "-----BEGIN CERTIFICATE-----\nY29ycA==\n-----END CERTIFICATE-----\n")

    # Stubs for the two commands the block may reach for. They must SUCCEED silently: whether the
    # image installs ca-certificates is not this guard's question.
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for name in ("apt-get", "update-ca-certificates"):
        stub = binaries / name
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)

    rebased = (script.replace("/usr/local/share/openfactory", f"{root}/usr/local/share/openfactory")
                     .replace("/usr/local/share/ca-certificates", f"{root}/usr/local/share/ca-certificates")
                     .replace("/etc/ssl/certs", f"{root}/etc/ssl/certs")
                     .replace("/etc/pip.conf", f"{root}/etc/pip.conf")
                     .replace("/tmp/extra-ca", f"{root}/tmp/extra-ca")
                     .replace("/var/lib/apt/lists/*", f"{root}/var-lib-apt"))
    (root / "etc").mkdir(exist_ok=True)
    proc = subprocess.run(["sh", "-c", rebased], capture_output=True, text=True,
                          env={"PATH": f"{binaries}:/usr/bin:/bin", "HOME": str(tmp_path)})
    assert proc.returncode == 0, f"the block itself failed:\n{proc.stdout}\n{proc.stderr}"
    return root / "usr/local/share/openfactory/extra-ca.crt"


@pytest.mark.parametrize("dockerfile", DOCKERFILES)
def test_the_env_names_a_file_every_block_in_that_file_writes(dockerfile):
    """The two halves have to agree, and they are forty lines apart in the same file."""
    text = (ROOT / dockerfile).read_text()
    named = _ENV.findall(text)

    assert named, f"{dockerfile} has no ENV NODE_EXTRA_CA_CERTS — this guard is aimed at nothing"
    assert set(named) == {"/usr/local/share/openfactory/extra-ca.crt"}, named
    assert _blocks(text), f"{dockerfile} sets the variable and no RUN block writes the file"


@pytest.mark.parametrize("dockerfile", DOCKERFILES)
def test_with_no_extra_certificate_the_file_is_still_a_valid_pem(tmp_path, dockerfile):
    """THE DEFECT. `docker/extra-ca/` holds no `.crt` in the public build — every published image
    took this path, and left the file at zero bytes."""
    for n, script in enumerate(_blocks((ROOT / dockerfile).read_text())):
        produced = _run_in_sandbox(script, tmp_path / f"b{n}", with_extra_cert=False)

        assert produced.exists(), f"{dockerfile} block {n}: the file the ENV names was not written"
        body = produced.read_text()
        assert body.strip(), (
            f"{dockerfile} block {n}: extra-ca.crt is EMPTY, and NODE_EXTRA_CA_CERTS points at it "
            f"— the harness runtime refuses an empty PEM and every agent call fails"
        )
        assert "-----BEGIN CERTIFICATE-----" in body, (
            f"{dockerfile} block {n}: the file is not a PEM, so loading it fails the same way"
        )


@pytest.mark.parametrize("dockerfile", DOCKERFILES)
def test_an_extra_certificate_still_reaches_the_file(tmp_path, dockerfile):
    """The reverse, and the reason the mechanism exists at all: a deployment behind an inspecting
    proxy drops its `.crt` in `docker/extra-ca/` and needs it TRUSTED, not merely tolerated."""
    for n, script in enumerate(_blocks((ROOT / dockerfile).read_text())):
        produced = _run_in_sandbox(script, tmp_path / f"b{n}", with_extra_cert=True)

        assert "Y29ycA==" in produced.read_text(), (
            f"{dockerfile} block {n}: the supplied certificate did not reach the file the ENV names"
        )


def test_the_cli_image_sets_no_such_variable(tmp_path):
    """`cli.Dockerfile` writes the same file and deliberately does NOT export it — it configures
    pip alone. If that ever changes it joins DOCKERFILES above, and this guard says so rather than
    letting an image acquire the variable with nobody measuring its file."""
    text = (ROOT / "docker/cli.Dockerfile").read_text()

    assert not _ENV.findall(text), (
        "cli.Dockerfile now sets NODE_EXTRA_CA_CERTS — add it to DOCKERFILES so its file is "
        "measured too"
    )


def test_sh_is_what_this_guard_needs_and_nothing_else():
    """Stated so a reader does not go looking for a Docker requirement that is not there: the
    block is shell, and running it is cheaper and more honest than building an image."""
    assert shutil.which("sh"), "no /bin/sh — this guard cannot run"
