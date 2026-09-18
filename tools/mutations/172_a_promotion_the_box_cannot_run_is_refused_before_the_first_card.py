"""#172, proven by breaking it — a promotion chain the box cannot walk is refused before any card.

A manifest that declared `environments:` on a local box (`worktree`, `container`) passed the doctor
(`ok post_merge after a merge: the promotion chain observes …`) and then failed its job AFTER the
merge, in `_run_promotion`, which refuses every box that is not remote. The change was on the base,
the job ended failed, and the card never reached Done.

THREE CLAIMS:

  1. **The doctor fails it**, before any card, with or without a deploy watch beside the chain —
     and a remote box, a local box with no environments, and a box nothing can name read as before.
  2. **One sentence, two speakers.** The doctor and the promotion both ask
     `after_merge.no_local_promotion`; either one composing its own words is caught by running both.
  3. **The remedy's advice loads**: it names `promote:` too, because dropping `environments:` alone
     leaves a chain naming stages nothing declares, which the manifest refuses.

The guard is `tests/test_a_promotion_the_box_cannot_run_is_refused_before_the_first_card.py`.
"""

TEST = "tests/test_a_promotion_the_box_cannot_run_is_refused_before_the_first_card.py"

DOCTOR = "openfactory/doctor.py"
AFTER_MERGE = "openfactory/after_merge.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"

MUTATIONS = [
    ("THE DEFECT ITSELF: the doctor never asks which box walks the chain", DOCTOR,
     "    box = _traits(p) if envs else None\n",
     "    box = None\n"),

    ("the doctor asks, and reads the answer backwards — local passes, remote fails", DOCTOR,
     "    if box is not None and not box.remote:\n",
     "    if box is not None and box.remote:\n"),

    ("a deploy watch beside the chain hides it — the watch's ok branch is where the check stops",
     DOCTOR,
     "    box = _traits(p) if envs else None\n",
     "    box = _traits(p) if envs and watch is None else None\n"),

    ("the doctor composes its own words instead of the promotion's", DOCTOR,
     "        what, remedy = no_local_promotion(box.name)\n",
     "        what, remedy = (f\"promotion needs a remote box, not {box.name!r}\",\n"
     "                        \"use a remote box, or drop `environments:` and `promote:`\")\n"),

    ("the promotion composes its own words instead of the doctor's (the sentence before #172)",
     ACTIVITIES,
     "        raise ApplicationError(f\"{what}. Either {remedy} — nothing was promoted.\",\n",
     "        raise ApplicationError(\n"
     "            f\"the {phase!r} promotion phase has no implementation for the local \"\n"
     "            f\"{sandbox!r} box: promotion runs the box program on a remote box only. \"\n"
     "            f\"Either run the deployment on a remote box or drop `environments:` from \"\n"
     "            f\"the manifest until a local promotion exists — nothing was promoted.\",\n"),

    ("the remedy tells the reader to drop `environments:` alone, which the manifest then refuses",
     AFTER_MERGE,
     "or drop `environments:` (and `promote:`, which \"\n"
     "              \"names them) from the manifest",
     "or drop `environments:` from the manifest\"\n"
     "              \""),

    ("a probe set that predates the box probe crashes the check instead of reading as before",
     DOCTOR,
     "    probe = getattr(p, \"sandbox\", None)\n",
     "    probe = p.sandbox\n",
     "tests/test_somebody_is_asked_to_look_at_what_shipped.py"),
]
