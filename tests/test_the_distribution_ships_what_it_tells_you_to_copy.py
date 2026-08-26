"""Every file the setup instructions name must actually be in the repository.

`docker-compose.yml`'s first line is `cp .env.compose.example .env.compose`, and that file was
NOT tracked: `.gitignore` says `.env.*`, and its one exception named `.env.example` literally, so
the compose template was swallowed. The distribution's opening instruction pointed at a file that
existed only on the machine of the person who wrote it — which is a strange property for the
opening instruction of a downloadable product, and invisible to anyone who never clones it fresh.

The negation is now a pattern rather than a name, and this is the guard that makes the class stay
fixed: a template is the opposite of a secret. It is the thing somebody clones the repository to
get.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP = (".venv", "node_modules", ".git", "__pycache__", "site-packages", ".claude")


def _tracked(rel: str) -> bool:
    return subprocess.run(["git", "ls-files", "--error-unmatch", rel],
                          cwd=ROOT, capture_output=True).returncode == 0


# THE PARTS OF THE PATH INSIDE THE REPOSITORY, never the absolute string. Matched against the absolute
# path, `.claude` in SKIP made every template vanish for a checkout that lives under a `.claude/`
# directory — which is exactly where this repository's own review worktrees live — and the sweep
# reported an empty tree as if the templates had been deleted. Your machine is not the reference.
EXAMPLES = sorted(
    str(p.relative_to(ROOT)) for p in ROOT.rglob("*.example")
    if not any(part in SKIP for part in p.relative_to(ROOT).parts)
)


def test_the_sweep_finds_the_templates():
    assert len(EXAMPLES) >= 4, EXAMPLES


@pytest.mark.parametrize("rel", EXAMPLES)
def test_every_template_is_in_the_repository(rel):
    assert _tracked(rel), (
        f"{rel} is a template and is not tracked, so nobody who clones this repository has it. "
        "A `.example` file is the opposite of a secret."
    )


#: Files whose setup instructions tell a reader to copy something. Derived from `cp X Y` lines
#: rather than from a hand-kept list, so a new instruction is covered the day it is written.
INSTRUCTIONS = ["docker-compose.yml", "README.md", "docs/ONBOARDING.md",
                "addons/openfactory-aws/docs/DEPLOYMENT.md"]


@pytest.mark.parametrize("doc", [d for d in INSTRUCTIONS if (ROOT / d).exists()])
def test_what_the_instructions_tell_you_to_copy_exists(doc):
    missing = []
    for source in re.findall(r"\bcp\s+([\w./-]+)\s+[\w./-]+", (ROOT / doc).read_text()):
        if source.startswith(("/", "$")) or not (ROOT / source).exists():
            missing.append(f"{doc}: `cp {source} …` — no such file in the repo")
        elif not _tracked(source):
            missing.append(f"{doc}: `cp {source} …` — present locally but NOT tracked")
    assert not missing, "\n  ".join([""] + missing)
