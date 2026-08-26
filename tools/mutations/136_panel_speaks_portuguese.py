"""#136: every word the panel shows a human is English.

The first four cuts put back the Portuguese that shipped — one per surface, so a partial
translation cannot pass. The last three attack the GUARD itself: a language detector is exactly the
shape that goes green because its word list missed, so the cuts that blind it must go red too.
"""

TEST = "tests/test_the_panel_speaks_one_language.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    ("a tile label goes back to Portuguese", PANEL,
     '<div class="k">total cost</div>', '<div class="k">custo total</div>'),

    ("the A/B arm labels go back", PANEL,
     'const _ARM_L={injected:"with map",off:"without map",unavailable:"map unavailable",',
     'const _ARM_L={injected:"com mapa",off:"sem mapa",unavailable:"mapa indisponível",'),

    ("the empty-table sentence goes back", PANEL,
     'class="sub" style="padding:16px">no tasks match this filter</td>',
     'class="sub" style="padding:16px">nenhuma task nesse filtro</td>'),

    ("the chat's own button goes back", PANEL,
     '<button class="btn sm" id="askBtn" onclick="askTechlead()">Send</button>',
     '<button class="btn sm" id="askBtn" onclick="askTechlead()">Enviar</button>'),

    ("the map filter's label moves without its value — the control stops filtering", PANEL,
     '  if(f.know){ tasks=tasks.filter(t=>_hasMap(t.knowledge)===(f.know==="with"));',
     '  if(f.know){ tasks=tasks.filter(t=>_hasMap(t.knowledge)===(f.know==="com"));'),

    # ── and the guard itself, which is the part most likely to be quietly decorative ────────────
    ("the detector loses the content words, so a two-word LABEL walks past", TEST,
     '    "custo", "custos", "projeto", "projetos", "modelo", "modelos", "papel", "mapa", "braço",',
     '    "zzz-not-a-word",'),

    ("the detector stops reading the page at all", TEST,
     "        stripped = _strip_urls(stripped)\n",
     "        stripped = ''\n"),

    ("stripping addresses also strips the prose", TEST,
     '    return re.sub(r"[\\w-]+(\\.[\\w-]+)+", " ", text)',
     '    return re.sub(r"\\S+", " ", text)'),
]
