"""The five guards the 2026-08-17 audit proved blind, re-proven able to see after repair.

Two were tautologies (the anchor was a substring of the guarded function's own `def` line — they
could NEVER fail), one had a live comment collision (release.py mentions `approve_job` in prose,
so deleting the real call stayed green), and two read raw text a comment could satisfy. Each cut
below removes exactly the thing the repaired guard now watches; before the repair, every one of
these cuts survived.
"""

TEST = "tests/test_a_wedged_job_has_an_exit.py"

MUTATIONS = [
    ("the product sweep stops gating on the product module",
     "openfactory/runtime/temporal/schedule.py",
     'cfg = getattr(project, "product", None)',
     'cfg = getattr(project, "produtos", None)',
     "tests/test_techlead_watch.py"),

    ("the set-language command stops reaching the setter",
     "openfactory/cli.py",
     "        reg.set_language(name, language)",
     "        _ = (reg, name, language)",
     "tests/test_a_project_can_change_the_language_it_speaks_first.py"),

    ("the release routes straight past the gate query",
     "openfactory/product/release.py",
     "        await approve_job(client, name, str(issue).lstrip(\"#\"),",
     "        await _signal_directly(client, name, str(issue).lstrip(\"#\"),",
     "tests/test_the_client_releases_production.py"),

    ("a retired suggestion silently disappears from the panel",
     "openfactory/api/panel.html",
     ': `<div class="sub">${esc(_RETIRED[_staged.reason]'
     '||("sugestão encerrada ("+_staged.reason+")"))}</div>`;',
     ': "";',
     "tests/test_a_staged_decision_survives_a_refresh.py"),

    ("the row stops carrying is_wedged's answer",
     "openfactory/runtime/temporal/view.py",
     '        row["wedged"] = is_wedged(row, live=live)',
     '        row["wedged"] = False'),
]
