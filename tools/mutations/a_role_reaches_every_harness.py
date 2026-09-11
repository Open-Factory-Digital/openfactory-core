"""A role's instructions reach every harness, not only Claude Code.

The judging roles (sizer, coordinator, tech-lead, chat) were already unified behind `ask()`
(`adapters/agent/techlead.py`), so any harness gets them by implementing the one required
primitive. The CODING roles — planner, executor — never got the same treatment: `codex.py`,
`kimi.py` and `opencode.py` hardcoded their own English instead of reading
`org_defaults/roles/planner.md` / `executor.md` through `roles.role_prompt`, so a deployment's or
project's own house doctrine reached Claude Code and nowhere else. No test caught it, because no
test asserted prompt CONTENT for these three adapters at all — only CLI flag construction.

ROWS 1, 4, 7 cut `plan()`'s role read to nothing, on Codex/Kimi/OpenCode respectively. ROWS 2, 5, 8
do the same for `execute()`. ROWS 3, 6, 9 do the same for `repair()`. Each turns the role prompt
back into the empty string this adapter always sent before — provably the same defect
`test_the_techlead_roles_carry_the_ROLE_FILES_not_adapter_prose` (this repo's own prior instance of
the same claim, one primitive over) already guards for the judging roles.

ROWS 10-12 are the mistake this exact change made once and caught by its own tests: `repair()`'s
instruction ("staying strictly in scope…") is NOT a role-prompt fallback, it is ALWAYS-PRESENT
guidance about what a repair pass is — the role prompt does not say it, and a first draft of this
plan made it disappear the moment `role_prompt` succeeded. One row per adapter, cutting the
instruction out of the always-present path while leaving the role prompt in place.
"""

TEST = "tests/test_agent_harness.py"

MUTATIONS = [
    # ── Codex ──────────────────────────────────────────────────────────────────────────────────
    ("Codex's planner never reads its role file, so `org_defaults/roles/planner.md` — a "
     "deployment's or project's own house doctrine on what a plan must look like — reaches Claude "
     "Code and nowhere else",
     "openfactory/adapters/agent/codex.py",
     '        role = role_prompt("planner")',
     '        role = ""'),

    ("Codex's executor never reads its role file, so `org_defaults/roles/executor.md` (TDD "
     "discipline, scope limits) reaches Claude Code and nowhere else",
     "openfactory/adapters/agent/codex.py",
     '        role = role_prompt("executor")\n'
     '        prompt = f"{role}\\n\\n{ticket_brief(context)}" if role else ticket_brief(context)',
     '        role = ""\n'
     '        prompt = f"{role}\\n\\n{ticket_brief(context)}" if role else ticket_brief(context)'),

    ("Codex's repair pass never reads the executor role file, so a fix attempt on this harness "
     "carries no identity at all, not even the TDD discipline the original attempt had",
     "openfactory/adapters/agent/codex.py",
     '        role = role_prompt("executor")\n'
     '        lead = f"{role}\\n\\n" if role else ""',
     '        role = ""\n'
     '        lead = f"{role}\\n\\n" if role else ""'),

    # ── Kimi ───────────────────────────────────────────────────────────────────────────────────
    ("Kimi's planner never reads its role file",
     "openfactory/adapters/agent/kimi.py",
     '        role = role_prompt("planner")',
     '        role = ""'),

    ("Kimi's executor never reads its role file",
     "openfactory/adapters/agent/kimi.py",
     '        role = role_prompt("executor")\n'
     '        prompt = f"{role}\\n\\n{ticket_brief(context)}" if role else ticket_brief(context)',
     '        role = ""\n'
     '        prompt = f"{role}\\n\\n{ticket_brief(context)}" if role else ticket_brief(context)'),

    ("Kimi's repair pass never reads the executor role file",
     "openfactory/adapters/agent/kimi.py",
     '        role = role_prompt("executor")\n'
     '        lead = f"{role}\\n\\n" if role else ""',
     '        role = ""\n'
     '        lead = f"{role}\\n\\n" if role else ""'),

    # ── OpenCode ───────────────────────────────────────────────────────────────────────────────
    ("OpenCode's planner never reads its role file",
     "openfactory/adapters/agent/opencode.py",
     '        role = role_prompt("planner")',
     '        role = ""',
     "tests/test_opencode_harness.py"),

    ("OpenCode's executor never reads its role file",
     "openfactory/adapters/agent/opencode.py",
     '        role = role_prompt("executor")\n'
     '        prompt = f"{role}\\n\\n{ticket_brief(context)}" if role else ticket_brief(context)',
     '        role = ""\n'
     '        prompt = f"{role}\\n\\n{ticket_brief(context)}" if role else ticket_brief(context)',
     "tests/test_opencode_harness.py"),

    ("OpenCode's repair pass never reads the executor role file",
     "openfactory/adapters/agent/opencode.py",
     '        role = role_prompt("executor")\n'
     '        lead = f"{role}\\n\\n" if role else ""',
     '        role = ""\n'
     '        lead = f"{role}\\n\\n" if role else ""',
     "tests/test_opencode_harness.py"),

    # ── the mistake this change made once: the repair instruction is not a fallback ──────────────
    ("Codex's repair instruction — what THIS pass is, which the role prompt does not say — "
     "disappears the moment a role file resolves, the exact regression this change's own tests "
     "caught in a first draft",
     "openfactory/adapters/agent/codex.py",
     '        prompt = (\n'
     '            lead + f"{REPAIR_INSTRUCTION}\\n\\n"\n'
     '            f"## Failures\\n{failure_log[:12000]}\\n\\n" + ticket_brief(context)\n'
     '        )',
     '        prompt = (\n'
     '            lead\n'
     '            + f"## Failures\\n{failure_log[:12000]}\\n\\n" + ticket_brief(context)\n'
     '        )'),

    ("Kimi's repair instruction disappears the moment a role file resolves",
     "openfactory/adapters/agent/kimi.py",
     '        prompt = (\n'
     '            lead + f"{REPAIR_INSTRUCTION}\\n\\n"\n'
     '            f"## Failures\\n{failure_log[:12000]}\\n\\n" + ticket_brief(context)\n'
     '        )',
     '        prompt = (\n'
     '            lead\n'
     '            + f"## Failures\\n{failure_log[:12000]}\\n\\n" + ticket_brief(context)\n'
     '        )'),

    ("OpenCode's repair instruction disappears the moment a role file resolves",
     "openfactory/adapters/agent/opencode.py",
     '        prompt = (\n'
     '            lead + f"{REPAIR_INSTRUCTION}\\n\\n"\n'
     '            f"## Failures\\n{failure_log[:12000]}\\n\\n" + ticket_brief(context)\n'
     '        )',
     '        prompt = (\n'
     '            lead\n'
     '            + f"## Failures\\n{failure_log[:12000]}\\n\\n" + ticket_brief(context)\n'
     '        )',
     "tests/test_opencode_harness.py"),
]
