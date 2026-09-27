"""A guideline the manifest names is read from the repository, and from nowhere else (#329).

ROWS 1-3 ARE THE HOLE ITSELF: the manifest is the repository's content, and each guideline it
names is inlined into the agent's prompt. The join going back to `repo_path / g`, the path
contained without being resolved (a `..` or a link committed in the repository walks out), and a
component's guidelines left out of the list the job reads and the doctor checks.

ROWS 4-6 ARE THE REFUSAL STAYING LOUD, which is what makes closing the hole safe for a deployment
that used it as the workaround #318 was filed about: the job's warning cut, the doctor's line
dropped from the report, and the doctor reading only one of the two ways out.

ROWS 7-9 ARE THE DOCTOR AND THE JOB AGREEING (review of #346): an entry that names the repository
itself passed by the doctor, admitted by the job in silence, or called an escape by it.

ROW 10 IS THE DOCTOR SAYING WHAT IT CHECKED (second review of #346): a green line that claims every
guideline is inside the repository, when it read only the manifest's text and cannot see a link.
"""

TEST = "tests/test_a_guideline_stays_inside_the_repository.py"

CONTEXT = "openfactory/orchestrator/context.py"
DOCTOR = "openfactory/doctor.py"

MUTATIONS = [
    ("the guideline join is not contained, so any readable file of the worker is inlined", CONTEXT,
     "        doc = _inside(repo_path, g, named_by=named_by)",
     "        doc = repo_path / g"),

    ("the path is contained without being resolved, so `..` and a link out walk past it", CONTEXT,
     "        candidate = (repo_path / relative).resolve()\n    except OSError:\n        return None\n"
     "    if candidate == root",
     "        candidate = (repo_path / relative).absolute()\n    except OSError:\n        return None\n"
     "    if candidate == root"),

    ("a component's guidelines are left out of what is read and checked", CONTEXT,
     '        named += [(f"components.{name}.guidelines", g) for g in comp.guidelines]',
     "        pass"),

    ("the job refuses an entry in silence", CONTEXT,
     '        _log.warning(\n            "%s names %r, which resolves outside the checkout',
     '        (lambda *_a: None)(\n            "%s names %r, which resolves outside the checkout'),

    ("the doctor never says a guideline is outside the repository", DOCTOR,
     '    findings.append(_guarded("guidelines", lambda: _guidelines(probes)))\n',
     ""),

    ("the doctor misses an entry that climbs out with `..`", DOCTOR,
     '        if posixpath.isabs(path) or norm.split("/")[0] == "..":',
     "        if posixpath.isabs(path):"),

    ("the doctor passes an entry that names the repository itself", DOCTOR,
     '        elif norm == ".":',
     "        elif False:"),

    # RELABELLED 2026-09-27 (review of #346): this cut admits the root in silence, which is what
    # it holds; calling the root an escape is the row below, the old combined condition
    ("the repository itself is admitted as a guideline, in silence", CONTEXT,
     "    if candidate == root:\n        # THE ROOT IS NOT OUTSIDE",
     "    if False:\n        # THE ROOT IS NOT OUTSIDE"),

    ("the job calls the repository itself an escape", CONTEXT,
     "    if candidate == root:\n        # THE ROOT IS NOT OUTSIDE",
     "    if not candidate.is_relative_to(root):\n        # THE ROOT IS NOT OUTSIDE"),

    ("the doctor's pass claims a containment it did not check", DOCTOR,
     '                   f"no guideline the manifest names is a path outside the repository "',
     '                   f"every guideline the manifest names is inside the repository "'),

    ("the doctor misses an absolute entry", DOCTOR,
     '        if posixpath.isabs(path) or norm.split("/")[0] == "..":',
     '        if norm.split("/")[0] == "..":'),
]
