"""#738: the CLI image did not build when `docker/extra-ca/` held a certificate, the one case its
extra-CA block exists for.

The block appended the extra root to `certifi`'s bundle and pointed `/etc/pip.conf` at it, asking
`python -c 'import certifi; print(certifi.where())'` where that bundle lives. At that line the image
is a bare `python:3.12-slim`, and it has no `certifi`:

    $ docker run --rm python:3.12-slim python -c 'import certifi'
    ModuleNotFoundError: No module named 'certifi'

so `cat … >> ""` failed, `set -eu` stopped the layer, and the build ended on `exit code: 2`. With
no certificate the branch never runs, which is the release workflow and every public build: the
block shipped in v0.4.0, v0.5.0 and both 0.6.0 candidates without anybody running it. It was found
rehearsing the upgrade to v0.6.0-rc.2 on a machine behind TLS interception (#650).

NOTHING EVER RAN IT WITH A CERTIFICATE. The guard of #122
(`test_the_extra_ca_file_is_always_a_valid_pem.py`) executes the other images' blocks under the
host's `sh`, and leaves this one out on purpose, because this image sets no `NODE_EXTRA_CA_CERTS`.

WHY IN THE IMAGE'S OWN BASE FIRST. The defect was a fact about the base image, what its Python can
import, and a sandbox on the host answers with the host's Python. So the first tests run the real
block inside the image this Dockerfile builds `FROM`, and then ask `pip config` what pip will
trust: the thing, not text about it. The sandbox tests after them need no daemon. Their `python`
answers `certifi` the way the base image does, so a machine without Docker still catches the shape.
"""

from __future__ import annotations

import functools
import pathlib
import re
import shutil
import subprocess

import pytest

from tests.test_the_extra_ca_file_is_always_a_valid_pem import _blocks

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLI = ROOT / "docker/cli.Dockerfile"

#: A throwaway root. The block concatenates files and never parses one, so a PEM's frame is enough;
#: the body is base64 for "openfactory-738", a string no system bundle holds.
_EXTRA = "-----BEGIN CERTIFICATE-----\nb3BlbmZhY3RvcnktNzM4\n-----END CERTIFICATE-----\n"
_MARK = "b3BlbmZhY3RvcnktNzM4"


def _the_block() -> str:
    blocks = _blocks(CLI.read_text())
    assert len(blocks) == 1, f"cli.Dockerfile has {len(blocks)} extra-CA blocks; this guard reads one"
    return blocks[0]


def _base_image() -> str:
    """The image the block runs in: the last `FROM` above it, read from the file, not restated."""
    text = CLI.read_text()
    above = text[: text.index("COPY docker/extra-ca/")]
    return re.findall(r"^FROM\s+(\S+)", above, flags=re.MULTILINE)[-1]


# ── in the image's own base ───────────────────────────────────────────────────────────────────────

def _docker() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


needs_docker = pytest.mark.skipif(not _docker(), reason="needs a Docker daemon")

#: What the build does at that layer, then what pip makes of it. `COPY docker/extra-ca/` is the
#: printf; the block runs as the `RUN` would, under `sh -c`; `pip config list` is pip reading
#: `/etc/pip.conf` itself, merged the way an install merges it (`pip config get` reads the USER
#: file alone, and answers "No such key" for a key `/etc/pip.conf` sets — measured). The system
#: bundle is copied aside first so "the roots are kept" is a comparison of bytes and not a count.
_IN_THE_IMAGE = r"""
cp /etc/ssl/certs/ca-certificates.crt /tmp/system-before.crt
mkdir -p /tmp/extra-ca
if [ -n "${EXTRA:-}" ]; then printf '%s' "$EXTRA" > /tmp/extra-ca/throwaway.crt; fi
sh -c "$BLOCK"
echo "BLOCK_EXIT=$?"
if [ -e /etc/pip.conf ]; then echo "PIP_CONF=present"; else echo "PIP_CONF=absent"; fi
cert=$(python -m pip config list 2>/dev/null | sed -n "s/^global\.cert='\(.*\)'$/\1/p")
echo "PIP_CERT=$cert"
python - "$cert" <<'EOF'
import sys
before = open("/tmp/system-before.crt").read()
now = open("/etc/ssl/certs/ca-certificates.crt").read()
print("SYSTEM_UNCHANGED=" + ("yes" if now == before else "no"))
named = sys.argv[1]
if named:
    try:
        bundle = open(named).read()
    except OSError:
        bundle = ""
    print("EXTRA_TRUSTED=" + ("yes" if "b3BlbmZhY3RvcnktNzM4" in bundle else "no"))
    print("SYSTEM_KEPT=" + ("yes" if before.strip() and before in bundle else "no"))
EOF
"""


@functools.cache
def _in_the_image(with_extra: bool) -> dict[str, str]:
    env = ["-e", f"BLOCK={_the_block()}"] + (["-e", f"EXTRA={_EXTRA}"] if with_extra else [])
    done = subprocess.run(
        ["docker", "run", "--rm", *env, _base_image(), "sh", "-c", _IN_THE_IMAGE],
        capture_output=True, text=True, timeout=600,
    )
    assert done.returncode == 0, f"the probe itself failed:\n{done.stdout}\n{done.stderr[-2000:]}"
    report = dict(line.split("=", 1) for line in done.stdout.splitlines() if "=" in line)
    report["_stderr"] = done.stderr[-2000:]
    return report


@needs_docker
def test_with_a_certificate_the_block_succeeds_in_the_image_it_runs_in():
    """THE DEFECT. Before #738 this was `BLOCK_EXIT=2`, the layer that stopped the build."""
    got = _in_the_image(True)

    assert got["BLOCK_EXIT"] == "0", (
        f"the extra-CA block fails in {_base_image()} when a certificate is given, so the CLI "
        f"image cannot be built behind TLS interception:\n{got['_stderr']}"
    )


@needs_docker
def test_pip_trusts_a_bundle_that_holds_the_extra_root_and_the_system_roots():
    """What the block is FOR: the `pip install` below it, through a proxy that re-signs every
    certificate with the extra root. Both halves, because a bundle holding the extra root alone
    loses every site the proxy does not intercept."""
    got = _in_the_image(True)

    assert got.get("PIP_CERT"), "pip has no `global.cert`: it would not trust the extra root"
    assert got.get("EXTRA_TRUSTED") == "yes", (
        f"the bundle pip names ({got['PIP_CERT']}) does not hold the supplied certificate"
    )
    assert got.get("SYSTEM_KEPT") == "yes", (
        f"the bundle pip names ({got['PIP_CERT']}) lost the system roots the image shipped"
    )


@needs_docker
def test_with_no_certificate_the_block_writes_nothing_and_changes_nothing():
    """The public build, every release: the block is a no-op, and pip keeps its own defaults."""
    got = _in_the_image(False)

    assert got["BLOCK_EXIT"] == "0", got["_stderr"]
    assert got["PIP_CONF"] == "absent", "a pip.conf was written although no certificate was given"
    assert got["SYSTEM_UNCHANGED"] == "yes", "the system bundle changed with no certificate given"


# ── the same block in a sandbox, for a machine with no daemon ────────────────────────────────────

#: `python:3.12-slim`'s interpreter as far as this block may ask it: everything the host's has,
#: except `certifi`, which the base image does not carry (the measurement in the docstring).
_BASE_PYTHON = """#!/bin/sh
case "$*" in *certifi*) echo "ModuleNotFoundError: No module named 'certifi'" >&2; exit 1;; esac
exec python3 "$@"
"""


def _in_a_sandbox(tmp_path: pathlib.Path, *, with_extra: bool):
    root = tmp_path / "root"
    (root / "etc/ssl/certs").mkdir(parents=True)
    (root / "tmp/extra-ca").mkdir(parents=True)
    system = root / "etc/ssl/certs/ca-certificates.crt"
    system.write_text("-----BEGIN CERTIFICATE-----\nc3lzdGVt\n-----END CERTIFICATE-----\n")
    if with_extra:
        (root / "tmp/extra-ca/throwaway.crt").write_text(_EXTRA)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "python").write_text(_BASE_PYTHON)
    (binaries / "python").chmod(0o755)

    rebased = (_the_block()
               .replace("/usr/local/share/openfactory", f"{root}/usr/local/share/openfactory")
               .replace("/etc/ssl/certs", f"{root}/etc/ssl/certs")
               .replace("/etc/pip.conf", f"{root}/etc/pip.conf")
               .replace("/tmp/extra-ca", f"{root}/tmp/extra-ca"))
    done = subprocess.run(["sh", "-c", rebased], capture_output=True, text=True,
                          env={"PATH": f"{binaries}:/usr/bin:/bin", "HOME": str(tmp_path)})
    return done, root, system


def test_in_a_sandbox_a_certificate_reaches_the_bundle_pip_is_told_to_trust(tmp_path):
    done, root, system = _in_a_sandbox(tmp_path, with_extra=True)

    assert done.returncode == 0, f"the block failed with a certificate given:\n{done.stderr}"
    conf = root / "etc/pip.conf"
    assert conf.exists(), "no pip.conf was written, so pip would not trust the extra root"
    named = re.search(r"^cert\s*=\s*(\S+)\s*$", conf.read_text(), flags=re.MULTILINE)
    assert named, f"pip.conf names no cert:\n{conf.read_text()}"
    bundle = pathlib.Path(named.group(1)).read_text()
    assert _MARK in bundle, "the bundle pip.conf names does not hold the supplied certificate"
    assert "c3lzdGVt" in bundle, "the bundle pip.conf names lost the system roots"


def test_in_a_sandbox_no_certificate_writes_no_pip_conf(tmp_path):
    done, root, system = _in_a_sandbox(tmp_path, with_extra=False)

    assert done.returncode == 0, done.stderr
    assert not (root / "etc/pip.conf").exists(), "pip.conf written with no certificate given"
    assert system.read_text().count("BEGIN CERTIFICATE") == 1, "the system bundle changed"


def test_the_base_this_guard_runs_the_block_in_is_the_one_the_dockerfile_names():
    """Read, so a new base in the Dockerfile moves this guard with it instead of leaving it
    proving the old one."""
    assert _base_image().startswith("python:"), _base_image()
