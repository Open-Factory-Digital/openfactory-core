"""The second yes is the requester's — the cuts that let any admin promise for anybody."""

TEST = "tests/test_the_second_yes_is_the_requesters.py"

MUTATIONS = [
    ("the act does not ask whose yes it is",
     "openfactory/product/module.py",
     "        refused = _not_the_requester(cfg, actor=actor, "
     "requester=getattr(req, \"asked_by\", \"\"),\n",
     "        refused = \"\" and _not_the_requester(cfg, actor=actor, "
     "requester=getattr(req, \"asked_by\", \"\"),\n"),

    ("the configuration is ignored — an admin is always let through",
     "openfactory/product/module.py",
     '    if getattr(cfg, "accept_on_behalf", False):\n        return ""\n',
     '    if True:\n        return ""\n'),

    ("the stamp does not ask whose yes it is",
     "openfactory/product/module.py",
     "        refused = _not_the_requester(getattr(self.project, \"product\", None), "
     "actor=actor,\n",
     "        refused = \"\" and _not_the_requester(getattr(self.project, \"product\", None), "
     "actor=actor,\n"),

    ("a result that cannot say it landed is treated as landed",
     "openfactory/product/confirm.py",
     '    if not getattr(result, "merged", False):\n',
     '    if not getattr(result, "merged", True):\n'),

    # hermes, #70: the gate knew five phrases for "nobody" and brownfield wrote a sixth
    ("a sentence in the field is a person again — nobody is a list, not a shape",
     "openfactory/product/corpus.py",
     "    if not who or who.lower() == UNRECORDED or any(ch.isspace() for ch in who):\n",
     "    if not who or who.lower() == UNRECORDED:\n"),

    ("the placeholder is a person again",
     "openfactory/product/corpus.py",
     "    if not who or who.lower() == UNRECORDED or any(ch.isspace() for ch in who):\n",
     "    if not who or any(ch.isspace() for ch in who):\n"),

    ("brownfield spells nobody its own way again",
     "openfactory/product/brownfield.py",
     '        f"- **Asked by:** {UNRECORDED}",\n',
     '        "- **Asked by:** nobody — reverse-engineered from the code",\n'),

    ("the card names the placeholder as the person it awaits",
     "openfactory/product/module.py",
     '    return asked_by if requester_identity(asked_by) else "the requester"\n',
     '    return asked_by or "the requester"\n'),
]
