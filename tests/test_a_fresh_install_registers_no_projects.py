"""The distribution seed registers NOTHING — a fresh install's first screen is an empty floor.

The worker image seeds its registry on first boot, and the seed used to be
`deploy/registry.yaml.example` — the annotated DOCUMENTATION, whose illustrative `myapp` entry
therefore arrived REGISTERED on every fresh install. The first panel the pilot operator ever
opened was red with a HELD phantom project ("é isso mesmo? faz sentido?", 2026-08-10). "A fresh
install is never empty" was our own deployment's premise — where an empty registry once meant a
KeyError on every job — not the product's: a stranger's fresh install has no projects, and the
truthful first screen says so.

Three properties, and the pairing is the point (a negative guard needs a positive twin):

  1. what the Dockerfile SHIPS as the seed holds zero projects — read from the COPY line, not
     from a filename this test assumes, so pointing the seed back at the example goes red;
  2. the example stays RICH — it is the reference for hand-writing an entry, and emptying it
     would "fix" the seed by deleting the documentation;
  3. the gitignored real registry still overwrites the seed (the glob line) — our own
     deployments keep baking their project list.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_DOCKERFILE = _ROOT / "docker" / "worker.Dockerfile"


def _seed_copy_sources() -> list[str]:
    """The COPY sources aimed at the seed path, in order."""
    out = []
    for line in _DOCKERFILE.read_text().splitlines():
        m = re.match(r"\s*COPY\s+(\S+)\s+/etc/openfactory/registry\.seed\.yaml\s*$", line)
        if m:
            out.append(m.group(1))
    return out


def test_the_shipped_seed_holds_zero_projects():
    sources = _seed_copy_sources()
    assert sources, "the Dockerfile no longer seeds the registry — this guard needs re-thinking"
    first = sources[0]
    assert first != "deploy/registry.yaml.example", (
        "the seed is the DOCUMENTATION again — its example entry boots every fresh install "
        "with a phantom registered project")
    seed = yaml.safe_load((_ROOT / first).read_text())
    assert (seed or {}).get("projects") in ({}, None), (
        f"the distribution seed {first} registers projects — a fresh install must start empty")


def test_the_example_stays_the_rich_reference():
    example = yaml.safe_load((_ROOT / "deploy" / "registry.yaml.example").read_text())
    assert example.get("projects"), (
        "the example lost its illustrative entry — it is the reference for hand-writing one, "
        "and emptying it is the wrong way to empty the seed")


def test_a_real_deployments_registry_still_overwrites_the_seed():
    sources = _seed_copy_sources()
    assert any("registry.yam[l]" in s for s in sources[1:]), (
        "the gitignored deploy/registry.yaml no longer overwrites the seed — our own "
        "deployments would boot with an empty project list")
