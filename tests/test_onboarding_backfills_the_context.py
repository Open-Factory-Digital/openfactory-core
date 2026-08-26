"""#99 slice 2 — the BACKFILL: the context an AI needs, reverse-engineered from legacy code.

THIS FILE SPEAKS PORTUGUESE, DELIBERATELY AND ONCE. Its guards assert the platform's own pt-BR
words ("não têm README nem docstring", "não é documentação aprovada") because that word table is
what they are about. They used to inherit pt-BR from the module default — and when the product's
default became English (2026-08-14: a default IS the product, and this one ships to clients who
do not speak Portuguese), fifty tests across sixteen files went red while nothing had broken.
The premise is declared once in the fixture below rather than threaded through twenty-seven call
sites; the one test that is genuinely ABOUT the default names both languages itself.

`openfactory/onboarding/context.py` has two halves and they are tested as two different things, because
they make two different promises:

    survey()           deterministic. Same repository state, identical object. It is the EVIDENCE,
                       so a test may assert its exact content.
    propose_context()  a model wrote the sentences, so no test may assert what they say. What IS
                       testable — and is the entire product — is the MECHANISM around them: every
                       claim is anchored to a file that really exists, at a line that really
                       exists, and a claim that cannot be anchored is republished as a question
                       instead of printed as a fact.

The guards below are written against the second in particular, because "a human corrects it in
the room" is a process promise and this repository's own history says a promise no code enforces
lasts until the first busy afternoon.

Each guard names the defect it would catch. Every one of them was verified by MUTATION — the
defect reintroduced in `context.py`, the named test watched go red, the mutation reverted. The
mutation log is in the slice report; `test_control_*` below is the control that must stay GREEN
under every one of those mutations, so a mutation that merely breaks the module (a SyntaxError
reddens everything and looks exactly like proof) is distinguishable from one that breaks the
property under test.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from openfactory.onboarding.context import (
    _INERT_SUFFIXES,
    _SOURCE_SUFFIXES,
    ContextProposal,
    _is_tooling,
    build_prompt,
    context_layout,
    propose_context,
    render_context_report,
    render_survey,
    survey,
    write_documents,
)


@pytest.fixture(autouse=True)
def _this_file_speaks_portuguese(monkeypatch):
    """The premise above, in one place: these guards read the pt-BR word table."""
    import openfactory.onboarding.context as _ctx

    monkeypatch.setattr(_ctx, "DEFAULT_LANGUAGE", "pt-BR")


# ---------------------------------------------------------------------------------------------
# fixtures — repositories as clients really hand them over
# ---------------------------------------------------------------------------------------------

#: THE REPOSITORY CARD #99 IS ABOUT: real code, real structure, and not one line of prose about
#: itself. No README, no docstring, no comment. Every deterministic purpose the OKF generator can
#: produce for it is the folder's own name handed back, which is the gap this slice exists to
#: measure and then fill.
def _mute_legacy(root: Path) -> Path:
    (root / "cobranca").mkdir(parents=True)
    (root / "cobranca" / "__init__.py").write_text("")
    (root / "cobranca" / "boleto.py").write_text(
        "def emitir_boleto(fatura):\n"
        "    assert fatura.valor > 0\n"
        "    return {'nosso_numero': fatura.id}\n"
    )
    (root / "cobranca" / "fatura.py").write_text(
        "class Fatura:\n    def __init__(self, valor):\n        self.valor = valor\n")
    (root / "conciliacao").mkdir()
    (root / "conciliacao" / "__init__.py").write_text("")
    (root / "conciliacao" / "extrato.py").write_text(
        "def conciliar_extrato(linhas):\n    return [l for l in linhas if l]\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_boleto.py").write_text("def test_emite():\n    assert True\n")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "cobranca"\nversion = "1.0"\n\n'
        '[project.scripts]\nemitir = "cobranca.boleto:main"\n'
    )
    return root


@pytest.fixture()
def legacy(tmp_path: Path) -> Path:
    return _mute_legacy(tmp_path / "legado")


def _ask_saying(payload: dict, *, calls: list[str] | None = None):
    """A scripted stand-in for the read-only agent primitive. No model, no harness, no network —
    the primitive is `prompt -> text`, which is exactly what `agent_ask` binds a harness into."""

    def _ask(prompt: str) -> str:
        if calls is not None:
            calls.append(prompt)
        return "Here is what I found.\n```json\n" + json.dumps(payload) + "\n```\n"

    return _ask


# ---------------------------------------------------------------------------------------------
# the control — must stay GREEN under every mutation used to verify the guards below
# ---------------------------------------------------------------------------------------------


def test_control_a_survey_of_a_real_repository_returns_a_populated_object(legacy: Path) -> None:
    """THE CONTROL. A mutation that introduces a SyntaxError reddens every test in this file and
    reads exactly like proof that a guard works. This one asserts only that the module imports
    and does something at all, so a mutation that reddens IT has broken the module rather than
    the property any other test names."""
    result = survey(legacy)
    assert result.module_count >= 2
    assert result.repo == str(legacy.resolve())


# ---------------------------------------------------------------------------------------------
# survey() — the deterministic half
# ---------------------------------------------------------------------------------------------


def test_a_path_that_cannot_be_read_raises_instead_of_surveying_nothing(tmp_path: Path) -> None:
    """CATCHES: a typo in a path coming back as a confident survey of a repository with no
    modules, no stacks and no tests — a failure wearing the costume of an answer. `os.walk`
    swallows the error and yields nothing, so silence is the DEFAULT behaviour here, not an
    exotic one."""
    with pytest.raises(NotADirectoryError):
        survey(tmp_path / "nao-existe")

    afile = tmp_path / "a-file.txt"
    afile.write_text("not a repository")
    with pytest.raises(NotADirectoryError):
        survey(afile)


def test_the_same_repository_surveys_identically_twice(legacy: Path) -> None:
    """CATCHES: any dependency on `os.walk` order. A survey you cannot diff against last week's
    is a survey nobody can review, and it is also the evidence block of a prompt — a prompt that
    changes byte-for-byte between runs makes every difference in the agent's answer
    unattributable."""
    assert survey(legacy).model_dump_json() == survey(legacy).model_dump_json()


def test_it_surveys_identically_under_a_different_hash_seed(tmp_path: Path) -> None:
    """THE SAME CLAIM, WHERE IT CAN ACTUALLY FAIL — and the in-process test above cannot.

    Set and dict iteration order for strings depends on `PYTHONHASHSEED`, which is fixed for the
    life of ONE interpreter. So a survey that leaks a `set`'s order into its output compares equal
    to itself all day inside a single pytest run and differs between two runs on the same machine
    — the exact shape of a guard that looks like a guard. Two subprocesses with different seeds is
    the only place the property is observable, so it is asserted there.

    The repository is built HERE rather than reused, and deliberately spreads one word across four
    modules: a set with one element in it sorts identically however it is iterated, so a fixture
    with one module per term makes this test unfalsifiable — measured, when removing the `sorted`
    from `TermSighting.modules` left it green.
    """
    import subprocess
    import sys

    repo = tmp_path / "espalhado"
    for area in ("cobranca", "emissao", "portal", "arquivo"):
        (repo / area).mkdir(parents=True)
        (repo / area / "__init__.py").write_text("")
        (repo / area / f"fatura_{area}.py").write_text(f"class Fatura{area.title()}:\n    pass\n")
        (repo / area / f"boleto_{area}.py").write_text(f"def emitir_{area}():\n    return 1\n")

    script = (
        "import sys; from openfactory.onboarding.context import survey; "
        "sys.stdout.write(survey(sys.argv[1]).model_dump_json())"
    )
    outputs = []
    for seed in ("0", "424242"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-c", script, str(repo)],
            capture_output=True, text=True, env=env,
            cwd=str(Path(__file__).resolve().parent.parent), check=True)
        outputs.append(done.stdout)
    assert "fatura" in outputs[0], "the fixture must exercise a term spanning several modules"
    assert outputs[0] == outputs[1]


def test_a_module_with_no_prose_is_reported_as_KNOWN_NOTHING_not_described(legacy: Path) -> None:
    """THE MEASUREMENT CARD #99 TURNS ON, and the reason this slice exists.

    `knowledge/generator.py` is deterministic on purpose and correct to be: it quotes a README,
    a docstring, a JSDoc or a `<summary>`, and when a legacy repository has none of those it falls
    through to the humanized folder name. `cobranca` then "means" *cobranca*, which is nothing.

    CATCHES: that fall-through being silently accepted as a description. If `purpose_is_folder_
    name` ever stops being computed, a survey of a repository nobody documented reads as a
    repository that documented itself.
    """
    result = survey(legacy)
    by_name = {m.name: m for m in result.modules}
    assert by_name["cobranca"].purpose == "cobranca"
    assert by_name["cobranca"].purpose_is_folder_name is True
    assert by_name["conciliacao"].purpose_is_folder_name is True
    assert result.degraded_purposes >= 2

    # …and the survey turns it into the question a developer answers out loud, rather than
    # leaving the reader to notice a table full of folder names.
    proposal = propose_context(result)
    assert any("não têm README nem docstring" in q for q in proposal.questions)


def test_a_module_that_DOES_describe_itself_is_not_reported_as_blind(legacy: Path) -> None:
    """THE POSITIVE TWIN of the guard above. "Nothing is described" cannot see a broken detector
    that answers True for everything — absence reads as compliance either way. This one fails if
    `purpose_is_folder_name` is hardwired True."""
    (legacy / "faturamento").mkdir()
    (legacy / "faturamento" / "__init__.py").write_text(
        '"""Regras de faturamento mensal por contrato."""\n')
    result = survey(legacy)
    by_name = {m.name: m for m in result.modules}
    assert by_name["faturamento"].purpose == "Regras de faturamento mensal por contrato."
    assert by_name["faturamento"].purpose_is_folder_name is False


def test_a_directory_that_cannot_be_opened_is_declared_not_counted_as_empty(
    legacy: Path,
) -> None:
    """CATCHES this codebase's most expensive defect class inside the function written against
    it: `os.walk`'s default is to swallow an unreadable directory and yield fewer entries, so a
    vendored subtree the process cannot read surveys identically to one that is empty."""
    if os.geteuid() == 0:
        pytest.skip("running as root: no directory is unreadable")
    locked = legacy / "vendor"
    locked.mkdir()
    (locked / "legacy.py").write_text("x = 1\n")
    locked.chmod(0o000)
    try:
        result = survey(legacy)
        assert result.unreadable_dirs, "an unopenable directory surveyed as an empty one"
        assert any("vendor" in d for d in result.unreadable_dirs)
        assert "não puderam ser abertos" in render_survey(result)
        proposal = propose_context(result)
        assert any("não puderam ser abertos" in q for q in proposal.questions)
    finally:
        locked.chmod(stat.S_IRWXU)


def test_a_clean_walk_declares_itself_clean_rather_than_staying_silent(legacy: Path) -> None:
    """The other half of the None-vs-empty rule: `[]` here is a MEASURED answer ("every directory
    was entered"), not an absence of information."""
    assert survey(legacy).unreadable_dirs == []


def test_a_stack_the_structural_map_cannot_read_is_declared_not_absent(tmp_path: Path) -> None:
    """CATCHES the C-49 collapse in a new place. The OKF map understands Python, TS/JS and .NET;
    a Java or Go repository produces an EMPTY module map, which reads exactly like a repository
    with no code in it. The vocabulary survey still works there — reading a file NAME needs no
    parser — so the client hears "we cannot read your stack, here are its words" rather than
    silence."""
    repo = tmp_path / "java-legado"
    (repo / "src" / "main" / "java" / "cobranca").mkdir(parents=True)
    for name in ("BoletoService.java", "FaturaRepository.java", "ConciliacaoJob.java"):
        (repo / "src" / "main" / "java" / "cobranca" / name).write_text("class X {}\n")
    result = survey(repo)

    assert result.module_count == 0, "the OKF map is expected to be empty for Java"
    assert ".java" in result.unread_code_extensions, "an unread stack read as an absent one"
    assert {"boleto", "fatura", "conciliacao"} <= {t.term for t in result.terms}
    assert any(".java" in q for q in propose_context(result).questions)


def test_an_entry_point_is_read_out_of_the_file_that_declares_it(legacy: Path) -> None:
    """CATCHES an entry-point list with no provenance. "Where does this start" is the first
    question of any reverse-engineering session, and an answer nobody can open is an opinion."""
    (legacy / "Dockerfile").write_text(
        "FROM python:3.12\nWORKDIR /app\nCMD [\"python\", \"-m\", \"cobranca\"]\n")
    result = survey(legacy)
    kinds = {e.kind for e in result.entry_points}
    assert "console script" in kinds
    assert "container CMD" in kinds
    for entry in result.entry_points:
        assert (legacy / entry.evidence.path).is_file(), entry.evidence.path
    docker = next(e for e in result.entry_points if e.kind == "container CMD")
    assert docker.evidence.line == 3
    assert "cobranca" in docker.evidence.excerpt


def test_a_test_file_that_names_a_PACKAGE_counts_as_naming_it(legacy: Path) -> None:
    """CATCHES a confident wrong finding about somebody's test discipline.

    Exact stem matching credits `tests/test_boleto.py` to `cobranca/boleto.py` and then reports
    `conciliacao` — a package with its own test module — as named by nothing, because no FILE is
    called `conciliacao.py`. Measured on this repository first: `openfactory.knowledge` (nine files,
    four test modules) and `openfactory.product` (eighteen files) both came back uncovered, and the
    untested count fell from 25 to 7 once a test may name a package or a prefix of one."""
    (legacy / "tests" / "test_conciliacao.py").write_text("def test_x():\n    assert True\n")
    (legacy / "tests" / "test_boleto_emite_com_juros.py").write_text(
        "def test_y():\n    assert True\n")
    by_name = {m.name: m for m in survey(legacy).modules}

    assert by_name["conciliacao"].tested_by == ["tests/test_conciliacao.py"]
    # the longest prefix wins, so a wordier test name still lands on the file it names
    assert set(by_name["cobranca"].tested_by) == {
        "tests/test_boleto.py", "tests/test_boleto_emite_com_juros.py"}


def test_a_module_nothing_names_is_still_reported_untested(legacy: Path) -> None:
    """THE NEGATIVE TWIN of the guard above: a matcher that credits everything to everything
    satisfies it perfectly while reporting a repository with no tests as fully covered."""
    (legacy / "relatorios").mkdir()
    (legacy / "relatorios" / "__init__.py").write_text("")
    (legacy / "relatorios" / "mensal.py").write_text("def gerar():\n    return []\n")
    result = survey(legacy)
    assert "relatorios" in result.untested_modules
    assert "cobranca" not in result.untested_modules
    assert any("nenhum arquivo de teste nomeia" in q for q in propose_context(result).questions)


def test_the_glossary_is_the_domain_not_the_test_suites_phrasing(legacy: Path) -> None:
    """CATCHES two blemishes measured on the real `fx-dsk-flows`, both in the first three lines a
    client reads.

    A test module's SYMBOLS reach the vocabulary through the OKF map even though its FILES are
    already excluded, and one C# test method put `respeita`, `ignora`, `todas`, `nada` and `caixa`
    above the repository's actual domain terms. And a word reaches the collector twice for one
    file — from the stem and from a symbol anchored to that same file — which printed
    `ex. src/Admissao.cs, src/Admissao.cs`."""
    result = survey(legacy)
    terms = {t.term for t in result.terms}
    assert "emitir" in terms, "the domain verb from cobranca/boleto.py must survive"
    assert "emite" not in terms, "a test function's name became a glossary candidate"

    # The duplicate needs a module whose ANCHOR is a code file that also contributes a term —
    # the .NET shape, where `src/Admissao.cs` is both the anchor of module `src` and the file
    # whose stem says `admissao`. A Python package anchors on `__init__.py` and cannot produce
    # it, so asserting only over `legacy` above leaves this unfalsifiable (measured).
    dotnet = legacy.parent / "flows"
    (dotnet / "src").mkdir(parents=True)
    (dotnet / "src" / "Admissao.cs").write_text(
        "public class Admissao {\n  public void Iniciar() {}\n}\n")
    (dotnet / "src" / "Flows.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        "<TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>\n")
    dotnet_terms = survey(dotnet).terms
    assert "admissao" in {t.term for t in dotnet_terms}
    for term in list(result.terms) + list(dotnet_terms):
        locators = [e.locator for e in term.evidence]
        assert len(locators) == len(set(locators)), (term.term, locators)


def test_every_line_of_a_document_is_in_ONE_language(legacy: Path) -> None:
    """CATCHES the defect `roles.py` already paid for — *"an English block between two Portuguese
    ones reads as two different people wrote the ticket"* — in the artefact that is HANDED TO THE
    CLIENT.

    The first version of this module had Portuguese headings over English body prose, and the
    demoted-claim sentence (the line most likely to be read aloud) arrived in English inside a
    Portuguese glossary. Both directions are asserted, because a table with only one language
    filled in passes the pt half and ships the en half untranslated."""
    payload = {"does": [{"text": "x", "cites": ["nao/existe.py"]}]}
    pt = propose_context(survey(legacy), ask=_ask_saying(payload))
    en = propose_context(survey(legacy), ask=_ask_saying(payload), language="en")

    assert any("o agente propôs" in q for q in pt.demoted)
    assert any("the agent proposed" in q for q in en.demoted)

    pt_body = "\n".join(d.body for d in pt.documents)
    en_body = "\n".join(d.body for d in en.documents)
    for english_leak in ("no README and no docstring", "the walk completed", "none found",
                         "modules nothing names in a test file", "the filter is ours"):
        assert english_leak not in pt_body, english_leak
    for portuguese_leak in ("não têm README nem docstring", "a varredura foi completa",
                            "o filtro é nosso"):
        assert portuguese_leak not in en_body, portuguese_leak
    assert "Levantamento do repositório" in pt_body and "Repository survey" in en_body


def test_the_stoplist_says_which_of_the_clients_words_it_removed(legacy: Path) -> None:
    """CATCHES an unauditable filter. The stoplist is OURS, applied to somebody else's
    vocabulary; a term list with no record of what it dropped cannot be argued with, and a
    silently deleted domain word is invisible — nobody misses a term they never saw."""
    result = survey(legacy)
    assert "fatura" in {t.term for t in result.terms}
    assert result.terms_dropped, "the stoplist removed words and said nothing about it"
    assert any("o filtro é nosso" in q for q in propose_context(result).questions)


# ---------------------------------------------------------------------------------------------
# propose_context() — the authored half, and the mechanism that replaces trust
# ---------------------------------------------------------------------------------------------


def test_a_claim_citing_a_file_that_does_not_exist_becomes_a_question(legacy: Path) -> None:
    """THE GUARD THIS SLICE RESTS ON.

    "The difference between inventing and proposing is the person present" is true and it is not
    enforceable. This is: a citation naming a file this repository does not contain deletes the
    sentence and republishes it as a question, so a model that invents a source loses the claim
    every time, whether or not anybody in the room notices.

    CATCHES: the anchoring check being removed, weakened to a string-format test, or applied to
    only some of the sections."""
    payload = {
        "does": [
            {"text": "emite boletos a partir de faturas", "cites": ["cobranca/boleto.py:1"]},
            {"text": "integra com o banco central", "cites": ["cobranca/bacen.py:12"]},
        ],
        "entities": [{"text": "Fatura", "cites": ["cobranca/inventado.py"]}],
        "invariants": [{"text": "valor > 0", "cites": ["cobranca/boleto.py:2"]}],
        "vocabulary": [
            {"term": "Boleto", "meaning": "cobranca bancaria", "cites": ["cobranca/boleto.py"]},
            {"term": "Apolice", "meaning": "contrato de seguro", "cites": ["seguros/apolice.py"]},
        ],
        "questions": [],
    }
    proposal = propose_context(survey(legacy), ask=_ask_saying(payload))

    assert proposal.ok and proposal.semantic
    said = [c.text for c in proposal.what_it_does]
    assert said == ["emite boletos a partir de faturas"], said
    assert proposal.entities == []
    assert [t.term for t in proposal.vocabulary] == ["Boleto"]

    # the invented ones are not gone, they are QUESTIONS — with the failed citation named, so a
    # reader can tell a wrong belief from a right one with a mistyped path
    joined = "\n".join(proposal.demoted)
    assert "integra com o banco central" in joined
    assert "cobranca/bacen.py:12" in joined
    assert "Apolice" in joined
    assert all(d in proposal.questions for d in proposal.demoted)

    # and nothing that survived carries a citation the repository does not have
    for claim in proposal.what_it_does + proposal.invariants:
        for ev in claim.evidence:
            assert (legacy / ev.path).is_file()


def test_a_citation_past_the_end_of_a_real_file_is_rejected_too(legacy: Path) -> None:
    """CATCHES the half-fix: checking that the FILE exists and trusting the line. A real path
    with an impossible line is the tell that separates a model reading a file from a model
    reciting a plausible path, and it is free to check."""
    payload = {"does": [
        {"text": "verdadeiro", "cites": ["cobranca/boleto.py:2"]},
        {"text": "inventado", "cites": ["cobranca/boleto.py:9999"]},
    ]}
    proposal = propose_context(survey(legacy), ask=_ask_saying(payload))
    assert [c.text for c in proposal.what_it_does] == ["verdadeiro"]
    assert any("9999" in d and "line(s)" in d for d in proposal.demoted)


def test_a_surviving_citation_carries_the_clients_own_line(legacy: Path) -> None:
    """THE POSITIVE TWIN of the two guards above: a rejection test alone passes just as happily
    when EVERYTHING is rejected. Here a true citation must survive AND come back with the line
    text read off disk, which is what a client actually reads under the sentence."""
    payload = {"invariants": [
        {"text": "uma fatura nunca e emitida com valor zero",
         "cites": ["cobranca/boleto.py:2"]},
    ]}
    proposal = propose_context(survey(legacy), ask=_ask_saying(payload))
    assert len(proposal.invariants) == 1
    evidence = proposal.invariants[0].evidence[0]
    assert evidence.path == "cobranca/boleto.py"
    assert evidence.line == 2
    assert evidence.excerpt == "assert fatura.valor > 0"
    assert proposal.demoted == []


def test_a_citation_that_walks_out_of_the_repository_is_refused(legacy: Path) -> None:
    """CATCHES a path traversal in a function whose whole job is to open a file named by a model,
    on a laptop sitting in front of a client.

    BOTH ESCAPES ARE EXERCISED AGAINST FILES THAT REALLY EXIST, because a rejection test over
    paths that are absent anyway proves nothing: `/etc/hosts` is real on this machine and the
    sibling below is created here on purpose. A first version of this test used only absent paths
    and stayed green with the entire `..`/resolve guard removed — the citation was rejected for
    not existing, not for escaping, and the guard under test was never reached."""
    outside = legacy.parent / "segredo.txt"
    outside.write_text("credenciais de producao\n")
    payload = {"does": [
        {"text": "le a lista de usuarios do sistema",
         "cites": ["/etc/hosts", "~/.ssh/id_rsa", "https://example.com/x.py"]},
        {"text": "le um arquivo do diretorio acima",
         "cites": ["../segredo.txt", "cobranca/../../segredo.txt"]},
    ]}
    proposal = propose_context(survey(legacy), ask=_ask_saying(payload))
    assert proposal.what_it_does == []
    assert len(proposal.demoted) == 2
    assert "segredo.txt" not in "".join(
        e.excerpt for c in proposal.what_it_does for e in c.evidence)


def test_an_answer_with_no_json_is_a_refusal_not_an_empty_context(legacy: Path) -> None:
    """CATCHES the most damaging possible failure of this module: an unreadable agent answer
    rendered as a context document that says the system does nothing. That is a claim about the
    CLIENT'S CODE; the truth is a claim about us, and the two send a room in opposite
    directions."""
    proposal = propose_context(survey(legacy), ask=lambda prompt: "I could not do that, sorry.")
    assert proposal.ok is False
    assert proposal.semantic is False
    assert "no JSON object" in proposal.refusal
    assert proposal.what_it_does == [] and proposal.vocabulary == []
    assert "REFUSED" in render_context_report(proposal)


def test_an_agent_that_raises_does_not_take_the_survey_down_with_it(legacy: Path) -> None:
    """CATCHES a harness failure erasing the half of the session that never involved a harness.
    The deterministic survey was true before the model was asked and it is true after it failed,
    and it is the document the client keeps either way."""

    def _explode(prompt: str) -> str:
        raise RuntimeError("credential expired")

    proposal = propose_context(survey(legacy), ask=_explode)
    assert proposal.ok is False
    assert "credential expired" in proposal.refusal
    assert proposal.asked == 0
    assert any(d.kind == "survey" and not d.from_model for d in proposal.documents)
    assert proposal.questions, "the deterministic agenda disappeared with the harness"


def test_exactly_one_agent_pass_is_spent(legacy: Path) -> None:
    """CATCHES a per-module fan-out creeping in. An onboarding step whose cost scales with the
    size of the client's monolith is one nobody can quote a price for."""
    calls: list[str] = []
    proposal = propose_context(survey(legacy), ask=_ask_saying({"does": []}, calls=calls))
    assert len(calls) == 1
    assert proposal.asked == 1


def test_no_ask_means_zero_tokens_and_still_a_usable_session(legacy: Path) -> None:
    """`ask=None` is a MODE, not a failure — and it is the mode every client is in on the morning
    of day one, before a harness is configured. CATCHES it being conflated with the refusal path:
    `ok` must stay True, and the survey document plus the agenda must still be produced."""
    proposal = propose_context(survey(legacy))
    assert proposal.ok is True
    assert proposal.semantic is False
    assert proposal.refusal == ""
    assert proposal.asked == 0
    assert proposal.questions
    assert {d.kind for d in proposal.documents} == {
        "survey", "overview", "glossary", "invariants", "questions"}
    assert all(d.from_model is False for d in proposal.documents)
    assert "DETERMINISTIC ONLY" in render_context_report(proposal)


def test_the_prompt_shows_the_evidence_and_states_the_verification_rule(legacy: Path) -> None:
    """CATCHES a prompt that asks for citations without telling the model they are CHECKED, and
    one that asks about a repository it was never shown. The evidence block is the same renderer
    the client reads, so the two cannot drift into describing different repositories."""
    result = survey(legacy)
    prompt = build_prompt(result)
    assert "CHECKED against the filesystem" in prompt
    assert "questions" in prompt
    assert render_survey(result, for_prompt=True) in prompt
    assert "cobranca" in prompt


# ---------------------------------------------------------------------------------------------
# the documents, and the two gates on writing them
# ---------------------------------------------------------------------------------------------


def test_write_documents_refuses_without_consent(legacy: Path, tmp_path: Path) -> None:
    """Same rule as slice 1: this module PROPOSES, a caller decides. CATCHES a default that
    writes into a client's repository as a side effect of producing a report."""
    docs_root = tmp_path / "contexto"
    docs_root.mkdir()
    proposal = propose_context(survey(legacy))
    outcome = write_documents(proposal, docs_root)
    assert outcome.refusal and outcome.wrote == []
    assert list(docs_root.iterdir()) == []


def test_with_consent_it_writes_and_the_files_are_real(legacy: Path, tmp_path: Path) -> None:
    """THE POSITIVE TWIN. A refusal test alone passes for a function that never writes anything
    at all — which would make the whole phase produce nothing while every guard stayed green."""
    docs_root = tmp_path / "contexto"
    docs_root.mkdir()
    proposal = propose_context(survey(legacy))
    outcome = write_documents(proposal, docs_root, consent=True)
    assert outcome.failed == [] and outcome.skipped == []
    assert len(outcome.wrote) == len(proposal.documents)
    for rel in outcome.wrote:
        assert (docs_root / rel).read_text().strip()
    # the survey document says it was produced WITHOUT a model — it is evidence, so it carries
    # provenance rather than the "correct me" banner…
    survey_doc = (docs_root / "docs/levantamento.md").read_text()
    assert "cobranca" in survey_doc
    assert "nenhum modelo participou" in survey_doc
    # …and every document that makes a statement about the client's business carries the banner,
    # because a draft nobody is told to correct is a draft somebody will cite as approved
    for rel in ("docs/arquitetura/visao-geral.md", "docs/glossario.md", "docs/invariantes.md"):
        assert "não é documentação aprovada" in (docs_root / rel).read_text(), rel


def test_a_file_the_client_already_wrote_is_never_overwritten(legacy: Path, tmp_path: Path) -> None:
    """The context repository belongs to the CLIENT — `product/onboard.py` says it in the same
    words after a client arrived with a context repo written long before it met us. CATCHES a
    tool that tidies somebody else's repository on first contact."""
    docs_root = tmp_path / "contexto"
    (docs_root / "docs").mkdir(parents=True)
    theirs = docs_root / "docs" / "glossario.md"
    theirs.write_text("# Glossario\n\nEscrito por nos em 2019.\n")
    proposal = propose_context(survey(legacy), docs_root=docs_root)

    glossary = next(d for d in proposal.documents if d.kind == "glossary")
    assert glossary.exists is True, "the proposal did not notice the client's own file"
    assert "already exists" in render_context_report(proposal)

    outcome = write_documents(proposal, docs_root, consent=True)
    assert "docs/glossario.md" in outcome.skipped
    assert theirs.read_text() == "# Glossario\n\nEscrito por nos em 2019.\n"
    assert outcome.wrote, "skipping one file must not stop the others"


def test_the_layout_follows_the_context_repository_the_client_already_has(tmp_path: Path) -> None:
    """Measured against the real shape of `fx-dsk-context` (client 2's own repository, written
    before it met us): `docs/arquitetura/`, `docs/decisoes/`, its own numbering. CATCHES a second
    documentation tree being started beside theirs — `docs/architecture/overview.md` landing next
    to `docs/arquitetura/visao-geral.md` is not onboarding, it is a fork of their docs."""
    docs_root = tmp_path / "dsk-context"
    (docs_root / "docs" / "arquitetura").mkdir(parents=True)
    (docs_root / "docs" / "arquitetura" / "visao-geral.md").write_text("# Visão geral\n")
    (docs_root / "docs" / "decisoes").mkdir()

    layout = context_layout(docs_root)
    assert layout.architecture_dir == "docs/arquitetura"
    assert layout.overview_name == "visao-geral.md"

    # and with no context repository at all, the LANGUAGE decides — named here rather than
    # inherited, because this is the one test in the file that is ABOUT the default
    assert context_layout(None, language="pt-BR").architecture_dir == "docs/arquitetura"
    assert context_layout(None, language="en").architecture_dir == "docs/architecture"
    assert context_layout(tmp_path / "nowhere").glossary_path == "docs/glossario.md"


def test_the_documents_never_include_the_product_manifest(legacy: Path) -> None:
    """`.openfactory/product.yaml` has exactly one writer — `product/onboard.py::plan`, which merges,
    honours a `requirements_dir` the client already chose, and refuses a folder that already
    holds somebody else's numbering. CATCHES a second writer of the file that decides which
    repository a product's requirements live in, which ADR-0019 calls a client isolation
    breach."""
    proposal = propose_context(survey(legacy))
    assert all("product.yaml" not in d.path for d in proposal.documents)


def test_a_document_survives_even_when_the_model_produced_nothing(legacy: Path) -> None:
    """THE COMMERCIAL CLAIM, as a guard: *"the client leaves the first session with documentation they did not have… that has value
    even if the factory never runs a ticket."* CATCHES a pipeline
    where a silent model means an empty folder."""
    proposal = propose_context(survey(legacy), ask=lambda prompt: "nothing to say")
    assert proposal.ok is False
    survey_doc = next(d for d in proposal.documents if d.kind == "survey")
    assert survey_doc.from_model is False
    assert "cobranca" in survey_doc.body
    assert "conciliacao" in survey_doc.body


def test_an_empty_section_prints_as_a_question_not_as_a_finished_document(legacy: Path) -> None:
    """CATCHES a document that reads as complete because a section came back empty. An empty
    `invariants` list is a real and acceptable answer from the model; a document that renders it
    as a heading with nothing under it says this system has no rules."""
    proposal = propose_context(survey(legacy), ask=_ask_saying({"does": [], "invariants": []}))
    invariants = next(d for d in proposal.documents if d.kind == "invariants")
    assert "Nada foi proposto aqui" in invariants.body
    assert "perguntas em aberto" in invariants.body


def test_write_documents_refuses_a_docs_root_that_is_not_there(legacy: Path, tmp_path: Path) -> None:
    """CATCHES a write that silently succeeds into a path nobody checked — the `box_prove.save`
    defect card #99 §0 measured, where an `OSError` was swallowed and the caller printed
    `recorded at …` over a file that was never created."""
    proposal = propose_context(survey(legacy))
    outcome = write_documents(proposal, tmp_path / "sem-clone", consent=True)
    assert outcome.wrote == [] and "not a directory" in outcome.refusal


# ---------------------------------------------------------------------------------------------
# against real repositories, never a hypothetical one
# ---------------------------------------------------------------------------------------------

from tests.demo_projects import demo_projects_root  # noqa: E402 — beside its one use

_REAL = demo_projects_root()


@pytest.mark.parametrize("name", ["py-mono", "fx-dsk-flows", "py-serverless"])
def test_it_surveys_the_real_toy_projects(name: str) -> None:
    """The fixtures the platform is actually proven against — a Python monorepo with no prose
    anywhere, a .NET 8 Azure Functions repo, and a SAM serverless one. CATCHES a module that only
    works on the repository its tests build."""
    repo = _REAL / name
    if not repo.is_dir():
        pytest.skip(f"{repo} is not checked out on this machine")
    result = survey(repo)
    assert result.repo == str(repo.resolve())
    assert result.unreadable_dirs == []
    assert survey(repo).model_dump_json() == result.model_dump_json()
    # a survey that says nothing at all about a real repository is a broken survey
    assert result.stacks or result.modules or result.terms


def test_it_surveys_this_repository_and_finds_its_own_vocabulary() -> None:
    """The biggest real codebase on hand (183 source files across 36 modules), used here for the
    two things a toy project cannot exercise: an entry point declared in packaging metadata, and
    a domain vocabulary big enough that ranking matters."""
    result = survey(Path(__file__).resolve().parent.parent)
    assert result.module_count > 20
    terms = {t.term for t in result.terms}
    assert {"ticket", "board", "project"} <= terms, sorted(terms)[:20]
    scripts = [e for e in result.entry_points if e.kind == "console script"]
    assert any("openfactory.cli" in e.target for e in scripts)
    # `endswith`, not equality: the add-on packages under addons/ carry a pyproject of their own
    # with a console entry (the chat listener, 2026-08-26), and the survey reads every one — a
    # multi-package repository is a shape a real client has
    assert all(e.evidence.path.endswith("pyproject.toml") and e.evidence.line for e in scripts)
    assert any(e.evidence.path == "pyproject.toml" for e in scripts), "the root pyproject was not read"
    # THE MAP READS ONLY THE FAMILIES ITS GENERATOR PARSES, AND SAYS SO — asserted on what THIS
    # tree holds, never on a typed extension. `.tf` was typed here, and the public export (no
    # `infra/`) holds none, so the line was red there for a reason that was not the survey's.
    # Every tracked file whose suffix is neither inert, nor parsed, nor tooling must be reported
    # (the container images' `.Dockerfile` is one in both trees); and every reported suffix is
    # one some file under the root actually carries.
    root = Path(__file__).resolve().parent.parent
    tracked = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True,
                             timeout=120).stdout.split("\n")
    present = {Path(rel).suffix for rel in tracked if rel and Path(rel).suffix
               and Path(rel).suffix.lower() not in _INERT_SUFFIXES | _SOURCE_SUFFIXES
               and not _is_tooling(rel)}
    assert present, "this tree holds no code the map cannot read — the assertion has no subject"
    assert present <= set(result.unread_code_extensions), (
        f"code the map cannot read is in this tree and not reported: "
        f"{sorted(present - set(result.unread_code_extensions))}")
    for ext in result.unread_code_extensions:
        assert any(p.suffix == ext for p in root.rglob(f"*{ext}")), f"{ext} reported, none here"


def test_the_report_never_prints_a_claim_without_its_source(legacy: Path) -> None:
    """CATCHES a renderer that drops provenance under pressure. The citation is the part being
    sold; a sentence without one is an opinion, and a report of opinions is worth nothing in a
    room full of the people who wrote the code."""
    payload = {
        "does": [{"text": "emite boletos", "cites": ["cobranca/boleto.py:1"]}],
        "vocabulary": [{"term": "Fatura", "meaning": "o documento", "cites": ["cobranca/fatura.py"]}],
    }
    proposal = propose_context(survey(legacy), ask=_ask_saying(payload))
    report = render_context_report(proposal)
    assert "cobranca/boleto.py:1" in report
    assert "cobranca/fatura.py" in report
    overview = next(d for d in proposal.documents if d.kind == "overview")
    assert "`cobranca/boleto.py:1`" in overview.body


def test_a_proposal_object_alone_writes_nothing_anywhere(legacy: Path, tmp_path: Path) -> None:
    """The whole-module invariant, asserted rather than trusted: producing a proposal — survey,
    agent pass, documents, report — must leave the client's repository byte-identical."""
    before = sorted((p.relative_to(legacy).as_posix(), p.stat().st_mtime_ns)
                    for p in legacy.rglob("*") if p.is_file())
    proposal = propose_context(
        survey(legacy),
        ask=_ask_saying({"does": [{"text": "x", "cites": ["cobranca/boleto.py"]}]}),
        docs_root=tmp_path,
    )
    render_context_report(proposal)
    after = sorted((p.relative_to(legacy).as_posix(), p.stat().st_mtime_ns)
                   for p in legacy.rglob("*") if p.is_file())
    assert before == after
    assert isinstance(proposal, ContextProposal)


# ---------------------------------------------------------------------------------------------
# adversarial review, second pass — four defects measured on real repositories and fixed here
# ---------------------------------------------------------------------------------------------


def test_a_line_this_pass_could_not_verify_is_never_printed_as_a_verified_one(
    tmp_path: Path,
) -> None:
    """CATCHES THE VERIFICATION SILENTLY SWITCHING ITSELF OFF, on exactly the repositories this
    module exists for.

    `_Anchorer` opens at most `MAX_FILES_OPENED` distinct files to check a line number. Past that
    the line count is UNKNOWN — and `if line is not None and count is not None` let the citation
    through unchecked, so the claim was published as anchored fact with a `path:line` a client
    would open and find nothing at. Measured before the fix: thirty claims citing line 500 of
    one-line files came back as twenty anchored sentences, each printing `pkg/m2xx.py:500`, and
    nothing in the object, the report or the document said a ceiling had been reached. Small
    repositories never reach it; a legacy monolith with a chatty model does.

    The claim survives — the FILE was checked and is real — but citing only what was verified.
    """
    repo = tmp_path / "monolito"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "__init__.py").write_text("")
    for i in range(220):
        (repo / "pkg" / f"m{i:03}.py").write_text("x = 1\n")  # exactly ONE line each

    # 22 claims x 10 citations = 220 distinct files, every citation at an impossible line 500.
    # The first 200 are checked and rejected; the tail is what this guard is about.
    payload = {"does": [
        {"text": f"afirmacao {i}", "cites": [f"pkg/m{i * 10 + j:03}.py:500" for j in range(10)]}
        for i in range(22)
    ]}
    proposal = propose_context(survey(repo), ask=_ask_saying(payload))

    assert proposal.citations_unverified, "the ceiling was reached and nothing said so"
    for claim in proposal.what_it_does:
        for evidence in claim.evidence:
            assert evidence.line is None, (claim.text, evidence.locator)
    overview = next(d for d in proposal.documents if d.kind == "overview")
    assert ":500" not in overview.body, "an unchecked line was printed under a claim"
    assert "LINES NOT CHECKED" in render_context_report(proposal)


def test_a_line_that_was_checked_is_still_published_with_it(legacy: Path) -> None:
    """THE POSITIVE TWIN of the guard above, and the reason it cannot be satisfied by dropping
    every line number: below the ceiling the citation keeps its line, its excerpt, and reports
    nothing unverified."""
    payload = {"does": [{"text": "emite boletos", "cites": ["cobranca/boleto.py:2"]}]}
    proposal = propose_context(survey(legacy), ask=_ask_saying(payload))
    evidence = proposal.what_it_does[0].evidence[0]
    assert evidence.line == 2 and evidence.excerpt == "assert fatura.valor > 0"
    assert proposal.citations_unverified == []
    assert "LINES NOT CHECKED" not in render_context_report(proposal)


def test_a_questions_field_that_is_not_a_list_is_neither_a_crash_nor_one_letter_per_line(
    legacy: Path,
) -> None:
    """CATCHES the one section that was not type-checked, in both of the ways it actually broke.

    `(envelope.get("questions") or [])[:60]` assumes a list. Measured: `"questions": {...}` raised
    `KeyError: slice(None, 60, None)` straight out of `propose_context` — a traceback on a shared
    screen — and `"questions": "como isso funciona?"` sliced the STRING, so every character became
    its own numbered question and the agenda document opened `1. c  2. o  3. m  4. o`. The second
    is the worse one: it is a failure wearing the costume of an answer, in the document that IS
    the agenda for the room."""
    from_dict = propose_context(survey(legacy),
                                ask=_ask_saying({"does": [], "questions": {"a": "b"}}))
    assert from_dict.ok is True and from_dict.semantic is True

    from_string = propose_context(
        survey(legacy), ask=_ask_saying({"does": [], "questions": "como isso funciona?"}))
    assert not any(len(q) == 1 for q in from_string.questions), from_string.questions[:8]
    agenda = next(d for d in from_string.documents if d.kind == "questions")
    assert "\n1. c\n" not in agenda.body

    # THE POSITIVE TWIN, in the same test: a well-formed list must still reach the agenda, or the
    # two assertions above are satisfied perfectly by dropping every question the model asks.
    proper = propose_context(
        survey(legacy),
        ask=_ask_saying({"does": [], "questions": ["quem opera o fechamento mensal?"]}))
    assert "quem opera o fechamento mensal?" in proper.questions
    assert "quem opera o fechamento mensal?" in next(
        d for d in proper.documents if d.kind == "questions").body


def test_a_broken_symlink_in_the_checkout_is_not_written_through(
    legacy: Path, tmp_path: Path,
) -> None:
    """CATCHES a write leaving the checkout, and an outcome that names the wrong path.

    A DANGLING symlink is a path that exists on disk and about which `exists()` answers False —
    it follows the link. Measured before the fix: with `docs/glossario.md` a broken link,
    `write_text` followed it and put 662 bytes OUTSIDE the repository while `WriteOutcome`
    reported `wrote: docs/glossario.md`. No attacker is needed for this; a broken relative
    symlink is ordinary in a repository whose docs were moved years ago."""
    docs_root = tmp_path / "contexto"
    (docs_root / "docs").mkdir(parents=True)
    outside = tmp_path / "fora.md"
    (docs_root / "docs" / "glossario.md").symlink_to(outside)

    proposal = propose_context(survey(legacy), docs_root=docs_root)
    glossary = next(d for d in proposal.documents if d.kind == "glossary")
    assert glossary.exists is True, "the report would have called a skipped path 'new'"

    outcome = write_documents(proposal, docs_root, consent=True)
    assert not outside.exists(), "the write followed a symlink out of the checkout"
    assert "docs/glossario.md" in outcome.skipped
    assert outcome.wrote, "skipping one path must not stop the others"


def test_a_stack_read_that_failed_does_not_print_as_a_repository_with_no_stacks(
    legacy: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE None/[] RULE IN THE ARTEFACT THE CLIENT KEEPS.

    `RepoSurvey.stacks` is populated from the manifest read, and `survey()` deliberately swallows
    a failure there so the rest of the survey survives. But the empty list then rendered as
    *"nenhuma detectada"* — a measurement about the CLIENT'S repository produced by a failure of
    OURS, in a document written into their context repo and read by every agent afterwards. The
    object was already honest (`manifest is None`); this is the document catching up."""
    import openfactory.onboarding.context as module

    def _explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("the client's CI file is a YAML bomb")

    monkeypatch.setattr(module, "infer_manifest", _explode)
    broken = survey(legacy)
    assert broken.manifest is None and broken.stacks == []
    assert "nenhuma detectada" not in render_survey(broken)
    assert "não foi possível ler" in render_survey(broken)

    # THE POSITIVE TWIN: with the read working, the stack is named and the sentence above must
    # NOT appear — a renderer that always says "could not read" passes the half above and lies
    # about every repository that was read perfectly well.
    monkeypatch.undo()
    good = survey(legacy)
    assert good.manifest is not None
    assert [s.stack for s in good.stacks] == ["python"]
    assert "não foi possível ler" not in render_survey(good)
    assert "**python**" in render_survey(good)
