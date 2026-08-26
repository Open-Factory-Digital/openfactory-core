"""Every word the panel shows a human is English (#136).

2026-08-17, the pilot, on the surface ADR-0038 calls the REFERENCE one: *"o cost esta todo em
portugues, tinha que estar em ingles"*. He was right, and it was not a stray label — the entire cost
dashboard was Portuguese: filters, tiles, chart legends, table headers, the A/B explanation, and the
two chat fallbacks the panel prints when it cannot reach the worker.

WHY IT SURVIVED SO LONG. The house rule is *"como já alinhado tudo no sistema é em inglês"*, and it
was kept everywhere somebody thought to look. The cost dashboard was written in one sitting, by
somebody whose own language is Portuguese, for a reader who was in the room — and nothing ever
asked. A rule enforced by remembering is a rule that holds until the day somebody is in a hurry.

THE OPERATOR'S OWN LANGUAGE IS NOT THE PRODUCT'S. This one is easy to get backwards: the tech-lead
and the product role deliberately answer in the PROJECT's language (`test_the_operator_hears_the_
projects_language.py`) — that is agent voice, addressed to one client's team. The panel's own
chrome is the product speaking, and the product is English, whoever is reading it.

Scoped to what a human READS: comments are exempt, and deliberately so. Several of them quote
the product owner verbatim in Portuguese, and those citations are the evidence that justifies the code under
them — a guard that forced them out would be paid for in lost reasons.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from openfactory.api import app as api

PANEL_PATH = Path(inspect.getfile(api)).parent / "panel.html"
PANEL = PANEL_PATH.read_text()

#: Portuguese words with no English homograph. TWO CLASSES, and the second exists because the first
#: alone let the reported defect through: `custo total` is a Portuguese label containing no function
#: word at all, so a function-word detector called it English. Caught by feeding the guard the very
#: string the operator complained about, before trusting a green run.
#:
#: Function words first — a Portuguese SENTENCE cannot avoid them:
PT_WORDS = [
    "não", "nao", "são", "está", "estão", "foi", "foram", "será", "com", "sem", "pelo", "pela",
    "isso", "esse", "essa", "este", "esta", "aquele", "nenhum", "nenhuma", "todos", "todas",
    "para", "pra", "porque", "quando", "onde", "qual", "quais", "mais", "muito", "também",
    "então", "já", "ainda", "aqui", "agora", "depois", "antes", "sobre", "entre", "cada",
    "mesmo", "mesma", "outro", "outra", "seu", "sua", "seus", "suas", "você", "voce",
    "fechar", "limpar", "carregando", "salvar", "enviar", "clique", "aguarde",
    # …then content words a two-word LABEL is made of. Every one of these is Portuguese-only: no
    # English homograph, and none is a substring this codebase uses as an identifier. Deliberately
    # NOT here: `data`, `total`, `cost`, `no` — shared with English or with HTML attributes, and a
    # detector that cries on `data-since` is a detector somebody deletes.
    "custo", "custos", "projeto", "projetos", "modelo", "modelos", "papel", "mapa", "braço",
    "título", "titulo", "tarefa", "tarefas", "usuário", "usuario", "mediano", "medianos",
    "mediana", "medianas", "médio", "medio", "médios", "médias", "média", "erro", "aviso",
    "pergunta", "resposta", "conhecimento", "chão", "arquivo", "pasta", "senha", "ajuda",
    "aguardando", "executada", "expirou", "indisponível", "indisponivel", "histórico",
]
_PT = re.compile(r"(?<![\w-])(" + "|".join(PT_WORDS) + r")(?![\w-])", re.IGNORECASE)


def _visible_text() -> list[tuple[int, str]]:
    """The lines a human can read, with comments removed — numbered against the real file.

    Line numbers are preserved by BLANKING comments rather than deleting them, so a failure names
    the line an editor can open. Both comment syntaxes: `//` for the script, `/* */` for the CSS
    and any block comment — the CSS colour guard learned that the hard way when a card number in a
    `/* */` comment was read as a hex value.
    """
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), PANEL, flags=re.S)
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        stripped = re.sub(r"(^|\s)//.*$", "", line)
        stripped = _strip_urls(stripped)
        if stripped.strip():
            out.append((i, stripped))
    return out


def _strip_urls(text: str) -> str:
    """Addresses are nobody's language.

    `com` is a Portuguese word and the commonest TLD there is, so `dev.azure.com` and
    `github.com` read as Portuguese to any word-boundary detector — nine of them across the CLI
    and the API, found by running this detector over them. A guard that fires on every link is a
    guard whose next failure is assumed to be noise."""
    text = re.sub(r"https?://\S+", " ", text)
    return re.sub(r"[\w-]+(\.[\w-]+)+", " ", text)


def test_the_detector_actually_READS_the_page():
    """The positive twin, and a mutation survived without it.

    "Nothing on this page is Portuguese" is a claim about an ABSENCE, and absence reads as
    compliance: blank the extractor and the guard below passes over an empty string, for ever,
    while the page says whatever it likes. So assert the detector still has the page in its hands —
    by volume, and by strings only a real read can produce."""
    lines = _visible_text()
    assert len(lines) > 1000, (
        f"the extractor returned {len(lines)} readable lines from a {len(PANEL.splitlines())}-line "
        f"page — it is no longer reading it, and the guard below is passing over nothing")
    body = "\n".join(t for _, t in lines)
    # LANDMARKS THE PANEL ITSELF OWNS. The fourth used to be a word of the status vocabulary,
    # which moved to the platform in #144 — a landmark that can migrate out from under the guard
    # is a landmark that silently stops proving anything.
    for landmark in ("Recent runs", "total cost", "askTechlead", "reading the floor"):
        assert landmark in body, f"the extractor dropped {landmark!r} — it is not reading the page"


def test_no_portuguese_reaches_the_screen():
    """The whole page, not the dashboard that happened to be reported."""
    offenders = [(n, _PT.search(t).group(0), t.strip()[:100])
                 for n, t in _visible_text() if _PT.search(t)]
    assert not offenders, "the panel shows Portuguese to its reader:\n" + "\n".join(
        f"  {PANEL_PATH.name}:{n}  [{w}]  {t}" for n, w, t in offenders)


def test_the_COST_dashboard_is_english_end_to_end():
    """The surface he reported, asserted by its own strings rather than by the absence of others —
    absence reads as compliance, and a dashboard deleted would pass the test above."""
    for shown in ("total cost", "average cost / task", "cost per day", "by model", "by harness",
                  "median tokens", "with map", "without map", "map unavailable",
                  "no tasks match this filter", "knowledge map (OKF)"):
        assert shown in PANEL, f"the cost dashboard lost {shown!r}"


def test_the_FILTER_VALUE_moved_with_its_label():
    """The one place this translation could break behaviour rather than wording. The `map` filter
    compares against its option's VALUE, so renaming the label alone leaves a control that reads
    "with map" and filters for a string nothing emits — every row silently vanishing."""
    values = set(re.findall(r'<option value="(with|without|com|sem)"', PANEL))
    assert values == {"with", "without"}, f"the map filter's option values are {values}"
    assert 'f.know==="with"' in PANEL, (
        "the filter's reader still compares against the old value — the control is now decorative")


def test_the_AGENT_VOICE_is_left_alone():
    """The other half of the rule, and the one this guard could easily break. The tech-lead and the
    product role answer in the PROJECT's language by design — that is a client's team being spoken
    to, not the product's chrome. A guard that swept those away would 'fix' a feature."""
    from openfactory.product import voice

    assert "language" in inspect.getsource(voice), (
        "the product role no longer takes a language — the panel's English rule has been applied "
        "to the agent voice, which is a different rule")


@pytest.mark.parametrize("smuggled", [
    '  <div class="k">custo total</div>',
    '  toast("não consegui")',
    '      <option value="">todos</option>',
])
def test_the_guard_ACTUALLY_BITES(smuggled):
    """Verify the verifier. A detector built from a word list is exactly the shape that passes
    because its list missed — so feed it cases that MUST fail before trusting a green run."""
    assert _PT.search(smuggled), f"Portuguese walked straight past the detector: {smuggled!r}"


def test_an_ADDRESS_is_not_a_language():
    """`com` is both a Portuguese preposition and the commonest TLD, so a link reads as Portuguese
    to any word-boundary detector. Asserted through `_strip_urls`, not by hoping no link is ever
    added to this page — the panel links to boards, consoles and engines by construction."""
    for link in ('<a href="https://dev.azure.com/acme/_git/repo">board ↗</a>',
                 'board = `https://github.com/${owner}/projects/${n}`',
                 '<a href="https://eu-west-2.console.aws.amazon.com/ecs">console ↗</a>'):
        assert not _PT.search(_strip_urls(link)), f"a link was read as Portuguese: {link!r}"
    assert _PT.search(_strip_urls('<div>com mapa</div>')), (
        "stripping addresses also stripped the prose — the guard now sees nothing")


def test_the_guard_does_not_fire_on_the_ENGLISH_page():
    """Its positive twin: a detector that flagged ordinary English would be turned off within a
    week, and `com`/`sem`/`data` are the sort of fragment that appears inside English identifiers."""
    for innocent in ('<div class="k">total cost</div>',
                     'const _ARM_L={injected:"with map",off:"without map"}',
                     'data-p="${esc(j.project)}" data-since="${esc(j.start_time)}"',
                     'toast("Board scan", d.message || "done")',
                     '<th class="num">median in / out</th>'):
        assert not _PT.search(innocent), f"the detector fires on English: {innocent!r}"
