"""#162, credential sweep — what the adversarial review measured (2026-08-20).

Nine confirmed findings. The one that mattered: the sweep changed which DOOR the GitHub App mint
came in by, not whether it came in — `token_provider` is that door, and the tracker registry's
Jira and Azure rows called it.
"""

TEST = "tests/test_a_credential_is_asked_of_its_own_axis.py"
LAUNCH = "tests/test_the_box_program_can_be_launched.py"
TREG = "openfactory/adapters/tracker/registry.py"
CAT = "openfactory/actions/catalog.py"
TF = "infra/terraform/sandbox_task.tf"
DOCKER = "docker/sandbox.Dockerfile"

MUTATIONS = [
    # ── the door the sweep did not close ────────────────────────────────────────────────────────
    ("the Jira row honours the caller's provider again — the mint reaches Jira", TREG,
     "    token = kw.get(\"token\") or vendor_default(getattr(project, \"tracker\", None))",
     '    token = kw.get("token")\n'
     '    if not token and kw.get("token_provider"):\n        token = kw["token_provider"]()'),

    ("…and the reverse: Jira's own credential stops being read", TREG,
     "    token = kw.get(\"token\") or vendor_default(getattr(project, \"tracker\", None))",
     '    token = kw.get("token")'),

    ("the Azure row honours it again", TREG,
     '    token = kw.get("token")\n    organization, ado_project = coordinates(',
     '    token = kw.get("token")\n'
     '    if not token and kw.get("token_provider"):\n        token = kw["token_provider"]()'),

    ("…and the reverse: an EXPLICIT azure token is dropped", TREG,
     '    token = kw.get("token")\n    organization, ado_project = coordinates(',
     "    token = None\n    organization, ado_project = coordinates("),

    ("the prod release hands the tracker a GitHub token again", CAT,
     "        tracker=build_tracker(p, token=tracker_tok), forge=forge,",
     "        tracker=build_tracker(p, token=token_from_env()), forge=forge,"),

    # ── the ratchet's blind spots ───────────────────────────────────────────────────────────────
    ("the ratchet stops seeing an ALIAS of the mint", TEST,
     '    name = getattr(func, "id", None) or getattr(func, "attr", None) or ""\n'
     '    return name.lstrip("_") == "github_app_token_from_env"',
     '    return getattr(func, "id", "") == "github_app_token_from_env"'),

    ("…and the reverse: it matches anything ending in the name, however unrelated", TEST,
     '    return name.lstrip("_") == "github_app_token_from_env"',
     '    return "github_app_token_from_env" in name'),

    ("the crossed-axis check goes back to a regex blind to a nested call", TEST,
     "            axes = [getattr(v.func, \"id\", \"\") for v in node.values "
     "if isinstance(v, ast.Call)]",
     "            axes = []"),

    # ── the box program ─────────────────────────────────────────────────────────────────────────
    ("the task definition names a module that does not exist", TF,
     '      command   = ["python", "-m", "openfactory.runtime.boxed_job"]',
     '      command   = ["python", "-m", "openfactory.runtime.fargate.entrypoint"]', LAUNCH),

    ("the image CMD does", DOCKER,
     'CMD ["python", "-m", "openfactory.runtime.boxed_job"]',
     'CMD ["python", "-m", "openfactory.runtime.fargate.entrypoint"]', LAUNCH),

    ("…and the two launchers are allowed to disagree", DOCKER,
     'CMD ["python", "-m", "openfactory.runtime.boxed_job"]',
     'CMD ["python", "-m", "openfactory.doctor"]', LAUNCH),
]
