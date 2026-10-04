"""A manifest whose stages nothing would observe is refused when it loads, and a pending deploy
is not a reached stage (#501).

The claims, one row each:
  (a) environments with no `promote:` and neither `staging` nor `prod` are refused at load;
  (b) a stage the chain walks with neither `deploy_ref` nor `health_url` is refused at load —
      production included — while an environment the chain does NOT walk is still only warned;
  a pending deploy is waited for, inside ONE window for the whole walk, and still pending at its
  end is "not reached": held, said as its own sentence, and on production never rolled back.

And #518 — a stage counts as reached ONLY on what was observed:
  (c) `unknown` / `none` with no `health_url` is "not reached" — held, in a sentence of its own
      (both languages), the cause carried to the hold — while a GREEN deploy alone still reaches;
  (d) with a `health_url`, the probe decides — healthy reaches, unhealthy is red — and the `none`
      row really probes it;
  (e) on a project whose CI reads no deploy (`ci: none`, a `local` forge) a chain stage with no
      `health_url` is refused when the manifest loads — production included — through the
      context the loader fills from the registry row, and only a row that DECLARES it reads none;
  (f) the compatibility rule says a pre-1.0 minor may refuse such a shape, and the docs say #518.
"""

TEST = "tests/test_a_manifest_that_would_announce_early_is_refused.py"
MANIFEST = "openfactory/contracts/manifest.py"
PROMO = "openfactory/orchestrator/promotion.py"
EXAMPLE = "docs/project.yaml.example"
LOADER = "openfactory/loader.py"
REGISTRY = "openfactory/adapters/environment/registry.py"
NONE = "openfactory/adapters/environment/none.py"
VOICE = "openfactory/techlead/voice.py"

MUTATIONS = [
    # ── (a) the derived chain that walks nothing ────────────────────────────────────────────────
    ("a `qa`-only manifest loads again and is announced at the merge", MANIFEST,
     "            if not stages and production is None:",
     "            if False:"),

    # ── (b) a stage with nothing to observe ─────────────────────────────────────────────────────
    ("a chain stage with neither probe loads again", MANIFEST,
     "                 and not (env.deploy_ref or env.health_url)]",
     "                 and False]"),
    # re-pinned 2026-10-04: #518's sibling validator walks the same chain, so the line is pinned
    # by the one after it (#518)
    ("production is left out of the stages that must be observed", MANIFEST,
     "        walked = [*stages, *([production] if production else [])]\n        blind =",
     "        walked = [*stages]\n        blind ="),
    ("an environment the chain does not walk is refused instead of warned", MANIFEST,
     "        blind = [name for name in walked\n",
     "        blind = [name for name in self.environments\n"),

    # ── a pending deploy ────────────────────────────────────────────────────────────────────────
    ("a deploy still pending at the window's end passes as reached again", PROMO,
     "            if status == \"pending\":\n                log.warning(",
     "            if status == \"never\":\n                log.warning("),
    ("a pending deploy is not waited for", PROMO,
     "            while status == \"pending\" and self.clock() < deadline:",
     "            while False:"),
    # re-pinned 2026-10-04: `_verify` answers why as well, so the call is on two lines (#518)
    ("each stage gets a window of its own, and the walk outlives its box", PROMO,
     "                                     deadline=deadline)",
     "                                     deadline=self.clock() + self.reach_window)"),
    ("a production deploy still pending is rolled back as if it were red", PROMO,
     "        if seen == \"not reached\":\n            # NOT LIVE",
     "        if False:\n            # NOT LIVE"),
    # re-pinned 2026-10-04: the unread sentence comes first, so this branch is an `elif` (#518)
    ("not reached is said as a failure", PROMO,
     "        elif seen == \"not reached\":\n            window =",
     "        elif False:\n            window ="),

    # ── the document a reader copies ────────────────────────────────────────────────────────────
    ("the example promises a stage with neither probe passes through unchecked again", EXAMPLE,
     "# chain, production included, declares one or both: a stage with neither would count as "
     "reached\n",
     "# chain may declare one or both; a stage with neither is passed through unchecked, reached\n"),

    # ── #518 (c): what nothing read is not reached ─────────────────────────────────────────────
    ("a deploy nothing read, with no health_url, counts as reached again", PROMO,
     "        return \"not reached\", \"unread\"\n",
     "        return \"reached\", \"\"\n"),
    ("a GREEN deploy with no health_url is held too", PROMO,
     "        if status == \"success\":\n            return \"reached\", \"\"\n",
     "        if False:\n            return \"reached\", \"\"\n"),
    ("a stage nothing read is said as a deploy still pending", PROMO,
     "        if seen == \"not reached\" and why == \"unread\":",
     "        if False:"),
    ("the cause is dropped on the way to the hold", PROMO,
     "                return self._failed_env(ticket_ref, name, seen, why)",
     "                return self._failed_env(ticket_ref, name, seen)"),
    ("the nothing-read sentence is English in a pt-BR project", VOICE,
     "        \"pt-BR\": \"⏸️ {env} não alcançado: nenhum deploy desta mudança foi lido lá e ele não \"",
     "        \"pt-BR\": \"⏸️ {env} not reached: no deploy of this change was read there, ele não \""),

    # ── #518 (d): with a health_url, the probe decides ──────────────────────────────────────────
    ("an unhealthy probe reaches the stage", PROMO,
     "            return (\"reached\" if self.observer.health(url=env.health_url) else \"red\"), \"\"",
     "            return \"reached\", \"\""),
    ("an unknown or none deploy is held without asking the health_url", PROMO,
     "        if env.health_url:\n            return (\"reached\" if",
     "        if status in (\"unknown\", \"none\"):\n"
     "            return \"not reached\", \"unread\"\n"
     "        if env.health_url:\n            return (\"reached\" if"),
    ("the none row answers False without probing again", NONE,
     "            return httpx.get(url, timeout=timeout).is_success",
     "            return False"),

    # ── #518 (e): refused when the manifest loads ───────────────────────────────────────────────
    ("a project whose CI reads no deploy loads a stage only a deploy would show", MANIFEST,
     "        if not kind:\n            return self\n",
     "        if True:\n            return self\n"),
    ("a deploy_ref alone is taken for an observation there", MANIFEST,
     "                    if (env := self.environments.get(name)) is not None and not env.health_url]",
     "                    if (env := self.environments.get(name)) is not None\n"
     "                    and not (env.deploy_ref or env.health_url)]"),
    ("production is left out of the stages a health_url must probe", MANIFEST,
     "        walked = [*stages, *([production] if production else [])]\n        unprobed =",
     "        walked = [*stages]\n        unprobed ="),
    ("the loader validates without the registry's half", LOADER,
     "        manifest = Manifest.model_validate(data, context=_what_only_the_registry_knows(project))",
     "        manifest = Manifest.model_validate(data)"),
    ("the none row stops declaring that it reads no deploy", REGISTRY,
     "_none.reads_deploys = False\n",
     "_none.reads_deploys = True\n"),
    ("every CI is taken to read no deploy", REGISTRY,
     "    return declared is not False\n",
     "    return False\n"),

    # ── #518 (f): the rule and the documents ────────────────────────────────────────────────────
    ("the compatibility rule loses the line #501 and #518 stand on", MANIFEST,
     "#:   may refuse in a   a shape that silently did the WRONG THING — keeping version 1, with the\n",
     "#:   (nothing narrows version 1 without a bump)\n"),
    ("the example no longer says a stage counts only on what was observed", EXAMPLE,
     "# A stage counts as reached ONLY on what was observed (#518): a green deploy of this change, or a\n",
     "# A stage counts as reached on a green deploy of this change, or a\n"),
]
