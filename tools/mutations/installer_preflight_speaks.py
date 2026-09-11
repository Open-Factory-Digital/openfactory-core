"""P1.1 — preflight names a cause, a remedy and a machine, and its JSON is a contract.

Run:  .venv/bin/python tools/mutate.py tools/mutations/installer_preflight_speaks.py

Twelve cuts across three properties.

THE REMEDY cuts are the house rule made testable: a refusal with no remedy is a symptom handed to
the one person who does not yet know the system.

THE THIRD-STATE cuts are the ones worth reading. `answered=False` is neither a pass nor a failure,
and both ways of collapsing it are represented here — turning "could not ask" into a PASS hands the
agent lane a clean bill of health for a question nobody could answer, and turning it into a FAILURE
sends somebody to `docker pull` against a daemon that is not running. `doctor.BoardUnreadable`
spends a page on why two values cannot carry three meanings; these are that page, executable.

THE SCHEMA cuts break the document the agent lane reads. Its shape is a published interface the
moment `install.md` is served, so a key added or dropped without moving `SCHEMA` is a reader
half-understanding a document it believes it understands.
"""

TEST = "tests/test_preflight_names_a_remedy_for_every_thing_it_refuses.py"

MODULE = "openfactory/preflight.py"
JSON_TEST = "tests/test_preflight_json_is_the_document_the_agent_lane_reads.py"
MACHINE_TEST = "tests/test_preflight_says_which_machine_it_measured.py"

MUTATIONS = [
    # ── a refusal with nothing to do about it ───────────────────────────────────────────────────
    ("the box image refusal drops its `docker pull` remedy",
     MODULE,
     'f"docker pull {image}   (the worker launches it as a SIBLING container on this daemon, so "\n'
     '        f"it has to be here — compose does not fetch it, and the job that needs it fails at the "\n'
     '        f"first ticket rather than at `up`)", on=LOCAL)',
     '"", on=LOCAL)'),

    ("the agent credential refusal restates the problem instead of answering it",
     MODULE,
     '"run `claude setup-token` and put the result in CLAUDE_CODE_OAUTH_TOKEN in .env.compose "\n'
     '        "(or ANTHROPIC_API_KEY if you bill per token). The stack starts without it and no ticket "\n'
     '        "can run — this is the one credential that cannot be postponed", on=LOCAL)',
     '"no agent credential is visible", on=LOCAL)'),

    ("a check that raises becomes a traceback instead of a finding",
     MODULE,
     "    try:\n        return fn()\n    except Exception as exc:  # noqa: BLE001",
     "    try:\n        return fn()\n    except ZeroDivisionError as exc:  # noqa: BLE001"),

    # ── the report stops at the first problem ───────────────────────────────────────────────────
    ("preflight stops after the daemon fails, so one install becomes six",
     MODULE,
     "    return Report(findings=[\n        _guarded(\"docker_daemon\", lambda: _daemon(probes)),",
     "    if not probes.daemon()[0]:\n"
     "        return Report(findings=[_guarded(\"docker_daemon\", lambda: _daemon(probes))])\n"
     "    return Report(findings=[\n        _guarded(\"docker_daemon\", lambda: _daemon(probes)),"),

    # ── the three states collapse into two, in both directions ──────────────────────────────────
    ("a question nobody could answer is counted as a failure — `docker pull` against a dead daemon",
     MODULE,
     "        return [f for f in self.findings if f.answered and not f.ok]",
     "        return [f for f in self.findings if not f.ok]"),

    ("a question nobody could answer reads as a pass, and the verdict stops saying so",
     MODULE,
     '        if self.unanswered:\n            return f"OK, {len(self.unanswered)} could not be '
     'answered here"\n        return "OK"',
     '        return "OK"'),

    ("the box image falls back to the framework default, passing about the wrong image",
     MODULE,
     "    image = p.sandbox_image()\n    if image is None:",
     "    image = p.sandbox_image() or \"openfactory-python\"\n    if image is None:"),

    # ── which machine ───────────────────────────────────────────────────────────────────────────
    ("the findings stop saying which machine they measured",
     MODULE,
     "from openfactory.onboarding.readiness import LOCAL, Finding, _fail, _ok, _unanswered",
     "from openfactory.onboarding.readiness import Finding, _fail, _ok, _unanswered\n\nLOCAL = \"\"",
     MACHINE_TEST),

    ("preflight invents its own word for the machine instead of readiness's",
     MODULE,
     "from openfactory.onboarding.readiness import LOCAL, Finding, _fail, _ok, _unanswered",
     "from openfactory.onboarding.readiness import Finding, _fail, _ok, _unanswered\n\n"
     "LOCAL = \"host\"",
     MACHINE_TEST),

    # ── the document the agent lane reads ───────────────────────────────────────────────────────
    ("the schema field disappears, so a reader cannot tell one version from the next",
     MODULE,
     '            "schema": SCHEMA,\n',
     "",
     JSON_TEST),

    ("the three states are flattened on the way into the document",
     MODULE,
     '                    "ok": f.ok,\n                    "answered": f.answered,',
     '                    "ok": f.ok,',
     JSON_TEST),

    ("only the failures are serialised, so the agent proposes steps already taken",
     MODULE,
     "                for f in self.findings\n            ],",
     "                for f in self.findings if not f.ok\n            ],",
     JSON_TEST),

    ("the verdict is carried beside the findings instead of computed from them, and drifts",
     MODULE,
     '            "ok": self.ok,',
     '            "ok": True,',
     JSON_TEST),
]
