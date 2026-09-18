"""#181, proven by breaking it — the panel never reads a refusal as an answer, and a session has a
way out.

OBSERVED on a one-machine deployment, 2026-09-18, in a floor tab whose credential had been replaced
by a product-only sign-in in another tab of the same browser. The server refused every floor read
from that tab (`DENIED_SCOPE_READ … 403`, dozens of times) and the page drew:

    cockpit   harness blank · auth blank · models `agent ?` · review `unknown` · token pool `0 ()`
    header    "Armed — nothing is running — the next card in TO-DO will be picked up",
              then "Unknown — this page has heard nothing for N"
    exit      none: `/auth/logout` and `whoami.logout` existed; the page never read either

FIVE CLAIMS:

  1. **`api()` rejects on every non-2xx**, carrying the status, the parsed body and the server's
     own sentence — so the `catch` paths callers already had are what runs. `mfetch` still hands
     back the response to the callers that read a refusal's body themselves.
  2. **A 403 asks `/api/whoami` again** — once per burst — and a credential that became
     product-only takes the route `boot()` takes, once, and is told why on arrival.
  3. **The floor header tells REFUSED from HEARD NOTHING from COULD NOT ASK**, never repeats a
     verdict given to the previous credential, and comes back when it is answered again.
  4. **No reader draws a refusal as the factory**: the cockpit, the engine frame, the board, the
     cost dashboard, a run's log, the address reading.
  5. **A sign-out control wherever `whoami` names a `logout`**, on both pages, and nothing where
     it is null. What the server said stays data.

The guard is `tests/test_a_refusal_is_not_an_answer.py`: the page's own functions, executed under
node against a `fetch` the case controls, and the real scope gate under `TestClient`.
"""

TEST = "tests/test_a_refusal_is_not_an_answer.py"

PAGE = "openfactory/api/panel.html"
APP = "openfactory/api/app.py"

MUTATIONS = [
    # ── 1. api() ────────────────────────────────────────────────────────────────────────────────
    ("THE DEFECT ITSELF: `api()` hands back the body for any status", PAGE,
     "  if(r.ok)return r.json();\n"
     "  let body=null;try{body=await r.json()}catch(e){}\n"
     "  throw refusal(r.status,body)}",
     "  return r.json()}"),

    ("the rejection loses the server's sentence, so `e.message` cannot say the remedy", PAGE,
     '  const e=new Error((typeof said==="string"&&said)?said:',
     "  const e=new Error(false?said:"),

    ("the rejection loses its status, so nobody can tell declined from failed", PAGE,
     'e.name="Refusal";e.status=status;e.body=body;return e}',
     'e.name="Refusal";e.body=body;return e}'),

    # ── 2. who is this browser holding NOW ──────────────────────────────────────────────────────
    ("a 403 no longer asks who the browser is holding", PAGE,
     "  if(r.status===403)askWhoAgain();\n",
     ""),

    ("every refusal of a burst starts its own `whoami`", PAGE,
     "  if(_whoAsk)return _whoAsk;\n",
     ""),

    ("`whoami` is asked again on the very next refusal", PAGE,
     "  if(Date.now()-_whoAskedAt<WHO_AGAIN_MS)return Promise.resolve(me);\n",
     ""),

    ("a credential that became product-only stays on a floor it may not read", PAGE,
     '      if(productOnly()&&_surface!=="product"&&takeBootsRoute())return me;\n',
     ""),

    ("the product page is reloaded by a row its person may not run", PAGE,
     'if(productOnly()&&_surface!=="product"&&takeBootsRoute())',
     "if(productOnly()&&takeBootsRoute())"),

    ("the reload is not limited, so a whoami that fails at boot loops the tab", PAGE,
     "  if(Date.now()-last<60000)return false;\n",
     ""),

    ("the arrival is said on every later boot too", PAGE,
     'let say="";try{say=sessionStorage.getItem(MOVED_KEY+".say")||"";'
     'sessionStorage.removeItem(MOVED_KEY+".say")}catch(e){}',
     'let say="";try{say=sessionStorage.getItem(MOVED_KEY+".say")||""}catch(e){}'),

    ("the arrival is a toast again, gone before the person is back in the tab", PAGE,
     "  if(say)_movedNote=true}",
     '  if(say)toast(sessionWho(),"this browser\'s session changed","err")}'),

    ("the product page is drawn without the reason it is there", PAGE,
     "    ${movedNotice()}\n",
     ""),

    ("the notice cannot be put away", PAGE,
     'function dismissMoved(){_movedNote=false;const n=$("#movedNote");if(n)n.remove()}',
     'function dismissMoved(){const n=$("#movedNote");if(n)n.remove()}'),

    ("the notice names a way out a token deployment does not have", PAGE,
     '          ${(me&&me.logout)?`<a class="btn sm" href="${esc(safeUrl(me.logout))}">Sign out</a>`:""}',
     '          <a class="btn sm" href="${esc(safeUrl(me.logout))}">Sign out</a>'),

    # ── 3. the floor header ─────────────────────────────────────────────────────────────────────
    ("a declined floor read is filed as a failure to ask", PAGE,
     '    if(declined(e)){_floorRefused=said;_floorErr=""}else{_floorErr=said;_floorRefused=""}}',
     "    _floorErr=said}"),

    ("the header has no sentence for refused, and falls through to the last verdict", PAGE,
     "  if(_floorRefused){\n    const who=sessionWho();",
     "  if(false){\n    const who=sessionWho();"),

    ("a refusal never clears, so an answered floor still reads Refused", PAGE,
     '  if(got&&got.word){_floorErr="";_floorRefused="";_floor=got;_floorAt=Date.now()}',
     '  if(got&&got.word){_floorErr="";_floor=got;_floorAt=Date.now()}'),

    ("a token deployment is told to sign out through a door that is not drawn", PAGE,
     '      +((me&&me.logout)?" — sign out (top right) to use another identity"',
     '      +(true?" — sign out (top right) to use another identity"'),

    ("the refused header does not say who is signed in", PAGE,
     "    const who=sessionWho();\n    const clause=",
     '    const who="";\n    const clause='),

    ("a declined session is still offered a scan that can only be refused", PAGE,
     '  return !(engine.jobs.some(j=>j.status=="running")||parked||_floorRefused)}',
     '  return !(engine.jobs.some(j=>j.status=="running")||parked)}'),

    ("the scan is never offered, to anybody", PAGE,
     '  return !(engine.jobs.some(j=>j.status=="running")||parked||_floorRefused)}',
     "  return false}"),

    ("the project page stops asking, and decides the button on its own", PAGE,
     '  if(sb)sb.style.display=scanOffered(parked)?"":"none";',
     '  if(sb)sb.style.display=(engine.jobs.some(j=>j.status=="running")||parked)?"none":"";'),

    # ── 4. the readers ──────────────────────────────────────────────────────────────────────────
    ("the cockpit stays the blank it was drawn with", PAGE,
     "  catch(e){\n    const c=$(\"#cockpit\");",
     "  catch(e){refreshProject();return;\n    const c=$(\"#cockpit\");"),

    ("saying why the cockpit failed cost the redraw: the floor card keeps what it showed before",
     PAGE,
     "\n    refreshProject();return}\n",
     "\n    return}\n"),

    # The older guard's assertion was rewritten in this branch (it pinned one spelling of the
    # catch), so the same cut is aimed at it: a rewritten assertion that cannot fail is worse
    # than the brittle one it replaced.
    ("the same cut, seen by the guard that has protected this since #134", PAGE,
     "\n    refreshProject();return}\n",
     "\n    return}\n",
     "tests/test_a_disabled_project_does_not_look_armed.py"),

    ("a harness the answer did not carry is a blank gauge again", PAGE,
     '<span class="lbl">harness</span><b>${known(f.harness)}</b>',
     '<span class="lbl">harness</span><b>${esc(f.harness)}</b>'),

    ("models nobody sent read `agent ?`", PAGE,
     "  const modelsHtml=!f.models ? unknown\n    : (f.single_agent",
     "  const modelsHtml=(f.single_agent"),

    ("a token pool nobody sent reads `0 ()`", PAGE,
     '<span class="lbl">token pool</span><b>${f.tokens?',
     '<span class="lbl">token pool</span><b>${true?'),

    ("the board does not keep why it could not be read", PAGE,
     "  catch(e){ d = null; _bd.why = String((e&&e.message)||e); }",
     "  catch(e){ d = null; }"),

    ("the board panel does not say why", PAGE,
     "    const why = (!d && _bd.why)\n",
     "    const why = (false)\n"),

    ("the cost dashboard drops the server's sentence", PAGE,
     "catch(e){ d=null;why=String((e&&e.message)||e) }",
     "catch(e){ d=null }"),

    ("a declined log read is a run that wrote no journal", PAGE,
     "      _logs.events=[];_logs.eventsError=String((e&&e.message)||e) }",
     "      _logs.events=[] }"),

    ("the address form parses whatever came, whatever its status", PAGE,
     "    d=await api(`/api/address?${q}`);",
     "    const r=await mfetch(`/api/address?${q}`);d=await r.json();"),

    ("a declined address read is silent", PAGE,
     '    el.innerHTML=(e&&e.status)?`<span class="badge b-err">not read</span> ${esc(e.message)}`:"";',
     '    el.innerHTML="";'),

    # ── 5. the way out ──────────────────────────────────────────────────────────────────────────
    ("a door is drawn on a deployment with no session to end", PAGE,
     '  if(!me||!me.logout){el.style.display="none";el.innerHTML="";return}',
     '  if(!me){el.style.display="none";el.innerHTML="";return}'),

    ("neither page boots with the way out drawn", PAGE,
     "  paintSession();   // before either page is drawn",
     "  // before either page is drawn"),

    ("the sign-out link goes wherever the payload says, scheme and all", PAGE,
     '<a id="signOut" href="${esc(safeUrl(me.logout))}">',
     '<a id="signOut" href="${esc(me.logout)}">'),

    ("who is signed in is written into the header as markup", PAGE,
     '  el.innerHTML=`<span id="whoTxt">${esc(sessionWho()||"signed in")}</span>`',
     '  el.innerHTML=`<span id="whoTxt">${sessionWho()||"signed in"}</span>`'),

    ("a narrowed credential is named like an unscoped one", PAGE,
     '  const narrow=Array.isArray(me.scopes)?` (${me.scopes.join(", ")||"no area"})`:"";',
     '  const narrow="";'),

    ("the header is not repainted once the page knows who is signed in", PAGE,
     "      paintSession();paintFloor()}\n    return me})();",
     "      }\n    return me})();"),

    # ── 6. the other end of the contract ────────────────────────────────────────────────────────
    ("the scope gate's refusal is no longer a 403", APP,
     '                               f"{wanted}."},\n                    status_code=403)',
     '                               f"{wanted}."},\n                    status_code=409)'),
]
