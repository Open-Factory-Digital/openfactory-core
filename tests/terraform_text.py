"""The reference deployment's terraform, read for the guards that cross the language boundary.

ONE HOME FOR THE STRIPPER. Guards that read the `.tf` files keep breaking on the comment that
explains the rule they protect (the eighth in a fortnight was `sdlc.api.app`, named above the fixed
start command as the thing that was wrong). Every reader strips comments the same way here, so two
guards cannot disagree about what "the terraform says".

THE DIRECTORY MAY BE ABSENT. `infra/` stays in the private repository and leaves the public cut;
a guard about the reference deployment has nothing to assert where that deployment does not exist,
and says so by SKIPPING by name (`require()`), never by reading an empty string as compliance.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TERRAFORM_DIR = ROOT / "infra" / "terraform"

#: The two spellings a task definition's environment takes in this repository:
#:   ECS container definitions    `{ name = "X", value = "y" }`
#:   App Runner runtime variables `X = "y"`
_ECS_ROW = re.compile(r'\{\s*name\s*=\s*"([A-Z0-9_]+)"\s*,\s*value\s*=\s*"([^"]*)"\s*\}')
_APPRUNNER_ROW = re.compile(r'^\s*([A-Z][A-Z0-9_]+)\s*=\s*"([^"]*)"\s*$', re.MULTILINE)


def strip_comments(text: str) -> str:
    """The `.tf` text without its `#` comments — whole-line and trailing."""
    out = []
    for line in text.splitlines():
        code = line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
        out.append(code)
    return "\n".join(out)


def files() -> dict[str, str]:
    """`{basename: comment-stripped text}` for every `.tf` in the reference deployment."""
    return {p.name: strip_comments(p.read_text()) for p in sorted(TERRAFORM_DIR.glob("*.tf"))}


def whole() -> str:
    """Every `.tf`, comment-stripped, as one text."""
    return "\n".join(files().values())


def require() -> None:
    """Skip, by name, the guards that are about the reference deployment when it is not here."""
    if not TERRAFORM_DIR.is_dir():
        pytest.skip(f"{TERRAFORM_DIR.relative_to(ROOT)} is absent — this guard is about the "
                    f"reference deployment, which exists only where infra/ does")


def literal_env(text: str) -> dict[str, str]:
    """The environment variables a task definition sets to a LITERAL string, in either spelling.
    A value built from a terraform expression (`var.x`, `aws_…`) is not a literal and is not here."""
    found = {name: value for name, value in _ECS_ROW.findall(text)}
    found.update({name: value for name, value in _APPRUNNER_ROW.findall(text)})
    return found
