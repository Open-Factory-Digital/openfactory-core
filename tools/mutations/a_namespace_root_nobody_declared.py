"""The derived rule has to bite where the deny list could not (public cut, 2026-08-26).

A client's three-letter organisation abbreviation shipped ten times across five files as the
leading segment of a code namespace, and every list-based identity scan was green over it: the
token was not on the list, and the bare three letters could not go ON the list — they are an
ordinary Portuguese word stem carried by four innocent tracked files. Enumeration had no fix to
offer, so `identity_forbidden.foreign_namespaces` derives instead: a coordinate's ROOT segment is
a vendor's published protocol, or something this tree invented, or it is somebody's.

The cuts are the ways that rule can be true and useless. Two put a foreign coordinate back where
one actually was; the rest attack the rule itself — reporting nothing, walking nothing, a shape
too narrow to see a three-segment root, and an allow-list widened with a root nothing uses.

NO FOREIGN COORDINATE IS SPELLED IN THIS FILE. It is composed, for the same reason the guard
composes its own: a tracked file carrying a foreign coordinate is the defect under test.
"""

TEST = "tests/test_the_product_carries_no_owners_name.py"
GUARD = TEST
SHAPES = "tests/identity_forbidden.py"

#: Built from parts, never written out — see the module docstring.
FOREIGN = ".".join(("ZZQ", "CF", "Deskline", "Context"))

MUTATIONS = [
    ("a client's own namespace comes back in an onboarding docstring — the defect itself",
     "openfactory/onboarding/context.py",
     "    `ACM.CA.Deskline.Context` — `docs/arquitetura/`, `docs/decisoes/`, its own `DEC-001…`",
     f"    `{FOREIGN}` — `docs/arquitetura/`, `docs/decisoes/`, its own `DEC-001…`"),

    ("a client's own namespace comes back in a test fixture, where it is 'just a string'",
     "tests/test_knowledge.py",
     '    assert ui.purpose == "Componentes do painel de admissão (ACM.CA.Deskline.UI)."',
     f'    assert ui.purpose == "Componentes do painel de admissão ({FOREIGN})."'),

    ("the rule reports nothing — every coordinate reads as declared",
     SHAPES,
     "            if m.group(0).split(\".\")[0] not in declared]",
     "            if m.group(0).split(\".\")[0] not in declared and False]"),

    ("the scan is built and never walked — no file is read at all",
     GUARD,
     "    for rel in _tracked(root):\n"
     "        text = _content(rel, root)\n"
     "        if text is None:\n"
     "            continue\n"
     "        offenders += [f\"{rel}:{line}  {literal}\"",
     "    for rel in []:\n"
     "        text = _content(rel, root)\n"
     "        if text is None:\n"
     "            continue\n"
     "        offenders += [f\"{rel}:{line}  {literal}\""),

    ("the shape narrows to four segments — a three-segment root walks past it",
     SHAPES,
     r'NAMESPACE_LITERAL = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:\.[A-Z][A-Za-z0-9]*){2,}\b")',
     r'NAMESPACE_LITERAL = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:\.[A-Z][A-Za-z0-9]*){3,}\b")'),

    ("a root this tree DID invent is dropped — proves the scan reads the set, over this tree",
     SHAPES,
     'OUR_NAMESPACE_ROOTS: frozenset[str] = frozenset({"ACM", "Flows"})',
     'OUR_NAMESPACE_ROOTS: frozenset[str] = frozenset({"Flows"})'),

    ("a root nothing uses is declared — the allow-list becomes a place to hide a name",
     SHAPES,
     'OUR_NAMESPACE_ROOTS: frozenset[str] = frozenset({"ACM", "Flows"})',
     'OUR_NAMESPACE_ROOTS: frozenset[str] = frozenset({"ACM", "Flows", "Contoso"})'),
]
