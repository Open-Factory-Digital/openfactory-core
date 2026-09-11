"""The inventory joins the renewal — the cuts that leave yesterday's tree in the bundle.

ROW 1 IS THE INVENTORY NEVER RE-TAKEN (the old one always wins). ROW 2 IS THE CHANGE NOT COUNTED
as a write, so the refresh reports "unchanged" and publishes nothing. ROW 3 IS THE RISKS
ACCUMULATING (old inventory gaps kept). ROW 4 IS THE COVERAGE NOT RECOMPUTED. ROW 5 IS THE FRESH
PATH NOT REPUBLISHING the manifest it changed. ROW 6 IS THE SHAPE IGNORING FINGERPRINTS, so a
file whose bytes moved is the same inventory.
"""

TEST = "tests/test_the_renewal_keeps_the_inventory_current.py"

MUTATIONS = [
    ("the inventory is never re-taken — the old one always wins",
     "openfactory/onboarding/renew.py",
     "    if old is not None and _shape(old) == _shape(fresh):\n        return old, False",
     "    if old is not None:\n        return old, False"),

    ("a changed inventory is not a write, so the refresh publishes nothing",
     "openfactory/onboarding/renew.py",
     '        return (self.broken > 0 or self.inventoried) and self.mode != "failed"',
     '        return self.broken > 0 and self.mode != "failed"'),

    ("the old inventory gaps are kept beside the new ones",
     "openfactory/onboarding/renew.py",
     "    kept = [g for g in manifest.gaps if g.kind != STALE_GAP and g.kind not in INVENTORY_GAP_KINDS]",
     "    kept = [g for g in manifest.gaps if g.kind != STALE_GAP]"),

    ("the coverage table is not recomputed",
     "openfactory/onboarding/renew.py",
     '        "coverage": _coverage_rows(manifest.coverage, concepts, inventory)})',
     '        "coverage": manifest.coverage})'),

    ("the fresh path does not republish the manifest it changed",
     "openfactory/onboarding/renew.py",
     "        if inventoried:\n            manifest = _manifest_for(bundle_dir, inventory, existing, commit=commit,",
     "        if False:\n            manifest = _manifest_for(bundle_dir, inventory, existing, commit=commit,"),

    ("the shape ignores fingerprints, so moved bytes are the same inventory",
     "openfactory/onboarding/renew.py",
     "    return (tuple((f.path, f.kind, f.fingerprint) for f in inventory.files),",
     "    return (tuple((f.path, f.kind) for f in inventory.files),"),

    ("the staged bundle is inventoried as the client's files — the refresh publishes for ever",
     "openfactory/onboarding/renew.py",
     "    fresh = take_inventory(source, commit=commit, generated_at=generated_at, exclude=bundle_dir)",
     "    fresh = take_inventory(source, commit=commit, generated_at=generated_at)"),
]
