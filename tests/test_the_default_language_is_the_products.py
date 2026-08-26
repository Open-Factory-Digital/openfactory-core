"""The default language is ENGLISH, in every seam that has one (2026-08-14).

`pt-BR` was the first deployment's language wearing a default's clothes. Every client who never
declared one — and the whole point of a default is that most never do — got a factory speaking
Portuguese to their team: the announcements, the triage reports, the questions nobody prompted,
and the backfill documents about their own codebase. The operator, on the day a backfill came
out in Portuguese for a repository whose next client is a European exchange: *"the default has to
be EN"*. A default IS the product ([[a-default-is-the-product]]).

  1. every default-language constant agrees, because three that drift produce a message whose
     halves are in different languages;
  2. a project that says nothing gets English — the contract's own field;
  3. a project that DECLARES one is obeyed, which is the half that keeps the pilot in pt-BR;
  4. the backfill asks the project rather than the module, which was the defect that surfaced
     this: `propose_context` was the one voice never handed the project's language.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from openfactory.contracts.project import Project

ROOT = Path(__file__).resolve().parents[1]


def test_every_default_language_constant_says_english():
    from openfactory.adapters.agent.roles import DEFAULT_LANGUAGE as ROLES_DEFAULT
    from openfactory.onboarding.context import DEFAULT_LANGUAGE as CONTEXT_DEFAULT
    from openfactory.product.voice import DEFAULT_LANGUAGE as VOICE_DEFAULT

    assert ROLES_DEFAULT == VOICE_DEFAULT == CONTEXT_DEFAULT == "en", (
        "the platform's default language is not English in every seam — a client who declares "
        "nothing would read one voice in one language and another in a second")


def test_a_project_that_declares_nothing_speaks_english():
    assert Project(name="c", repo_path="/t").language == "en"


def test_a_project_that_declares_one_is_obeyed():
    """The half that matters as much: the pilot's own project is pt-BR because it says so."""
    assert Project(name="c", repo_path="/t", language="pt-BR").language == "pt-BR"


def test_the_backfill_asks_the_PROJECT_for_its_language():
    """The defect that surfaced all of this: every other voice resolved
    `getattr(project, "language")` and the backfill alone fell through to the module default —
    right by accident wherever the two agreed, silently wrong everywhere else."""
    import textwrap

    from openfactory.onboarding import onboard

    tree = ast.parse(textwrap.dedent(inspect.getsource(onboard._backfill)))
    call = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "propose_context")
    languages = [kw for kw in call.keywords if kw.arg == "language"]
    assert languages, "the backfill still lets the module default decide the client's language"
    assert "language" in ast.unparse(languages[0].value), (
        f"the language passed is not read from the project: {ast.unparse(languages[0].value)}")


def test_the_portuguese_layout_names_its_own_language():
    """A pydantic field default is frozen at import too: `ContextLayout.language =
    DEFAULT_LANGUAGE` meant the Portuguese layout (`visao-geral.md`, `glossario.md`) started
    rendering ENGLISH prose into Portuguese filenames the moment the default moved."""
    from openfactory.onboarding.context import ContextLayout, context_layout

    assert ContextLayout().language == "pt-BR"
    assert context_layout(None, language="pt-BR").architecture_dir == "docs/arquitetura"
    assert context_layout(None).architecture_dir == "docs/architecture"


def test_the_codebase_NARRATES_in_english():
    """The product speaks the client's language; the CODEBASE speaks English (2026-08-15).

    Quoting the operator verbatim looked like fidelity and was a habit: over three days, twenty-odd
    docstrings and comments carried Portuguese sentences into modules whose every other line is in
    English — and the pilot, reading one of them, said so. The EVIDENCE is what the person meant;
    the language they happened to say it in is not part of the evidence, and a maintainer who does
    not read Portuguese loses the reason a decision was taken.

    NARRATION ONLY — docstrings and comments. Portuguese as DATA is the product working: the
    intent patterns a client's message is matched against, the pt-BR phrasebook, a fixture ticket
    written the way a client writes one. Those are exempt BY SUBJECT rather than by file list,
    which is why the exemption below names why each one is language-about-language.
    """
    import ast
    import io
    import tokenize

    #: Modules whose SUBJECT is the client's language — the Portuguese in them is the thing under
    #: test or the thing being matched, not a sentence about a decision.
    ABOUT_LANGUAGE = {
        "openfactory/product/intents.py",       # the patterns a pt-BR message is matched against
        "openfactory/product/voice.py",         # the phrasebook itself
        "openfactory/product/followup.py",      # example client messages the matcher must handle
        "openfactory/onboarding/context.py",    # the pt-BR document layout
        "tests/test_a_ticket_written_in_portuguese.py",
        "tests/test_confirmation_is_understood.py",
        "tests/test_card_maintenance_channel.py",
        "tests/test_memory_recall_eval.py",
        "tests/test_product_followup.py",
        "tests/test_the_product_role_lives_outside_slack.py",
        "tests/test_the_review_findings_stay_fixed.py",
        "tests/test_sweep_client_surface.py",
        "tests/test_the_default_language_is_the_products.py",  # this file, by definition
        # The MESSAGE is the artefact under test: three of its assertions turn on the exact
        # Portuguese words the channel produced — "mandei" being first person and past tense,
        # "resume" appearing under a sentence that rules it out. Translating the quote would
        # delete the evidence, which is the opposite of this rule's purpose (2026-08-16).
        "tests/test_a_message_never_claims_an_action_nobody_takes.py",
    }
    #: Function words no English sentence carries. Two or more in one docstring is prose, not a
    #: stray identifier or a client's name.
    PT = (" não ", " você ", " isso ", " aqui ", " para o ", " que a ", " está ", " ele ",
          " são ", " pela ", " pelo ", " seu ", " sua ", " mas ", " também ", " uma ", " nada ")

    offenders = []
    for path in sorted([*ROOT.glob("openfactory/**/*.py"), *ROOT.glob("tests/**/*.py")]):
        rel = str(path.relative_to(ROOT))
        if rel in ABOUT_LANGUAGE:
            continue
        try:
            src = path.read_text()
        except FileNotFoundError:
            # LISTED, THEN GONE. This globs the source trees and reads each hit, and something
            # else can delete a file in between — which is not an exotic case in THIS repo: the
            # product's whole job is agents working in a checkout, and a suite run beside one
            # raced exactly here (2026-08-17). A file that no longer exists carries no docstring
            # to judge; the next run judges it if it comes back. Narrow on purpose — it cannot
            # hide Portuguese in a file that IS there, which is the only thing this asserts.
            continue
        spans = []
        try:
            tree = ast.parse(src)
        except SyntaxError:  # pragma: no cover — a broken file fails louder elsewhere
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc:
                    spans.append((getattr(node, "lineno", 1), doc))
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                spans.append((tok.start[0], tok.string))
        offenders += [f"{rel}:{line}" for line, text in spans
                      if sum(w in f" {text.lower()} " for w in PT) >= 2]

    assert not offenders, (
        "these docstrings/comments narrate in Portuguese — translate the quote and keep the "
        "attribution; the meaning is the evidence:\n  " + "\n  ".join(offenders))
