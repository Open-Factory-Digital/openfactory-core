"""The backfill's reason for downgrading, and the eight ways it goes back to being untrue.

THE DEFECT. `_backfill` picked its mode from a binary resolved per-role and a credential that was
two hardcoded Anthropic variable names:

    binary = harness_binary(harness_kind(project, "techlead"))
    has_credential = bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
                          or os.environ.get("ANTHROPIC_API_KEY"))

So every deployment running `codex`, `kimi` or `opencode` took the else-branch on every onboarding,
whatever it had configured, and was told "no harness credential on this machine" — false, naming no
variable that would fix it, and sending a reader after a token they do not need. The platform held
the right answer in one place, `routes.resolve_route`, and nobody asked it.

ROW 3 IS THE SUBTLEST AND THE REASON `role` EXISTS AT ALL. `resolve_route` resolved
`harness_kind(project, "executor")` unconditionally, and `harness:` is per-role — so a project
running one harness for the executor and another for its roles got a WELL-FORMED answer about the
wrong harness. Nothing raises, nothing looks odd, and the sentence is confidently wrong.

ROW 7 IS THE ONE A REVIEWER SHOULD PUSH BACK ON. `codex` and `kimi` reach the generic route with
empty `requires`, because nobody here has verified which variable either reads. Treating "no
declared requirement" as "requirement unmet" would refuse a working deployment BY NAME, which is
the more expensive of the two mistakes — so an unknown route is attempted, and `propose_context`'s
own arms report a real failure with a real reason. Guessing a variable name would be worse than
either.
"""

TEST = "tests/test_the_backfill_names_the_real_reason.py"

MUTATIONS = [
    # ── the defect, restored ────────────────────────────────────────────────────────────────────
    ("the route is not asked and the two Anthropic variables come back, so every codex, kimi and "
     "opencode deployment is told it has no credential — the defect exactly as it shipped",
     "openfactory/onboarding/onboard.py",
     "        missing = route.missing(dict(os.environ))",
     ('        missing = [] if (os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")\n'
      '                         or os.environ.get("ANTHROPIC_API_KEY")) else ["a credential"]')),

    ("the backfill asks about the EXECUTOR's harness while running the tech-lead's, so the answer "
     "is well-formed and about the wrong thing",
     "openfactory/onboarding/onboard.py",
     '        route = resolve_route(project, role="techlead")',
     "        route = resolve_route(project)"),

    ("`resolve_route` ignores the role it is handed and always answers for the executor — the "
     "silent half of the defect, and the reason the parameter exists",
     "openfactory/adapters/agent/routes.py",
     "    kind = harness_kind(project, role)",
     '    kind = harness_kind(project, "executor")'),

    ("the opencode route reads the EXECUTOR's model to answer about another role, so a project "
     "running one provider for its executor and another for its roles is told the wrong provider",
     "openfactory/adapters/agent/routes.py",
     "    model = model_for(project, role) or \"\"",
     '    model = model_for(project, "executor") or ""'),

    ("the role stops defaulting to the executor, so every caller that predates the parameter — "
     "`box_prove`, `firstrun`, `readiness` — silently starts answering about the tech-lead",
     "openfactory/adapters/agent/routes.py",
     'def resolve_route(project=None, env: dict[str, str] | None = None, *,\n'
     '                  role: str = "executor") -> AuthRoute:',
     'def resolve_route(project=None, env: dict[str, str] | None = None, *,\n'
     '                  role: str = "techlead") -> AuthRoute:'),

    # ── the two reasons collapse back into one ──────────────────────────────────────────────────
    ("an uninstalled harness is reported as a missing credential again, so a reader goes looking "
     "for a token they already have instead of installing the binary",
     "openfactory/onboarding/onboard.py",
     "        if not which_mod.which(binary):\n"
     "            return None, (f\"deterministic (the {kind} binary `{binary}` is not on this "
     "machine's \"",
     "        if False:\n"
     "            return None, (f\"deterministic (the {kind} binary `{binary}` is not on this "
     "machine's \""),

    ("the downgrade names no variable, so the sentence is a diagnosis with no remedy — which is "
     "what sent readers after the wrong token in the first place",
     "openfactory/onboarding/onboard.py",
     "                          f\"{route.name} route — it needs {' and '.join(missing)}; the "
     "survey \"",
     '                          f"{route.name} route; the survey "'),

    # ── the expensive direction ─────────────────────────────────────────────────────────────────
    ("a route that declares NO requirement is treated as one whose requirement is unmet, so a "
     "codex or kimi deployment is refused by name on a credential nobody here has verified it "
     "even needs",
     "openfactory/onboarding/onboard.py",
     "        if missing:",
     "        if missing or not route.requires:"),

    ("a satisfied route stops reaching the agent pass at all, so the backfill silently becomes "
     "deterministic-only for every deployment and every other guard here stays green",
     "openfactory/onboarding/onboard.py",
     "        return ask_fn, \"semantic (one agent pass, every claim citation-checked)\"",
     "        return None, \"semantic (one agent pass, every claim citation-checked)\""),
]
