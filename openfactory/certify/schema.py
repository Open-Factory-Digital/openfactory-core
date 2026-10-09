"""The published shape of `pack.json`, and a validator the standard library can run (#356).

THE SCHEMA IS A FILE, NOT A DOCSTRING. `pack.schema.json` sits beside this module and ships in the
wheel, because the bot that validates submissions and `certify verify` on a partner's laptop must
read the SAME definition the command wrote against — a shape described in prose is a shape two
readers implement twice.

WHY NOT `jsonschema`. It is not a dependency of this package, and a certification command that
pulls a validator library into every worker image for one document is a heavier promise than the
document needs. So this module implements the small subset of JSON Schema (2020-12) the pack's
schema uses — and REFUSES ANY KEYWORD OUTSIDE IT. That refusal is the point: a validator that
silently ignored an unknown keyword would read `"format": "date-time"` or `"oneOf"` as satisfied,
and the schema would promise a check nothing performs. A keyword this module does not implement is
an error at load time, so the schema can only say what is actually enforced.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

#: The schema id `pack.json` carries, and the `$id` of the published schema. MOVES WHEN THE SHAPE
#: MOVES — a reader that cannot tell version 1 from version 2 half-understands a document it
#: believes it understands.
PACK_SCHEMA = "openfactory.certify/1"

#: Where the published schema lives — inside the package, so the wheel carries it.
PACK_SCHEMA_FILE = Path(__file__).with_name("pack.schema.json")

#: The keywords this validator ENFORCES, and the ones it reads as annotations. Anything else in a
#: schema is refused (`SchemaError`) rather than ignored.
ENFORCED = frozenset({"type", "enum", "const", "properties", "required", "additionalProperties",
                      "items", "minItems", "maxItems", "pattern", "minLength", "minimum", "$ref"})
ANNOTATIONS = frozenset({"$schema", "$id", "$defs", "title", "description", "$comment"})

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


class SchemaError(ValueError):
    """The SCHEMA uses something this validator cannot enforce — a defect in the schema file."""


@lru_cache(maxsize=1)
def pack_schema() -> dict:
    """The published schema, read once and checked for keywords this module cannot enforce."""
    schema = json.loads(PACK_SCHEMA_FILE.read_text(encoding="utf-8"))
    unknown = sorted(_unknown_keywords(schema))
    if unknown:
        raise SchemaError(f"{PACK_SCHEMA_FILE.name} uses {', '.join(unknown)}, which this "
                          f"validator does not enforce — a check the schema promises and nothing "
                          f"performs")
    return schema


def _unknown_keywords(schema, *, at_properties: bool = False) -> set[str]:
    """Every keyword in `schema`, at any depth, that is neither enforced nor an annotation."""
    found: set[str] = set()
    if not isinstance(schema, dict):
        return found
    for key, value in schema.items():
        if at_properties:
            # THE KEYS OF `properties`/`$defs` ARE NAMES, NOT KEYWORDS — each value is a schema.
            found |= _unknown_keywords(value)
            continue
        if key not in ENFORCED and key not in ANNOTATIONS:
            found.add(key)
        if key in ("properties", "$defs"):
            found |= _unknown_keywords(value, at_properties=True)
        elif key in ("items", "additionalProperties") and isinstance(value, dict):
            found |= _unknown_keywords(value)
    return found


def validate(document, schema: dict | None = None) -> list[str]:
    """Every way `document` departs from `schema` (the pack's, by default) — `[]` when it does not.

    ALL OF THEM, NOT THE FIRST. A reader fixing one finding at a time against a validator that
    stops early runs it once per mistake; the doctor's rule, one layer out."""
    root = schema if schema is not None else pack_schema()
    errors: list[str] = []
    _check(document, root, root, "$", errors)
    return errors


def _resolve(ref: str, root: dict) -> dict:
    if not ref.startswith("#/"):
        raise SchemaError(f"only local references are supported, not {ref!r}")
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _check(value, schema: dict, root: dict, where: str, errors: list[str]) -> None:
    if "$ref" in schema:
        _check(value, _resolve(schema["$ref"], root), root, where, errors)
    if "type" in schema:
        allowed = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPES[t](value) for t in allowed):
            errors.append(f"{where}: expected {' or '.join(allowed)}, got {type(value).__name__}")
            return
    if "const" in schema and value != schema["const"]:
        errors.append(f"{where}: must be {schema['const']!r}, got {value!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{where}: {value!r} is not one of {schema['enum']}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{where}: shorter than {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{where}: {value!r} does not match {schema['pattern']}")
    if isinstance(value, int | float) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{where}: {value} is below {schema['minimum']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{where}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{where}: more than {schema['maxItems']} items")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                _check(item, schema["items"], root, f"{where}[{i}]", errors)
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{where}: missing {name!r}")
        properties = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for name, item in value.items():
            if name in properties:
                _check(item, properties[name], root, f"{where}.{name}", errors)
            elif extra is False:
                errors.append(f"{where}: {name!r} is not part of the schema")
            elif isinstance(extra, dict):
                _check(item, extra, root, f"{where}.{name}", errors)
