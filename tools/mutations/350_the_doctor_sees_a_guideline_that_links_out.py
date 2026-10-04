"""The doctor sees a guideline committed in the repository as a link out of it (#350).

ROWS 1-4 ARE THE HOLE ITSELF: the doctor reading the text with a checkout at hand, the real probe
set carrying no checkout or resolving none, and the shared rule no longer following links — which
is red here only because the doctor asks the job's rule and keeps no copy of its own.

ROWS 5-6 ARE THE DOCTOR AND THE JOB AGREEING: a link to the repository itself passed, and a link
that stays inside failed.

ROWS 7-9 ARE THE LINE SAYING WHAT A PERSON NEEDS: where the link leads, that the file goes in place
of the link, and which checkout was resolved.

ROWS 10-11 ARE NO CHECKOUT AT HAND: the text-only pass claiming a containment it did not check, and
a checkout that cannot be resolved crashing the probe instead of answering None.
"""

TEST = "tests/test_the_doctor_sees_a_guideline_that_links_out.py"

CONTEXT = "openfactory/orchestrator/context.py"
DOCTOR = "openfactory/doctor.py"

MUTATIONS = [
    ("the doctor reads the text with a checkout at hand, so a link out passes", DOCTOR,
     "        if checkout is not None:\n            # THE JOB'S RULE IN THE JOB'S TREE",
     "        if False:\n            # THE JOB'S RULE IN THE JOB'S TREE"),

    ("the real probe set carries no checkout", DOCTOR,
     "        checkout=_checkout,\n",
     ""),

    ("the real probe resolves no checkout", DOCTOR,
     "        return root if root.is_dir() else None\n",
     "        return None\n"),

    ("the shared rule stops following links, and the doctor passes a link out", CONTEXT,
     "    candidate = (repo_path / relative).resolve()\n    if candidate == root",
     "    candidate = (repo_path / relative).absolute()\n    if candidate == root"),

    ("the doctor passes a link to the repository itself", DOCTOR,
     '            elif refused:\n                out.append(f"{where}: {path!r} ({refused})")',
     '            elif False:\n                out.append(f"{where}: {path!r} ({refused})")'),

    ("the doctor fails a link that stays inside the repository", DOCTOR,
     "            if refused == OUTSIDE:\n                out.append",
     "            if refused != ITSELF:\n                out.append"),

    ("the failing line does not say where the link leads", DOCTOR,
     '({OUTSIDE}: it resolves to {target})")',
     '({OUTSIDE})")'),

    ("the remedy does not say the file goes in place of the link", DOCTOR,
     "into the repository, in place of the link if it is one, and name it",
     "into the repository and name it"),

    ("the pass does not say which checkout it resolved", DOCTOR,
     "resolved in the checkout at {checkout}, links ",
     "resolved in the checkout, links "),

    ("with no checkout at hand the pass claims a containment it did not check", DOCTOR,
     '                   f"no guideline the manifest names is a path outside the repository "',
     '                   f"every guideline the manifest names resolves inside the repository "'),

    ("a checkout that cannot be resolved crashes the probe", DOCTOR,
     "        except Exception as exc:  # noqa: BLE001 — a diagnostic never breaks on a probe\n"
     "            log.info(\"could not resolve %s's checkout to resolve its guidelines in",
     "        except ZeroDivisionError as exc:  # noqa: BLE001\n"
     "            log.info(\"could not resolve %s's checkout to resolve its guidelines in"),
]
