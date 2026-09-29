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
CONTROL = container._CONTROL_PATH

#: Services this build does not know, as the review of #377 listed them: each answers the three
#: paths in its own words, differently from the control.
DIGITALOCEAN_404 = "HTTP/1.1 404 Not Found\nContent-Type: text/plain\n\n404 page not found"
ALIBABA_INDEX = "HTTP/1.1 200 OK\n\ninstance-id\nimage-id\nhostname\n"
#: Azure's refusal as it would read if Microsoft reworded it: no test may rely on today's sentence.
AZURE_REWORDED = ('HTTP/1.1 400 Bad Request\nContent-Type: application/json\n\n'
                  '{"error":"Bad request. The Metadata header is required"}')


def _probe_output(answers: dict[str, str], *, control: str = "", ended: bool = True) -> str:
    """What the probe script prints: each path's marker, then whatever came back on it — the
    three metadata paths, then the control."""
    out = "".join(f"@@probe {p}\n{answers.get(p, '')}\n" for p in PATHS)
    out += f"@@probe {CONTROL}\n{control}\n"
    return out + ("@@end\n" if ended else "")


def _verdict(out: str) -> bool | None:
    return _answered_as_metadata(out)[0]


# ── the decision ───────────────────────────────────────────────────────────────────────────────

def test_a_proxys_refusal_on_every_path_and_the_control_is_not_the_endpoint():
    """THE DEFECT (#376): the proxy's refusal is an HTTP status line, and that was enough. It
    answers the control path the same, and names the address it could not reach (measured)."""
    out = _probe_output({p: DOCKER_DESKTOP_REFUSAL for p in PATHS}, control=DOCKER_DESKTOP_REFUSAL)
    assert _verdict(out) is False


@pytest.mark.parametrize("path, answer", [
    (PATHS[0], AZURE), (PATHS[1], GCP), (PATHS[2], AWS_V1), (PATHS[2], AWS_V2_ONLY),
], ids=["azure", "gcp", "aws-v1", "aws-v2-only"])
def test_each_services_own_answer_is_the_endpoint(path, answer):
    """The positive the fix must not lose: a box that can reach a real endpoint is still red."""
    others = {p: DOCKER_DESKTOP_REFUSAL for p in PATHS if p != path}
    out = _probe_output({path: answer, **others}, control=DOCKER_DESKTOP_REFUSAL)
    assert _verdict(out) is True


@pytest.mark.parametrize("answers, control", [
    ({p: DIGITALOCEAN_404 for p in PATHS}, DIGITALOCEAN_404),
    ({PATHS[2]: ALIBABA_INDEX}, DIGITALOCEAN_404),
    ({PATHS[0]: AZURE_REWORDED}, ""),
    ({PATHS[0]: "HTTP/1.1 200 OK\n\nami-id"}, ""),
], ids=["a-404-everywhere", "an-unknown-index", "azure-reworded", "words-on-the-wrong-path"])
def test_an_answer_nobody_recognises_is_unknown_never_safe(answers, control):
    """REVIEW OF #377: each of these is a box that may reach a live metadata service — one this
    build does not know, or Azure's refusal reworded — and reporting it as `False` is the doctor
    going green because a vendor edited a sentence. A 404 that is the same on every path, the
    control included, is still unknown: it does not name the address it failed to reach, which is
    what a proxy's refusal does."""
    verdict, why = _answered_as_metadata(_probe_output(answers, control=control))
    assert verdict is None and "answered" in why, (verdict, why)


def test_a_proxy_is_only_a_proxy_where_every_path_got_its_refusal():
    """The control proves a proxy only where EVERY metadata path got the answer the control got.
    A proxy that forwards one path to something it CAN reach, which answers in words this build
    does not know, is that something answering: unknown."""
    answers = {p: DOCKER_DESKTOP_REFUSAL for p in PATHS}
    answers[PATHS[0]] = AZURE_REWORDED
    verdict, _ = _answered_as_metadata(_probe_output(answers, control=DOCKER_DESKTOP_REFUSAL))
    assert verdict is None


def test_nothing_answering_is_not_reached():
    said = "nc: can't connect to remote host (169.254.169.254): No route to host"
    assert _verdict(_probe_output({p: said for p in PATHS}, control=said)) is False


def test_a_probe_that_did_not_run_to_its_end_is_unknown_never_false():
    """Unknown is never reported as safe: the doctor says it could not measure."""
    assert _verdict(_probe_output({}, ended=False)) is None


def test_the_doctor_says_an_unplaceable_answer_red_with_the_block_as_its_remedy(monkeypatch):
    """None from an answer is not "docker could not be asked": the remedy is the block, which
    costs nothing if the address is not the metadata endpoint after all."""
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.doctor import probes_for
    from openfactory.runtime.temporal import io

    monkeypatch.setattr(io, "default_sandbox", lambda: "container")
    monkeypatch.setattr(container, "metadata_reached", lambda network: (
        None, "something on 169.254.169.254 answered, in words no metadata service this build "
              "knows uses (`HTTP/1.1 404 Not Found`)"))
    ref = ProviderRef(kind="azure_devops", repo="api",
                      options={"organization": "acme", "project": "Deskline",
                               "identity": "workload"})
    project = Project(name="dsk", repo_path="/tmp/x", tracker=ref, forge=ref)

    ok, message, remedy = probes_for(project).box_identity()

    assert not ok and "cannot place" in message
    assert "DOCKER-USER" in remedy and "169.254.169.254/32" in remedy


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
    """A network of its own and a server on it answering `request.param` to every connection,
    with `{address}` in it replaced by the server's own address — so a proxy-like refusal names
    the address it was asked for, as the real one does. Yields `(network, address)`."""
    from openfactory.adapters.preview.compose import UTILITY_IMAGE

    tag = f"of-376-{int(time.time() * 1000) % 10**9}"
    subprocess.run(["docker", "network", "create", tag], check=True, capture_output=True)
    try:
        subprocess.run(["docker", "run", "-d", "--rm", "--name", tag, "--network", tag,
                        UTILITY_IMAGE, "sh", "-c",
                        # WAITS FOR ITS ANSWER: the address is known only once it runs, and a
                        # first connection served before the file exists would get nothing.
                        "until [ -f /tmp/ready ]; do sleep 0.1; done; "
                        # ONE LISTENER FOR THE WHOLE TEST, NEVER ONE PER CONNECTION (#419). This
                        # was `while true; do nc -l -p 80 …; done`: busybox `nc -l` closes its
                        # listening socket on the first accept, so between one `nc` exiting and
                        # the next binding, nothing listened — and the probe asks its paths back
                        # to back, the next leaving exactly then. The request that lost the race
                        # was refused, which this `nc` reports by printing NOTHING, so the
                        # control came back empty and the verdict was `None`: `assert None is
                        # False` about 1 run in 10 under `-n 8` (4/40 measured), in CI on #406.
                        # `-lk -e` keeps the socket listening and forks the answer per
                        # connection, so a request arriving mid-close waits in the backlog. The
                        # child reads the request to its end before closing, so the close is a
                        # FIN, never a reset that could take the answer with it.
                        "exec nc -lk -p 80 -e sh -c 'cat /tmp/answer; cat >/dev/null'"],
                       check=True, capture_output=True)
        address = subprocess.run(
            ["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
             tag], check=True, capture_output=True, text=True).stdout.strip()
        answer = request.param.replace("169.254.169.254", address).replace("\n", "\r\n")
        subprocess.run(["docker", "exec", "-i", tag, "sh", "-c",
                        "cat > /tmp/answer && touch /tmp/ready"],
                       input=answer, text=True, check=True, capture_output=True)
        # LISTENING IS WAITED FOR, NOT SLEPT FOR (#419): one second stood for "it is listening by
        # now", the same assumption as above one step earlier, and on a loaded machine it is not.
        deadline = time.monotonic() + 30
        while subprocess.run(["docker", "exec", tag, "nc", "-z", "127.0.0.1", "80"],
                             capture_output=True).returncode != 0:
            if time.monotonic() > deadline:
                raise RuntimeError(f"the server in {tag} never listened on port 80")
            time.sleep(0.1)
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
@pytest.mark.parametrize("served", [DIGITALOCEAN_404], indirect=True, ids=["a-404-everywhere"])
def test_a_server_this_build_cannot_place_is_unknown_never_safe(served):
    """The review's case, against a real daemon: something answers, the same on every path, in
    words no known service uses and without naming the address — could not be measured."""
    network, address = served
    reached, why = metadata_reached(network, address=address)
    assert reached is None and "answered" in why, (reached, why)


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
        return 0, _probe_output({p: DOCKER_DESKTOP_REFUSAL for p in PATHS},
                                control=DOCKER_DESKTOP_REFUSAL)

    monkeypatch.setattr(container, "_host", host)

    metadata_reached("bridge")

    script = ran[0][-1]
    assert "GET %s HTTP/1.0" in script and "Host: " in script
    assert "Metadata" not in script.split("GET %s", 1)[1].split('"', 1)[0], script
    assert "token" not in script, "the probe asks a token path"
