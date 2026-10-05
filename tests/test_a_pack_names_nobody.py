"""A deployment pack names nobody: every redaction rule of #356, each with its guard.

THE PROMISE, as the partners page makes it to a customer: a pack never contains organisation,
repository, project or person names — those are pseudonyms from a per-pack random salt — nor URLs,
hostnames, e-mail addresses or any credential; the practitioner is the one name it keeps; and
`redactions.json` says what was replaced and dropped, never the original, even when nothing was.

THE GUARD AT THE TOP IS THE ONE THAT MATTERS. It builds a deployment out of real-looking names
(`tests/certify_bed.py`) — planted in the registry, the manifests, the approver store, the
environment, the doctor's and the preflight's own words, a box proof's advisory output — runs the
real command, and reads EVERY file of the pack for every one of them. The rules below it pin each
mechanism on its own, so a guard that went green for the wrong reason is caught by its neighbour.
"""

from __future__ import annotations

import json
import re
import tarfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from openfactory.certify import controls as c
from openfactory.certify import pack, redact
from openfactory.certify.schema import validate
from tests import certify_bed as bed

ROOT = Path(__file__).resolve().parents[1]
CONSENT = "Lucia Andrade, CTO of the customer, 2026-10-01"


def _run(*extra: str):
    from openfactory.cli import app

    return CliRunner().invoke(app, ["certify", "deployment", "--partner", "altiva",
                                    "--profile", "standard", "--practitioner", bed.PRACTITIONER,
                                    "--consent", CONSENT, *extra])


def _leaks(files: dict[str, str]) -> list[str]:
    return [f"{name}: {word!r}" for name, text in files.items() for word in bed.FORBIDDEN
            if word.lower() in text.lower()]


# ── the whole promise, end to end ───────────────────────────────────────────────────────────────

def test_a_deployment_full_of_real_names_yields_a_pack_that_names_nobody(tmp_path, monkeypatch):
    bed.build(tmp_path, monkeypatch)

    # NOT VACUOUS: the deployment really says these names where certify reads them.
    reading = pack.gather()
    said = json.dumps([p.doctor for p in reading.projects]) + json.dumps(reading.preflight) \
        + json.dumps(reading.identifiers, default=sorted)
    for planted in ("castello", bed.GH_TOKEN, "mariana.souza@castello.com.br", "https://ghe."):
        assert planted.lower() in said.lower(), f"the bed stopped planting {planted!r}"

    result = _run("--dry-run")

    assert result.exit_code == 0, result.output
    files = bed.files_of(result.output)
    assert {"pack.json", "summary.md", "redactions.json",
            "diagnostics/preflight.json"} <= set(files), sorted(files)
    assert any(f.startswith("diagnostics/doctor-") for f in files)
    assert any(f.startswith("diagnostics/box-status-") for f in files)
    assert _leaks(files) == [], "the pack carries what it must not"
    assert bed.PRACTITIONER in files["pack.json"] and bed.PRACTITIONER in files["summary.md"], (
        "the practitioner — the one name a pack keeps — was redacted too")


def test_the_written_tarball_names_nobody_either(tmp_path, monkeypatch):
    """The same promise for the file that leaves the machine, member by member."""
    bed.build(tmp_path, monkeypatch)
    out = tmp_path / "pack.tgz"

    result = _run("--yes", "--out", str(out))

    assert result.exit_code == 0, result.output
    with tarfile.open(out) as tar:
        files = {m.name: tar.extractfile(m).read().decode() for m in tar.getmembers()}
    assert _leaks(files) == []
    assert validate(json.loads(files["pack.json"])) == []


# ── pseudonyms ──────────────────────────────────────────────────────────────────────────────────

def _redactor(salt: bytes, **kw) -> redact.Redactor:
    repos = {f"acme-corp/service-{n}": {f"service-{n}"} for n in range(8)}
    return redact.Redactor(salt=salt, identifiers={"repository": repos,
                                                    "organisation": {"acme-corp": set()}}, **kw)


def test_pseudonyms_are_stable_within_a_pack_and_unrelated_across_packs():
    one, other = _redactor(b"a" * 32), _redactor(b"b" * 32)
    text = "acme-corp/service-3 failed; service-3 again; ACME-CORP/SERVICE-3 once more"

    scrubbed = one.scrub(text, where="t")
    pseudonym = one.repository("acme-corp/service-3")
    assert scrubbed == f"{pseudonym} failed; {pseudonym} again; {pseudonym} once more", scrubbed
    assert re.fullmatch(r"repo-[1-8]", pseudonym)
    order = [one.repository(f"acme-corp/service-{n}") for n in range(8)]
    assert order != [other.repository(f"acme-corp/service-{n}") for n in range(8)], (
        "two salts numbered eight repositories identically — the numbering is not salted")
    assert sorted(order) == [f"repo-{n}" for n in range(1, 9)]


def test_the_salt_is_never_written_only_its_id(tmp_path, monkeypatch):
    bed.build(tmp_path, monkeypatch)
    salt = bytes(range(32))

    built = pack.assemble(pack.gather(), profile="light", partner="altiva",
                          practitioner=bed.PRACTITIONER, salt=salt)

    assert built.document["salt_id"] == redact.salt_id(salt)
    for text in built.files.values():
        assert salt.hex() not in text and salt.decode("latin-1") not in text


def test_a_name_nobody_registered_is_a_placeholder_never_the_original():
    r = _redactor(b"c" * 32)

    assert r.repository("someone-else/thing") == "repo-unnamed"
    assert r.project("never-registered") == "project-unnamed"


# ── what is dropped ─────────────────────────────────────────────────────────────────────────────

#: One sample of every format `org_defaults/floor.yaml`'s credential scan names.
FLOOR_FORMATS = [
    "AKIAQWERTYUIOPASDFGH", "ghp_" + "a1B2" * 9, "github_pat_" + "x" * 30, "xoxb-12345678901-abc",
    "glpat-" + "Z" * 20, "AIza" + "S" * 35, "sk-ant-" + "q" * 24, "npm_" + "n" * 36,
    "AccountKey=" + "k" * 64,
]


@pytest.mark.parametrize("secret", FLOOR_FORMATS)
def test_every_credential_format_the_floor_scans_for_is_dropped(secret):
    r = redact.Redactor(salt=b"d" * 32, identifiers={})

    scrubbed = r.scrub(f"the run printed {secret} and stopped", where="t")

    assert secret not in scrubbed and "[credential]" in scrubbed, scrubbed


def test_a_pem_private_key_is_dropped_header_body_and_footer():
    r = redact.Redactor(salt=b"d" * 32, identifiers={})

    scrubbed = r.scrub(f"the key was {bed.APP_KEY} in the log", where="t")

    assert "PRIVATE KEY" not in scrubbed and "MIIEpAIBAAKCAQEA" not in scrubbed, scrubbed
    assert "the key was [credential]" in scrubbed


def test_the_credential_patterns_are_READ_from_the_floor_not_copied(monkeypatch):
    """A format the floor's gate learns is a format the pack drops — and a floor that carries no
    pattern is a pack that cannot be written, never one written without the rule."""
    from openfactory.policy import presets

    monkeypatch.setattr(presets, "org_default_validation",
                        lambda: {"security": {"command": "true"}})

    with pytest.raises(ValueError, match="no credential pattern"):
        redact.Redactor(salt=b"e" * 32, identifiers={})


def _security_md_names() -> set[str]:
    text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    names: set[str] = set()
    for anchor in ("reaches-the-agent", "box-allow-list"):
        region = text.split(f"<!-- {anchor} -->", 1)[1].split(f"<!-- /{anchor} -->", 1)[0]
        names |= set(re.findall(r"`([A-Z][A-Z0-9_]+)`", region))
    return names


def test_every_name_SECURITY_md_lists_is_a_credential_here():
    """`SECURITY_NAMES` is a copy of the document's table; this holds the two equal from the
    document's side, so a credential SECURITY.md learns is one a pack drops."""
    listed = _security_md_names()

    assert listed, "SECURITY.md's regions were not read — the guard has stopped guarding"
    assert listed <= redact.credential_names(), sorted(listed - redact.credential_names())
    assert all(redact.holds_a_credential(n) for n in listed)


def test_a_variable_name_the_customer_chose_is_dropped_and_the_platforms_are_kept():
    """`CASTELLO_ADO_PAT` names the customer, and the doctor quotes a stored secret by its name."""
    from openfactory.contracts.project import BoxConfig, Project, ProviderRef

    row = Project(name="p", repo_path="/x", box=BoxConfig(env=["ACME_SONAR_TOKEN"]),
                  tracker=ProviderRef(kind="github", repo="o/r",
                                      options={"token_env": "ACME_ADO_PAT"}))
    names = pack._variable_names([row])
    r = redact.Redactor(salt=b"g" * 32, identifiers={}, variables=names)

    assert names == {"ACME_ADO_PAT", "ACME_SONAR_TOKEN"}
    assert r.scrub("a stored secret (`ACME_ADO_PAT`) and OPENFACTORY_BOT_TOKEN",
                   where="t") == "a stored secret (`[variable]`) and OPENFACTORY_BOT_TOKEN"


def test_the_value_of_every_credential_variable_is_dropped_whatever_its_name(monkeypatch):
    """The names SECURITY.md lists, a name merely SHAPED like a credential, and a name only the
    registry knows is one (`token_env`) — the value of each is a secret the pack drops."""
    from openfactory.contracts.project import Project, ProviderRef

    env = {name: f"value-of-{name.lower()}-0123456789" for name in _security_md_names()}
    env["CASTELLO_SONAR_TOKEN"] = "sonar-0123456789-abcdef"
    env["ACME_FORGE"] = "named-only-by-the-registry-123"
    env["OPENFACTORY_SANDBOX"] = "container"
    row = Project(name="p", repo_path="/x",
                  tracker=ProviderRef(kind="github", repo="o/r",
                                      options={"token_env": "ACME_FORGE"}))

    found = pack._secret_values([row], env)

    assert found == {v for k, v in env.items() if k != "OPENFACTORY_SANDBOX"}


@pytest.mark.parametrize("text,dropped,mark", [
    ("clone https://ghe.acme.io/acme/web.git now", "https://ghe.acme.io/acme/web.git", "[url]"),
    ("remote git@github.com:acme/web.git now", "git@github.com:acme/web.git", "[url]"),
    ("mail ana.lima@acme.io now", "ana.lima@acme.io", "[email]"),
    ("the host ghe.acme.io now", "ghe.acme.io", "[host]"),
    ("on 10.20.30.40:5432 now", "10.20.30.40", "[host]"),
    ("in src/billing/ledger.py now", "src/billing/ledger.py", "[path]"),
    ("a key Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFiY2RlZmdo now", "Zm9vYmFyYmF6", "[credential]"),
])
def test_urls_addresses_hosts_paths_and_long_secrets_are_dropped_by_their_own_rule(
        text, dropped, mark):
    """EACH BY ITS OWN RULE, said in its mark: the rules overlap (a URL has a `/` in it), and a
    guard that only asked "is it gone" would stay green with a rule cut and its neighbour
    covering."""
    r = redact.Redactor(salt=b"f" * 32, identifiers={})

    scrubbed = r.scrub(text, where="t")

    assert dropped not in scrubbed and scrubbed.endswith(f"{mark} now"), scrubbed
    assert r.survivors(scrubbed) == [], scrubbed


@pytest.mark.parametrize("text", [
    "proven on sha256:" + "a" * 64, "(sha256:aaaaaaaaaaaa…)", "python=Python 3.12.5",
    "version 0.6.0.dev0", "linux/arm64", ".env.compose is mode 0600",
    "see diagnostics/doctor-project-1.json#post_merge", "schema openfactory.doctor/1",
])
def test_the_platforms_own_words_are_kept(text):
    """Over-redaction has a cost too: a digest, a version, the platform's own file names."""
    r = redact.Redactor(salt=b"f" * 32, identifiers={})

    assert r.scrub(text, where="t") == text


def test_a_box_proofs_advisory_output_is_withheld_and_logged(tmp_path, monkeypatch):
    """A gate's output can quote a path in the customer's tree or a line of their code."""
    bed.build(tmp_path, monkeypatch)

    built = pack.assemble(pack.gather(), profile="standard", partner="altiva",
                          practitioner=bed.PRACTITIONER)

    box = [t for n, t in built.files.items() if n.startswith("diagnostics/box-status-")]
    assert any(pack.WITHHELD in t for t in box), box
    assert not any("pagamentos" in t for t in box)
    log = json.loads(built.files["redactions.json"])
    assert any(d["field"] == "advisories[].message" for d in log["fields_dropped"]), log


# ── the log ─────────────────────────────────────────────────────────────────────────────────────

def _bare_reading() -> c.Reading:
    return c.Reading(version="0.6.0", build=("", ""), env={}, env_file=c.EnvFileReading("", False),
                     sandbox="container", identity="local", providers={}, projects=[],
                     floor_protected=(".openfactory/**",), approvers=[])


def test_redactions_json_is_written_even_when_nothing_was_redacted():
    built = pack.assemble(_bare_reading(), profile="light", partner="altiva",
                          practitioner=bed.PRACTITIONER)

    log = json.loads(built.files["redactions.json"])
    assert log["pseudonyms"] == {} and log["replaced"] == [] and log["dropped"] == []
    assert log["salt_id"] == built.document["salt_id"]


def test_the_log_names_each_pseudonyms_category_and_never_an_original(tmp_path, monkeypatch):
    bed.build(tmp_path, monkeypatch)

    built = pack.assemble(pack.gather(), profile="standard", partner="altiva",
                          practitioner=bed.PRACTITIONER, consent=CONSENT)

    log = json.loads(built.files["redactions.json"])
    assert set(log["pseudonyms"].values()) == {"organisation", "repository", "project", "person"}
    assert all(re.fullmatch(r"(org|repo|project|person)-\d+", p) for p in log["pseudonyms"])
    assert log["replaced"] and log["dropped"], "a deployment full of names was logged as clean"
    assert _leaks({"redactions.json": built.files["redactions.json"]}) == []


def test_the_consenting_person_is_a_pseudonym_too(tmp_path, monkeypatch):
    """The practitioner is the ONLY name kept — the customer's person who consented is not her."""
    bed.build(tmp_path, monkeypatch)

    built = pack.assemble(pack.gather(), profile="standard", partner="altiva",
                          practitioner=bed.PRACTITIONER, consent=CONSENT)

    consent = built.document["consent"]
    assert re.fullmatch(r"person-\d+", consent["by"]), consent
    assert consent["date"] == "2026-10-01"
    assert "Lucia" not in json.dumps(built.files)


# ── the check before anything is written ────────────────────────────────────────────────────────

def test_a_pack_in_which_anything_survived_is_never_written(tmp_path, monkeypatch):
    """The classifier that scrubbed the pack reads it back before it leaves `assemble`. A scrub
    that missed something — here, one that does nothing at all to the diagnostics — is a pack that
    is refused, and the command says so and writes nothing."""
    bed.build(tmp_path, monkeypatch)
    monkeypatch.setattr(redact.Redactor, "scrub_document", lambda self, doc, where: doc)
    out = tmp_path / "pack.tgz"

    result = _run("--yes", "--out", str(out))

    assert result.exit_code == 1
    assert "no pack was written" in result.output and "defect" in result.output
    assert not out.exists()
