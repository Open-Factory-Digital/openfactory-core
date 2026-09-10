"""ADR-0049 slice 9a, proven by breaking it — the Merge on a pull request nobody is parked on.

THREE CLAIMS:

  1. **It lands it, and it is the forge's own act** — the base moves and nothing else is touched.
  2. **A refusal comes back in git's words**, not as a success and not as a paraphrase: the file
     that is in the way is named in it.
  3. **A hosted forge is refused by name**, because there the merge belongs to the job that opened
     the pull request — and the PAGE offers the button only where the row would accept it.

The guard under test is `tests/test_the_button_without_a_gate.py`.
"""

TEST = "tests/test_the_button_without_a_gate.py"

CATALOG = "openfactory/actions/catalog.py"
API = "openfactory/api/app.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    ("the row stops landing anything, so the button is a promise nothing keeps", CATALOG,
     "        forge.merge_pr(pr=pr)", "        pass", TEST),

    ("a refused fast-forward reads as a merge — work reported as delivered over a base that "
     "never moved", CATALOG,
     '    except Exception as exc:  # noqa: BLE001 — the refusal IS the answer, in git\'s own '
     'words\n        return refused(CONFLICT, str(exc)[:2000])',
     "    except Exception:  # noqa: BLE001\n        pass", TEST),

    ("the refusal is paraphrased, so the file in the way is no longer named", CATALOG,
     "        return refused(CONFLICT, str(exc)[:2000])",
     '        return refused(CONFLICT, "the merge was refused")', TEST),

    ("a hosted forge is landed from this page too, behind the CI and the gate that belong to it",
     CATALOG,
     '    if kind != "local":\n        return refused(', '    if False:\n        return refused(',
     TEST),

    ("the page offers the button on a hosted row, which the row then refuses", API,
     '        "can_merge_here": (getattr(getattr(project, "forge", None), "kind", "") == "local"\n'
     '                           and state == "open"),',
     '        "can_merge_here": True,', TEST),

    ("the page offers it on a pull request that is already merged", API,
     '                           and state == "open"),', "                           ),", TEST),

    ("the page loses the button altogether and the only way back is git by hand", PANEL,
     "      ${p.can_merge_here ? `<div style=\"margin-top:14px\">", "      ${false ? `<div>",
     TEST),
]
