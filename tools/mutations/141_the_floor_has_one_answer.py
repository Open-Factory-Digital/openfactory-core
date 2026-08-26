"""#141: one computation, six words, and no two surfaces that can disagree.

The first cuts restore the contradiction: a surface deriving its own opinion again, the ladder
losing a rung, `Armed` going back to meaning "no bad news arrived".

The rest go the other way, and they are the ones worth reading. A vocabulary this loud fails just
as badly by crying wolf: a paused tech-lead round must not paint a shipping factory red, a
machine-owned wait must not ask for a human, a demoted cause must not be swallowed, and a fresh
deployment must not read as broken for its first three minutes.

SUPERSEDED BY `144_the_floor_is_a_platform_capability.py` (2026-08-19). The JavaScript ladder
these cuts attacked moved to `openfactory/floor/` so that every channel — a Slack bot, the
CLI, a customer's own dashboard — gets the same verdict instead of re-implementing nine
rungs. The anchors no longer match and the runner refuses the plan rather than passing
quietly, which is the intended failure. Every claim it made is now made against the Python
ladder, and stated to a function rather than executed under node.
"""

TEST = "tests/test_the_floor_has_one_answer.py"
PANEL = "openfactory/api/panel.html"
ARMED = "tests/test_a_disabled_project_does_not_look_armed.py"

MUTATIONS = [
    # ── the contradiction, restored ─────────────────────────────────────────────────────────────
    ("the project card derives its own opinion again", PANEL,
     "    const fs=floorState(name);",
     "    const fs={cause:'x',level:'ok',clause:'',word:'Idle'};"),

    ("the header answers for the deployment while a project page is open", PANEL,
     '  const fs=floorState(curProject()||"");', "  const fs=floorState(\"\");"),

    ("the idle card stops redrawing when the verdict changes", PANEL,
     "      : `idle|${fs.cause}|${fs.level}|${fs.clause}`;", '      : "idle";', ARMED),

    ("the card's glyph stops coming from the same level as its word", PANEL,
     '        const glyph={ok:"—",clock:"◷",warn:"!",err:"⏸",unknown:"?"}[fs.level]||"—";',
     '        const glyph="—";'),

    ("the pickup answer stops being stored per project, on ONE of the two paths", PANEL,
     "  window._pickup[name]=(f.pickup_enabled===undefined)?null:f.pickup_enabled;",
     "  window._pickup=(f.pickup_enabled===undefined)?null:f.pickup_enabled;", ARMED),

    # ── Armed stops being earned ────────────────────────────────────────────────────────────────
    ("a poller that stopped firing is called Armed again", PANEL,
     '  if(ago>late) return {verdict:"late",ago,at:ik.fired_at,next:ik.next_at,\n'
     '                       skipped:ik.skipped_overlap};',
     '  if(false) return {verdict:"late"};'),

    ("a poller with no next tick is called Armed", PANEL,
     '  if(next==null||next<=0||ago>dead) return {verdict:"dead",ago,at:ik.fired_at};',
     '  if(ago>dead) return {verdict:"dead",ago,at:ik.fired_at};'),

    ("an unreadable intake is treated as running", PANEL,
     '  if(!ik||ik.known!==true) return {verdict:"unread"};',
     '  if(!ik) return {verdict:"unread"};'),

    ("an unknown pickup reads as armed", PANEL,
     "    if(fsPickup(snap,p.name)===null) unread.push(`whether ${p.name} takes cards`);\n", ""),

    ("the project's own switch is masked by a healthy deployment schedule", PANEL,
     "    if(fsPickup(snap,p.name)===false)", "    if(false)"),

    # ── the ladder loses its order ──────────────────────────────────────────────────────────────
    ("a disagreeing build stops outranking everything", PANEL,
     '    out.push(fsCause("unknown",1,"builds_disagree",',
     '    out.push(fsCause("unknown",9,"builds_disagree",'),

    ("a blind page reports the floor as if it could see it", PANEL,
     "  if(!f||!snap.frameAt){\n", "  if(false){\n"),

    ("an engine that did not answer becomes a verdict on the factory", PANEL,
     '      : fsCause("unknown",3,"engine_down",', '      : fsCause("stopped",3,"engine_down",'),

    ("the raw exception is put on the headline", PANEL,
     '          "the engine did not answer, so this page cannot say what the floor is doing",\n'
     '          {detail:String(f.error||"")}));',
     '          "the engine did not answer: "+String(f.error||"")));'),

    # ── the other direction: crying wolf ────────────────────────────────────────────────────────
    ("a paused tech-lead round paints a shipping factory red", PANEL,
     '      out.push(fsCause("needs",10,"watcher_dark",',
     '      out.push(fsCause("stopped",10,"watcher_dark",'),

    ("…and stops saying what stopping it costs", PANEL,
     '        `the ${who} round is paused — cards still start, nobody reviews between runs`',
     '        `the ${who} round is paused`'),

    ("…and takes the headline from Armed", PANEL,
     '      out.push(fsCause("needs",10,"watcher_dark",',
     '      out.push(fsCause("needs",4,"watcher_dark",'),

    ("a machine-owned wait starts asking for a human", PANEL,
     '    if(a.kind==="rate_limit"&&!fsOverdue(snap,j)){',
     '    if(false){'),

    ("a park is promoted off the vendor string the engine refuses to obey", PANEL,
     "  const wake=a.wakes_at?Date.parse(a.wakes_at):NaN;",
     "  const wake=a.retry_at?Date.parse(a.retry_at):NaN;"),

    ("a fresh deployment reads as broken for its first three minutes", PANEL,
     "    if(ik.num_actions===0&&born!=null&&born<=late&&next!=null&&next>0)\n"
     '      return {verdict:"starting",next:ik.next_at};\n', ""),

    ("a demoted cause is swallowed by the headline", PANEL,
     "  const also=pinned.concat(plain.slice(0,FS_ALSO_CAP));", "  const also=[];"),

    ("the cap eats a Stopped row", PANEL,
     "  const pinned=rest.filter(c=>c.pinned), plain=rest.filter(c=>!c.pinned);\n"
     "  const also=pinned.concat(plain.slice(0,FS_ALSO_CAP));",
     "  const also=rest.slice(0,FS_ALSO_CAP);"),

    ("one failure is reported as three", PANEL,
     "  const rest=causes.slice(1).filter(c=>!(downstream[win.cause]||[]).includes(c.cause));",
     "  const rest=causes.slice(1);"),

    ("the census prints its empty buckets", PANEL,
     "  return order.filter(k=>c[k]).map(k=>`· ${c[k]} ${label[k]}`).join(\" \");",
     "  return order.map(k=>`· ${c[k]} ${label[k]}`).join(\" \");"),

    ("a 503 from the inbox is read as 'nothing needs you'", PANEL,
     "  const inboxRows=Array.isArray(snap.inbox)", "  const inboxRows=(snap.inbox||[]).length>=0"),

    # ── the guard file that used to own these claims still owns them ────────────────────────────
    ("the disabled project's switch stops being consulted at all", PANEL,
     "function fsPickup(snap,project){\n  if(project in (snap.pickup||{})) return "
     "snap.pickup[project];",
     "function fsPickup(snap,project){\n  if(false) return snap.pickup[project];", ARMED),

]
