"""#259: a `manifest_path` outside the repository is refused before anything is written.

The claims, and what each cut breaks: the RULE (an absolute value leaves the repository, and so
does one that climbs out with `..`), the three places it is asked (`env apply --pr`, `onboard`,
`propose` itself), the SENTENCE (which has to name the path, since git's own words about a path
the platform composed are what this replaces), and — the reverses that matter most — that the
refusal did not leak into the paths where an explicit `manifest_path` is still obeyed: the local
`env apply` writes where it was told, and the loader reads a manifest that lives outside the
checkout.
"""

TEST = "tests/test_a_manifest_outside_the_repository_is_not_proposed.py"
PM = "openfactory/onboarding/propose_manifest.py"
CAT = "openfactory/actions/catalog.py"
ONB = "openfactory/onboarding/onboard.py"

MUTATIONS = [
    ("an absolute path is read as living inside the repository — the join that started this", PM,
     "    if relative.is_absolute():\n        return True\n",
     "    if relative.is_absolute():\n        return False\n"),

    ("…and the other way out: `..` climbing past the root stops counting", PM,
     '        depth += -1 if part == ".." else 1\n        if depth < 0:\n            return True\n',
     "        depth += 1\n"),

    ("`env apply --pr` composes the destination without asking first", CAT,
     "        if leaves_the_repository(str(found.manifest_path)):\n",
     "        if False:\n"),

    ("`onboard` writes the inferred manifest without asking first", ONB,
     "    if leaves_the_repository(manifest_rel):\n",
     "    if False:\n"),

    ("`propose` stages whatever it is handed — the backstop under the next caller", PM,
     "        if leaves_the_repository(path):\n",
     "        if False:\n"),

    ("the refusal stops saying what the situation IS", CAT,
     '                f"outside the repository — a pull request on {raw_path} can only carry files "\n',
     '                f"unusable — a pull request on {raw_path} can only carry files "\n'),

    ("the refusal stops naming the way forward for somebody who meant that path", CAT,
     '                f"that file where it lives yourself: `openfactory env apply "\n'
     '                f"<path-to-your-checkout> --out {found.manifest_path} --yes`.",\n',
     '                f"that file where it lives yourself.",\n'),

    ("the refusal stops naming the path it is about — in EITHER half, which is the one thing "
     "git's own sentence did do", CAT,
     '                f"{found.name} declares manifest_path {str(found.manifest_path)!r}, which is "\n'
     '                f"outside the repository — a pull request on {raw_path} can only carry files "\n'
     '                f"that live in it, so there is nothing to propose and nothing was written. "\n'
     '                f"Either give manifest_path a path relative to the repository root, or write "\n'
     '                f"that file where it lives yourself: `openfactory env apply "\n'
     '                f"<path-to-your-checkout> --out {found.manifest_path} --yes`.",\n',
     '                f"{found.name} cannot be proposed as a pull request.",\n'),

    ("the reverse: the refusal leaks into the LOCAL write, which has no pull request to carry "
     "anything and has always honoured an explicit path", CAT,
     "    destination = (Path(str(out)).expanduser() if out else checkout / found.manifest_path)\n",
     '    destination = (Path(str(out)).expanduser() if out\n'
     '                   else checkout / str(found.manifest_path).lstrip("/"))\n'),

    ("the reverse: it leaks into READING, where an absolute manifest_path is the whole point of "
     "the field", "openfactory/namespace.py",
     "    new = root / relative\n",
     '    new = root / str(relative).lstrip("/")\n'),
]
