"""#131: the same GNU-only `sed -i` shipped three times, and CI cannot see any of them.

`sed -i` with no argument is GNU's spelling. **BSD sed reads the next word as the backup suffix**,
so `sed -i 's|a|b|' FILE` makes `s|a|b|` the suffix and `FILE` the script, and the command dies
with `invalid command code`. It is unportable by definition, not by measurement.

THE DEFECT IS INVISIBLE TO CI BY CONSTRUCTION. Everything here runs on `ubuntu-latest`, where the
line works — so a mutation restoring it goes red on a maintainer's Mac and green on every runner
this project owns. No behavioural guard on Linux can ever pin it. That is why this one reads the
source instead: the spelling IS the defect, and there is nothing to execute that would disagree.

That makes this a BACKSTOP, not the proof. The proof is
`tests/test_the_release_assembles_what_the_installer_downloads.py`, which runs the real script and
reads the file it produced — and which was red for five of its nine guards on every Mac until #131.
This exists so the fourth instance is caught before it ships rather than after.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: `sed -i` NOT followed by an EMPTY-STRING suffix. The discriminator is the doubled quote: BSD
#: needs `-i ''`, and GNU's form puts the script straight after `-i`. A single quote is no signal
#: at all — both spellings have one there, which is what `test_the_pattern_recognises_both_...`
#: caught when this read `(?!['"])` and called the portable form a defect.
_GNU_ONLY = re.compile(r"sed\s+(?:-[a-zA-Z]+\s+)*-i\s+(?!['\"]{2})")

#: The shell this repository ships or runs. Not the whole tree: a `sed -i` inside a document is
#: prose about the defect, and the mutation plans deliberately carry the cut they restore.
_SHIPPED = ("scripts/*.sh", "install.sh", ".github/workflows/*.yml")


def _shipped_files() -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    for pattern in _SHIPPED:
        found.extend(sorted(ROOT.glob(pattern)))
    return found


def test_there_is_shell_to_check_at_all():
    """The guard's own premise. A glob that silently matches nothing is a guard that passes
    forever, which is the failure this repository names by example."""
    files = _shipped_files()

    assert len(files) >= 3, f"only found {[str(f) for f in files]} — re-aim these globs"
    assert any(f.name == "collect-release-assets.sh" for f in files), (
        "the script #131 was about is not in the swept set")


def test_no_shell_we_ship_uses_the_GNU_only_sed():
    """Three sites carried the identical line: the release assembly (#131), the installer test's
    curl stub (#121), and the mutation plan anchoring it. The stub was FAITHFUL to the release —
    its comment says the checksums are generated the way the release generates them — which is how
    the defect was copied rather than caught."""
    offenders = []
    for path in _shipped_files():
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if _GNU_ONLY.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")

    assert not offenders, (
        "BSD sed reads the word after `-i` as a backup suffix, so these die on a maintainer's Mac "
        "while passing on every runner this project owns. Rewrite through a temporary file — "
        "`sed 's|a|b|' F > F.new && mv F.new F` — which both accept:\n  " + "\n  ".join(offenders))


def test_the_pattern_recognises_both_spellings():
    """Verify the verifier. A regex that matched nothing would satisfy the guard above forever."""
    assert _GNU_ONLY.search("sed -i 's| \\./| |' SHA256SUMS"), "the GNU-only form is not detected"
    assert _GNU_ONLY.search("cat x && sed -i -e 's/a/b/' f"), "flags before -i defeat the pattern"

    assert not _GNU_ONLY.search("sed -i '' 's|a|b|' f"), "the portable BSD form is flagged"
    assert not _GNU_ONLY.search("sed 's|a|b|' f > f.new && mv f.new f"), "the rewrite is flagged"
