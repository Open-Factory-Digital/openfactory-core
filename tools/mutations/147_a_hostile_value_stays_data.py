"""#147: an agent-authored value stops reaching JavaScript through an HTML attribute.

The cuts put each shape back — the string one the old ratchet knew, and the three it did not: a
single-quoted attribute, a non-click event, and a bare number where nothing has to escape a string
because there is no string.

The rest go the other way. A security fix on twenty-six buttons fails just as badly by leaving a
dead control on a gate a human is waiting at, so the dispatch table is guarded in both directions:
every verb with buttons has an entry, and every entry has buttons.
"""

TEST = "tests/test_a_hostile_value_stays_data.py"
PANEL = "openfactory/api/panel.html"
RATCHET = "tests/test_a_free_deployment_can_read_its_logs.py"

MUTATIONS = [
    # ── each shape, put back ────────────────────────────────────────────────────────────────────
    ("a decision option's key goes back through a JS string in an attribute", PANEL,
     'data-act="decide" data-p="${esc(p)}" data-i="${esc(i)}" data-k="${esc(o.key)}"',
     'onclick="decide(\'${esc(p)}\',\'${esc(i)}\',\'${esc(o.key)}\')"'),

    ("a requirement number goes back as a BARE argument — nothing to escape at all", PANEL,
     'data-act="acceptRequirement" data-n="${esc(r.number)}"',
     'onclick="acceptRequirement(${r.number})"'),

    ("a non-click event goes back — the door beside the one being watched", PANEL,
     'data-oninput="paintJobLog" data-p="${esc(project)}" data-i="${esc(issue)}"',
     'oninput="paintJobLog(\'${esc(project)}\',\'${esc(issue)}\')"'),

    ("the chat's answer token goes back", PANEL,
     'data-act="answerQuestion" data-p="${esc(_chatProject)}" data-tok="${esc(m.token)}" '
     'data-k="${esc(o.key)}"',
     'onclick="answerQuestion(\'${esc(_chatProject)}\',\'${esc(m.token)}\','
     '\'${esc(o.key)}\')"'),

    # ── the pattern narrows, in its ONE home ────────────────────────────────────────────────────
    ("the pattern narrows back to the one shape the first ratchet knew", TEST,
     'INLINE_HANDLER = re.compile(r"""on\\w+\\s*=\\s*["\'](\\w+)\\s*\\([^)]*\\$\\{""", re.I)',
     'INLINE_HANDLER = re.compile(r"""onclick="(\\w+)\\(\'\\$\\{esc\\(""", re.I)'),

    ("the seven are grandfathered again, so the rule stops being simply true", RATCHET,
     "_INLINE_ARG_HANDLERS: set[str] = set()",
     '_INLINE_ARG_HANDLERS: set[str] = {"actJob", "answerQuestion", "decide", "mergeGate",\n'
     '                                  "openPromote", "scanNow", "submitPromote"}'),

    ("the stripper stops stripping, so the guard trips on the prose explaining itself", TEST,
     '    code = re.sub(r"/\\*.*?\\*/", "", page, flags=re.S)\n'
     '    return "\\n".join(re.sub(r"(^|\\s)//.*$", "", ln) for ln in code.splitlines())',
     "    return page"),

    # ── the other direction: a fix must not leave a dead control ────────────────────────────────
    ("a converted button loses its dispatch entry — a dead control on a human gate", PANEL,
     "  mergeGate:     d=>mergeGate(d.p,d.i,d.k),\n", ""),

    ("…and the reverse: an entry nobody carries, dead code in the one file no test executes",
     PANEL, "  scanNow:       d=>scanNow(d.p),",
     "  scanNow:       d=>scanNow(d.p),\n  neverUsed:     d=>scanNow(d.p),"),

    ("the listener goes back to per-button, so a re-render leaves it dead", PANEL,
     '  const el=ev.target.closest&&ev.target.closest("[data-act]");\n  if(!el)return;\n',
     "  const el=null;\n  if(!el)return;\n"),

    ("an unknown verb fails silently, looking like a button nobody pressed", PANEL,
     '  if(!run){console.warn("no handler for data-act",el.dataset.act);return}',
     "  if(!run)return;"),
]
