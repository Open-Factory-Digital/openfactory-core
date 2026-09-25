"""A product as the panel shows it, stood up in process — the bed the read model's guard runs on
(#267 slice 1).

WHAT IS REAL AND WHAT IS STOOD IN FOR. The panel's routes are real, called through `TestClient`;
so are the engine's views (`view.list_jobs`, `view.job_detail`), the floor's ladder, the board
reader and the model. What is stood in for is what they READ: the tracker, the board and the forge
behind the ports, the engine's client, the loop ledger and the channel's store. A field a route or
a view grows tomorrow therefore reaches the guard with no edit here — the discovery is the routes',
not this file's.

EVERY PLANTED STRING IS FINDABLE. A fact is checked by finding its value in the role's files, so
each value here carries a marker that occurs nowhere else (`q7`), and each thing the role must NOT
see is a named constant the guard looks for: the people of other conversations, the spend, a
credential, and another product's data.

THE PRODUCT. `acme-web` and `acme-api` are two registry projects of ONE product (both point at
the context repository `acme/docs`); `globex` is another product on the same deployment. The turn
the files are written for answers `YURI`; `ZELDA` asked for card #41 and for a requirement, in
another conversation.
"""

from __future__ import annotations

import asyncio
import json
import types
from datetime import UTC, datetime

from openfactory.adapters.tracker.base import NOT_REPORTED, TicketComment, TicketSummary

# ── the people ──────────────────────────────────────────────────────────────────────────────────

#: The person the turn answers.
YURI = "yuri.q7@acme.test"
#: A requester, in another conversation — and her spelling on the tracker.
ZELDA = "zelda.q7@acme.test"
ZELDA_FORGE = "zelda-q7-gh"
#: A product admin, who answered a question on the factory's thread.
ADA = "ada.q7@acme.test"
#: A person the platform knows ONLY from a loop — asked for a delivery in her private conversation
#: — and whose id a teammate typed into a comment.
QUINN = "quinn.q7@acme.test"
#: Every person the role's files may not name (the speaker included: she is "you").
PEOPLE = (YURI, ZELDA, ZELDA_FORGE, ADA, QUINN)

# ── what the role must never see ────────────────────────────────────────────────────────────────

#: A credential this process holds, planted into a comment and a pull request's description.
TOKEN = "ghp_q7SECRETSECRETSECRETSECRET01"
#: Spend, as the factory writes it: a finished job's total, the pull request's own `Cost:` line,
#: the cost-ceiling park, the journal's per-call figure.
SPEND_TOTAL = 987.65
SPEND_OTHER = 12.34
SPEND_LINE = "Cost: $1.2345"
CEILING = ("cost ceiling reached ($7.50 > $5.00) — held for review; split the ticket or raise "
           "max_cost_usd")
SPEND_WORDS = ("987.65", "12.34", "1.2345", "$7.50", "$5.00", "3.21", "55.55")
#: Another product's data — none of it may reach acme's files.
GLOBEX = "GLOBEX-q7"

# ── the product's state ─────────────────────────────────────────────────────────────────────────

COLUMNS = ["Backlog", "TO-DO", "In progress", "In review", "Needs Action", "Done"]
PR_141 = "https://forge.example/acme/web/pull/141"
PR_140 = "https://forge.example/acme/web/pull/140"
PR_GLOBEX = "https://forge.example/globex/app/pull/55"

_BODY_41 = (f'---\nrequester: "{ZELDA}"\nrequester_forge: "{ZELDA_FORGE}"\n---\n'
            "## Objective\nWEB41-body export the monthly report as a CSV file\n\n"
            f"Awaiting the acceptance of {ZELDA} (ADR-0047). Until then this card is a proposal.\n"
            f"Pedido por: {ZELDA} ({ZELDA_FORGE})\n")

CARDS = {
    "acme-web": [
        # ref, title, body, state, reason, column, labels, assignees, updated
        ("41", "WEB41-title Export the monthly report", _BODY_41, "open", "", "In review",
         ["feature-q7", "ux-q7"], ["octo-dev-q7"], "2026-09-20T10:00:00Z"),
        ("39", "WEB39-title Migrate the invoices table", "## Objective\nWEB39-body migrate it\n",
         "open", "", "Needs Action", ["backend-q7"], [], "2026-09-19T09:00:00Z"),
        ("40", "WEB40-title Login with SSO", "## Objective\nWEB40-body sign in with SSO\n",
         "closed", "completed", "Done", [], ["octo-dev-q7"], "2026-09-18T08:00:00Z"),
        ("38", "WEB38-title Rebuild the search index", "## Objective\nWEB38-body reindex\n",
         "closed", "not_planned", "Done", [], [], "2026-09-10T08:00:00Z"),
        ("12", "WEB12-title Dark mode", "## Objective\nWEB12-body a dark theme\n",
         "open", "", "Backlog", [], [], "2026-09-01T08:00:00Z"),
    ],
    "acme-api": [
        ("7", "API7-title Rate limit the export endpoint", "## Objective\nAPI7-body limit it\n",
         "open", "", "TO-DO", ["api-q7"], [], "2026-09-21T08:00:00Z"),
        ("8", "API8-title Health endpoint", "## Objective\nAPI8-body a health check\n",
         "closed", "completed", "Done", [], [], "2026-09-02T08:00:00Z"),
    ],
    "globex": [
        ("5", f"{GLOBEX}-title the other product's card", f"{GLOBEX}-body", "open", "",
         "In review", [], [], "2026-09-21T08:00:00Z"),
    ],
}

THREADS = {
    ("acme-web", "41"): [
        ("octo-dev-q7", "WEB41-comment started on the export", "2026-09-19T11:00:00Z"),
        (ZELDA_FORGE, f"WEB41-comment please hurry — my token is {TOKEN}",
         "2026-09-19T12:00:00Z"),
        ("octo-dev-q7", f"WEB41-comment @{ZELDA_FORGE} does the preview work for you?",
         "2026-09-19T13:00:00Z"),
    ],
    ("acme-web", "39"): [
        ("openfactory-bot", "### Tech-lead triage\nWEB39-diagnosis the migration has no rollback; "
                            "somebody has to decide whether to keep the old table",
         "2026-09-19T09:30:00Z"),
    ],
    ("acme-web", "12"): [],
    # A CLOSED card's thread: what it promised is a question the drawer answers after it ships.
    ("acme-web", "40"): [("octo-dev-q7", "WEB40-comment shipped behind the sso flag",
                          "2026-09-18T07:30:00Z")],
    ("acme-api", "7"): [("octo-dev-q7", "API7-comment use a token bucket",
                         "2026-09-21T09:00:00Z"),
                        ("octo-dev-q7", f"API7-comment {QUINN} asked for this one too",
                         "2026-09-21T09:10:00Z")],
    ("globex", "5"): [("globex-dev", f"{GLOBEX}-comment", "2026-09-21T09:00:00Z")],
}

PULLS = {
    PR_141: {"state": "open",
             "body": f"WEB-PR141-body adds the CSV export\n\n{SPEND_LINE}\n"
                     f"clone https://x-access-token:{TOKEN}@github.com/acme/web.git\n",
             "diff": "diff --git a/WEB-PR141-diff.py b/WEB-PR141-diff.py\n+export = True\n",
             "events": [{"event": "COMMENT", "body": "WEB-PR141-event looks close",
                         "at": "2026-09-21T09:00:00Z"}],
             "refused": "WEB-PR141-refusal your local changes to app.py would be overwritten",
             "checks": [{"name": "WEB-check-e2e", "bucket": "fail", "state": "FAILURE",
                         "blocking": True, "kind": "code", "url": "https://ci.example/WEB-run-q7",
                         "remedy": ""}]},
    PR_140: {"state": "merged", "body": "WEB-PR140-body SSO", "diff": "", "events": [],
             "refused": "",
             "checks": [{"name": "WEB-check-unit", "bucket": "pass", "state": "SUCCESS",
                         "blocking": True, "kind": "code", "url": "", "remedy": ""}]},
    PR_GLOBEX: {"state": "open", "body": f"{GLOBEX}-pr", "diff": "", "events": [], "refused": "",
                "checks": []},
}

TAGS = {"acme-web": "v1.4.2-q7", "acme-api": "v0.9.0-api-q7", "globex": f"{GLOBEX}-v9"}

VERDICT_41 = {"decision": "rejected", "score": 42,
              "summary": "WEB41-review the migration has no rollback",
              "findings": [{"file": "WEB41-finding-file.py", "note": "WEB41-finding no rollback"}]}

#: The engine's jobs: `(project, issue, status, parked-as, result)`.
JOBS = [
    ("acme-web", "41", "running",
     {"merge": {"auto": False, "pr_url": PR_141, "working": False, "can_review": True},
      "verdict": VERDICT_41}, None),
    ("acme-web", "39", "running",
     {"action": {"state": "on_hold", "kind": "impediment",
                 "note": "WEB39-note the migration needs a decision",
                 "decision": {"question": "WEB39-question keep the old table?",
                              "options": [{"key": "keep", "label": "WEB39-option keep it"},
                                          {"key": "drop", "label": "WEB39-option drop it"}]},
                 "parked_at": "2026-09-19T09:20:00Z", "wakes_at": None}}, None),
    ("acme-web", "40", "completed", {},
     {"state": "merged", "total_cost_usd": SPEND_TOTAL, "pr_url": PR_140,
      "note": "WEB40-note merged cleanly", "repair_attempts": 1,
      "review": {"decision": "approved", "score": 91, "summary": "WEB40-review fine"},
      "suppression_details": [{"kind": "coverage", "file": "WEB40-suppressed.py", "line": 9}],
      "added_suppressions": [],
      "validations": [{"name": "WEB40-gate-tests", "passed": True}]}),
    ("acme-web", "38", "completed", {},
     {"state": "on_hold", "total_cost_usd": SPEND_OTHER, "pr_url": None, "note": CEILING,
      "repair_attempts": 0, "review": None, "suppression_details": [],
      "added_suppressions": [], "validations": []}),
    ("acme-api", "7", "running", {}, None),
    ("globex", "5", "running",
     {"merge": {"auto": False, "pr_url": PR_GLOBEX, "working": False,
                "note": f"{GLOBEX}-merge-note"}}, None),
]

#: When each job started and ended — the timeline's clock.
_START = {"41": "2026-09-19T10:00:00+00:00", "39": "2026-09-19T09:00:00+00:00",
          "40": "2026-09-17T08:00:00+00:00", "38": "2026-09-09T08:00:00+00:00",
          "7": "2026-09-21T08:30:00+00:00", "5": "2026-09-21T08:30:00+00:00"}
_CLOSE = {"40": "2026-09-18T07:00:00+00:00", "38": "2026-09-10T07:00:00+00:00"}


# ── the ports ───────────────────────────────────────────────────────────────────────────────────

class Tracker:
    def __init__(self, project: str) -> None:
        self.project = project
        self.asked: list[str] = []

    def _rows(self):
        return CARDS.get(self.project, [])

    def list_tickets(self, *, state="all", updated_since="", limit=0):
        out = [TicketSummary(ref=r, title=t, body=b, state=s, state_reason=why, labels=labels,
                             assignees=who, updated_at=at)
               for r, t, b, s, why, _col, labels, who, at in self._rows()
               if state == "all" or s == state]
        out.sort(key=lambda s: s.updated_at, reverse=True)
        return out[:limit] if limit else out

    def get_ticket(self, ref):
        for r, t, b, s, _why, _col, labels, _who, _at in self._rows():
            if r == str(ref).lstrip("#"):
                return types.SimpleNamespace(title=t, raw=b, state=s, labels=labels)
        raise KeyError(ref)

    def comments(self, ref, *, limit=0):
        self.asked.append(str(ref))
        rows = THREADS.get((self.project, str(ref)))
        if rows is None:
            return []
        return [TicketComment(author=a, body=b, created_at=at) for a, b, at in rows]

    def budget(self):
        return NOT_REPORTED


class Board:
    def __init__(self, project: str) -> None:
        self.project = project

    def column_names(self):
        return list(COLUMNS)

    def columns(self):
        return {r: col for r, _t, _b, _s, _w, col, *_ in CARDS.get(self.project, [])}

    def poll_seconds(self) -> int:
        return 3

    def url(self):
        return f"https://board.example/{self.project}"


class Forge:
    def __init__(self, project: str) -> None:
        self.project = project

    def _pull(self, pr):
        return PULLS[str(pr)]

    def pr_status(self, *, pr, repo=""):
        return self._pull(pr)["state"]

    def pr_body(self, *, pr, repo=""):
        return self._pull(pr)["body"]

    def pr_diff(self, *, pr, repo="", max_chars=60000):
        return self._pull(pr)["diff"]

    def pr_checks(self, *, pr):
        return list(self._pull(pr)["checks"])

    def pr_events(self, *, pr):
        return list(self._pull(pr)["events"])

    def pr_refusal(self, *, pr):
        return self._pull(pr)["refused"]

    def latest_tag(self):
        return TAGS.get(self.project)

    def clone_url(self, repo, token=None):
        return f"https://forge.example/{repo}.git"


# ── the engine ──────────────────────────────────────────────────────────────────────────────────

def _when(stamp: str | None):
    return datetime.fromisoformat(stamp) if stamp else None


class _Workflow:
    """One job as the engine's list and its handle both answer for it."""

    def __init__(self, project, issue, status, parked, result, statuses) -> None:
        self.id = f"openfactory-{project}-{issue}"
        self.run_id = f"run-{project}-{issue}"
        self.status = statuses[status]
        self.start_time = _when(_START.get(issue))
        self.close_time = _when(_CLOSE.get(issue))
        self._parked, self._result = parked, result
        self._title = next((t for r, t, *_ in CARDS.get(project, []) if r == issue), "")

    async def memo(self):
        return {"title": self._title}

    async def describe(self):
        return self

    async def query(self, which, *a, **k):
        name = getattr(which, "__name__", str(which))
        return {"awaiting_action": self._parked.get("action"),
                "awaiting_merge": self._parked.get("merge"),
                "awaiting_approval": False,
                "verdict": self._parked.get("verdict")}.get(name)

    async def result(self):
        return self._result


class _Deploy:
    def __init__(self, statuses) -> None:
        self.status = statuses["completed"]

    async def describe(self):
        return self

    async def result(self):
        return "success"


class Engine:
    """The durable engine's client, answering the reads `view.py` makes."""

    def __init__(self) -> None:
        from openfactory.runtime.temporal.view import WorkflowExecutionStatus as S

        statuses = {"running": S.RUNNING, "completed": S.COMPLETED}
        self.jobs = {w.id: w for w in (_Workflow(*job, statuses) for job in JOBS)}
        self._deploy = _Deploy(statuses)

    def list_workflows(self, query):
        jobs = list(self.jobs.values()) if "JobWorkflow" in query else []

        async def rows():
            for job in jobs:
                yield job

        return rows()

    def get_workflow_handle(self, wf_id, run_id=None):
        if wf_id.startswith("openfactory-deploy-"):
            if wf_id == "openfactory-deploy-acme-web-40":
                return self._deploy
            raise KeyError(wf_id)
        return self.jobs[wf_id]


INTAKE = {"known": True, "on": True, "note": "", "fired_ago_s": 30.0, "next_in_s": 150.0,
          "every_s": 180.0, "num_actions": 12, "running_now": 0, "created_ago_s": 9999.0,
          "fired_at": "2026-09-21T09:59:30+00:00", "next_at": "2026-09-21T10:02:30+00:00",
          "watchers": {}}


# ── the bed ─────────────────────────────────────────────────────────────────────────────────────

def stand_up(tmp_path, monkeypatch) -> dict:
    """Register the three projects, point every port at the stand-ins, plant the ledger, the
    channel's thread and a run's journal, and forget every cache that could carry a previous
    test's reading. Returns the registry's projects by name."""
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_HOME", str(tmp_path / ".openfactory"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("TEMPORAL_ADDRESS", "localhost:7233")
    monkeypatch.setenv("OPENFACTORY_GH_TOKEN", TOKEN)
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    for name in ("OPENFACTORY_PANEL_TOKEN", "OPENFACTORY_PANEL_TOKENS",
                 "OPENFACTORY_PRODUCT_TOKENS"):
        monkeypatch.delenv(name, raising=False)

    registry = ProjectRegistry()
    made = {}
    # ONE ORGANISATION, TWO PRODUCTS: the registry refuses a deployment spanning two (one App
    # installation), and a product is its context repository, not its organisation.
    for name, repo, docs in (("acme-web", "acme/web", "acme/docs"),
                             ("acme-api", "acme/api", "acme/docs"),
                             ("globex", "acme/globex-app", "acme/globex-docs")):
        checkout = tmp_path / name
        checkout.mkdir()
        registry.add(Project(
            name=name, repo_path=str(checkout),
            tracker=ProviderRef(kind="github", repo=repo),
            forge=ProviderRef(kind="github", repo=repo),
            product=ProductConfig(docs_repo=docs, admins=[ADA] if name != "globex" else [])))
        made[name] = registry.get(name)

    import openfactory.adapters.board as board_axis
    import openfactory.adapters.forge.registry as forge_axis
    import openfactory.adapters.tracker.registry as tracker_axis

    monkeypatch.setattr(tracker_axis, "build_tracker",
                        lambda project, *a, **k: Tracker(project.name))
    monkeypatch.setattr(board_axis, "build_board", lambda project, *a, **k: Board(project.name))
    monkeypatch.setattr(forge_axis, "build_forge", lambda project, *a, **k: Forge(project.name))

    from openfactory.runtime.temporal import view as tv

    engine = Engine()

    async def _connect():
        return engine

    async def _intake(client):
        return dict(INTAKE)

    monkeypatch.setattr(tv, "connect", _connect)
    monkeypatch.setattr(tv, "intake", _intake)
    monkeypatch.setattr("openfactory.box_prove.health",
                        lambda project: {"state": "proven", "detail": "", "gate": "", "image": "",
                                         "at": ""})
    tv._answered()

    _plant_the_ledger(monkeypatch)
    _plant_the_thread(monkeypatch)
    _plant_a_journal(made["acme-web"])
    _plant_the_spend()
    forget()
    return made


def _plant_the_spend() -> None:
    """What the cost dashboard shows about acme-web — withheld from the role whole."""
    from openfactory.observability.metrics import MetricRecord
    from openfactory.observability.registry import deployment_metrics_sink

    sink = deployment_metrics_sink()
    sink.record(MetricRecord(project="acme-web", ticket="41", ts="2026-09-19T10:05:00+00:00",
                             kind="agent_run", role="executor", model="METRIC-q7-model",
                             harness="METRIC-q7-harness", cost_usd=55.55, num_turns=7,
                             input_tokens=1000, output_tokens=200))
    sink.record(MetricRecord(project="acme-web", ticket="41", ts="2026-09-19T11:00:00+00:00",
                             kind="job", state="merged", title="METRIC-q7 the job's own title",
                             wall_s=3600.0))


def forget() -> None:
    """Every in-process memory a reading could be carried in from another test."""
    from openfactory.floor import reading
    from openfactory.product import board, model

    board.forget_board()
    reading.forget_intake()
    reading.forget_budget()
    model._THREADS.clear()


def _plant_the_ledger(monkeypatch) -> None:
    from openfactory.memory import store
    from openfactory.memory.ledger import ACCEPTANCE, DECISION, FINDING, open_loop
    from openfactory.product.speaker import sealed

    loops = {
        "acme-web": [
            open_loop(DECISION, "WEB-loop-export-format", owner="product",
                      ts="2026-09-19T14:00:00+00:00", about=f"person:{YURI}",
                      context={"asked": "WEB-loop-asked CSV or XLSX?",
                               "asked_of": sealed(YURI), "asked_in": sealed(f"person:{YURI}")}),
            open_loop(ACCEPTANCE, "40", owner="product", ts="2026-09-18T09:00:00+00:00",
                      about=f"person:{ZELDA}", context={"defect": "", "asked_by": ZELDA}),
            open_loop(FINDING, "41", owner="techlead", ts="2026-09-19T15:00:00+00:00",
                      about="rejected",
                      context={"detail": "WEB-finding the migration has no rollback",
                               "score": "42", "pr": PR_141}),
        ],
        "acme-api": [
            open_loop(ACCEPTANCE, "API-delivery-7", owner="product",
                      ts="2026-09-21T10:00:00+00:00", about=f"person:{QUINN}",
                      context={"defect": "", "asked_by": QUINN}),
        ],
        "globex": [open_loop(DECISION, f"{GLOBEX}-loop", owner="product",
                             ts="2026-09-19T14:00:00+00:00", context={"asked": f"{GLOBEX}-ask"})],
    }
    monkeypatch.setattr(store, "read", lambda project, **_k: list(loops.get(project, [])))


def _plant_the_thread(monkeypatch) -> None:
    """The factory's thread with its operators — withheld from the role whole."""
    from openfactory.memory import messages

    rows = [messages.Message(kind=messages.TOLD, text="MSG-q7-told what an operator said",
                             ts="2026-09-19T10:00:00+00:00", by=ADA),
            messages.Message(kind=messages.SAID, text="MSG-q7-said the factory's notice",
                             ts="2026-09-19T10:01:00+00:00")]
    monkeypatch.setattr(messages, "read", lambda project, **_k: list(rows) if project.startswith(
        "acme") else [])
    monkeypatch.setattr(messages, "pending", lambda project, **_k: [])
    monkeypatch.setattr(messages, "staged", lambda project, **_k: None)


def _plant_a_journal(project) -> None:
    """A run's raw log — withheld from the role whole; it names a credential and a call's spend."""
    from openfactory.paths import events_file

    path = events_file(project, "41")
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"ts": "2026-09-19T10:00:00+00:00", "job_id": "41", "ticket_id": "41",
             "kind": "note", "message": "EVT-q7 credential 1/3 (pool-id-q7)",
             "data": {"credential": {"id": "pool-id-q7", "index": 1, "total": 3}}},
            {"ts": "2026-09-19T10:05:00+00:00", "job_id": "41", "ticket_id": "41",
             "kind": "agent_action", "message": "EVT-q7 edited a file",
             "data": {"cost_usd": 3.21}}]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def corpus():
    """The product's requirements: one, asked for by `ZELDA` in her conversation."""
    from openfactory.product.corpus import Corpus, Requirement

    return Corpus(requirements=[
        Requirement(number=3, slug="monthly-export", path="requirements/0003-monthly-export.md",
                    title="WEB-REQ3 the monthly export", status="accepted", asked_by=ZELDA,
                    affects=["acme/web"]),
        Requirement(number=4, slug="dark-mode", path="requirements/0004-dark-mode.md",
                    title="WEB-REQ4 dark mode", status="proposed", asked_by="")])


def the_model(project, *, corpus=None):
    """The read model of `project`'s product, built the way a turn builds it."""
    from openfactory.product import model

    return model.build(project, corpus=corpus)


def run(coro):
    return asyncio.run(coro)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
