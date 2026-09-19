"""A declined read is said where it is read, proven by breaking it (2026-09-19).

Two readers #181 left behind. `pollBudget` answered every failure with the SERVER's `unread`, so a
403 about the session hovered as "the poller scans without that safety net"; `refreshChat` returned
from its `catch` before painting, so a declined chat said nothing, went on offering Send, and drew
neither a typed question nor the server's refusal of it.

FOUR CLAIMS:

  1. **The budget's hover text never borrows the server's word**: declined is `refused`, a request
     with no answer is `unasked`, nothing asked yet is silent — and the server's own `unread` still
     reads as it did.
  2. **The chat says which outcome its read had**, inside the chat, with the server's sentence as
     data; the note leaves when the read is answered, and a pushed frame withdraws "could not be
     read" but never a refusal.
  3. **Send is not offered to a session the server has just declined**, and is offered again the
     moment it is answered — a read that merely failed withdraws nothing.
  4. **The repaint does not depend on the read**: the last answer is kept per project, and what a
     person typed or pressed is answered on screen under a declined read.

The guard is `tests/test_a_declined_read_is_said_where_it_is_read.py`: the page's own functions
under node (the harness of `test_a_refusal_is_not_an_answer`), and the real scope gate's bytes.
"""

TEST = "tests/test_a_declined_read_is_said_where_it_is_read.py"

PAGE = "openfactory/api/panel.html"

MUTATIONS = [
    # ── 1. the budget ───────────────────────────────────────────────────────────────────────────
    ("THE DEFECT ITSELF: every failed budget read is the server's `unread`", PAGE,
     '  catch(e){_budget={state:declined(e)?"refused":"unasked",said:String(e&&e.message||e)};paintFloor();return}\n',
     '  catch(e){_budget={state:"unread"};paintFloor();return}\n'),
    ("a declined budget read is filed as a page that could not ask", PAGE,
     '_budget={state:declined(e)?"refused":"unasked",', '_budget={state:"unasked",'),
    ("the hover claims the vendor's failure before anything was asked", PAGE,
     'let _budget={state:""};\n', 'let _budget={state:"unread"};\n'),
    ("a declined budget read hovers as nothing at all", PAGE,
     '  if(b.state==="refused")return "API budget not shown — this session may not read it";\n', ""),
    ("a page that could not ask hovers as nothing at all", PAGE,
     '  if(b.state==="unasked")return `API budget not known', '  if(b.state==="never")return `API budget not known'),
    ("a declined budget read does not redraw the header", PAGE,
     'said:String(e&&e.message||e)};paintFloor();return}', 'said:String(e&&e.message||e)};return}'),
    ("the server's own `unread` loses its sentence", PAGE,
     '  if(b.state==="unread")return `${who}${pool} budget could not be read',
     '  if(b.state==="unread")return "";return `${who}${pool} budget could not be read'),

    # ── 2. the chat's note ──────────────────────────────────────────────────────────────────────
    ("THE DEFECT ITSELF: a chat read that fails returns before anything is said or drawn", PAGE,
     "  catch(e){\n    if(asked!==_chatProject)return;\n    const said=String(e&&e.message||e);\n",
     "  catch(e){return;\n    if(asked!==_chatProject)return;\n    const said=String(e&&e.message||e);\n"),
    ("a declined chat read is filed as one that could not be read", PAGE,
     '    if(declined(e)){_chatRefused=said;_chatErr=""}else{_chatErr=said;_chatRefused=""}\n',
     '    _chatErr=said;_chatRefused="";\n'),
    ("a chat read that failed is filed as declined", PAGE,
     '    if(declined(e)){_chatRefused=said;_chatErr=""}else{_chatErr=said;_chatRefused=""}\n',
     '    _chatRefused=said;_chatErr="";\n'),
    ("the refusal never clears once the read is answered", PAGE,
     '  _chatRefused="";\n  paintChat(d);\n', '  paintChat(d);\n'),
    ("a pushed frame withdraws a refusal", PAGE,
     '  if(!kept){_chatLast=d;_chatErr=""}\n', '  if(!kept){_chatLast=d;_chatErr="";_chatRefused=""}\n'),
    ("a pushed frame leaves 'could not be read' standing", PAGE,
     '  if(!kept){_chatLast=d;_chatErr=""}\n', '  if(!kept){_chatLast=d}\n'),
    ("the server's sentence is dropped from the note", PAGE,
     "`${esc(_chatRefused)}</span> Send is off", "`</span> Send is off"),
    ("the server's sentence reaches the note as markup", PAGE,
     "`${esc(_chatRefused)}</span> Send is off", "`${_chatRefused}</span> Send is off"),
    ("the chat is mounted with nowhere to say it", PAGE,
     '      <div class="sub" id="chatNote" style="display:none;padding:8px 14px;border-top:1px solid var(--line)"></div>\n',
     ""),
    ("the note is composed and painted nowhere", PAGE,
     '  if(n){n.innerHTML=chatNote();n.style.display=n.innerHTML?"":"none"}\n', ""),

    # ── 3. send ─────────────────────────────────────────────────────────────────────────────────
    ("Send stays offered to a session the server has declined", PAGE,
     "  const off=!!_chatRefused;\n", "  const off=false;\n"),
    ("Send is withdrawn from a read that merely failed", PAGE,
     "  const off=!!_chatRefused;\n", "  const off=!!(_chatRefused||_chatErr);\n"),
    ("Send never comes back", PAGE,
     "  const off=!!_chatRefused;\n", '  const off=!!_chatRefused||!!(($("#askBtn")||{}).disabled);\n'),

    # ── 4. the repaint ──────────────────────────────────────────────────────────────────────────
    ("a declined read says so and draws nothing: the typed question and its refusal stay invisible",
     PAGE, "    paintChat(_chatLast||{},true);return}\n", "    drawChatNote();return}\n"),
    ("a declined read wipes the thread it was keeping", PAGE,
     "    paintChat(_chatLast||{},true);return}\n", "    paintChat({},true);return}\n"),
    ("a refusal that lands late is said on the NEXT project's chat", PAGE,
     "  catch(e){\n    if(asked!==_chatProject)return;\n", "  catch(e){\n"),
    ("an answer that lands late is drawn as the NEXT project's thread", PAGE,
     "  if(asked!==_chatProject)return;\n  // ANSWERED, so this credential", "  // ANSWERED, so this credential"),
    ("the next project's refusal keeps the previous project's thread", PAGE,
     '  _chatLast=null;_chatRefused="";_chatErr="";\n', '  _chatRefused="";_chatErr="";\n'),
]
