"""#135: a stack rebuilt by halves must say so — and a healthy one must stay quiet.

Half these cuts restore the original blindness (nobody announces, nobody compares, the banner is
never painted). The other half go the OTHER way: they make the banner fire when it must not. Both
directions matter here — a warning that says "this screen is unreliable" is worthless the day it
starts crying wolf, and this one would cry on every deployment that has not rebuilt yet.
"""

TEST = "tests/test_the_two_halves_agree_on_which_code_they_run.py"
NS = "openfactory/namespace.py"
APP = "openfactory/api/app.py"
PANEL = "openfactory/api/panel.html"
WORKER = "openfactory/runtime/temporal/worker.py"
CLI = "openfactory/cli.py"

MUTATIONS = [
    # ── the blindness this card removes ─────────────────────────────────────────────────────────
    ("the worker stops announcing its build at boot", WORKER,
     '    log.info("this worker runs build %s", _ns.announce_build(WORKER_ROLE) or '
     '"(not a built image)")\n', ""),

    ("the PANEL stops announcing, so a stale panel is invisible to the worker", CLI,
     "    namespace.announce_build(PANEL_ROLE)\n", ""),

    ("doctor stops naming a half that runs different code", CLI,
     "        for role, (stamp, when) in sorted("
     "namespace.build_disagreement(WORKER_ROLE).items()):",
     "        for role, (stamp, when) in sorted({}.items()):"),

    ("a half-written announcement is read as somebody's build", NS,
     "        except (OSError, ValueError):\n            continue",
     "        except (OSError, ValueError):\n            data = {}"),

    ("a process compares itself against its own announcement and always agrees", NS,
     "    return {r: v for r, v in announced_builds(where=where).items()\n"
     "            if r != role and v[0] and v[0] != mine}",
     "    return {r: v for r, v in announced_builds(where=where).items()\n"
     "            if v[0] and v[0] != mine}"),

    ("the report is dropped when the engine is unreachable", APP,
     '        return {"connected": False, "error": str(exc), "jobs": [], "build": build}',
     '        return {"connected": False, "error": str(exc), "jobs": []}'),

    ("the report is dropped when the engine is UP — the working case", APP,
     '            "connected": True, "address": addr, "ui_base": tv.ui_base(), "build": build,',
     '            "connected": True, "address": addr, "ui_base": tv.ui_base(),'),

    ("the banner is never painted from the engine frame", PANEL,
     "  paintBuildSplit();  // before anything else reads this page: it may not be the page it "
     "thinks\n", ""),

    ("the banner names no build, so nobody can tell which half is old", PANEL,
     '    +`served by <code>${esc(b.stamp||"?")}</code>${when(b.built_at)}; '
     '${others.join("; ")}. Whatever `',
     "    +`served by an older build. Whatever `"),

    ("the banner stops naming WHICH half disagrees", PANEL,
     "    .map(([r,o])=>`the <b>${esc(r)}</b> runs "
     "<code>${esc(o.stamp)}</code>${when(o.built_at)}`);",
     "    .map(([r,o])=>`another half runs different code`);"),

    ("the remedy stops warning against the narrowed rebuild that caused this", PANEL,
     "    +`no service name after it — then reload.`;",
     "    +`the service name of your choice — then reload.`;"),

    ("the banner is moved out of the header, so some screens cannot show it", PANEL,
     '  <div class="buildsplit" id="buildsplit" style="display:none"></div>\n</header>',
     "</header>"),

    # ── the other direction: it must not cry wolf ───────────────────────────────────────────────
    ("a half that has not announced is reported as DISAGREEING", APP,
     "    if not mine or not others:\n        agree: bool | None = None",
     "    if not mine:\n        agree: bool | None = None"),

    ("a checkout is reported as disagreeing with whatever it can see", APP,
     "    if not mine or not others:\n        agree: bool | None = None",
     "    if not others:\n        agree: bool | None = None"),

    ("a role that announced an EMPTY stamp is compared as if it were a build", APP,
     "    others = {r: v for r, v in announced_builds().items() if r != PANEL_ROLE and v[0]}",
     "    others = {r: v for r, v in announced_builds().items() if r != PANEL_ROLE}"),

    ("the banner fires on anything that is not a proven agreement", PANEL,
     "  if(b.agree!==false){el.style.display=\"none\";return}",
     "  if(b.agree===true){el.style.display=\"none\";return}"),

    ("a checkout writes a build file to say it is nothing in particular", NS,
     "    if not stamp:\n", "    if False:\n"),
]
