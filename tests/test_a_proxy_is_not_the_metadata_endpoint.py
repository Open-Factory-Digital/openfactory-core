"""The doctor's `box_identity` line says a box reaches the metadata endpoint only when the endpoint
answered as itself (#376).

WHAT IT DID: `metadata_reached` counted any HTTP status line as the endpoint answering. On a laptop
running Docker Desktop, which is not a cloud VM and has no endpoint, it answered `(True, …)`. The
status line was Docker Desktop's proxy refusing:

    HTTP/1.0 403 connecting to 169.254.169.254:80: … dial tcp 169.254.169.254:80: connectex:
    A socket operation was attempted to an unreachable network.

So a deployment that declared `identity: workload` was told that agent code could mint its token,
and given an `iptables` rule it did not need. Reached now means the service's own answer to a
request that carries no metadata header, so nothing is minted.

The decision is tested on the texts themselves. The probe is then run against a real daemon three
ways: a service that answers as Azure's does (the positive a fix could lose), a server that answers
as that proxy did, and an address where nothing listens.
"""

from __future__ import annotations

import shutil
import subprocess
import time

import pytest

from openfactory.adapters.sandbox import container
from openfactory.adapters.sandbox.container import _answered_as_metadata, metadata_reached

#: What Docker Desktop's proxy answered, byte for byte, measured 2026-09-28.
DOCKER_DESKTOP_REFUSAL = (
    "HTTP/1.0 403 connecting to 169.254.169.254:80: connecting to 169.254.169.254:80: dial tcp "
    "169.254.169.254:80: connectex: A socket operation was attempted to an unreachable network.\n"
    "Connection: close\n\n"
    "connecting to 169.254.169.254:80: connecting to 169.254.169.254:80: dial tcp "
    "169.254.169.254:80: connectex: A socket operation was attempted to an unreachable network.")

#: Each service's answer to a request with no metadata header, as each documents it.
AZURE = ('HTTP/1.1 400 Bad Request\nContent-Type: application/json; charset=utf-8\n\n'
         '{"error":"Bad request. Required metadata header not specified"}')
GCP = ("HTTP/1.1 403 Forbidden\nMetadata-Flavor: Google\n\n"
       "Missing required header: Metadata-Flavor: Google")
AWS_V1 = "HTTP/1.1 200 OK\n\nami-id\nami-launch-index\nhostname\n"
AWS_V2_ONLY = "HTTP/1.1 401 Unauthorized\nContent-Length: 0\n\n"

PATHS = [path for path, _ in container._METADATA_ANSWERS]


def _probe_output(answers: dict[str, str], *, ended: bool = True) -> str:
    """What the probe script prints: each path's marker, then whatever came back on it."""
    out = "".join(f"@@probe {p}\n{answers.get(p, '')}\n" for p in PATHS)
    return out + ("@@end\n" if ended else "")


# ── the decision ───────────────────────────────────────────────────────────────────────────────

def test_a_proxys_refusal_on_every_path_is_not_the_endpoint():
    """THE DEFECT: the refusal is an HTTP status line, and that was enough."""
    assert _answered_as_metadata(_probe_output({p: DOCKER_DESKTOP_REFUSAL for p in PATHS})) is False


@pytest.mark.parametrize("path, answer", [
    (PATHS[0], AZURE), (PATHS[1], GCP), (PATHS[2], AWS_V1), (PATHS[2], AWS_V2_ONLY),
], ids=["azure", "gcp", "aws-v1", "aws-v2-only"])
def test_each_services_own_answer_is_the_endpoint(path, answer):
    """The positive the fix must not lose: a box that can reach a real endpoint is still red."""
    others = {p: DOCKER_DESKTOP_REFUSAL for p in PATHS if p != path}
    assert _answered_as_metadata(_probe_output({path: answer, **others})) is True


def test_a_services_words_on_another_services_path_do_not_count():
    """Words are read on their own path only. A page that happens to say `ami-id` in answer to
    the Azure request is not the Azure endpoint."""
    assert _answered_as_metadata(_probe_output({PATHS[0]: "HTTP/1.1 200 OK\n\nami-id"})) is False


def test_nothing_answering_is_not_reached():
    said = "nc: can't connect to remote host (169.254.169.254): No route to host"
    assert _answered_as_metadata(_probe_output({p: said for p in PATHS})) is False


def test_a_probe_that_did_not_run_to_its_end_is_unknown_never_false():
    """Unknown is never reported as safe: the doctor says it could not measure."""
    assert _answered_as_metadata(_probe_output({}, ended=False)) is None


# ── the probe, against a real daemon ──────────────────────────────────────────────────────────

def _docker() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


needs_docker = pytest.mark.skipif(not _docker(), reason="needs a Docker daemon")


@pytest.fixture
def served(request):
    """A network of its own and a server on it answering `request.param` to every connection.
    Yields `(network, address)`."""
    from openfactory.adapters.preview.compose import UTILITY_IMAGE

    tag = f"of-376-{int(time.time() * 1000) % 10**9}"
    subprocess.run(["docker", "network", "create", tag], check=True, capture_output=True)
    try:
        body = request.param.replace("\n", "\\r\\n").replace('"', '\\"')
        subprocess.run(["docker", "run", "-d", "--rm", "--name", tag, "--network", tag,
                        UTILITY_IMAGE, "sh", "-c",
                        f'while true; do printf "{body}" | nc -l -p 80 >/dev/null; done'],
                       check=True, capture_output=True)
        address = subprocess.run(
            ["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
             tag], check=True, capture_output=True, text=True).stdout.strip()
        time.sleep(1)
        yield tag, address
    finally:
        subprocess.run(["docker", "rm", "-f", tag], capture_output=True)
        subprocess.run(["docker", "network", "rm", tag], capture_output=True)


@needs_docker
@pytest.mark.parametrize("served", [AZURE], indirect=True, ids=["azure-like"])
def test_a_service_answering_as_azures_is_reached(served):
    network, address = served
    reached, subnet = metadata_reached(network, address=address)
    assert reached is True and subnet, (reached, subnet)


@needs_docker
@pytest.mark.parametrize("served", [DOCKER_DESKTOP_REFUSAL], indirect=True, ids=["proxy-refusal"])
def test_a_server_answering_as_that_proxy_did_is_not_reached(served):
    network, address = served
    reached, _ = metadata_reached(network, address=address)
    assert reached is False


@needs_docker
@pytest.mark.parametrize("served", [AZURE], indirect=True, ids=["beside-a-service"])
def test_an_address_where_nothing_listens_is_not_reached(served):
    network, address = served
    silent = address.rsplit(".", 1)[0] + ".250"
    reached, _ = metadata_reached(network, address=silent)
    assert reached is False


def test_the_probe_asks_with_no_metadata_header_so_it_can_mint_nothing(monkeypatch):
    """With `Metadata: true` (Azure) or `Metadata-Flavor: Google`, a request to the token path
    returns the identity's token: the diagnostic would mint the credential it is guarding. The
    request carries neither, which is also what makes the service refuse in its own words."""
    ran: list[list[str]] = []

    def host(cmd, timeout=120):
        ran.append(cmd)
        return 0, _probe_output({p: DOCKER_DESKTOP_REFUSAL for p in PATHS})

    monkeypatch.setattr(container, "_host", host)

    metadata_reached("bridge")

    script = ran[0][-1]
    assert "GET %s HTTP/1.0" in script and "Host: " in script
    assert "Metadata" not in script.split("GET %s", 1)[1].split('"', 1)[0], script
    assert "token" not in script, "the probe asks a token path"
