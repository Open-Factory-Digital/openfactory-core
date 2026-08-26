"""The role axis is an axis: a `role.qa` entry point resolves everywhere a shipped role does,
an unregistered name still raises, a shipped role wins a collision, and an unknown phase is
localised (2026-08-24 doctrine: agents around the core are addable without editing core).

Each cut is one way the claim comes apart: the registry stops asking the loader, one surface
keeps iterating the shipped table, a refusal stops refusing, the once-per-role log repeats, one
adapter reverts to the allowlist, the closed coding set drifts.

The second round (2026-08-25, after review) cuts the fact the first round left unmodelled: a
verdict CODE parses gets no language directive — the two shipped ones (`MACHINE_PHASES`) and an
add-on's (`human_facing=False`) — and the platform's variables are reserved by NAMESPACE, a role
may not be named `default` or after a shipped phase, and one variable binds one role.

The third round (2026-08-26, after the second review) cuts the derivation that replaced the last
hand table: each shape of environment read the scan knows drops out one at a time, the scan
stops being consulted, an install with no sources fails open, an export list counts as a read;
the second review's survivor (only the harness slot claimed) is cut again and must now be red; a
bare word passes as an env name; and the role-prompt call-site guard, rewritten to read code
rather than prose, is fed a real unchecked call and a tuple that forgot a called name.
"""

TEST = "tests/test_a_stranger_can_add_a_role.py"

_LOCALISED_OLD = (
    "        from openfactory.adapters.agent.roles import language_directive, "
    "needs_language_directive\n"
    "\n"
    "        if not needs_language_directive(phase):\n")
_LOCALISED_ALLOWLIST = (
    "        from openfactory.adapters.agent.roles import CODING_PHASES, HUMAN_PHASES, "
    "language_directive\n"
    "\n"
    "        if phase in CODING_PHASES or phase not in HUMAN_PHASES:\n")

_CODING_ROW = ('    "plan", "planner", "execute", "executor", "repair", "continue", "recover", '
               '"review",')

MUTATIONS = [
    # ── the registry consults the loader ────────────────────────────────────────────────────────
    ("known_roles() answers the shipped table only",
     "openfactory/adapters/agent/registry.py",
     "    return sorted({*ROLES, *_addon_roles()})",
     "    return sorted(ROLES)"),

    ("the resolvers never look at an add-on spec",
     "openfactory/adapters/agent/registry.py",
     "    spec = addon_role(role)\n    if spec is None:\n        raise ValueError(f\"unknown role",
     "    spec = None\n    if spec is None:\n        raise ValueError(f\"unknown role"),

    ("the loader's builder is loaded and never validated into a role",
     "openfactory/adapters/agent/registry.py",
     "        spec = _valid_role(kind, build)\n        if spec is None:\n            continue",
     "        spec = None\n        if spec is None:\n            continue"),

    ("the add-on's default harness is ignored",
     "openfactory/adapters/agent/registry.py",
     "    return spec.harness_env, spec.model_env, spec.harness or DEFAULT_KIND",
     "    return spec.harness_env, spec.model_env, DEFAULT_KIND"),

    # ── what stays closed ───────────────────────────────────────────────────────────────────────
    ("an add-on may shadow a shipped role (built-ins no longer win)",
     "openfactory/adapters/agent/registry.py",
     "        build = plugins.builder(\"role\", kind, builtin=ROLES)",
     "        build = plugins._load().get(\"role\", {}).get(kind)"),

    ("an add-on may take a shipped PROMPT's name",
     "openfactory/adapters/agent/registry.py",
     "    if kind in shipped_prompt_names():",
     "    if False and kind in shipped_prompt_names():"),

    ("a spec may answer to a name its entry point does not carry",
     "openfactory/adapters/agent/registry.py",
     "    if spec.name != kind:",
     "    if False:"),

    ("a builder returning anything is honoured as a role",
     "openfactory/adapters/agent/registry.py",
     "    if not isinstance(spec, RoleSpec):",
     "    if False:"),

    ("an add-on may read an env var that already means something else",
     "openfactory/adapters/agent/registry.py",
     "        why = environ.reserved(env)\n        if why:",
     "        why = None\n        if why:"),

    ("a role may be named `default`, the per-role fallback key",
     "openfactory/adapters/agent/registry.py",
     "    if kind == FALLBACK_KEY:",
     "    if False:"),

    ("a role may be named after a shipped phase (and decide its language)",
     "openfactory/adapters/agent/registry.py",
     "    if taken_phase:",
     "    if False:"),

    ("the second add-on claiming a variable is accepted (one variable binds two roles)",
     "openfactory/adapters/agent/registry.py",
     "        if clash is not None:\n            _refuse(",
     "        if False:\n            _refuse("),

    ("the refusal is said on every resolution",
     "openfactory/adapters/agent/registry.py",
     "    if kind not in _REFUSED_SAID:\n        _REFUSED_SAID.add(kind)",
     "    if True:\n        _REFUSED_SAID.add(kind)"),

    # ── the platform's variables are reserved by namespace ──────────────────────────────────────
    ("the platform's own prefix is open to add-ons (only a list of names is reserved)",
     "openfactory/environ.py",
     "        if name.startswith(prefix):\n            return f\"under {prefix}*, {whose}\"",
     "        if False:\n            return f\"under {prefix}*, {whose}\""),

    ("a foreign variable the platform reads is open to add-ons (the derivation is not consulted)",
     "openfactory/environ.py",
     "    if name in read:\n        return \"a variable of a tool this platform drives",
     "    if False:\n        return \"a variable of a tool this platform drives"),

    ("an install with no sources reserves nothing (fails open)",
     "openfactory/environ.py",
     "    if not read:\n        return (\"unverifiable",
     "    if False:\n        return (\"unverifiable"),

    ("a subscript read is not a read (shape 1)",
     "openfactory/environ.py",
     "            elif isinstance(node, ast.Subscript):\n"
     "                names.add(_key_of(node.slice, bound))",
     "            elif isinstance(node, ast.Subscript):\n"
     "                pass"),

    ("os.getenv is not a read (shape 1)",
     "openfactory/environ.py",
     '_READ_METHODS = frozenset({"get", "getenv", "pop", "setdefault"})',
     '_READ_METHODS = frozenset({"get", "pop", "setdefault"})'),

    ("a names table is not a read (shape 2, the route's `requires`)",
     "openfactory/environ.py",
     "                found = [_env_shaped(e) for e in node.elts]\n"
     "                if all(found):",
     "                found = [_env_shaped(e) for e in node.elts]\n"
     "                if False:"),

    ("a dict of names is not a read (shape 2, the vendor defaults)",
     "openfactory/environ.py",
     "                found = [_env_shaped(v) for v in node.values]\n"
     "                if all(found):",
     "                found = [_env_shaped(v) for v in node.values]\n"
     "                if False:"),

    ("a default handed to a reading function is not a read (shape 3, `_resolve_token`)",
     "openfactory/environ.py",
     "            if isinstance(node, ast.Call) and _callee(node) in readers:",
     "            if False:"),

    ("a module constant a read names is not a read (shape 4)",
     "openfactory/environ.py",
     "    if isinstance(expr, ast.Name):\n        return bound.get(expr.id)",
     "    if isinstance(expr, ast.Name):\n        return None"),

    ("an export list counts as a read",
     "openfactory/environ.py",
     "                    and id(node) not in exports:",
     "                    and True:"),

    ("only the harness slot of an accepted spec is claimed (the second review's survivor)",
     "openfactory/adapters/agent/registry.py",
     "        claimed[spec.harness_env] = claimed[spec.model_env] = kind",
     "        claimed[spec.harness_env] = kind"),

    ("a bare word (`HOME`) passes as an add-on's env name",
     "openfactory/adapters/agent/roles.py",
     '            if not ENV_NAME_SHAPE.match(env or ""):',
     '            if not re.match(r"^[A-Z][A-Z0-9_]*$", env or ""):'),

    # ── the role-prompt call-site guard reads code, not prose ───────────────────────────────────
    ("a call site passes a prompt name the readiness tuple does not check",
     "openfactory/adapters/agent/roles.py",
     "",
     "\n\ndef _unchecked_call_site() -> str:\n    return role_prompt(\"nobody_checks\")\n",
     "tests/test_three_commands_one_verdict.py"),

    ("the readiness tuple forgets a prompt a caller passes",
     "openfactory/onboarding/readiness.py",
     '    "coordinator", "executor", "planner", "product", "recovery", "sizer", "techlead",',
     '    "coordinator", "executor", "planner", "product", "recovery", "techlead",',
     "tests/test_three_commands_one_verdict.py"),

    # ── the value refuses what would fail later and silently ────────────────────────────────────
    ("an empty prompt is accepted at declaration",
     "openfactory/adapters/agent/roles.py",
     "        if not (self.prompt or \"\").strip():",
     "        if False:"),

    ("one env var may name both the harness and the model",
     "openfactory/adapters/agent/roles.py",
     "        if self.harness_env == self.model_env:",
     "        if False:"),

    # ── the prompt ──────────────────────────────────────────────────────────────────────────────
    ("role_prompt never reads an add-on's own text",
     "openfactory/adapters/agent/roles.py",
     "    spec = addon_role(role)\n    if spec is not None:\n        return spec.prompt",
     "    spec = addon_role(role)\n    if spec is not None and False:\n        return spec.prompt"),

    # ── the two surfaces the first draft would have left unreached ──────────────────────────────
    ("set-model --role validates against the shipped table",
     "openfactory/registry.py",
     "            from openfactory.adapters.agent.registry import known_roles\n\n"
     "            known = known_roles()",
     "            from openfactory.adapters.agent.registry import ROLES\n\n"
     "            known = sorted(ROLES)"),

    ("the panel cockpit iterates the shipped table",
     "openfactory/api/app.py",
     "    for role in known_roles():",
     "    for role in (\"executor\", \"reviewer\", \"techlead\", \"product\"):"),

    # ── the registry file's unknown-role warning ────────────────────────────────────────────────
    ("a role key nothing reads loads silently",
     "openfactory/registry.py",
     "        for field in (\"harness\", \"model\"):",
     "        for field in ():"),

    ("`default` is reported as a typo",
     "openfactory/registry.py",
     "                for key in sorted(set(per_role) - {*known_roles(), FALLBACK_KEY}):",
     "                for key in sorted(set(per_role) - {*known_roles()}):"),

    ("an installed add-on's key is reported as a typo",
     "openfactory/registry.py",
     "                for key in sorted(set(per_role) - {*known_roles(), FALLBACK_KEY}):",
     "                for key in sorted(set(per_role) - {\"executor\", \"reviewer\", \"techlead\", "
     "\"product\", \"default\"}):"),

    # ── language: one adapter reverts to the allowlist ──────────────────────────────────────────
    ("claude_code reverts to the allowlist",
     "openfactory/adapters/agent/claude_code.py", _LOCALISED_OLD, _LOCALISED_ALLOWLIST),
    ("codex reverts to the allowlist",
     "openfactory/adapters/agent/codex.py", _LOCALISED_OLD, _LOCALISED_ALLOWLIST),
    ("kimi reverts to the allowlist",
     "openfactory/adapters/agent/kimi.py", _LOCALISED_OLD, _LOCALISED_ALLOWLIST),
    ("opencode reverts to the allowlist",
     "openfactory/adapters/agent/opencode.py", _LOCALISED_OLD, _LOCALISED_ALLOWLIST),

    ("one adapter localises the coding path too",
     "openfactory/adapters/agent/kimi.py",
     "        if not needs_language_directive(phase):\n            return prompt",
     "        if False:\n            return prompt"),

    # ── language: the verdicts code parses ──────────────────────────────────────────────────────
    ("the two shipped verdict phases are localised again (the review's blocker, re-opened)",
     "openfactory/adapters/agent/roles.py",
     'MACHINE_PHASES: frozenset[str] = frozenset({"product_confirm", "product_accept"})',
     "MACHINE_PHASES: frozenset[str] = frozenset()"),

    ("a verdict phase joins the coding set (two facts in one name)",
     "openfactory/adapters/agent/roles.py",
     _CODING_ROW, _CODING_ROW + ' "product_confirm",'),

    ("one adapter decides by its own rule, not the shared one (a verdict is localised there)",
     "openfactory/adapters/agent/codex.py",
     "        if not needs_language_directive(phase):\n            return prompt",
     "        from openfactory.adapters.agent.roles import CODING_PHASES\n"
     "        if phase in CODING_PHASES:\n            return prompt"),

    ("an add-on's `human_facing=False` is not read (the flag reached by nothing, again)",
     "openfactory/adapters/agent/roles.py",
     "    return spec is None or spec.human_facing",
     "    return True"),

    ("an add-on owns only the phase spelled exactly like it (`qa_verdict` is nobody's)",
     "openfactory/adapters/agent/registry.py",
     '    return phase == role or phase.startswith(f"{role}_")',
     "    return phase == role"),

    # ── the closed coding set drifts ────────────────────────────────────────────────────────────
    ("codex's coding label falls out of the closed set (its executor prompt gets localised)",
     "openfactory/adapters/agent/roles.py",
     _CODING_ROW,
     '    "plan", "execute", "repair", "continue", "recover", "review",'),

    ("a human phase joins the coding set (two facts in one value)",
     "openfactory/adapters/agent/roles.py",
     _CODING_ROW, _CODING_ROW + ' "ask",'),
]
