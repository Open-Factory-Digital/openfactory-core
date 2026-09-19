"""#184, proven by breaking it — `doctor` names the merge gates only a person settles.

A repository policy the factory can never satisfy was discovered by the first card, at the price
of two blind repair passes. The doctor now says it before any card runs — through a row
capability (`merge_gates`), never a vendor branch in the doctor.

THREE CLAIMS:

  1. **The finding names exactly the blocking process gates**, with the row's remedy: a failure
     under `merge_policy: auto` (nobody is in the loop), a pass with a note under `human`. A
     listing that could not be made is said so and never read as "no gates".
  2. **The probe asks the row**, for the manifest's base branch, with the static token only.
  3. **Each forge maps its own listing**: Azure DevOps its enabled policy configurations scoped to
     this repository and branch; GitHub the branch's rules about the pull request; the local
     forge `[]`; and an unreadable listing is `None` on every one of them.

The guard is `tests/test_the_doctor_names_the_gates_only_a_person_settles.py`.
"""

TEST = "tests/test_the_doctor_names_the_gates_only_a_person_settles.py"

DOCTOR = "openfactory/doctor.py"
BASE = "openfactory/adapters/forge/base.py"
ADO = "openfactory/adapters/forge/azure_devops.py"
GITHUB = "openfactory/adapters/forge/github.py"
LOCAL = "openfactory/adapters/forge/local.py"

MUTATIONS = [
    # ── claim 1: the finding ──────────────────────────────────────────────────────────────────
    ("an OPTIONAL policy is named as a gate every merge waits on — the case seen, as a finding",
     DOCTOR,
     '            and r.get("blocking") is True and r.get("kind") == "process"]\n',
     '            and r.get("kind") == "process"]\n'),

    ("a build is named as something only a person settles", DOCTOR,
     '            and r.get("blocking") is True and r.get("kind") == "process"]\n',
     '            and r.get("blocking") is True]\n'),

    ("under auto-merge a gate no agent can settle passes", DOCTOR,
     '    if policy == "auto":\n',
     "    if False:\n"),

    ("anything that is not None is taken for a listing, a mock included", DOCTOR,
     "    rows = p.merge_gates()\n    if not isinstance(rows, list):\n",
     "    rows = p.merge_gates()\n    if rows is None:\n"),

    ("the check never runs", DOCTOR,
     '        *([_guarded("merge_gates", lambda: _merge_gates(probes))] '
     "if probes.merge_gates else []),\n",
     "        *([]),\n"),

    # ── claim 2: the probe ────────────────────────────────────────────────────────────────────
    ("the probe hands its forge a minting provider — a diagnostic that spends", DOCTOR,
     "        return merge_gates_of(build_forge(project, token=forge_token_for(project)), base)\n",
     "        return merge_gates_of(build_forge(project, token=forge_token_for(project),\n"
     "                                          token_provider=object()), base)\n"),

    ("the probe asks about `main` whatever the manifest's base branch is", DOCTOR,
     '        base = getattr(load_manifest_quietly(project), "base_branch", "") or "main"\n',
     '        base = "main"\n'),

    ("a test double's answer is taken for a listing", BASE,
     "    return rows if isinstance(rows, list) else None\n",
     "    return rows\n"),

    ("a listing that raised reads as `no gates`", BASE,
     "                 str(exc)[:160])\n        return None\n    return rows if isinstance",
     "                 str(exc)[:160])\n        return []\n    return rows if isinstance"),

    # ── claim 3: the rows ─────────────────────────────────────────────────────────────────────
    ("Azure DevOps: a disabled or deleted policy is listed as a gate", ADO,
     '            if (not isinstance(config, dict) or not config.get("isEnabled")\n'
     '                    or config.get("isDeleted")):\n',
     "            if not isinstance(config, dict):\n"),

    ("Azure DevOps: a sibling repository's or another branch's policy is listed as this one's "
     "(C-18)", ADO,
     "            if not _policy_applies(config, repository_id, ref):\n                continue\n",
     "            if False:\n                continue\n"),

    ("Azure DevOps: a policy on a folder of branches does not reach the branches in it", ADO,
     "            if ref.startswith(name):\n                return True\n",
     "            if False:\n                return True\n"),

    ("Azure DevOps: a listed process policy carries no remedy, so the doctor names a gate and "
     "no way out", ADO,
     "            if kind == \"process\":\n"
     "                row[\"remedy\"] = _POLICY_REMEDY.get(_policy_type(config)[0],",
     "            if kind == \"never\":\n"
     "                row[\"remedy\"] = _POLICY_REMEDY.get(_policy_type(config)[0],"),

    ("Azure DevOps: an unreadable listing reads as `no gates`", ADO,
     '            log.info("could not list the branch policies of %s (%s)", self.repo, '
     "str(exc)[:160])\n            return None\n",
     '            log.info("could not list the branch policies of %s (%s)", self.repo, '
     "str(exc)[:160])\n            return []\n"),

    ("GitHub: a required review is not a gate", GITHUB,
     "                if wanted > 0:\n",
     "                if False:\n"),

    ("GitHub: required status checks are dropped from the listing", GITHUB,
     '            elif kind == "required_status_checks":\n',
     '            elif kind == "never":\n'),

    ("GitHub: an unreadable listing reads as `no gates`", GITHUB,
     '            return None\n        try:\n            rules = _json.loads(p.stdout or "[]")\n',
     '            return []\n        try:\n            rules = _json.loads(p.stdout or "[]")\n'),

    ("the local forge says it cannot tell, when it can", LOCAL,
     'it can: the forge is a directory on this machine."""\n        return []\n',
     'it can: the forge is a directory on this machine."""\n        return None\n'),
]
