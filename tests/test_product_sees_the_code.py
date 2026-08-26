"""The role must be able to open the product's code — and must never claim it can when it cannot.

The product owner, 2026-07-29, after asking the product role to write the requirements of an
existing product: *"shouldn't she have access to the code repo?"* She should — her own
instructions said
so. The runtime handed over the documentation checkout alone, so she answered, correctly:

    "não tenho o código do produto acessível, só a pasta de requisitos. Sem ele, qualquer coisa
     que eu escreva sobre o comportamento actual é adivinhação."

Refusing to guess is exactly right. The defect is that the system had promised her something and
not delivered it — a prompt that asserts a capability the runtime may not provide is a lie the
agent then repeats to a client, or (as here) is caught out by.
"""

from __future__ import annotations

from pathlib import Path

from openfactory.product.role import ProductRole


class _Agent:
    name = "fake"


def test_the_prompt_names_the_code_when_it_is_mounted():
    role = ProductRole(_Agent(), mounted={"docs": "documentation", "code": "code"})
    text = "\n".join(role._sources_section())
    assert "code/" in text
    assert "read it" in text.lower()


def test_the_prompt_says_PLAINLY_when_the_code_is_absent():
    """The honest degradation: it must tell her she cannot verify behaviour, not stay silent and
    let her infer that silence means access."""
    role = ProductRole(_Agent(), mounted={"docs": ".", "code": ""})
    text = "\n".join(role._sources_section())
    assert "NOT the source code" in text
    assert "guessing is worse" in text


def test_the_role_prompt_no_longer_ASSERTS_code_access():
    """The fixed sentence was the root cause: `product.md` promised source access unconditionally,
    while only one of the role's operations ever received it."""
    doc = Path("openfactory/org_defaults/roles/product.md").read_text()
    assert "You also have read access to the source code" not in doc, (
        "the role's instructions assert access the runtime may not provide"
    )
    assert "What you can open" in doc, "the prompt must point at the mounted list instead"


def test_both_repositories_are_mounted_under_one_root():
    """The agent runs with `cwd` at the workspace root, so everything it may open has to live
    inside it — through the ONE mechanism written for that (`product/workspace.py`).

    THIS TEST USED TO PIN THE OPPOSITE. It asserted `symlink` appeared in the body, with the
    reason "copying two checkouts on every message would be absurd" — a real cost concern that
    reached the wrong conclusion, because `compose()` already avoided both: git worktrees are real
    files whose objects are shared, and it is idempotent at a stable root, so the unchanged turn
    costs a `rev-parse`. That function existed, was tested, and was called by nothing — the
    fifteenth instance of this codebase's signature defect, and this test is why it survived: it
    defended the workaround instead of the property.

    So the property is what is pinned now: the conversational mount goes through `compose`, and the
    names the prompt is given are DERIVED from where things were actually put rather than from
    constants two places have to keep in step."""
    import ast

    src = Path("openfactory/product/module.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_workspace")
    # THE CODE, NOT THE PROSE. The docstring explains at length why the symlink layout was wrong,
    # and that explanation is the most valuable thing in the function — a test that made keeping it
    # impossible would be trading the reason for the rule.
    statements = [s for s in fn.body
                  if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    body = ast.unparse(ast.Module(body=statements, type_ignores=[]))

    assert "compose(" in body, "the mount reinvented a layout instead of using the composed one"
    assert "symlink" not in body, (
        "a root of pointers out of the tree reads as empty under a confined sandbox — the whole "
        "point of board #1")

    mounted = ast.unparse(next(n for n in ast.walk(tree)
                               if isinstance(n, ast.FunctionDef) and n.name == "mounted"))
    assert "relpath" in mounted, (
        "what the prompt is told to open is a literal again, so it can drift from where the files "
        "actually are")


def test_a_missing_source_degrades_to_docs_only_and_is_REPORTED():
    """No code is survivable. A silent promise of code is not."""
    import ast

    src = Path("openfactory/product/module.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_source_checkout")
    handlers = [n for n in ast.walk(fn) if isinstance(n, ast.ExceptHandler)]
    assert handlers, "a checkout failure would crash a chat handler"
    for h in handlers:
        said = ast.unparse(ast.Module(body=h.body, type_ignores=[]))
        assert "log." in said, "the role would silently lose the code and never say so"


def test_writes_never_go_through_the_mounted_view():
    """Both mounts are read-only by intent: a requirement is written through its own clone and a
    pull request. Writing into a symlinked checkout would edit a cache shared between messages."""
    import ast

    src = Path("openfactory/product/module.py").read_text()
    tree = ast.parse(src)
    for name in ("propose", "note_fact", "baseline"):
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == name), None)
        if fn is None:
            continue
        body = ast.unparse(fn)
        assert "clone_url" in body, f"{name} no longer writes through its own clone"
