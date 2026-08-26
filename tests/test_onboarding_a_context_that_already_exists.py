"""C-36 (#77): the client already HAS the context repository we require.

The product owner, 2026-08-05: *"we require creating a context, and this is a case where the
project already has one — an interesting scenario for us to test"*. The second external client
arrived with `ACM.CA.Deskline.Context` — docs, architecture, decisions numbered `DEC-001…` —
written long before it met us. That is the GOOD case, and nothing covered it.

The refusal half was already right: the module stays off, in a sentence, until `.openfactory/product.yaml`
says who the product is and which repositories implement it. What did not exist was any step that
gets a client there — four files across three repositories, by hand.

Two rules everything here defends:

    the context belongs to the CLIENT      merge, never replace: their keys, their folder, their
                                           structure all survive first contact
    an unknown folder is not a free one    `load_corpus` answers "0 requirements, next number 1"
                                           for a folder full of `DEC-001…`, and `0001-….md` would
                                           land beside them with nothing to tell the schemes apart
"""

from __future__ import annotations

from openfactory import namespace
from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.product.onboard import foreign_documents, plan

CONTEXT = "acme/dsk-context"
FLOWS = "acme/dsk-flows"
UI = "acme/dsk-ui"


def _project(**product_kw) -> Project:
    return Project(name="dsk", repo_path="unused",
                   tracker=ProviderRef(kind="github", repo=FLOWS),
                   product=ProductConfig(docs_repo=CONTEXT, **product_kw))


def _client_context(tmp_path, *, decisions=("DEC-001-orquestracao.md", "DEC-002-contexto.md")):
    """A context repo as a client really wrote it: docs, their own numbering, nothing of ours."""
    (tmp_path / "docs" / "decisoes").mkdir(parents=True)
    (tmp_path / "README.md").write_text("# Contexto\n")
    for name in decisions:
        (tmp_path / "docs" / "decisoes" / name).write_text(f"# {name}\n")
    return tmp_path


# ── first contact ───────────────────────────────────────────────────────────────────────────────

def test_a_context_that_never_heard_of_us_gets_a_complete_declaration(tmp_path):
    root = _client_context(tmp_path)

    result = plan(_project(), root, sources=[FLOWS, UI])

    assert not result.refusal, result.refusal
    assert "product: dsk" in result.product_yaml
    assert FLOWS in result.product_yaml and UI in result.product_yaml, (
        "sources must list EVERY repository — one missing is invisible to the product role")
    assert result.requirements_dir == "requirements"


def test_it_says_what_each_SOURCE_repo_still_needs(tmp_path):
    """The declaration is two-way, and the other half lives in repositories this command is not
    touching. Silence about them is how an onboarding half-completes."""
    result = plan(_project(), _client_context(tmp_path), sources=[FLOWS, UI])

    assert len(result.todo) == 2
    assert all("docs_repo: " + CONTEXT in line for line in result.todo)
    assert any(FLOWS in line for line in result.todo)


def test_nothing_the_client_wrote_is_touched(tmp_path):
    """It is their repository. A tool that tidies it on first contact has not onboarded them."""
    root = _client_context(tmp_path)
    (root / namespace.DIR).mkdir()
    (root / namespace.PRODUCT_MANIFEST).write_text(
        "product: dsk\nrequirements_dir: docs/requisitos\nsources: [acme/dsk-flows]\n"
        "dono: equipe-dsk\ncontato: rh@acme\n", encoding="utf-8")

    result = plan(_project(), root, sources=[FLOWS, UI])

    assert "dono: equipe-dsk" in result.product_yaml, "a key we do not recognise was dropped"
    assert "contato: rh@acme" in result.product_yaml
    assert result.requirements_dir == "docs/requisitos", "the client's own folder choice must win"
    assert UI in result.product_yaml, "the missing source still had to be added"


# ── an unknown folder is not a free folder ──────────────────────────────────────────────────────

def test_it_REFUSES_a_folder_that_already_holds_another_numbering(tmp_path):
    """THE finding this card was opened for. `load_corpus` reads OUR files, so a folder full of
    `DEC-001…` comes back empty and the next requirement lands on top of their scheme, in
    silence."""
    root = _client_context(tmp_path)
    (root / namespace.DIR).mkdir()
    (root / namespace.PRODUCT_MANIFEST).write_text(
        "product: dsk\nrequirements_dir: docs/decisoes\n", encoding="utf-8")

    result = plan(_project(), root, sources=[FLOWS])

    assert result.refusal
    assert "DEC-001" in result.refusal, "the refusal must name what it found"
    assert "requirements_dir" in result.refusal, "…and what to change"
    assert not result.product_yaml, "a refusal must not also hand over a file to write"


def test_our_OWN_requirements_are_not_strangers(tmp_path):
    """The guard must not fire on a repo this platform has already been writing into."""
    root = _client_context(tmp_path)
    (root / "requirements").mkdir()
    (root / "requirements/0001-editar-conciliado.md").write_text("# REQ-0001\n")

    assert foreign_documents(root, "requirements") == []
    assert not plan(_project(), root, sources=[FLOWS]).refusal


def test_a_folder_that_does_not_exist_yet_is_simply_free(tmp_path):
    assert foreign_documents(_client_context(tmp_path), "requirements") == []


# ── the states that are not first contact ───────────────────────────────────────────────────────

def test_a_context_that_already_says_everything_is_left_alone(tmp_path):
    """Running it twice must be a no-op, not a second PR."""
    root = _client_context(tmp_path)
    (root / namespace.DIR).mkdir()
    (root / namespace.PRODUCT_MANIFEST).write_text(
        f"product: dsk\nrequirements_dir: requirements\nsources: [{FLOWS}]\n", encoding="utf-8")

    assert plan(_project(), root, sources=[FLOWS]).already_correct


def test_a_project_with_no_product_section_is_told_that_first(tmp_path):
    """Which repository holds a client's requirements is an operator's decision — inferring it
    from a name is how one client's requirements land in another's repository."""
    project = Project(name="dsk", repo_path="unused",
                      tracker=ProviderRef(kind="github", repo=FLOWS))

    result = plan(project, tmp_path, sources=[FLOWS])

    assert "no `product:` section" in result.refusal
    assert "docs_repo" in result.refusal


def test_an_unreadable_product_yaml_does_not_erase_the_repo(tmp_path):
    """Malformed YAML in the client's file must not be read as "they declared nothing" and then
    overwritten — the safe move is to treat it as absent for MERGING and keep going."""
    root = _client_context(tmp_path)
    (root / namespace.DIR).mkdir()
    (root / namespace.PRODUCT_MANIFEST).write_text("product: [unclosed\n", encoding="utf-8")

    result = plan(_project(), root, sources=[FLOWS])

    assert not result.refusal
    assert "product: dsk" in result.product_yaml
