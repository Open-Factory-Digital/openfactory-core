"""A manifest whose stages nothing would observe is refused when it loads, and a pending deploy
is not a reached stage (#501).

The claims, one row each:
  (a) environments with no `promote:` and neither `staging` nor `prod` are refused at load;
  (b) a stage the chain walks with neither `deploy_ref` nor `health_url` is refused at load —
      production included — while an environment the chain does NOT walk is still only warned;
  a pending deploy is waited for, inside ONE window for the whole walk, and still pending at its
  end is "not reached": held, said as its own sentence, and on production never rolled back.
"""

TEST = "tests/test_a_manifest_that_would_announce_early_is_refused.py"
MANIFEST = "openfactory/contracts/manifest.py"
PROMO = "openfactory/orchestrator/promotion.py"
EXAMPLE = "docs/project.yaml.example"

MUTATIONS = [
    # ── (a) the derived chain that walks nothing ────────────────────────────────────────────────
    ("a `qa`-only manifest loads again and is announced at the merge", MANIFEST,
     "            if not stages and production is None:",
     "            if False:"),

    # ── (b) a stage with nothing to observe ─────────────────────────────────────────────────────
    ("a chain stage with neither probe loads again", MANIFEST,
     "                 and not (env.deploy_ref or env.health_url)]",
     "                 and False]"),
    ("production is left out of the stages that must be observed", MANIFEST,
     "        walked = [*stages, *([production] if production else [])]",
     "        walked = [*stages]"),
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
    ("each stage gets a window of its own, and the walk outlives its box", PROMO,
     "            seen = self._verify(ref, self.manifest.environments.get(name), deadline=deadline)",
     "            seen = self._verify(ref, self.manifest.environments.get(name),\n"
     "                                deadline=self.clock() + self.reach_window)"),
    ("a production deploy still pending is rolled back as if it were red", PROMO,
     "        if seen == \"not reached\":\n            # NOT LIVE",
     "        if False:\n            # NOT LIVE"),
    ("not reached is said as a failure", PROMO,
     "        if seen == \"not reached\":\n            window =",
     "        if False:\n            window ="),

    # ── the document a reader copies ────────────────────────────────────────────────────────────
    ("the example promises a stage with neither probe passes through unchecked again", EXAMPLE,
     "# chain, production included, declares one or both: a stage with neither would count as "
     "reached\n",
     "# chain may declare one or both; a stage with neither is passed through unchecked, reached\n"),
]
