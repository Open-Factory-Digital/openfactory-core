"""#129 (and the half of #122 a proof could have caught): a variable that is SET is not a variable
that is USABLE, and nothing had ever read the file one names.

`v0.2.0` shipped `ENV NODE_EXTRA_CA_CERTS=/usr/local/share/openfactory/extra-ca.crt` over a file the
build created EMPTY. On the published images no agent call could reach the API — and `doctor`,
`box prove` and the poller were all green while it happened.

THE NETWORK STATION IS THE ONE THAT SHOULD HAVE SEEN IT, and its own docstring names the class:

    a proxy, an intercepting CA or an egress policy passes a smoke test and then kills the first
    real agent call

It probes with `curl`. `curl` reads the system trust store and ignores every one of these
variables; the harness ships its own runtime, reads them, and refuses an empty PEM. Measured
against the real endpoint with the exact file `v0.2.0` ships:

    NODE_EXTRA_CA_CERTS=<empty file>  curl … → http_code=405 ssl_verify=0
                                      curl … → http_code=405 ssl_verify=0

Byte-identical. The probe and the thing it is a proxy for do not share a trust store, so no amount
of care in the probe could have closed this. Reading the file does, and it still costs zero tokens.
"""

from __future__ import annotations

import pathlib
import subprocess
import tempfile

from openfactory import box_prove as bp

_A_CERT = "-----BEGIN CERTIFICATE-----\nx\n-----END CERTIFICATE-----\n"


def _probes(**over):
    """A green box, so every test below fails for exactly the reason it names."""
    base = dict(
        resolve_digest=lambda _i: "sha256:" + "a" * 64,
        image_platform=lambda _i: ("linux", "amd64", "glibc"),
        toolbox_stamp=lambda: {"variant": "linux-amd64-glibc", "harnesses": ["claude"]},
        contract=lambda _i: {},
        run_in_box=lambda _c: (0, "ok"),
        harness_reachable=lambda: (True, "200"),
        setup_commands=list,
        validate_commands=dict,
        harness_name=lambda: "claude",
    )
    base.update(over)
    return bp.Probes(**base)


def _trust(check: str, proof) -> list:
    return [f for f in proof.findings if f.check == check]


def _run_the_script(**env) -> str:
    """EXECUTE the shell the box would run, under this machine's `sh`, with real files on disk.

    The script is what ships; a test that asserted its text would be satisfied by a script that
    prints nothing, which is the shape of every bug this file is about."""
    done = subprocess.run(["sh", "-c", bp.trust_script()], capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stderr[:400]
    return done.stdout.strip()


# ── the script, run ─────────────────────────────────────────────────────────────────────────────

def test_the_script_counts_zero_for_the_file_v0_2_0_actually_shipped():
    """The defect itself, reproduced: an empty file is a file, so every `[ -f ]` and every
    presence check in this repository passes over it."""
    work = pathlib.Path(tempfile.mkdtemp(prefix="oftrust"))
    empty = work / "extra-ca.crt"
    empty.write_text("")

    assert empty.is_file(), "the premise: the shipped file EXISTS, which is why presence missed it"
    assert _run_the_script(NODE_EXTRA_CA_CERTS=str(empty)) == "NODE_EXTRA_CA_CERTS 0"


def test_the_script_counts_the_certificates_a_real_store_holds():
    work = pathlib.Path(tempfile.mkdtemp(prefix="oftrust"))
    store = work / "ca-certificates.crt"
    store.write_text(_A_CERT * 3)

    assert _run_the_script(NODE_EXTRA_CA_CERTS=str(store)) == "NODE_EXTRA_CA_CERTS 3"


def test_the_script_says_minus_one_when_the_variable_names_nothing():
    """A different fault with a different remedy, and the two must not arrive as one number."""
    assert _run_the_script(NODE_EXTRA_CA_CERTS="/nowhere/at/all.crt") == "NODE_EXTRA_CA_CERTS -1"


def test_the_script_prints_nothing_when_no_runtime_was_told_anything():
    assert _run_the_script() == ""


def test_it_reports_every_runtime_separately():
    """A box carries several of these at once, which is exactly how one stays broken while the
    others are fine — so one verdict over all of them would hide the broken one."""
    work = pathlib.Path(tempfile.mkdtemp(prefix="oftrust"))
    (work / "good.crt").write_text(_A_CERT)
    (work / "bad.crt").write_text("")

    out = _run_the_script(SSL_CERT_FILE=str(work / "good.crt"),
                          NODE_EXTRA_CA_CERTS=str(work / "bad.crt"))

    assert sorted(out.splitlines()) == ["NODE_EXTRA_CA_CERTS 0", "SSL_CERT_FILE 1"]


def test_neither_the_path_nor_a_byte_of_the_file_ever_leaves_the_box():
    """The doctrine `presence_script` already follows, and it applies harder here: the value is a
    path into the CLIENT's image and the contents are their certificates. A name and a number say
    everything the finding needs."""
    work = pathlib.Path(tempfile.mkdtemp(prefix="oftrust"))
    store = work / "secret-looking-name.crt"
    store.write_text("-----BEGIN CERTIFICATE-----\nSUPERSECRET\n-----END CERTIFICATE-----\n")

    out = _run_the_script(NODE_EXTRA_CA_CERTS=str(store))

    assert str(store) not in out, f"the script printed the path: {out}"
    assert "SUPERSECRET" not in out, f"the script printed the file's contents: {out}"
    assert out == "NODE_EXTRA_CA_CERTS 1"


# ── the station, over the proof ─────────────────────────────────────────────────────────────────

def test_an_empty_trust_file_FAILS_the_proof():
    """The whole point. This proof was PROVEN on the deployment where no ticket could run."""
    proof = bp.prove("p", "img", _probes(trust_files=lambda: {"NODE_EXTRA_CA_CERTS": 0}))

    found = _trust("trust store", proof)
    assert found and not found[0].ok, [f.to_dict() for f in proof.findings]
    assert not proof.ok, "the proof stayed green over a box no agent call can leave"
    assert found[0].remedy, "a finding with no remedy is a symptom handed to somebody"


def test_a_variable_naming_a_file_that_is_not_there_FAILS_too():
    proof = bp.prove("p", "img", _probes(trust_files=lambda: {"SSL_CERT_FILE": -1}))

    found = _trust("trust store", proof)
    assert found and not found[0].ok
    assert "no file" in found[0].message, found[0].message


def test_a_populated_store_passes_and_says_how_many():
    """A number, not a tick: "set" was already true of the broken one."""
    proof = bp.prove("p", "img", _probes(trust_files=lambda: {"NODE_EXTRA_CA_CERTS": 147}))

    found = _trust("trust store", proof)
    assert found and found[0].ok
    assert "147" in found[0].message, found[0].message


def test_the_broken_one_is_named_when_another_is_fine():
    """One green variable must not carry a red one over the line."""
    proof = bp.prove("p", "img", _probes(
        trust_files=lambda: {"SSL_CERT_FILE": 120, "NODE_EXTRA_CA_CERTS": 0}))

    found = _trust("trust store", proof)
    assert found and not found[0].ok
    assert "NODE_EXTRA_CA_CERTS" in found[0].message, found[0].message


def test_a_box_with_no_trust_variable_at_all_is_fine_and_says_so():
    proof = bp.prove("p", "img", _probes(trust_files=dict))

    found = _trust("trust store", proof)
    assert found and found[0].ok
    assert proof.ok


def test_a_probe_set_that_cannot_look_inside_claims_NOTHING():
    """`None` is *could not read*, never *there is nothing wrong* — the three-state rule this
    repository learned the expensive way, and the default for every older `Probes`."""
    proof = bp.prove("p", "img", _probes())

    assert _trust("trust store", proof) == [], "a probe that cannot see reported a verdict"
    assert proof.ok


# ── and the station below it stops overclaiming ─────────────────────────────────────────────────

def test_the_network_line_does_not_claim_the_harness_can_connect():
    """`api.anthropic.com answers` reads as *the agent can talk to the API*. It is not that claim,
    and on the deployment where #122 shipped three people read it as one."""
    proof = bp.prove("p", "img", _probes(harness_reachable=lambda: (True, "200")))

    net = _trust("network", proof)[0]
    assert net.ok
    assert "curl" in net.message, (
        f"the network finding does not say what it probed WITH, so a reader takes it for a claim "
        f"about the harness: {net.message}")
    assert "harness" in net.message and "not proven" in net.message, net.message
