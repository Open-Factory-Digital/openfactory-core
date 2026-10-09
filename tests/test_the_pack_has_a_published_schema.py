"""`pack.json` has a published schema, every pack validates against it, and the validator is not
a rubber stamp (#356).

THE SCHEMA IS A FILE IN THE PACKAGE (`openfactory/certify/pack.schema.json`), read by the command
before it writes and — when it is built — by `certify verify` and the submissions bot. The
validator is this package's own small subset of JSON Schema, because `jsonschema` is not a
dependency; so the guards below hold it from three sides: it REFUSES a keyword it does not enforce
(a schema cannot promise a check nobody performs), it FAILS a pack that departs from the shape (it
is not vacuous), and the schema's enums are the code's own tables (the two cannot drift).
"""

from __future__ import annotations

import copy
import json

import pytest

from openfactory.box_prove import VALIDITY
from openfactory.certify import controls as c
from openfactory.certify import pack, schema
from tests import certify_bed as bed


@pytest.fixture()
def document(tmp_path, monkeypatch) -> dict:
    bed.build(tmp_path, monkeypatch)
    return pack.assemble(pack.gather(), profile="standard", partner="altiva",
                         practitioner=bed.PRACTITIONER,
                         consent="Lucia Andrade, CTO, 2026-10-01").document


def test_the_schema_is_the_file_the_package_ships_and_names_its_version():
    published = json.loads(schema.PACK_SCHEMA_FILE.read_text())

    assert published["$id"] == schema.PACK_SCHEMA == "openfactory.certify/1"
    assert published["properties"]["schema"] == {"const": schema.PACK_SCHEMA}
    assert schema.pack_schema() == published


def test_the_schema_uses_no_keyword_the_validator_does_not_enforce():
    assert schema._unknown_keywords(schema.pack_schema()) == set()


def test_a_keyword_the_validator_does_not_enforce_is_refused(tmp_path, monkeypatch):
    """`format: date-time` would read as satisfied by a validator that ignored it."""
    widened = json.loads(schema.PACK_SCHEMA_FILE.read_text())
    widened["properties"]["generated_at"] = {"type": "string", "format": "date-time"}
    path = tmp_path / "pack.schema.json"
    path.write_text(json.dumps(widened))
    monkeypatch.setattr(schema, "PACK_SCHEMA_FILE", path)
    schema.pack_schema.cache_clear()
    try:
        with pytest.raises(schema.SchemaError, match="format"):
            schema.pack_schema()
    finally:
        schema.pack_schema.cache_clear()


def test_the_schemas_enums_are_the_codes_own_tables():
    s = schema.pack_schema()
    control = s["$defs"]["control"]["properties"]

    assert control["id"]["enum"] == list(c.CONTROL_IDS)
    assert control["result"]["enum"] == list(c.RESULTS)
    assert control["evidence"]["properties"]["source"]["enum"] == list(c.SOURCES)
    assert s["properties"]["profile"]["enum"] == list(c.PROFILES)
    assert s["properties"]["controls"]["minItems"] == len(c.CONTROLS)
    assert s["$defs"]["proof"]["properties"]["status"]["enum"] == [*VALIDITY, "unknown"]


@pytest.mark.parametrize("profile", sorted(c.PROFILES))
def test_every_pack_validates(tmp_path, monkeypatch, profile):
    bed.build(tmp_path, monkeypatch)

    for consent in ("", "Lucia Andrade, CTO, 2026-10-01"):
        built = pack.assemble(pack.gather(), profile=profile, partner="altiva",
                              practitioner=bed.PRACTITIONER, consent=consent)
        assert schema.validate(built.document) == [], (profile, consent)


def test_a_pack_with_no_projects_validates_too():
    reading = c.Reading(version="0.6.0", build=("abc123def456", "2026-10-05T10:00:00Z"), env={},
                        env_file=c.EnvFileReading("", False), sandbox="container",
                        identity="local", providers={}, projects=[], floor_protected=None,
                        approvers=None)

    built = pack.assemble(reading, profile="light", partner="altiva", practitioner="x")

    assert schema.validate(built.document) == []
    assert built.document["platform"]["build"] == {"code": "abc123def456",
                                                   "built": "2026-10-05T10:00:00Z"}


@pytest.mark.parametrize("break_it,expect", [
    (lambda d: d.update(extra=1), "'extra' is not part of the schema"),
    (lambda d: d.pop("salt_id"), "missing 'salt_id'"),
    (lambda d: d["controls"][0].update(result="ok"), "is not one of"),
    (lambda d: d["controls"].pop(), "fewer than 18"),
    (lambda d: d.update(signature="abc"), "expected null"),
    (lambda d: d["outcomes"].update(status="zeros"), "is not one of"),
    (lambda d: d["outcomes"].update(jobs=-1), "below 0"),
    (lambda d: d["outcomes"].pop("parks"), "missing 'parks'"),
    (lambda d: d["outcomes"].update(parks={"transient": 1}), "missing 'unknown'"),
    (lambda d: d["outcomes"].update(versions={"seen": [{"version": "castello tributos",
                                                        "build": "", "attempts": 1}],
                                              "unstamped": 0}), "does not match"),
    (lambda d: d["window"].update(days=0), "below 1"),
    (lambda d: d.update(partner="Altiva AI"), "does not match"),
    (lambda d: d["proofs"][0].update(repository="castello-tributos/folha"), "does not match"),
    (lambda d: d["checksums"].update({"x": "md5:abc"}), "does not match"),
])
def test_a_pack_that_departs_from_the_shape_is_refused(document, break_it, expect):
    broken = copy.deepcopy(document)
    break_it(broken)

    errors = schema.validate(broken)

    assert any(expect in e for e in errors), errors


def test_assemble_refuses_a_pack_its_schema_refuses(tmp_path, monkeypatch):
    bed.build(tmp_path, monkeypatch)
    monkeypatch.setattr(pack, "validate", lambda doc: ["$.controls: invented"])

    with pytest.raises(pack.Unsafe, match="published schema"):
        pack.assemble(pack.gather(), profile="light", partner="altiva", practitioner="x")
