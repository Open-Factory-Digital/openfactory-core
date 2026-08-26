"""The suite's view of "what is installed" is a controlled input, not the bench (2026-08-26).

RUN THIS WITH A `make install` INTERPRETER. The firewall's effect can only be measured where the
platform's own add-on packages are actually installed; on a plain `pip install -e '.[dev]'` venv
the filter has nothing to remove and rows 4-6 survive for a true reason. That asymmetry IS the
defect this plan is about, so the plan is honest only on the bench that has the subject:

    <a venv built by `make install`>/bin/python tools/mutate.py \
        tools/mutations/the_bench_is_not_the_case.py

Point-in-time proof; anchors rot as code moves and fail loudly on rerun.
"""

TEST = "tests/test_the_bench_is_not_the_case.py"

MUTATIONS = [
    # ── the pure filter: measurable on any bench ────────────────────────────────────────────────
    ("the filter keeps everything — the firewall is a no-op",
     "tests/vendor_addons.py",
     "    return [p for p in points if ours.get(p.name) != p.value]",
     "    return list(points)"),
    ("the filter hides by NAME, so a stranger's same-named row disappears too",
     "tests/vendor_addons.py",
     "    return [p for p in points if ours.get(p.name) != p.value]",
     "    return [p for p in points if p.name not in ours]"),
    ("the filter hides everything — a stranger's row disappears with ours",
     "tests/vendor_addons.py",
     "    return [p for p in points if ours.get(p.name) != p.value]",
     "    return []"),
    # ── the wiring: only measurable where the packages ARE installed ────────────────────────────
    ("the firewall is wired but never filters",
     "tests/conftest.py",
     '        return vendor_addons.not_ours(points, ours) if params.get("group") else points',
     "        return points"),
    ("the firewall gives up whenever the tree declares rows",
     "tests/conftest.py",
     "    ours = vendor_addons.declared()\n    if not ours:\n        return",
     "    ours = vendor_addons.declared()\n    if ours:\n        return"),
    ("the firewall leaves the loader's cache holding what the bench answered",
     "tests/conftest.py",
     ("    from openfactory import plugins as _plugins\n"
      '    monkeypatch.setattr(_plugins, "_cache", None)'),
     "    pass"),
]
