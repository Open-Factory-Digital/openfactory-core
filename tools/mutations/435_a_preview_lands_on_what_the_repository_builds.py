"""A preview's front door is the declared entry, else a service the repository builds (#435)."""

TEST = "tests/test_a_preview_lands_on_what_the_repository_builds.py"
PREVIEW = "openfactory/preview/__init__.py"
ASSEMBLE = "openfactory/preview/assemble.py"
STEPS = "openfactory/preview/steps.py"
MANIFEST = "openfactory/contracts/manifest.py"
PRODUCT = "openfactory/contracts/product.py"
PRODUCT_SHAPE = "openfactory/preview/product.py"

MUTATIONS = [
    ("a pulled service is ranked with what the repository builds — infrastructure is the door",
     PREVIEW,
     "                    not self.built.get(s, False),\n",
     "                    False,\n"),
    ("the declared entry is not put first", PREVIEW,
     "            return (bool(self.entry) and s != self.entry,\n",
     "            return (False,\n"),
    ("the plan does not say what the compose document builds", ASSEMBLE,
     '        built={n: "build" in services_in[n] for n in cfg.expose if n in services_in},\n',
     "        built={},\n"),
    ("the plan drops the declared entry", ASSEMBLE,
     "        entry=cfg.entry,\n",
     '        entry="",\n'),
    ("the live record forgets what is built and the entry", STEPS,
     "            built=dict(planned.built), entry=planned.entry,\n",
     ""),
    ("the manifest accepts an entry nobody may open", MANIFEST,
     "        if self.entry and self.entry not in self.expose:\n",
     "        if False:\n"),
    ("the product block accepts an entry nobody may open", PRODUCT,
     "        if self.entry and self.entry not in self.expose:\n",
     "        if False:\n"),
    ("a product's declared entry never reaches the assembler", PRODUCT_SHAPE,
     "                             data=dict(p.data), exclude=list(p.exclude), entry=p.entry)",
     "                             data=dict(p.data), exclude=list(p.exclude))"),
]
