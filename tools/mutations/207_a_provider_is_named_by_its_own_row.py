"""#207, proven by breaking it — what a provider is called comes from its own row.

`runtime/temporal/view.py` kept `_FORGE_LABELS`, a table from CI kind to the panel's heading, so
an add-on's CI was shown by its registry key and showing it properly meant editing the core. The
observer rows now declare `display_name` where they are declared, `plugins.display_name` is the
one rule for what counts as a declaration (the forge's `display_name`, from #184, goes through it
too), and the view asks.

THREE CLAIMS:

  1. **Generic code spells no provider's display name** — parsed over the whole package outside
     `adapters/`, with one exemption by name.
  2. **A row's declared name reaches the heading and the payload the panel draws** — built-in or
     add-on; a row that declares nothing is shown by its kind, and a test double is not a row.
  3. **Every shipped observer row says what it is called**, `none` included: "nothing is watched"
     is that row's own sentence (ADR-0049 D1).

The guard is `tests/test_a_provider_is_named_by_its_own_row.py`.
"""

TEST = "tests/test_a_provider_is_named_by_its_own_row.py"

VIEW = "openfactory/runtime/temporal/view.py"
PLUGINS = "openfactory/plugins.py"
REGISTRY = "openfactory/adapters/environment/registry.py"
FORGE_BASE = "openfactory/adapters/forge/base.py"

MUTATIONS = [
    # ── claim 1: no table in generic code ─────────────────────────────────────────────────────
    ("THE DEFECT ITSELF: the view looks the heading up in a table of its own", VIEW,
     "        return observer_name(ProjectRegistry().get(project))\n",
     "        from openfactory.adapters.environment.registry import observer_kind\n"
     "        kind = observer_kind(ProjectRegistry().get(project))\n"
     '        return {"github": "GitHub Actions", "gitlab": "GitLab"}.get(kind, kind)\n'),

    # ── claim 2: the row's name reaches the reader ────────────────────────────────────────────
    ("the row is found and never asked: every CI is shown by its registry key", REGISTRY,
     "    return plugins.display_name(row, kind)\n",
     "    return kind\n"),

    ("only the built-in table is consulted, so an add-on's name is never read", REGISTRY,
     "    row = OBSERVERS.get(kind) or plugins.builder(AXIS, kind, builtin=OBSERVERS)\n",
     "    row = OBSERVERS.get(kind)\n"),

    ("the heading reads the FORGE's kind again, and names one system over another's checks "
     "(ADR-0049 D6 has to survive the move)", REGISTRY,
     "    kind = observer_kind(project)\n"
     "    row = OBSERVERS.get(kind) or",
     "    from openfactory.adapters.forge.registry import forge_kind\n"
     "    kind = forge_kind(project)\n"
     "    row = OBSERVERS.get(kind) or"),

    # re-pinned 2026-09-19: the rule is `plugins.sentence`'s now, and `display_name` asks it.
    ("any truthy attribute is a name, so a mock row names itself", PLUGINS,
     "    return declared.strip() if isinstance(declared, str) and declared.strip() "
     "else default\n",
     "    return str(declared) if declared else default\n"),

    ("a row that declares nothing is given an invented name instead of its kind", REGISTRY,
     "    return plugins.display_name(row, kind)\n",
     '    return plugins.display_name(row, "CI")\n'),

    ("the forge's name stops going through the one rule", FORGE_BASE,
     '    return plugins.display_name(forge, "the forge")\n',
     '    return getattr(forge, "display_name", "") or "the forge"\n',
     "tests/test_the_repair_brief_states_the_failure_it_was_given.py"),

    # ── claim 3: the shipped rows ─────────────────────────────────────────────────────────────
    ("the GitHub Actions row stops saying what it is called", REGISTRY,
     '_github_actions.display_name = "GitHub Actions"\n',
     '_github_actions.display_name = ""\n'),

    ("the Azure Pipelines row stops saying what it is called", REGISTRY,
     '_azure_pipelines.display_name = "Azure Pipelines"\n',
     '_azure_pipelines.display_name = ""\n'),

    ("`none` loses its sentence, and the panel shows a key where it said nothing is watched",
     REGISTRY,
     '_none.display_name = "nothing is watched"\n',
     '_none.display_name = ""\n'),
]
