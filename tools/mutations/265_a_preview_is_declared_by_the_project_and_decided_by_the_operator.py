"""Mutation plan for #265 slice 1, the contracts half — a preview is declared by the project and
decided by the operator (ADR-0050 D3, D8, D9, §8).

Each row takes away one rule; every row must turn the test file red.
"""

TEST = "tests/test_a_preview_is_declared_by_the_project_and_decided_by_the_operator.py"
MANIFEST = "openfactory/contracts/manifest.py"
PROJECT = "openfactory/contracts/project.py"
REGISTRY = "openfactory/registry.py"
FLOOR = "openfactory/org_defaults/floor.yaml"
PROTECTED = "openfactory/policy/protected.py"
POLICY = "openfactory/orchestrator/merge_policy.py"
MACHINE = "openfactory/orchestrator/machine.py"

MUTATIONS = [
    ("a compose path may climb out of the repository", MANIFEST,
     "            if not p or p.startswith((\"/\", \"~\")) or \"$\" in p or \"..\" in p.split(\"/\"):",
     "            if not p or p.startswith((\"/\", \"~\")) or \"$\" in p:"),
    ("a service may be both opened and excluded", MANIFEST,
     "        both = sorted(set(self.expose) & set(self.exclude))",
     "        both = []"),
    ("a name with the factory's own prefix reaches a preview", PROJECT,
     "    if name in PREVIEW_ENV_DENIED or name.startswith(PREVIEW_ENV_DENIED_PREFIXES):",
     "    if name in PREVIEW_ENV_DENIED:"),
    ("a factory credential passes when it is only the WORKER side of a mapping", PROJECT,
     "            why = preview_name_refused(str(container)) or preview_name_refused(str(worker))",
     "            why = preview_name_refused(str(container))"),
    ("the host's network is accepted as egress", PROJECT,
     "        if v in (\"bridge\", \"host\") or (v and not re.fullmatch(",
     "        if (v and not re.fullmatch("),
    ("a preview may live for ever", PROJECT,
     "            return min(max(int(v), 1), 24 * 7)",
     "            return max(int(v), 1)"),
    ("a run-time name reaches a build", PROJECT,
     "        table = self.build_args if build else self.env",
     "        table = self.env"),
    ("a token_env is written into the file and filtered only on the way out", REGISTRY,
     "            clean = _without_foreign_tokens(project, everyone).preview",
     "            clean = project.preview"),
    ("a hand-edited token_env reaches a preview through get()", REGISTRY,
     "        return _without_foreign_tokens(project, others)",
     "        return project"),
    ("two projects may share a slug", REGISTRY,
     "            if twin is not None:\n                raise ValueError(",
     "            if False:\n                raise ValueError("),
    ("a docker-compose.yml merges by itself", FLOOR,
     "  - \"docker-compose.yml\"\n",
     ""),
    ("a project's own compose files are not floored", PROTECTED,
     "        own += tuple(p.strip() for p in preview.compose if p.strip())",
     "        pass"),
    ("a project that requires a look is merged by the factory", POLICY,
     "    if result.preview_required:\n        return False\n",
     ""),
    ("the job never reads the operator's decision", MACHINE,
     "            result.preview_required = bool(getattr(getattr(self.project, \"preview\", None),",
     "            result.preview_required = False and bool(getattr(getattr(self.project, \"preview\", None),"),
    ("a shape change is signed off without the files it points at", MACHINE,
     "            result.preview_shape = self._preview_shape(ws)\n",
     ""),
    ("the shape follows a line out of the repository", MACHINE,
     "                digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12] if inside else \"\"",
     "                digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]"),
    ("a change that touches nothing of the shape still prints one", MACHINE,
     "        if not any(h in self._SHAPE_NAMES or h.startswith(\".openfactory/\") for h in hits):",
     "        if False:"),
    ("the body drops the files a shape change points at", MACHINE,
     "        if result.preview_shape:\n            lines += [\"\", \"## What merging this lets the factory run\",",
     "        if False:\n            lines += [\"\", \"## What merging this lets the factory run\","),
]
