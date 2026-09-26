"""The role sees what the panel sees — except what `EXCLUDED` names, and never spend (#267 slice 1).

THE GUARD. It finds the panel's project routes in `app.routes` — every GET under `/api/` that
takes a project, in its path or as a query parameter — calls each one on a bed that stands a
product up in process (`tests/the_product_bed.py`), and walks every field the answers carry. Each
field is then held to one of two things:

  * `EXCLUDED` covers it — and then nothing planted under it may reach the role's files;
  * or its value is in the role's files, as the pack a turn writes them.

"In the files" means: a string's text is there (whitespace aside), with the people of other
conversations, the spend and the credentials the bed planted cut out of it — those three must NOT
be there, and each is checked on its own below; a number is there as written; a yes/no is there
under its own key (`readable: yes`); an absence (`None`, `[]`, `{}`) carries no value to find.

NOTHING HERE LISTS A PANEL FIELD. A field a route grows tomorrow is walked tomorrow, and it turns
this red until the model carries it or `EXCLUDED` names it with a reason. That is proven below by
planting one, and by planting spend into the files.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from openfactory.api import app as panel
from openfactory.product import facts
from openfactory.product import model as read_model
from tests import the_product_bed as bed

MEMBERS = ("acme-web", "acme-api")


# ── the discovery ───────────────────────────────────────────────────────────────────────────────

def project_routes() -> list[APIRoute]:
    """Every panel route that answers something about ONE project — found, never listed."""
    return [r for r in panel.app.routes
            if isinstance(r, APIRoute) and "GET" in r.methods and r.path.startswith("/api/")
            and ("{project}" in r.path
                 or any(q.name == "project" for q in r.dependant.query_params))]


def _unfilled(route: APIRoute) -> set[str]:
    return set(re.findall(r"{(\w+)(?::\w+)?}", route.path)) - {"project", "issue"}


def _passed_over(route: APIRoute) -> bool:
    """A route the guard does not read on purpose: one whose path the bed cannot fill, which
    EXCLUDED withholds whole."""
    return bool(_unfilled(route)) and read_model.excluded(f"{route.path}:x") \
        and read_model.excluded(f"{route.path}:a.b[].c")


def _is_stream(route: APIRoute) -> bool:
    """A route that answers a stream, which a request cannot read to its end — by its own
    declaration (`-> StreamingResponse`), not by its name."""
    return "StreamingResponse" in str(route.endpoint.__annotations__.get("return", ""))


#: How the bed fills each query parameter a project route declares, per member. A parameter the
#: bed cannot fill turns the guard red by name — a new one is a new way to ask for a fact.
def _fill(name: str, member: str) -> list[str]:
    if name == "project":
        return [member]
    if name == "card":
        return [ref for ref, *_ in bed.CARDS[member]]
    if name == "pr":
        return [bed.PR_141] if member == "acme-web" else [""]
    raise LookupError(f"the bed cannot fill the query parameter {name!r}")


def _calls(route: APIRoute, member: str) -> list[tuple[str, dict]]:
    issues = [i for p, i, *_ in bed.JOBS if p == member] if "{issue}" in route.path else [""]
    names = [q.name for q in route.dependant.query_params]
    combos: list[dict] = [{}]
    for name in names:
        combos = [{**c, name: v} for c in combos for v in _fill(name, member)]
    # ONE CALL PER CARD, NOT PER CARD AND PULL REQUEST: the drawer opens one of each at a time.
    seen, out = set(), []
    for issue in issues:
        path = route.path.replace("{project}", member).replace("{issue}", issue)
        for params in combos:
            key = (path, tuple(sorted(params.items())))
            if key not in seen:
                seen.add(key)
                out.append((path, params))
    return out


def panel_fields(client) -> tuple[list[tuple[str, object]], list[str]]:
    """`(fields, problems)` — every `(route:path, value)` the project routes answer about the
    product's members, and what the guard could not read."""
    found: list[tuple[str, object]] = []
    problems: list[str] = []
    for route in project_routes():
        if _is_stream(route):
            # A STREAM THE GUARD CANNOT READ MUST BE WITHHELD WHOLE, or the guard is blind to it.
            if not (read_model.excluded(f"{route.path}:x")
                    and read_model.excluded(f"{route.path}:a.b[].c")):
                problems.append(f"{route.path} is a stream this guard cannot read, and EXCLUDED "
                                f"does not withhold it whole")
            continue
        for member in MEMBERS:
            try:
                calls = _calls(route, member)
            except LookupError as exc:
                problems.append(f"{route.path}: {exc}")
                continue
            for path, params in calls:
                answer = client.get(path, params=params)
                if answer.status_code != 200 and _passed_over(route):
                    # A PATH PARAMETER THE BED CANNOT FILL — a file's id — read with the
                    # placeholder spelled out: "no such item" is the right answer, and a route
                    # EXCLUDED withholds whole has nothing to prove here
                    continue
                if answer.status_code != 200:
                    problems.append(f"GET {path} {params} → {answer.status_code}: "
                                    f"{answer.text[:160]}")
                    continue
                found += [(f"{route.path}:{leaf}", value)
                          for leaf, value in read_model.fields(answer.json())]
    return found, problems


# ── the comparison ──────────────────────────────────────────────────────────────────────────────

#: What the role must never read, as the bed planted it — cut out of a value before the rest of
#: it is looked for, and looked for on its own to be ABSENT.
_WITHHELD = sorted({*(f"{k}:{p}" for p in bed.PEOPLE for k in ("person", "visitor")),
                    *bed.PEOPLE, f"x-access-token:{bed.TOKEN}@", bed.TOKEN, bed.SPEND_LINE,
                    bed.CEILING}, key=len, reverse=True)
_CUT = re.compile("|".join(re.escape(w) for w in _WITHHELD))


def _flat(text) -> str:
    return " ".join(str(text).split())


def compare(fields: list[tuple[str, object]], text: str) -> list[str]:
    """Every panel field that is neither excluded nor in `text` — the guard's verdict."""
    flat = _flat(text)
    problems = []
    for path, value in fields:
        if read_model.excluded(path) is not None or value is None:
            continue
        if isinstance(value, bool):
            key = path.rsplit(":", 1)[-1].rsplit(".", 1)[-1].removesuffix("[]")
            said = f"{key.replace('_', ' ')}: {'yes' if value else 'no'}"
            if said not in flat:
                problems.append(f"{path} = {value!r}: no `{said}` in the role's files")
        elif isinstance(value, int | float):
            if str(value) not in flat:
                problems.append(f"{path} = {value!r}: not in the role's files")
        elif isinstance(value, str):
            for piece in _CUT.split(value):
                piece = _flat(piece).strip()
                if len(piece.strip(" .,;:()[]\"'-—")) >= 3 and piece not in flat:
                    problems.append(f"{path}: {piece[:90]!r} is not in the role's files")
    return problems


def leaked(fields: list[tuple[str, object]], text: str) -> list[str]:
    """What must not be in `text` and is: every excluded value the bed planted (marked `q7`, or a
    figure), every person, the credential, the spend, and the other product."""
    flat = _flat(text)
    out = [f"{path} = {value!r} is excluded and reached the role"
           for path, value in fields
           if read_model.excluded(path) is not None
           and ((isinstance(value, str) and "q7" in value and _flat(value) in flat)
                or (isinstance(value, float) and str(value) in flat))]
    out += [f"{who!r} is named in the role's files" for who in bed.PEOPLE if who in text]
    out += [f"spend {figure!r} reached the role's files" for figure in bed.SPEND_WORDS
            if figure in text]
    out += ["a credential reached the role's files" for secret in (bed.TOKEN, "x-access-token")
            if secret in text]
    out += ["another product's data reached the role's files" for _ in [1] if bed.GLOBEX in text]
    return out


# ── the bed and the pack ────────────────────────────────────────────────────────────────────────

@pytest.fixture
def made(tmp_path, monkeypatch):
    return bed.stand_up(tmp_path, monkeypatch)


def pack(made, root: Path, *, speaker: str = bed.YURI) -> str:
    """The pack a turn in acme-web writes, read back from disk — every file, the README too."""
    model = bed.the_model(made["acme-web"], corpus=bed.corpus())
    files, gaps = facts.gather("acme-web", None, model=model, speaker=speaker)
    into = facts.write_facts(root, files=files, gaps=gaps)
    assert into is not None
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(into.rglob("*.md")))


@pytest.fixture
def seen(made, tmp_path):
    """`(fields, problems, text)`: what the panel shows, what the guard could not read, and the
    role's files."""
    fields, problems = panel_fields(TestClient(panel.app, raise_server_exceptions=False))
    root = tmp_path / "workspace"
    root.mkdir()
    return fields, problems, pack(made, root)


# ── the invariant ───────────────────────────────────────────────────────────────────────────────

def test_the_guard_found_every_project_route_and_read_each(seen):
    """An enumeration that quietly finds nothing passes every case below."""
    fields, problems, _ = seen
    paths = {r.path for r in project_routes()}
    assert {"/api/board/{project}", "/api/loops/{project}", "/api/floor/{project}",
            "/api/jobs/{project}/{issue}/detail", "/api/promote/{project}/{issue}",
            "/api/messages/{project}", "/api/factory/{project}", "/api/metrics",
            "/api/jobs/{project}/{issue}/events", "/api/jobs/{project}/{issue}/stream"} <= paths
    assert problems == []
    read = {path.split(":", 1)[0] for path, _ in fields}
    unread = {p for p in paths - read
              if not (lambda r: _is_stream(r) or _passed_over(r))(
                  next(r for r in project_routes() if r.path == p))}
    assert not unread, f"a route was found and never read: {sorted(unread)}"
    assert len(fields) > 300, "the bed answered almost nothing — the guard would prove nothing"
    # WHAT A PERSON OPENS IS READ TOO: the card drawer and the pull-request page answer only when
    # asked for one, and a guard that never asked would never see them.
    walked = {path for path, _ in fields}
    for opened in ("/api/board/{project}:card.comments[].body", "/api/board/{project}:pr.diff",
                   "/api/metrics:tasks[].title"):
        assert opened in walked, opened


def test_a_document_the_panel_shows_unreadable_is_one_the_role_knows_exists(seen):
    """#269: the documents screen is walked like every other, and each document it lists as
    unreadable — its path, its type, its audience, why — is in the role's files, so "could not
    read" never reaches a turn as "nothing there"."""
    fields, problems, text = seen
    assert problems == []
    shown = {(path, value) for path, value in fields
             if path.startswith("/api/product/{project}/documents:unreadable[]")}
    paths = {value for path, value in shown if path.endswith(".path")}
    assert paths == {"client/DOC-q7-contract.pdf"}, shown
    assert compare(sorted(shown), text) == []
    assert "DOC-q7 a protected PDF: it needs a password to be opened" in text
    assert "audience: client" in text


def test_an_internal_document_the_panel_shows_reaches_every_turn_by_name(seen):
    """The product owner's decision of 2026-09-25: the panel lists the internal document by name,
    and the turn the pack is written for — whoever it answers — is told it by name too; nothing
    about it is EXCLUDED any more."""
    fields, _, text = seen
    internal = {value for path, value in fields
                if path == "/api/product/{project}/documents:unreadable_internal[].path"}
    assert internal == {"internal/DOC-q7-legacy.docx"}
    assert not read_model.excluded("/api/product/{project}/documents:unreadable_internal[].path")
    assert "DOC-q7-legacy" in text and "not listed here" not in text


def test_every_project_fact_a_panel_screen_shows_is_reachable_by_the_role(seen):
    fields, problems, text = seen
    assert problems == []
    assert compare(fields, text) == []


def test_nothing_on_the_exclusion_list_reaches_the_role(seen):
    fields, _, text = seen
    assert leaked(fields, text) == []


def test_spend_never_enters_the_model(made):
    """Withheld on the way IN, so no renderer can print it: no key the spend entry names survives
    anywhere in the model the files are rendered from."""
    model = bed.the_model(made["acme-web"], corpus=bed.corpus())
    held = [path for layer in (model.now, model.history, model.meaning)
            for path, _ in read_model.fields(layer)
            if any(read_model._spend_key(part.removesuffix("[]")) for part in path.split("."))]
    assert held == []
    assert any(path.endswith("cost_usd") for path, _ in read_model.fields(
        _detail_answer("40"))), "the bed planted no spend — this proved nothing"


def _detail_answer(issue: str) -> dict:
    return TestClient(panel.app).get(f"/api/jobs/acme-web/{issue}/detail").json()


# ── the guard is proven able to fail ────────────────────────────────────────────────────────────

def test_a_new_panel_field_nobody_carries_turns_the_guard_red(seen, monkeypatch):
    """A route grows a fact the model does not carry: the guard names it."""
    from openfactory.runtime.temporal import view as tv

    real = tv.job_detail

    async def grown(client, project, issue, namespace):
        return {**await real(client, project, issue, namespace),
                "promised_date": "PLANTED-q7 the date the card was promised for"}

    monkeypatch.setattr(tv, "job_detail", grown)
    fields, problems = panel_fields(TestClient(panel.app, raise_server_exceptions=False))
    _, _, text = seen
    red = compare(fields, text)
    assert problems == [] and red
    assert all("promised_date" in line for line in red), red


def test_a_new_project_route_turns_the_guard_red(seen):
    """A screen nobody told the model about: found by the discovery, not by a list."""

    @panel.app.get("/api/planted/{project}")
    def planted(project: str) -> dict:
        return {"secret_of_the_screen": f"PLANTED-q7 only {project}'s panel shows this"}

    try:
        fields, problems = panel_fields(TestClient(panel.app, raise_server_exceptions=False))
    finally:
        panel.app.router.routes[:] = [r for r in panel.app.router.routes
                                      if getattr(r, "path", "") != "/api/planted/{project}"]
    _, _, text = seen
    red = compare(fields, text)
    assert any(line.startswith("/api/planted/{project}:secret_of_the_screen") for line in red)


def test_spend_planted_into_the_role_s_files_turns_the_guard_red(seen):
    fields, _, text = seen
    assert leaked(fields, text + f"\n- cost usd: {bed.SPEND_TOTAL}\n")
    assert leaked(fields, text + f"\n{bed.SPEND_LINE}\n")


def test_an_excluded_value_planted_into_the_files_turns_the_guard_red(seen):
    fields, _, text = seen
    assert set(leaked(fields, text + "\nMSG-q7-told what an operator said\n")) == {
        "/api/messages/{project}:messages[].text = 'MSG-q7-told what an operator said' is "
        "excluded and reached the role"}


def test_a_field_dropped_from_the_files_turns_the_guard_red(seen):
    fields, _, text = seen
    assert compare(fields, text.replace("WEB39-question keep the old table?", ""))
    assert compare(fields, text.replace("readable: yes", "readable: ?"))


# ── the exclusion list ──────────────────────────────────────────────────────────────────────────

def test_every_exclusion_names_what_it_withholds_and_why():
    for entry in read_model.EXCLUDED:
        assert len(entry.what) > 20 and len(entry.why) > 40, entry
        assert entry.paths or entry.keys, entry


def test_every_exclusion_withholds_something_a_panel_screen_shows(seen):
    """An entry that covers nothing the panel answers is a permission nobody needs — and the one
    that will quietly cover the next field somebody adds."""
    fields, _, _ = seen
    streams = [r.path for r in project_routes() if _is_stream(r)]
    for entry in read_model.EXCLUDED:
        assert any(entry.covers(path) for path, _ in fields) or any(
            entry.covers(f"{s}:x") for s in streams), entry.what


def test_spend_heads_the_list_and_names_the_decision():
    first = read_model.EXCLUDED[0]
    assert first.what.startswith("spend")
    assert "decision 7" in first.why
    for key in ("cost_usd", "total_cost_usd", "input_tokens", "tokens", "num_turns"):
        assert read_model.excluded(f"/api/anything:a.{key}") is first, key
    assert read_model.excluded("/api/metrics:totals.tasks") is first


def test_a_list_path_is_not_read_as_a_glob_class():
    """`[]` in `also[].cmd` is a list's items, not a character class that swallows the dot."""
    assert read_model.excluded("/api/floor/{project}:also[].cmd") is not None
    assert read_model.excluded("/api/floor/{project}:also[].clause") is None
    assert read_model.excluded("/api/floor/{project}:alsoXcmd") is None


def test_the_factory_s_own_sentences_about_spend_are_withheld_as_their_writers_write_them():
    """Three writers put spend into WORDS that travel as a park note, a job's `why` or a pull
    request's description. Each is built here by its own code, so a reworded writer turns this
    red instead of leaking past a scrub that no longer matches it."""
    from types import SimpleNamespace

    from openfactory.orchestrator.machine import JobRunner
    from openfactory.techlead.watch import HarnessReading

    ceiling = JobRunner._cost_reason(SimpleNamespace(manifest=SimpleNamespace(max_cost_usd=5.0)),
                                     7.5)
    billed = HarnessReading(events=12, spent_usd=3.25).note
    source = (Path(__file__).resolve().parents[1] / "openfactory/orchestrator/machine.py"
              ).read_text(encoding="utf-8")
    # the line is written from one constant since #310: its prefix, then the ticket's total
    prefix = re.search(r'^_COST_LINE = "([^"]*)"', source, re.M)
    shape = re.search(r'f"\{_COST_LINE\}\{result\.total_cost_usd:(\.\d+f)\}"', source)
    assert prefix and shape, (
        "the pull request's cost line changed shape — re-pin `model._SPEND_WORDS`")
    line = f"{prefix.group(1)}{1.2345:{shape.group(1)[:-1]}f}"
    for said in (ceiling, billed, f"adds the export\n\n{line}\nsee the diff"):
        withheld = read_model.scrub_spend(said)
        assert not re.search(r"\$\s?\d", withheld), withheld
    assert "12 events read" in read_model.scrub_spend(billed), "the rest of the note is kept"


# ── the three layers ────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def text(made, tmp_path):
    root = tmp_path / "pack"
    root.mkdir()
    return _flat(pack(made, root))


def test_now_is_the_floor_the_jobs_and_WHY_as_the_platform_said_it(text):
    assert "Needs you — 2 answers are waiting" in text, "the floor's verdict"
    assert ("acme-web#41 — WEB41-title Export the monthly report (awaiting_your_merge) - waits on: "
            "a person to merge its pull request") in text
    assert "why (the engine's own reason): The independent review REJECTED it (score 42)" in text
    assert "- name: WEB-check-e2e - bucket: fail" in text, "the pull request's checks"
    assert "WEB39-question keep the old table?" in text and "WEB39-option drop it" in text
    # THE TECH-LEAD'S DIAGNOSIS, AS IT WROTE IT — never re-diagnosed, never a bystander's remark
    assert ("the tech-lead's diagnosis, as it wrote it on the card: ### Tech-lead triage "
            "WEB39-diagnosis the migration has no rollback") in text
    assert "acme-api#7 — API7-title Rate limit the export endpoint (running)" in text


def test_now_says_what_waits_on_whom_by_relation_never_by_name(text):
    assert "decision `WEB-loop-export-format` waits on you" in text
    assert "acceptance `40` waits on its requester" in text
    assert "finding `41` waits on an operator" in text
    assert "acme-web#39 waits on a person — it is on hold" in text


def test_history_is_the_version_in_production_the_deliveries_and_who_asked(text):
    assert "latest tag: v1.4.2-q7" in text and "latest tag: v0.9.0-api-q7" in text
    assert "acme-web#40 merged (deployed)" in text
    assert "card #40 closed as completed — WEB40-title Login with SSO" in text
    assert "card #38 closed as" not in text, "closed as not planned is not delivered"
    assert "#41 «WEB41-title Export the monthly report» — asked by its requester" in text
    assert ("held for review: the run reached a limit the operator set" in text), \
        "a park for spend keeps its reason and loses its figures"


def test_the_board_is_whole_and_says_labels_assignees_and_who_asked(text):
    assert ("#41 [open] — WEB41-title Export the monthly report · labels: feature-q7, ux-q7 · "
            "assignees: octo-dev-q7 · asked by its requester · updated 2026-09-20T10:00:00Z") in text
    assert "#38 [closed:not_planned]" in text and "#8 [closed:completed]" in text
    assert "columns: Backlog · TO-DO · In progress · In review · Needs Action · Done" in text


def test_meaning_is_the_body_the_thread_and_the_linked_pull_request_of_every_card(text):
    assert "# Card acme-web#41" in text and "WEB41-body export the monthly report" in text
    assert "WEB41-comment started on the export" in text
    assert "pull requests: https://forge.example/acme/web/pull/141" in text
    assert "WEB40-comment shipped behind the sso flag" in text, "a CLOSED card's thread too"
    assert "WEB-PR141-diff.py" in text and "WEB-PR141-refusal" in text
    assert "- 2026-09-19T10:00:00+00:00 — a job started on it" in text, "the card's timeline"


def test_the_requirements_carry_who_asked_as_a_relation(made, tmp_path):
    root = tmp_path / "pack"
    root.mkdir()
    for speaker, said in ((bed.YURI, "its requester"), (bed.ZELDA, "you (the person speaking)")):
        got = _flat(pack(made, root, speaker=speaker))
        assert f"| REQ-0003 | accepted | WEB-REQ3 the monthly export | acme/web | {said} |" in got
        assert "| REQ-0004 | proposed | WEB-REQ4 dark mode | — | unrecorded |" in got


# ── one product ─────────────────────────────────────────────────────────────────────────────────

def test_the_model_is_the_union_of_the_product_s_registry_projects(made):
    web = bed.the_model(made["acme-web"])
    api = bed.the_model(made["acme-api"])
    assert web.key == api.key == "repo:acme/docs"
    assert web.members == ["acme-web", "acme-api"] and api.members == ["acme-api", "acme-web"]
    assert set(web.meaning) == set(api.meaning) == {"acme-web", "acme-api"}


def test_each_member_s_jobs_are_its_own(made):
    """The engine lists the product's jobs together; each lands under the registry project it
    runs for — acme-api#7 is never acme-web#7, a card that does not exist."""
    model = bed.the_model(made["acme-web"])

    def issues(layer, member, key):
        return sorted(str(j["issue"]) for j in layer[member][key])

    assert issues(model.now, "acme-web", "jobs") == ["39", "41"]
    assert issues(model.now, "acme-api", "jobs") == ["7"]
    assert issues(model.history, "acme-web", "finished") == ["38", "40"]
    assert issues(model.history, "acme-api", "finished") == []


def test_another_product_s_data_never_enters_this_one_s_model(made, text):
    """globex runs on the same deployment and the same engine: its job is in the engine's list,
    its board is one registry entry away — and none of it is acme's."""
    model = bed.the_model(made["acme-web"])
    held = " ".join(str(v) for layer in (model.now, model.history, model.meaning)
                    for _, v in read_model.fields(layer))
    assert bed.GLOBEX not in held and "globex" not in model.members
    assert bed.GLOBEX not in text


# ── names, credentials ──────────────────────────────────────────────────────────────────────────

def test_no_name_crosses_conversations(made, tmp_path):
    root = tmp_path / "pack"
    root.mkdir()
    got = pack(made, root)
    for who in bed.PEOPLE:
        assert who not in got, who
    assert "Awaiting the acceptance of [a person]" in got, "withheld where it rides, in a body"
    assert "[your private conversation]" in got and "[a private conversation]" in got
    assert "### 2026-09-19T12:00:00Z — [a person]" in got, "a requester, in the tracker's spelling"
    assert "— octo-dev-q7" in got, "the tracker's public record keeps its own names"


def test_files_another_conversation_may_read_call_nobody_you(made, tmp_path):
    root = tmp_path / "pack"
    root.mkdir()
    got = pack(made, root, speaker="")
    assert "you (the person speaking)" not in got and "[you]" not in got
    assert "waits on the person it was asked of" in got
    assert bed.YURI not in got


def test_a_credential_never_reaches_a_facts_file(made, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_SOME_API_KEY", "an-operator-secret-q7")
    monkeypatch.setitem(bed.THREADS, ("acme-api", "7"),
                        [("octo-dev-q7", "the key is an-operator-secret-q7",
                          "2026-09-21T09:00:00Z")])
    root = tmp_path / "pack"
    root.mkdir()
    got = pack(made, root)
    assert bed.TOKEN not in got and "x-access-token" not in got
    assert "an-operator-secret-q7" not in got
    assert got.count(read_model.WITHHELD_CREDENTIAL) >= 2, "said where it was withheld"
    assert "clone https://github.com/acme/web.git" in got, "the URL stays, its userinfo goes"


# ── what could not be read is said ──────────────────────────────────────────────────────────────

def test_an_engine_that_does_not_answer_is_a_gap_never_an_idle_floor(made, tmp_path,
                                                                      monkeypatch):
    from openfactory.runtime.temporal import view as tv

    async def refused():
        raise ConnectionError("the engine is down")

    monkeypatch.setattr(tv, "connect", refused)
    bed.forget()
    root = tmp_path / "pack"
    root.mkdir()
    got = _flat(pack(made, root))
    assert "the jobs could not be read — say so; never that nothing is running" in got
    assert "connected: no" in got
    assert "the engine's jobs could not be read" in got, "the manifest names the gap"
    assert "the engine did not answer" in got, "the floor's own verdict is still said"


def test_an_unreadable_board_and_thread_and_ledger_are_said_as_such(made, tmp_path, monkeypatch):
    from openfactory.memory import store

    listing = bed.Tracker.list_tickets

    def ledger_down(project, **_k):
        raise RuntimeError("the ledger is down")

    monkeypatch.setattr(bed.Tracker, "comments", lambda self, ref, *, limit=0: None)
    monkeypatch.setattr(bed.Tracker, "list_tickets",
                        lambda self, **kw: None if self.project == "acme-api"
                        else listing(self, **kw))
    monkeypatch.setattr(store, "read", ledger_down)
    bed.forget()
    root = tmp_path / "pack"
    root.mkdir()
    got = _flat(pack(made, root))
    assert "## acme-api - board: yes - columns: (could not be read)" not in got
    assert "The board could not be read for this message" in got
    assert "It could NOT be read — say the platform could not look" in got
    assert "the open-loop ledger could not be read" in got


# ── the whole board ─────────────────────────────────────────────────────────────────────────────

def test_the_model_reads_the_whole_board_and_every_other_reader_keeps_its_window(made,
                                                                                monkeypatch):
    """The window was on the READ, so a card outside the 300 most recently updated did not exist
    for the role. The sweep now keeps the whole board; a caller that names no window still gets the
    300 newest, and the model asks for all of them."""
    from openfactory.adapters.tracker.base import TicketSummary
    from openfactory.product import board

    many = [TicketSummary(ref=str(n), title=f"card {n}", state="closed",
                          updated_at=f"2026-01-01T00:{n // 60:02d}:{n % 60:02d}Z")
            for n in range(1, 351)]
    asked: list[int] = []

    def listing(self, *, state="all", updated_since="", limit=0):
        asked.append(limit)
        return sorted(many, key=lambda t: t.updated_at, reverse=True)

    monkeypatch.setattr(bed.Tracker, "list_tickets", listing)
    bed.forget()
    whole, _ = board.read_board(made["acme-web"], limit=0)
    window, _ = board.read_board(made["acme-web"])
    assert len(whole) == 350 and len(window) == board._LIMIT == 300
    assert {t.number for t in window} == {str(n) for n in range(51, 351)}, "the 300 NEWEST"
    assert asked[0] == 0 and board._LIMIT not in asked, (
        "the sweep reads the whole board and the window is cut from what it kept — never asked "
        "of the port")
    model = bed.the_model(made["acme-web"])
    assert len(model.meaning["acme-web"]["cards"]) == 350


# ── the pack and the turn ───────────────────────────────────────────────────────────────────────

def test_the_pack_writes_only_the_names_it_admits_and_lists_a_directory_as_one_line(tmp_path):
    files = {"board.md": "# board\n" * 5, "now.md": "# now\n" * 5,
             "cards/acme-web-41.md": "# card\n" * 5, "cards/acme-web-40.md": "# card\n" * 5,
             "../escaped.md": "# out\n" * 5, "cards/../../up.md": "# up\n" * 5,
             "cards/deeper/x.md": "# deep\n" * 5, "notes.txt": "# nope\n" * 5}
    into = facts.write_facts(tmp_path, files=files, gaps=[])
    assert into is not None
    written = sorted(str(p.relative_to(into)) for p in into.rglob("*") if p.is_file())
    assert written == ["README.md", "board.md", "cards/acme-web-40.md", "cards/acme-web-41.md",
                       "now.md"]
    assert not (tmp_path / "escaped.md").exists() and not (tmp_path / "up.md").exists()
    readme = (into / "README.md").read_text(encoding="utf-8")
    assert "cards/<project>-<ref>.md (2 files, one per card)" in readme
    assert "acme-web-41" not in readme


def test_a_turn_answering_somebody_is_handed_the_model_and_names_only_them(made, tmp_path):
    from types import SimpleNamespace

    from openfactory.product.module import _the_read_model

    built: list[int] = []
    context = SimpleNamespace(available=True, corpus=bed.corpus())

    def module(**kw):
        return SimpleNamespace(project=made["acme-web"], context=lambda: context, **kw)

    own = module(_facts_for=bed.YURI, _turn_view=str(tmp_path))
    real = read_model.build

    def counting(*a, **k):
        built.append(1)
        return real(*a, **k)

    read_model.build, restore = counting, read_model.build
    try:
        first = _the_read_model(own, str(tmp_path))
        again = _the_read_model(own, str(tmp_path))
        shared = _the_read_model(module(_facts_for=bed.YURI, _turn_view="elsewhere"),
                                 str(tmp_path))
        drafting = _the_read_model(module(), str(tmp_path))
    finally:
        read_model.build = restore
    assert first["speaker"] == bed.YURI and first["model"] is again["model"]
    assert shared["speaker"] == "", "a view another turn may read names nobody"
    assert drafting == {}, "only an answer to somebody is handed the model"
    assert len(built) == 2, "once per module, which is once per turn"


def test_answer_marks_the_module_for_the_model_before_it_builds_the_role():
    """The wiring, read where it is: `answer()` says who asks before `_role()` writes the pack."""
    import inspect

    from openfactory.product.module import ProductModule

    source = inspect.getsource(ProductModule.answer)
    assert source.index("self._facts_for =") < source.index("self._role(")
    assert "_the_read_model(self, root)" in inspect.getsource(ProductModule._write_facts)


def test_the_role_is_told_what_the_new_files_hold_and_to_name_nobody():
    from openfactory.product.role import ProductRole

    class _Agent:
        name = "fake"

    got = "\n".join(ProductRole(_Agent(), mounted={"facts": ".openfactory-facts-ab12"})
                    ._facts_section())
    for name in ("now.md", "history.md", "requirements.md", "cards/", "pulls/"):
        assert f".openfactory-facts-ab12/{name}" in got, name
    assert "never diagnose again" in got and "never name anybody" in got
