"""A guideline the manifest names is read from the repository, and from nowhere else (#329).

ROWS 1-3 ARE THE HOLE ITSELF: the manifest is the repository's content, and each guideline it
names is inlined into the agent's prompt. The join going back to `repo_path / g`, the path
contained without being resolved (a `..` or a link committed in the repository walks out), and a
component's guidelines left out of the list the job reads and the doctor checks.

ROWS 4-6 ARE THE REFUSAL STAYING LOUD, which is what makes closing the hole safe for a deployment
that used it as the workaround #318 was filed about: the job's warning cut, the doctor's line
dropped from the report, and the doctor reading only one of the two ways out.
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
     '           if posixpath.isabs(path) or posixpath.normpath(path).split("/")[0] == ".."]',
     "           if posixpath.isabs(path)]"),

    ("the doctor misses an absolute entry", DOCTOR,
     '           if posixpath.isabs(path) or posixpath.normpath(path).split("/")[0] == ".."]',
     '           if posixpath.normpath(path).split("/")[0] == ".."]'),
]
