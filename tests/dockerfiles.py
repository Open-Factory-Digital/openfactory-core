"""Reading the Dockerfiles this repository builds, one way, for every guard that asks.

WHY THIS IS A MODULE. Three guards needed "what is this image built FROM" within a day of each
other, and the naive answer — grep the file for `FROM` — is wrong in two ways that a release run
found the expensive way:

  · A COMMENT IS NOT AN INSTRUCTION. `test_the_sandbox_is_exempt_because_it_inherits_and_not_
    because_it_forgot` asserted `"FROM openfactory-python" in text` and kept passing after the
    real `FROM` had changed, because the comment above it QUOTES the old line while explaining why
    it was wrong (2026-08-31). A guard satisfied by prose about a defect is a guard that certifies
    the defect.

  · `FROM ${ARG}` NAMES NOTHING UNTIL THE ARG IS RESOLVED. The sandbox is built FROM a build
    argument so that one file can serve a contributor building offline and a workflow whose
    builder cannot see any local image; the answer a reader needs is the ARG's default, which is
    what a bare `docker build` of that file actually resolves.

`tests/add_ons.py` and `tests/installer_script.py` are the same pattern: a fact several guards
need is read in one place, so it cannot be read two different ways.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCKER = ROOT / "docker"

#: `FROM <ref> [AS <stage>]`, at the start of a line, which is the only place an instruction is.
_FROM = re.compile(r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?\s*$",
                   re.IGNORECASE | re.MULTILINE)
#: `ARG NAME=default` — only the ones with a default can resolve anything on their own.
_ARG = re.compile(r"^\s*ARG\s+([A-Za-z_][A-Za-z0-9_]*)=(\S+)\s*$", re.IGNORECASE | re.MULTILINE)


def instructions(text: str) -> str:
    """`text` with comment lines removed, so a `FROM` inside prose is never read as one."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def arg_defaults(text: str) -> dict[str, str]:
    return dict(_ARG.findall(instructions(text)))


def resolve(reference: str, args: dict[str, str]) -> str:
    """`${NAME}` / `$NAME` replaced by that ARG's default, as a bare `docker build` would."""
    for name, default in args.items():
        reference = reference.replace(f"${{{name}}}", default).replace(f"${name}", default)
    return reference


def froms(path: pathlib.Path) -> list[tuple[str, str | None]]:
    """`(resolved reference, stage name or None)` for every `FROM` in `path`, in order."""
    text = path.read_text()
    args = arg_defaults(text)
    return [(resolve(ref, args), stage) for ref, stage in _FROM.findall(instructions(text))]


def base_of(name: str) -> str:
    """What `docker/<name>.Dockerfile`'s FIRST stage is built on, ARG defaults resolved."""
    found = froms(DOCKER / f"{name}.Dockerfile")
    assert found, f"docker/{name}.Dockerfile declares no FROM at all"
    return found[0][0]


#: Compose's `${NAME}` / `${NAME:-default}` / `${NAME-default}`.
_COMPOSE_VAR = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*(?::?-([^}]*))?\}")


def interpolate(reference: str) -> str:
    """A compose reference with its `${…}` expressions replaced by their defaults."""
    return _COMPOSE_VAR.sub(lambda m: m.group(1) or "", reference)


def compose_image_name(reference: str) -> str:
    """`ghcr.io/org/name:tag` -> `name`, and `name:tag` -> `name`.

    The reduction that makes a LOCAL spelling and a REGISTRY spelling of the same artefact compare
    equal — which is exactly the distinction the v0.1.0 release failure turned on.

    IT INTERPOLATES FIRST, AND THAT IS NOT A DETAIL. Splitting the tag off before resolving
    `${OPENFACTORY_VERSION:-main}` splits at the LAST colon, which is the one INSIDE the
    expression: `ghcr.io/…/openfactory-base:${OPENFACTORY_VERSION:-main}` reduced to
    `openfactory-base:${OPENFACTORY_VERSION`. Every comparison against that set then failed to
    match anything, so the guard built on it passed over the exact defect it was written for —
    caught by its own mutation plan the day it was written (2026-08-31), which is the only reason
    this comment exists rather than a second incident."""
    return interpolate(reference).rsplit(":", 1)[0].rsplit("/", 1)[-1]


def compose_image(service: str) -> str:
    """The `image:` `docker-compose.yml` tags `service` with, `${VAR:-default}` resolved.

    Read here rather than in each caller so "what does this project call that image" has one
    answer, whichever file is asking."""
    import yaml

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    return interpolate(compose["services"][service]["image"])


def tracked() -> list[pathlib.Path]:
    """Every Dockerfile under `docker/`, sorted. A guard that globs cannot miss a new one."""
    return sorted(DOCKER.glob("*.Dockerfile"))
