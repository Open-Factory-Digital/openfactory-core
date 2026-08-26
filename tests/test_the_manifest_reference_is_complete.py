"""What a project CAN declare must be discoverable without reading the source (pilot, 2026-08-15).

The pilot looked at his five-line `.openfactory/project.yaml` and asked whether that was all of
it, and whether there was a better explanation of how to configure the rest. There was not:
`docs/project.yaml.example` calls itself *"the full annotated reference"* and covered 18 of the 32
fields the schema accepts — so the honest answer to "what else can this file say?" was "read
`openfactory/contracts/manifest.py`".

DERIVED FROM THE MODEL, never from a list somebody remembered to update: a field added tomorrow is
undocumented today, and this is the test that says so.

The second half is the boundary. `harness`, the model per role and `box.image` are NOT manifest
fields — the file lives in the repository the coding agent edits, and an agent that could name its
own image, model or CLI would be choosing what runs it and who pays. Anything that tells an
operator to put them in the manifest is telling them to break the manifest, because it forbids
unknown keys — which is exactly what `doctor` did until this test existed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from openfactory.contracts.manifest import Manifest

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "docs" / "project.yaml.example"


def test_every_field_the_schema_accepts_is_in_the_reference():
    doc = REFERENCE.read_text()
    missing = [name for name in Manifest.model_fields
               if not re.search(rf"^\s*#?\s*{re.escape(name)}\s*:", doc, re.M)]
    assert not missing, (
        f"these manifest fields exist in the code and in no document: {missing}. "
        f"{REFERENCE.relative_to(ROOT)} is what an operator reads to find out what this file can "
        "say — a field missing from it is a feature nobody can reach")


def test_the_reference_states_a_default_for_the_fields_that_have_one():
    """A field named without its default answers half the question: an operator cannot tell
    whether declaring it changes anything."""
    import pydantic_core

    doc = REFERENCE.read_text()
    for name, spec in Manifest.model_fields.items():
        # A field with no simple default (a factory, or an alias for another field) has nothing
        # to state — `validation:` is `validate:` under a second name, not a setting with a value.
        if (spec.is_required() or spec.default is None
                or spec.default is pydantic_core.PydanticUndefined):
            continue
        block = doc[max(0, doc.find(name) - 400):doc.find(name) + 400]
        assert "default" in block.lower() or str(spec.default) in block, (
            f"{name} is documented without saying what happens when it is absent")


@pytest.mark.parametrize("deployment_field", ["harness", "model", "box"])
def test_a_deployment_setting_is_not_a_manifest_field(deployment_field):
    """The schema refuses them, so any document or refusal that suggests otherwise is advice that
    breaks the file it edits."""
    assert deployment_field not in Manifest.model_fields
    with pytest.raises(Exception):  # noqa: B017 — pydantic's own ValidationError
        Manifest(**{deployment_field: "x"})


def test_nothing_tells_an_operator_to_put_a_deployment_setting_in_the_manifest():
    """THE LIVE DEFECT THIS GUARD WAS WRITTEN FOR. `doctor` answered a missing harness with
    "set `harness:` in .openfactory/project.yaml" — and `Manifest` forbids unknown keys, so an
    operator who followed it turned "the harness is not installed" into "the manifest no longer
    loads at all"."""
    offenders = []
    for path in [*ROOT.glob("docs/**/*.md"), *ROOT.glob("openfactory/**/*.py"), REFERENCE]:
        text = path.read_text(errors="ignore")
        for m in re.finditer(r"`?(harness|model|box\.image)\s*:`?[^\n]{0,80}", text):
            line = text[text.rfind("\n", 0, m.start()) + 1:text.find("\n", m.start())]
            # A python ANNOTATION is a declaration, not advice: `harness: str | None = None` in the
            # registry's own model is the very thing this guard protects, not a violation of it.
            if re.match(r"\s*\w+\s*:\s*[\w\[\], \"'|.]+\s*=", line):
                continue
            window = text[max(0, m.start() - 200):m.end() + 200]
            if "project.yaml" not in window:
                continue
            # the reference explains where they DO live; that is the opposite of the defect
            if "NOT here" in window or "not a manifest field" in window or "REGISTRY" in window:
                continue
            offenders.append(f"{path.relative_to(ROOT)}: {m.group(0)[:70]}")
    assert not offenders, (
        "these tell an operator to declare a DEPLOYMENT setting in the repository's manifest, "
        "which forbids unknown keys — the advice breaks the file:\n  " + "\n  ".join(offenders))


def test_the_reference_says_where_the_deployment_settings_DO_live():
    """Refusing is half an answer. The operator asked "where do I set the model", and the file
    that says "not here" owes them the command that does."""
    doc = REFERENCE.read_text()
    assert "openfactory project set-model" in doc
    assert "--harness" in doc
    assert "box.image" in doc
