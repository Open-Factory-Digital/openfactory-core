"""The system layer (#268 slice 2, ADR-0052 D17): the product's topology, derived without a model.

WHAT THIS FILE HOLDS, in the acceptance's order:

  1. ON THE MICROSERVICE FIXTURE (`tests/fixtures/evaluation/quayside/`, four repositories made
     real git repositories here), the map lists every component and every declared interface
     between them — exactly those, compared as sets — and every entry cites a file that exists at
     the commit it cites.
  2. WHAT COULD NOT BE DERIVED IS LISTED, with why, and exactly those on the fixture.
  3. NOTHING FROM A REPOSITORY RUNS: a source planted with files that would leave a mark if any of
     them ran — a compose command, a migration's module body, a Terraform provisioner, a YAML tag
     that calls `os.system` — is derived with every way of starting a process refused, and no mark
     appears.
  4. NO READ LEAVES THE TREE: a link out of the tree, to a file or a directory, and a `$ref` that
     climbs out, are named and never opened — every `os.open` of the derivation is recorded, and
     none is outside the source.
  5. NO SECRET VALUE REACHES THE MAP, only names.

Then each reader on its own: the rule it applies, and the case it must not get wrong.
"""

from __future__ import annotations

import ast
import builtins
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from openfactory.knowledge.system import (
    SourceTree,
    derive,
    derived_key,
    render,
    schemas,
    write_system,
)
from openfactory.knowledge.system import deployments as deploy
from openfactory.knowledge.system import interfaces as api
from openfactory.knowledge.system.adrs import is_adr, read_adr
from openfactory.knowledge.system.contracts import (
    AMBIGUOUS,
    AT_RUN_TIME,
    NOT_DECLARED,
    NOT_FOLLOWED,
    NOT_READ,
    PARSE_ERROR,
    SOURCE_UNREADABLE,
    TOO_LARGE,
    TRUNCATED,
    UNKNOWN_FORMAT,
    Cite,
)
from openfactory.knowledge.system.tree import Read, read_text, walk

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "evaluation" / "quayside"
SOURCES = ("quayside-billing", "quayside-freight", "quayside-orders", "quayside-platform")

_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t", "PATH": os.environ.get("PATH", "")}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True, env={**_ENV, "HOME": str(cwd)}).stdout


def _repository(src: Path, dest: Path) -> str:
    """`src` as a real git repository at `dest`, one commit; returns that commit."""
    shutil.copytree(src, dest)
    subprocess.run(["git", "init", "-q", "-b", "main", str(dest)], check=True,
                   capture_output=True)
    _git(dest, "add", "-A")
    _git(dest, "commit", "-qm", "the fixture")
    return _git(dest, "rev-parse", "HEAD").strip()


@pytest.fixture(scope="module")
def quayside(tmp_path_factory):
    """`(map, {repo: (path, commit)})` for the fixture's four repositories, derived once."""
    root = tmp_path_factory.mktemp("quayside")
    repos = {name: (root / name, _repository(FIXTURE / "sources" / name, root / name))
             for name in SOURCES}
    trees = [SourceTree(repo=n, root=p, commit=c) for n, (p, c) in repos.items()]
    return derive(trees, generated_at="2026-09-24T00:00:00+00:00"), repos


def _cites(node) -> list[dict]:
    """Every citation anywhere in a dumped map."""
    out = []
    if isinstance(node, dict):
        if set(node) == {"repo", "path", "commit", "line"}:
            out.append(node)
        for v in node.values():
            out += _cites(v)
    elif isinstance(node, list):
        for v in node:
            out += _cites(v)
    return out


# ── 1. every component and every interface between them, cited ─────────────────────────────────

def test_the_map_lists_every_component_of_the_microservice_fixture(quayside):
    system, _ = quayside
    assert {(c.name, c.kind) for c in system.components} == {
        ("orders", "service"), ("billing", "service"), ("freight", "service"),
        ("orders-db", "database"), ("billing-db", "database"), ("kafka", "broker")}
    code = {c.name: (c.repo, c.code, c.code_by) for c in system.components}
    assert code["orders"] == ("quayside-orders", ".", "build-context")
    assert code["billing"] == ("quayside-billing", ".", "build-context")
    assert code["freight"] == ("quayside-freight", ".", "build-context")
    # compose AND Kubernetes declare `orders`: one component, cited by both
    orders = system.component("orders")
    assert {(c.repo, c.path) for c in orders.declared_by} == {
        ("quayside-platform", "docker-compose.yml"), ("quayside-platform", "k8s/orders.yaml")}
    assert orders.depends_on == ["freight", "kafka", "orders-db"]


def test_every_declared_interface_between_them_is_on_the_map(quayside):
    system, _ = quayside
    assert {(lk.from_, lk.to, lk.kind, lk.via) for lk in system.links} == {
        ("billing", "orders", "http", "env ORDERS_URL"),
        ("orders", "freight", "grpc", "env FREIGHT_ADDR"),
        ("orders", "billing", "event", "channel order.placed"),
        ("orders", "orders-db", "database", "env DATABASE_URL"),
        ("billing", "billing-db", "database", "env DATABASE_URL"),
        ("orders", "kafka", "broker", "env KAFKA_BROKERS"),
        ("billing", "kafka", "broker", "env KAFKA_BROKERS"),
    }


def test_the_http_apis_carry_their_operations_and_their_callers(quayside):
    system, _ = quayside
    apis = {a.component: a for a in system.http}
    assert set(apis) == {"orders", "billing"}
    assert [(o.method, o.path, o.operation_id) for o in apis["orders"].operations] == [
        ("GET", "/orders", "listOrders"), ("POST", "/orders", "placeOrder"),
        ("GET", "/orders/{orderId}", "getOrder"), ("POST", "/orders/{orderId}/cancel",
                                                   "cancelOrder")]
    assert apis["orders"].callers == ["billing"]
    assert apis["orders"].owner_by == "servers"     # its servers name `orders`
    assert apis["billing"].owner_by == "code"       # it sits in billing's build context
    assert apis["billing"].callers == []


def test_the_grpc_service_is_its_rpcs_and_not_a_commented_one(quayside):
    system, _ = quayside
    [freight] = system.grpc
    assert (freight.component, freight.package, freight.service) == (
        "freight", "quayside.freight.v1", "FreightQuotes")
    assert [(r.name, r.request, r.response) for r in freight.rpcs] == [
        ("QuoteShipment", "QuoteRequest", "Quote"),
        ("StreamRates", "RatesRequest", "stream Rate")]
    assert freight.callers == ["orders"]
    lines = (FIXTURE / "sources" / "quayside-freight" / freight.source.path).read_text().splitlines()
    assert lines[freight.source.line - 1].startswith("service FreightQuotes")
    assert lines[freight.rpcs[0].line - 1].strip().startswith("rpc QuoteShipment")


def test_the_events_carry_who_sends_and_who_receives(quayside):
    system, _ = quayside
    events = {e.channel: e for e in system.events}
    assert {ch: ([p.component for p in e.producers], [c.component for c in e.consumers])
            for ch, e in events.items()} == {
        "order.placed": (["orders"], ["billing"]),
        "order.cancelled": (["orders"], []),
        "invoice.issued": (["billing"], []),
        "payment.settled": ([], ["billing"]),
    }
    assert events["order.placed"].broker == "kafka"
    assert events["order.placed"].protocol == "kafka"
    assert events["order.placed"].producers[0].message == "OrderPlaced"


def test_each_database_is_its_schema_its_owner_and_its_users(quayside):
    system, _ = quayside
    dbs = {d.name: d for d in system.databases}
    assert set(dbs) == {"orders-db", "billing-db"}
    orders = dbs["orders-db"]
    assert (orders.owners, orders.users, orders.engine, orders.tool) == (
        ["orders"], [], "postgres", "golang-migrate")
    tables = {t.name: t for t in orders.tables}
    assert set(tables) == {"orders", "order_lines"}
    # the third migration's columns, applied — and no `.down.sql` undid them
    assert [c.name for c in tables["orders"].columns][-2:] == ["freight_quote_id",
                                                              "freight_amount"]
    assert tables["order_lines"].references == ["orders"]
    assert [m.path for m in orders.migrations] == [
        "db/migrations/000001_create_orders.up.sql",
        "db/migrations/000002_create_order_lines.up.sql",
        "db/migrations/000003_fix_the_freight_on_the_order.up.sql"]
    billing = dbs["billing-db"]
    assert (billing.owners, billing.tool) == (["billing"], "flyway")
    assert {t.name for t in billing.tables} == {"invoices", "invoice_lines"}
    assert {c.name for c in next(t for t in billing.tables if t.name == "invoices").columns} \
        >= {"freight_amount", "status"}


def test_the_queue_the_infrastructure_and_the_decisions_are_indexed(quayside):
    system, _ = quayside
    assert [(q.name, q.kind) for q in system.queues] == [("quayside-invoice-emails", "queue")]
    assert [(i.address, i.kind, i.name, i.engine) for i in system.infrastructure] == [
        ("aws_db_instance.orders", "database", "quayside-orders", "postgres")]
    assert [(a.repo, a.number, a.status, a.date, a.component) for a in system.adrs] == [
        ("quayside-billing", "0001", "accepted", "2026-03-10", "billing"),
        ("quayside-orders", "0001", "Accepted", "2026-03-02", "orders"),
        ("quayside-orders", "0002", "Accepted", "2026-03-09", "orders")]


def test_every_entry_cites_a_file_that_exists_at_the_commit_it_cites(quayside):
    """The acceptance's second half. Every citation in the map names its repository's commit,
    and `git cat-file -e <commit>:<path>` finds the file there; a line, where given, is a line of
    that file. And no entry is uncited: every component, link, API, service, event end, table,
    queue, piece of infrastructure and ADR carries at least one citation."""
    system, repos = quayside
    cites = _cites(system.model_dump(by_alias=True))
    assert len(cites) > 40
    for c in cites:
        path, commit = repos[c["repo"]]
        assert c["commit"] == commit, c
        _git(path, "cat-file", "-e", f"{commit}:{c['path']}")
        if c["line"]:
            assert c["line"] <= len((path / c["path"]).read_text().splitlines()), c
    assert all(c.declared_by for c in system.components)
    assert all(lk.sources for lk in system.links)
    assert all(e.source.path for ev in system.events for e in ev.producers + ev.consumers)
    assert all(t.source.path for d in system.databases for t in d.tables)
    assert all(d.migrations for d in system.databases)
    assert [s.commit for s in system.sources] == [repos[s.repo][1] for s in system.sources]


# ── 2. what could not be derived ────────────────────────────────────────────────────────────────

def test_what_could_not_be_derived_is_listed_with_why(quayside):
    system, _ = quayside
    assert {(n.kind, n.repo, n.path) for n in system.not_derived} == {
        (NOT_DECLARED, "quayside-platform", "docker-compose.yml"),   # notifications
        (NOT_DECLARED, "quayside-billing", "asyncapi.yaml"),         # payment.settled
        (NOT_FOLLOWED, "quayside-platform", "infra/main.tf"),        # a remote module
        (NOT_READ, "quayside-platform", "k8s/orders.yaml"),          # a secret
        (UNKNOWN_FORMAT, "quayside-platform", "charts/quayside/Chart.yaml"),  # a Helm chart
    }
    said = " ".join(n.detail for n in system.not_derived)
    assert "`notifications`" in said and "`payment.settled`" in said
    assert "DATABASE_URL" in said and "Helm" in said


def test_a_source_that_could_not_be_read_is_named_not_dropped(tmp_path):
    system = derive([], missing={"acme/ledger": "it could not be checked out"})
    assert [(s.repo, s.missing) for s in system.sources] == [
        ("acme/ledger", "it could not be checked out")]
    assert [(n.kind, n.repo) for n in system.not_derived] == [(SOURCE_UNREADABLE, "acme/ledger")]


def test_the_files_are_deterministic_and_the_key_ignores_the_commit(quayside, tmp_path):
    system, repos = quayside
    trees = [SourceTree(repo=n, root=p, commit=c) for n, (p, c) in repos.items()]
    again = derive(list(reversed(trees)), generated_at="2026-09-24T00:00:00+00:00")
    assert render(again) == render(system)
    moved = derive([SourceTree(repo=t.repo, root=t.root, commit="f" * 40) for t in trees],
                   generated_at="later")
    assert derived_key(moved) == derived_key(system)
    assert render(moved)["system.yaml"] != render(system)["system.yaml"]
    # …and a change to a declaration moves it
    changed = tmp_path / "quayside-freight"
    shutil.copytree(repos["quayside-freight"][0], changed, ignore=shutil.ignore_patterns(".git"))
    proto = changed / "proto" / "freight" / "v1" / "freight.proto"
    proto.write_text(proto.read_text().replace("rpc StreamRates", "rpc StreamTariffs"))
    other = derive([t for t in trees if t.repo != "quayside-freight"]
                   + [SourceTree(repo="quayside-freight", root=changed)])
    assert derived_key(other) != derived_key(system)


def test_the_five_files_are_written_and_the_door_puts_the_gaps_first(quayside, tmp_path):
    system, _ = quayside
    written = write_system(system, tmp_path / "system")
    assert [p.name for p in written] == ["adr-index.yaml", "api.yaml", "index.md",
                                         "schema.yaml", "system.yaml"]
    door = (tmp_path / "system" / "index.md").read_text()
    assert door.index("could not derive") < door.index("## Components")
    assert "**billing** (service)" in door and "talks to **orders** (http, env ORDERS_URL)" in door
    import yaml

    for p in written:
        if p.suffix == ".yaml":
            assert yaml.safe_load(p.read_text())["derived_key"] == derived_key(system)


# ── 3. nothing from a repository runs ───────────────────────────────────────────────────────────

def _hostile(root: Path, sentinel: Path) -> Path:
    """A source every one of whose files would touch `sentinel` if anything ran it."""
    src = root / "hostile"
    touch = f"touch {sentinel}"
    files = {
        "docker-compose.yml": f"services:\n  app:\n    build: .\n    command: [\"sh\", \"-c\", "
                              f"\"{touch}\"]\n    entrypoint: \"{touch}\"\n",
        "Makefile": f"all:\n\t{touch}\n",
        "setup.py": f"open({str(sentinel)!r}, 'w').write('setup ran')\n",
        "package.json": f'{{"name": "x", "scripts": {{"postinstall": "{touch}"}}}}\n',
        "migrate.sh": f"#!/bin/sh\n{touch}\n",
        "alembic/env.py": f"open({str(sentinel)!r}, 'w').write('env ran')\n",
        "alembic/versions/0001_planted.py": (
            "import sqlalchemy as sa\nfrom alembic import op\n\n"
            f"open({str(sentinel)!r}, 'w').write('migration imported')\n\n"
            "revision = 'a1'\ndown_revision = None\n\n\n"
            "def upgrade():\n    op.create_table('planted', sa.Column('id', sa.Integer()))\n\n\n"
            f"def downgrade():\n    open({str(sentinel)!r}, 'w').write('downgrade ran')\n"),
        "shop/migrations/0001_initial.py": (
            "from django.db import migrations, models\n\n"
            f"open({str(sentinel)!r}, 'w').write('django migration imported')\n\n\n"
            "class Migration(migrations.Migration):\n"
            "    operations = [migrations.CreateModel(name='Basket', fields=[\n"
            "        ('id', models.AutoField(primary_key=True))])]\n"),
        "infra/main.tf": (
            'resource "null_resource" "x" {\n  provisioner "local-exec" {\n'
            f'    command = "{touch}"\n  }}\n}}\n'
            'resource "aws_sqs_queue" "q" {\n  name = "planted-queue"\n}\n'),
        "api/openapi.yaml": ("openapi: 3.0.0\ninfo:\n  title: !!python/object/apply:os.system "
                             f"[\"{touch}\"]\npaths: {{}}\n"),
        "api/asyncapi.yaml": (f"asyncapi: 2.6.0\ninfo: !!python/object/apply:os.system "
                              f"[\"{touch}\"]\n"),
        "schema.prisma": f'generator client {{\n  provider = "{touch}"\n}}\n'
                         'model Planted {\n  id Int @id\n}\n',
        "chart/Chart.yaml": "apiVersion: v2\nname: planted\n",
        "chart/templates/job.yaml": f"apiVersion: batch/v1\nkind: Job\nmetadata:\n  name: x\n"
                                    f"# {{{{ exec \"{touch}\" }}}}\n",
    }
    for rel, text in files.items():
        path = src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (src / "migrate.sh").chmod(0o755)
    return src


def test_nothing_in_a_repository_is_run(tmp_path, monkeypatch):
    """The layer READS: every way this process could start another is refused for the length of
    the derivation, and every file above would leave the sentinel behind if it ran — a compose
    command, a Makefile, a setup script, a migration's module body or its `downgrade()`, a
    Terraform provisioner, a YAML tag that calls `os.system`, a Helm template. None does, and the
    migrations are still derived: read as text, applied as data."""
    sentinel = tmp_path / "SENTINEL"
    src = _hostile(tmp_path, sentinel)

    def refused(*_a, **_k):
        raise AssertionError("the derivation tried to start a process")

    monkeypatch.setattr(subprocess, "Popen", refused)
    for name in ("system", "popen", "posix_spawn", "posix_spawnp", "fork", "forkpty", "execv",
                 "execve", "execvp", "execvpe", "spawnv", "spawnve", "spawnvp", "spawnvpe"):
        monkeypatch.setattr(os, name, refused, raising=False)
    monkeypatch.setattr(builtins, "exec", refused)
    monkeypatch.setattr(builtins, "eval", refused)
    system = derive([SourceTree(repo="acme/hostile", root=src, commit="c1")])
    monkeypatch.undo()

    assert not sentinel.exists()
    tables = {t.name for d in system.databases for t in d.tables}
    assert {"planted", "shop_basket", "Planted"} <= tables
    assert [q.name for q in system.queues] == ["planted-queue"]
    kinds = {(n.kind, n.path) for n in system.not_derived}
    assert (PARSE_ERROR, "api/openapi.yaml") in kinds       # the tag was refused, not built
    assert (PARSE_ERROR, "api/asyncapi.yaml") in kinds
    assert (UNKNOWN_FORMAT, "chart/Chart.yaml") in kinds
    rendered = "".join(render(system).values())
    assert "touch" not in rendered


def test_the_derivation_does_not_import_a_process_module():
    """Nothing the derivation is made of imports `subprocess` — the commit is handed in, never
    asked of git inside it (`tree.SourceTree`)."""
    root = Path(__file__).resolve().parent.parent / "openfactory" / "knowledge" / "system"
    for name in ("tree.py", "text.py", "interfaces.py", "schemas.py", "deployments.py",
                 "adrs.py", "derive.py", "render.py", "contracts.py"):
        tree = ast.parse((root / name).read_text())
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)
                    for a in n.names}
        imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree)
                     if isinstance(n, ast.ImportFrom)}
        assert not imported & {"subprocess", "multiprocessing", "pty", "importlib", "runpy"}, name


def test_a_fifo_is_not_opened_and_does_not_hang_the_walk(tmp_path):
    if not hasattr(os, "mkfifo"):
        pytest.skip("no FIFOs on this platform")
    src = tmp_path / "src"
    src.mkdir()
    os.mkfifo(src / "openapi.yaml")
    assert walk(src).files == []
    got = read_text(src, "openapi.yaml")
    assert got.text is None and "not a regular file" in got.why


# ── 4. no read leaves the tree ──────────────────────────────────────────────────────────────────

def test_a_symlink_out_of_the_tree_is_not_read(tmp_path, monkeypatch):
    """A link to a file out of the tree, a link to a directory out of it, a `$ref` that climbs out
    and a `$ref` to a link that points out: each is named as not followed, none is opened — every
    `os.open` the derivation makes is recorded, and none resolves outside the source."""
    outside = tmp_path / "outside"
    (outside / "migrations").mkdir(parents=True)
    stolen_spec = ("openapi: 3.0.0\ninfo: {title: stolen}\npaths:\n  /stolen:\n"
                   "    get: {operationId: stolen}\n")
    (outside / "openapi.yaml").write_text(stolen_spec)
    (outside / "paths.yaml").write_text("x:\n  get: {operationId: stolenByRef}\n")
    (outside / "migrations" / "0001_stolen.sql").write_text("CREATE TABLE stolen (id int);\n")
    src = tmp_path / "repo"
    (src / "api").mkdir(parents=True)
    (src / "db").mkdir()
    (src / "spec").mkdir()
    os.symlink(outside / "openapi.yaml", src / "api" / "openapi.yaml")
    os.symlink(outside / "migrations", src / "db" / "migrations")
    os.symlink(outside / "paths.yaml", src / "spec" / "linked.yaml")
    (src / "spec" / "openapi.yaml").write_text(
        "openapi: 3.0.0\ninfo: {title: mine}\npaths:\n"
        "  /mine:\n    get: {operationId: mine}\n"
        "  /x:\n    $ref: '../../outside/paths.yaml#/x'\n"
        "  /y:\n    $ref: 'linked.yaml#/x'\n")

    opened: list[str] = []
    real_open = os.open

    def recording(path, *a, **k):
        opened.append(os.path.realpath(path))
        return real_open(path, *a, **k)

    monkeypatch.setattr(os, "open", recording)
    system = derive([SourceTree(repo="acme/repo", root=src, commit="c1")])
    monkeypatch.undo()

    assert opened, "the derivation opened nothing at all — the recorder is not recording"
    assert not [p for p in opened if p.startswith(os.path.realpath(outside))]
    operations = [o.operation_id for a in system.http for o in a.operations]
    assert operations == ["mine"]
    assert not [t for d in system.databases for t in d.tables]
    followed = {(n.kind, n.path) for n in system.not_derived}
    assert (NOT_FOLLOWED, "api/openapi.yaml") in followed
    assert (NOT_FOLLOWED, "db/migrations") in followed
    assert (NOT_FOLLOWED, "spec/linked.yaml") in followed
    refs = [n.detail for n in system.not_derived if n.path == "spec/openapi.yaml"]
    assert len(refs) == 2 and any("outside this repository" in r for r in refs)
    # refused AS A LINK, and said so — not as whatever a later check would have called it
    assert any("which is a link, and a link is never followed" in r for r in refs)
    assert "outside/paths.yaml" not in " ".join(refs)     # the reference's text is not copied


def test_read_text_refuses_every_way_out(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("nope")
    (root / "inner").mkdir()
    os.symlink(tmp_path, root / "inner" / "up")
    for rel in ("../secret.txt", "/etc/hosts", "inner/up/secret.txt", "inner/../../secret.txt"):
        got = read_text(root, rel)
        assert got.text is None, rel
    # a link INSIDE the tree is not followed either: what it points at is read at its own path
    (root / "real.yaml").write_text("openapi: 3.0.0\n")
    os.symlink("real.yaml", root / "alias.yaml")
    assert read_text(root, "alias.yaml") == Read(None, "is a link, and a link is never followed")
    (root / "big.yaml").write_bytes(b"x" * 1_000_001)
    assert read_text(root, "big.yaml").too_large
    (root / "latin.sql").write_bytes("caf\xe9".encode("latin-1"))
    assert "UTF-8" in read_text(root, "latin.sql").why
    # a NUL in a path a document hands in is refused, never passed to the kernel (which raises)
    assert read_text(root, "api/x\x00.yaml").text is None
    from openfactory.knowledge.system.tree import resolve

    assert resolve("api/spec.yaml", "paths\x00.yaml") is None


# ── a repository is somebody else's input ───────────────────────────────────────────────────────

def test_a_hostile_shape_costs_its_file_never_the_map(tmp_path, monkeypatch):
    """Values where the formats put something else — a number for a list, a string for a
    mapping — are read around, and a reader that fails on a shape nobody foresaw costs that one
    file, named by the KIND of failure and nothing of the file's text."""
    files = {
        "a/openapi.yaml": "openapi: 3.0.0\nservers: 5\npaths: {/p: {get: {operationId: ok}}}\n",
        "b/asyncapi.yaml": ("asyncapi: 2.6.0\nchannels:\n  c:\n    bindings: {sqs: {queues: 7}}\n"
                            "    subscribe: {message: {name: M}}\n"),
        "k8s/cron.yaml": ("apiVersion: batch/v1\nkind: CronJob\nmetadata: {name: sweep}\n"
                          "spec: {jobTemplate: not-a-mapping}\n---\n"
                          "apiVersion: apps/v1\nkind: Deployment\nmetadata: {name: odd}\n"
                          "spec:\n  template:\n    spec:\n      containers: 3\n---\n"
                          "apiVersion: apps/v1\nkind: Deployment\nmetadata: {name: odder}\n"
                          "spec:\n  template:\n    spec:\n      containers:\n"
                          "        - {image: acme/x, env: 4, envFrom: five}\n"),
        "p/x.proto": "service S { rpc A(B) returns (C); }\n",
        "p/y.proto": "service T { rpc D(E) returns (F); }\n",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    real = api.read_proto

    def surprised(text):
        if "service T" in text:
            raise KeyError("sk_live_in_a_message")
        return real(text)

    monkeypatch.setattr(api, "read_proto", surprised)
    system = derive([SourceTree(repo="acme/x", root=tmp_path)])
    assert [o.operation_id for a in system.http for o in a.operations] == ["ok"]
    assert [e.channel for e in system.events] == ["c"]
    assert {c.name for c in system.components} >= {"sweep", "odd", "odder"}
    assert [g.service for g in system.grpc] == ["S"]
    [broken] = [n for n in system.not_derived if n.path == "p/y.proto"]
    assert (broken.kind, "KeyError" in broken.detail) == (PARSE_ERROR, True)
    assert "sk_live_in_a_message" not in "".join(render(system).values())


def test_pathological_text_is_read_in_linear_time(tmp_path):
    """Patterns a file can make quadratic — a line-start pattern over a file of blank lines, a
    block that never closes, heredoc after heredoc — take one pass. The bound is loose on purpose:
    the quadratic versions of these readers take hours on these files, not seconds."""
    import time

    blank = "\n" * 900_000
    (tmp_path / "blank.yaml").write_text(blank)
    (tmp_path / "blank-openapi.yaml").write_text("x: 1" + blank)
    (tmp_path / "open.tf").write_text('resource "aws_sqs_queue" "q" {\n' * 20_000)
    (tmp_path / "docs.tf").write_text('x = <<EOF\n"{\nEOF\n' * 40_000)
    (tmp_path / "open.proto").write_text("service S {\n" * 60_000)
    (tmp_path / "schema.prisma").write_text("model M {\n" * 60_000)
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "001.sql").write_text("DROP TABLE a" + " " * 900_000 + ";")
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "docs" / "adr" / "0001-x.md").write_text("#" + blank + "## \n" * 1000)
    started = time.monotonic()
    system = derive([SourceTree(repo="acme/x", root=tmp_path)])
    assert time.monotonic() - started < 30
    assert (TOO_LARGE, "open.tf") in {(n.kind, n.path) for n in system.not_derived}


# ── 5. no secret value reaches the map ──────────────────────────────────────────────────────────

_SECRETS = ("pw-in-a-url", "sk_live_planted", "stringdata-planted", "tf-password-planted",
            "servers-userinfo-token", "bearer-planted", "configmap-password-planted")


def test_no_secret_value_reaches_the_map_only_names(tmp_path):
    src = tmp_path / "repo"
    (src / "k8s").mkdir(parents=True)
    (src / "infra").mkdir()
    (src / "docker-compose.yml").write_text(
        "services:\n  api:\n    build: .\n    env_file: .env\n    environment:\n"
        "      DATABASE_URL: postgres://api:pw-in-a-url@db:5432/api\n"
        "      STRIPE_KEY: sk_live_planted\n"
        "      AUTH_HEADER: Bearer bearer-planted\n"
        "  db:\n    image: postgres:16\n")
    (src / "k8s" / "all.yaml").write_text(
        "apiVersion: v1\nkind: Secret\nmetadata: {name: creds}\n"
        "stringData:\n  password: stringdata-planted\n---\n"
        "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: cfg}\n"
        "data:\n  DB_PASSWORD: configmap-password-planted\n"
        "  CACHE_URL: redis://:configmap-password-planted@cache:6379\n---\n"
        "apiVersion: apps/v1\nkind: Deployment\nmetadata: {name: worker}\n"
        "spec:\n  template:\n    spec:\n      containers:\n        - name: w\n"
        "          image: acme/worker\n          envFrom:\n            - configMapRef: {name: cfg}\n"
        "          env:\n            - {name: TOKEN, value: bearer-planted}\n")
    # the password FIRST: a reader that took it among the attributes it reads would find it
    # before the name, whatever the order it asks its keys in
    (src / "infra" / "db.tf").write_text(
        'resource "aws_db_instance" "main" {\n  password = "tf-password-planted"\n'
        '  identifier = "main"\n  engine = "postgres"\n}\n')
    (src / "openapi.yaml").write_text(
        "openapi: 3.0.0\ninfo: {title: api}\nservers:\n"
        "  - url: https://svc:servers-userinfo-token@api:8080\npaths: {}\n")
    (src / ".env").write_text("SECRET=never-read-planted\n")
    system = derive([SourceTree(repo="acme/repo", root=src, commit="c1")])
    rendered = "".join(render(system).values())
    for secret in (*_SECRETS, "never-read-planted"):
        assert secret not in rendered, secret
    names = {e for c in system.components for e in c.env}
    assert {"DATABASE_URL", "STRIPE_KEY", "TOKEN", "DB_PASSWORD", "CACHE_URL"} <= names
    # the address inside a secret-bearing value still joins, by its host alone — and a database
    # no migrations describe is on the map with who uses it
    assert ("api", "db", "database") in {(lk.from_, lk.to, lk.kind) for lk in system.links}
    assert [(d.name, d.owners, d.users) for d in system.databases] == [("db", [], ["api"])]
    # …and so does the server a description names behind a user part
    assert [(a.component, a.owner_by) for a in system.http] == [("api", "servers")]
    assert (NOT_READ, "docker-compose.yml") in {(n.kind, n.path) for n in system.not_derived}


def test_host_ref_keeps_the_host_and_drops_the_rest():
    ref = deploy.host_ref("DATABASE_URL", "postgres://u:hunter2@orders-db:5432/orders?ssl=true")
    assert (ref.name, ref.scheme, ref.host) == ("DATABASE_URL", "postgres", "orders-db")
    assert "hunter2" not in repr(ref)
    assert deploy.host_ref("JDBC_URL", "jdbc:postgresql://db.internal:5432/x").host == "db.internal"
    assert deploy.host_ref("KAFKA_BROKERS", "kafka-1:9092,kafka-2:9092").host == "kafka-1"
    assert deploy.host_ref("ORDERS_HOST", "orders").host == "orders"
    assert deploy.host_ref("LOG_LEVEL", "debug") is None          # a bare word needs a host name
    assert deploy.host_ref("FEATURE_HOST", "true") is None        # …and is not a boolean
    assert deploy.host_ref("ORDERS_URL", "${ORDERS_URL}") is None
    assert deploy.host_ref("SELF_URL", "http://localhost:8080") is None
    assert deploy.host_ref("PORT", 8080) is None


# ── the readers, one rule at a time ─────────────────────────────────────────────────────────────

def test_sql_statements_split_outside_strings_comments_and_dollar_quotes():
    text = ("-- a comment; with a semicolon\nCREATE TABLE a (x text DEFAULT ';');\n"
            "/* block ; */\nCREATE FUNCTION f() RETURNS void AS $body$\n"
            "BEGIN CREATE TABLE never (y int); END;\n$body$ LANGUAGE plpgsql;\n"
            "CREATE TABLE b (\"select\" int);")
    stmts = schemas.sql_statements(text)
    assert [line for line, _ in stmts] == [2, 4, 7]
    schema = schemas.Schema()
    schemas.apply_sql(text, schema, Cite(repo="r", path="p"))
    assert [t.name for t in schema.tables()] == ["a", "b"]
    assert [c.name for c in schema.tables()[1].columns] == ["select"]


def test_sql_alterations_are_applied_in_order():
    schema = schemas.Schema()
    cite = Cite(repo="r", path="m.sql")
    schemas.apply_sql("CREATE TABLE IF NOT EXISTS public.orders (id int, note text, total int);\n"
                      "ALTER TABLE orders ADD COLUMN IF NOT EXISTS placed timestamptz;\n"
                      "ALTER TABLE orders DROP COLUMN note;\n"
                      "ALTER TABLE orders RENAME COLUMN total TO amount;\n"
                      "ALTER TABLE orders ALTER COLUMN amount TYPE numeric(10, 2);\n"
                      "ALTER TABLE orders ALTER COLUMN amount SET NOT NULL;\n"
                      "ALTER TABLE orders ADD CONSTRAINT fk FOREIGN KEY (id) REFERENCES people(id);\n"
                      "CREATE TABLE gone (id int); DROP TABLE IF EXISTS gone CASCADE;\n"
                      "ALTER TABLE orders RENAME TO purchases;\n", schema, cite)
    [table] = schema.tables()
    assert table.name == "purchases"
    assert [(c.name, c.type) for c in table.columns] == [
        ("id", "int"), ("amount", "numeric(10, 2)"), ("placed", "timestamptz")]
    assert table.references == ["people"]
    # every statement that changed what the map records is cited, and only those: `SET NOT NULL`
    # (line 6) changes nothing the map holds, and the table `gone` (line 8) is gone
    assert (table.source.line, [c.line for c in table.altered_in]) == (1, [2, 3, 4, 5, 7, 9])


def test_dbmate_down_and_golang_down_are_not_applied():
    schema = schemas.Schema()
    schemas.apply_sql("-- migrate:up\nCREATE TABLE kept (id int);\n"
                      "-- migrate:down\nDROP TABLE kept;\n", schema, Cite(repo="r", path="p"))
    assert [t.name for t in schema.tables()] == ["kept"]
    sets = schemas.migration_sets(["db/migrations/1_a.up.sql", "db/migrations/1_a.down.sql",
                                   "db/migration/V10__c.sql", "db/migration/V2__b.sql",
                                   "db/migration/R__views.sql", "db/migration/U2__b.sql",
                                   "queries/report.sql"], alembic_dirs=set())
    by_dir = {s.directory: s for s in sets}
    assert by_dir["db/migrations"].files == ["db/migrations/1_a.up.sql"]
    assert by_dir["db/migrations"].tool == "golang-migrate"
    assert by_dir["db/migration"].files == ["db/migration/V2__b.sql", "db/migration/V10__c.sql",
                                            "db/migration/R__views.sql"]
    assert by_dir["db/migration"].tool == "flyway"
    assert "queries" not in by_dir


def test_alembic_follows_the_revision_chain_not_the_file_names(tmp_path):
    root = tmp_path / "svc"
    versions = root / "alembic" / "versions"
    versions.mkdir(parents=True)
    (root / "alembic" / "env.py").write_text("")
    (versions / "aaa_second.py").write_text(
        "revision = 'r2'\ndown_revision = 'r1'\n\n\ndef upgrade():\n"
        "    op.add_column('t', sa.Column('added', sa.String()))\n"
        "    with op.batch_alter_table('t') as b:\n        b.drop_column('old')\n\n\n"
        "def downgrade():\n    op.drop_table('t')\n")
    (versions / "zzz_first.py").write_text(
        "revision = 'r1'\ndown_revision = None\n\n\ndef upgrade():\n"
        "    op.create_table('t', sa.Column('id', sa.Integer()), sa.Column('old', sa.Text()),\n"
        "                    sa.Column('owner_id', sa.Integer(), sa.ForeignKey('people.id')))\n"
        "    op.create_table(TABLE_NAME)\n")
    system = derive([SourceTree(repo="acme/svc", root=root)])
    [db] = system.databases
    assert db.tool == "alembic"
    [table] = db.tables
    assert [c.name for c in table.columns] == ["id", "owner_id", "added"]
    assert table.references == ["people"]
    assert [m.path for m in db.migrations] == ["alembic/versions/zzz_first.py",
                                               "alembic/versions/aaa_second.py"]
    assert (AT_RUN_TIME, "alembic/versions/zzz_first.py") in {
        (n.kind, n.path) for n in system.not_derived}


def test_a_branching_alembic_history_is_applied_in_file_order_and_said():
    trees = {f"v/{name}.py": ast.parse(f"revision = '{rev}'\ndown_revision = {down!r}\n")
             for name, rev, down in (("a", "r1", None), ("b", "r2", "r1"), ("c", "r3", "r1"))}
    order, linear = schemas.alembic_order(trees)
    assert (order, linear) == (["v/a.py", "v/b.py", "v/c.py"], False)


def test_django_migrations_build_tables_by_django_s_naming():
    tree = ast.parse(
        "class Migration:\n    operations = [\n"
        "        migrations.CreateModel(name='Order', fields=[('id', models.AutoField()),\n"
        "            ('customer', models.ForeignKey(to='people.Customer', on_delete=None))]),\n"
        "        migrations.CreateModel(name='Line', fields=[('id', models.AutoField())],\n"
        "            options={'db_table': 'order_line'}),\n"
        "        migrations.AddField(model_name='line', name='qty', field=models.IntegerField()),\n"
        "        migrations.RenameModel(old_name='Order', new_name='Purchase'),\n"
        "    ]\n")
    schema, models = schemas.Schema(), {}
    schemas.apply_django(tree, schema, Cite(repo="r", path="p"), app="shop", models=models)
    tables = {t.name: t for t in schema.tables()}
    assert set(tables) == {"shop_purchase", "order_line"}
    assert [c.name for c in tables["order_line"].columns] == ["id", "qty"]
    assert tables["shop_purchase"].references == ["people_customer"]
    assert [c.name for c in tables["shop_purchase"].columns] == ["id", "customer_id"]


def test_prisma_models_are_tables_and_relations_are_references():
    schema = schemas.Schema()
    engine = schemas.apply_prisma(
        'datasource db {\n  provider = "postgresql"\n  url = env("DATABASE_URL")\n}\n'
        "// model Ghost { id Int }\n"
        "model User {\n  id Int @id\n  posts Post[]\n}\n"
        'model Post {\n  id Int @id\n  author User @relation(fields: [authorId])\n'
        '  authorId Int @map("author_id")\n  @@map("posts")\n}\n',
        schema, Cite(repo="r", path="schema.prisma"))
    assert engine == "postgresql"
    tables = {t.name: t for t in schema.tables()}
    assert set(tables) == {"User", "posts"}
    assert [c.name for c in tables["posts"].columns] == ["id", "author_id"]
    assert tables["posts"].references == ["User"]


def test_asyncapi_two_reads_subscribe_as_send_and_publish_as_receive():
    """The inversion AsyncAPI 3 removed. A service whose 2.x document says `subscribe` SENDS."""
    decl, notes = api.read_asyncapi({"asyncapi": "2.6.0", "channels": {
        "a": {"subscribe": {"message": {"name": "A"}}},
        "b": {"publish": {"message": {"oneOf": [{"name": "B1"}, {"$ref": "#/x/B2"}]}}},
    }}, rel="x.yaml", repo="r")
    assert [(e.channel, e.action, e.message) for e in decl.ends] == [
        ("a", "send", "A"), ("b", "receive", "B1 | B2")]
    assert notes == []


def test_asyncapi_three_reads_the_action_and_the_address():
    decl, notes = api.read_asyncapi({
        "asyncapi": "3.0.0",
        "channels": {"k": {"address": "orders.v1", "bindings": {"amqp": {"queue": {
            "name": "orders-q"}}}}},
        "operations": {"o": {"action": "send", "channel": {"$ref": "#/channels/k"}},
                       "bad": {"action": "shout", "channel": {"$ref": "#/channels/k"}}},
    }, rel="x.yaml", repo="r")
    assert [(e.channel, e.action) for e in decl.ends] == [("orders.v1", "send")]
    assert decl.queues == [("orders-q", "amqp-queue", "orders.v1")]
    assert [n.kind for n in notes] == [PARSE_ERROR]


def test_openapi_follows_a_ref_into_the_tree_and_names_a_remote_one():
    """A relative `$ref` resolves against the description's own directory and is read through the
    caller's loader; a pointer inside the document is followed; a URL is named, never fetched, and
    nothing of its text — a user part included — is written."""
    asked: list[str] = []

    def load(rel: str):
        asked.append(rel)
        return ({"get": {"operationId": "fromFile"}}, "") if rel == "api/paths/orders.yaml" \
            else (None, "is missing")

    decl, notes = api.read_openapi({
        "swagger": "2.0", "host": "orders:8080", "paths": {
            "/a": {"$ref": "paths/orders.yaml"},
            "/b": {"$ref": "https://user:pw@example.invalid/x.yaml#/b"},
            "/c": {"$ref": "#/x-paths/c"},
            "/d": {"$ref": "missing.yaml"}},
        "x-paths": {"c": {"post": {"operationId": "internal"}}}},
        rel="api/spec.yaml", repo="r", load=load)
    assert [o.operation_id for o in decl.operations] == ["fromFile", "internal"]
    assert asked == ["api/paths/orders.yaml", "api/missing.yaml"]
    assert decl.hosts == ["orders"]
    assert [n.kind for n in notes] == [NOT_FOLLOWED, NOT_FOLLOWED]
    assert "pw" not in notes[0].detail and "example.invalid" not in notes[0].detail
    assert "`api/missing.yaml`, which is missing" in notes[1].detail


def test_proto_reads_services_and_ignores_comments():
    decl = api.read_proto('syntax = "proto3";\npackage a.b;\nimport "c/d.proto";\n'
                          "/* service Ghost { rpc Boo(X) returns (Y); } */\n"
                          "service S {\n  // rpc Old(X) returns (Y);\n"
                          "  rpc Live(stream In) returns (Out);\n}\n")
    assert (decl.package, decl.imports) == ("a.b", ["c/d.proto"])
    [service] = decl.services
    assert (service.name, service.line) == ("S", 5)
    assert [(r.name, r.request, r.response, r.line) for r in service.rpcs] == [
        ("Live", "stream In", "Out", 7)]


def test_a_proto_import_no_source_holds_is_not_declared(tmp_path):
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "a.proto").write_text('import "shared/money.proto";\n'
                                            'import "google/protobuf/empty.proto";\n'
                                            "service A { rpc X(Y) returns (Z); }\n")
    system = derive([SourceTree(repo="acme/a", root=tmp_path)])
    [note] = [n for n in system.not_derived if n.kind == NOT_DECLARED]
    assert "shared/money.proto" in note.detail


def test_terraform_reads_blocks_not_heredocs_and_never_a_password():
    resources, notes = deploy.read_terraform(
        '# resource "aws_sqs_queue" "commented" { name = "no" }\n'
        'resource "aws_lambda_function" "fn" {\n  function_name = "mailer"\n'
        '  policy = <<EOF\n{ "a": "}" \n  resource "aws_sqs_queue" "inside" {\nEOF\n'
        '  password = "hunter2"\n}\n'
        'resource "aws_sqs_queue" "jobs" {\n  name = var.queue_name\n}\n'
        'module "local" {\n  source = "./modules/x"\n}\n'
        'module "remote" {\n  source = "git::https://token@example.invalid/m.git"\n}\n',
        rel="main.tf", repo="r")
    assert [(r.type, r.label, r.name) for r in resources] == [
        ("aws_lambda_function", "fn", "mailer"), ("aws_sqs_queue", "jobs", "")]
    assert [n.kind for n in notes] == [NOT_FOLLOWED]
    assert "remote" in notes[0].detail and "token" not in notes[0].detail
    assert deploy.read_terraform_json(
        {"resource": {"aws_sns_topic": {"t": {"name": "events"}}}}, rel="x.tf.json",
        repo="r")[0].name == "events"


def test_kubernetes_services_select_workloads_and_config_maps_resolve(tmp_path):
    (tmp_path / "k8s").mkdir()
    (tmp_path / "k8s" / "a.yaml").write_text(
        "apiVersion: apps/v1\nkind: Deployment\nmetadata: {name: api-v2}\n"
        "spec:\n  template:\n    metadata: {labels: {app: api}}\n    spec:\n"
        "      containers:\n        - image: acme/api\n          env:\n"
        "            - name: STORE_URL\n              valueFrom:\n"
        "                configMapKeyRef: {name: cfg, key: STORE}\n---\n"
        "apiVersion: v1\nkind: Service\nmetadata: {name: api}\nspec:\n  selector: {app: api}\n"
        "---\napiVersion: v1\nkind: ConfigMap\nmetadata: {name: cfg}\n"
        "data:\n  STORE: http://store:80\n---\n"
        "apiVersion: apps/v1\nkind: StatefulSet\nmetadata: {name: store}\n"
        "spec:\n  template:\n    spec:\n      containers:\n        - image: acme/store\n"
        "          env:\n            - {name: API_URL, value: 'http://api.prod.svc.cluster.local'}\n"
        "---\n: [broken\n")
    system = derive([SourceTree(repo="acme/k", root=tmp_path)])
    assert {(lk.from_, lk.to, lk.via) for lk in system.links} == {
        ("api-v2", "store", "env STORE_URL"), ("store", "api-v2", "env API_URL")}
    text = (tmp_path / "k8s" / "a.yaml").read_text().splitlines()
    lines = {c.name: c.declared_by[0].line for c in system.components}
    assert lines == {"api-v2": 1, "store": text.index("kind: StatefulSet")}
    assert (PARSE_ERROR, "k8s/a.yaml") in {(n.kind, n.path) for n in system.not_derived}


def test_a_bare_pod_is_selected_by_its_own_labels_and_a_whole_secret_is_said(tmp_path):
    (tmp_path / "k8s.yaml").write_text(
        "apiVersion: v1\nkind: Pod\nmetadata: {name: cache-0, labels: {app: cache}}\n"
        "spec: {containers: [{image: redis:7}]}\n---\n"
        "apiVersion: v1\nkind: Service\nmetadata: {name: cache}\nspec: {selector: {app: cache}}\n"
        "---\napiVersion: apps/v1\nkind: Deployment\nmetadata: {name: api}\nspec:\n  template:\n"
        "    spec:\n      containers:\n        - image: acme/api\n"
        "          envFrom: [{secretRef: {name: api-env}}]\n"
        "          env: [{name: CACHE_URL, value: 'redis://cache:6379'}]\n")
    system = derive([SourceTree(repo="acme/k", root=tmp_path)])
    assert [(lk.from_, lk.to, lk.kind) for lk in system.links] == [("api", "cache-0", "cache")]
    [note] = [n for n in system.not_derived if n.kind == NOT_READ]
    assert "every variable of the secret `api-env`" in note.detail


def test_compose_says_what_it_does_not_follow(tmp_path):
    (tmp_path / "docker-compose.yml").write_text(
        "include:\n  - other.yml\nservices:\n  web:\n    build: ../elsewhere\n"
        "    env_file: [.env]\n    extends: {file: base.yml, service: b}\n"
        "    environment:\n      - UPSTREAM_URL\n      - PAYMENTS_URL=http://payments:80\n"
        "      - CALLBACK_URL=${CALLBACK}\n")
    system = derive([SourceTree(repo="acme/web", root=tmp_path)])
    kinds = sorted(n.kind for n in system.not_derived)
    assert kinds == sorted([NOT_FOLLOWED, NOT_FOLLOWED, NOT_READ, NOT_DECLARED, NOT_DECLARED,
                            AT_RUN_TIME, AT_RUN_TIME])
    said = " ".join(n.detail for n in system.not_derived)
    assert "`../elsewhere`" in said and "`payments`" in said and "UPSTREAM_URL" in said


def test_a_call_into_a_component_that_describes_no_api_is_said(tmp_path):
    (tmp_path / "compose.yaml").write_text(
        "services:\n  a:\n    image: acme/a\n    environment:\n      B_URL: http://b:80\n"
        "  b:\n    image: acme/b\n")
    system = derive([SourceTree(repo="acme/sys", root=tmp_path)])
    assert [(lk.from_, lk.to, lk.kind) for lk in system.links] == [("a", "b", "http")]
    [note] = system.not_derived
    assert (note.kind, note.path) == (NOT_DECLARED, "compose.yaml")
    assert "describes no API" in note.detail


def test_the_owner_rules_are_asked_in_order_and_written_on_the_entry(tmp_path):
    spec = "openapi: 3.0.0\ninfo: {title: t}\npaths: {/p: {get: {operationId: o}}}\n"
    mono = tmp_path / "mono"
    for rel in ("services/cart/openapi.yaml", "api/pricing.openapi.yaml", "loose/openapi.yaml",
                "built/api/openapi.yaml"):
        (mono / rel).parent.mkdir(parents=True, exist_ok=True)
        (mono / rel).write_text(spec)
    (mono / "compose.yml").write_text(
        "services:\n  cart:\n    image: acme/cart\n  pricing:\n    image: acme/pricing\n"
        "  builder:\n    build: ./built\n")
    shop = tmp_path / "shop"
    shop.mkdir()
    (shop / "openapi.yaml").write_text(spec)
    (shop / "client.yaml").write_text(spec.replace("info:", "servers: [{url: 'http://cart:80'}]\n"
                                                           "info:"))
    system = derive([SourceTree(repo="acme/mono", root=mono),
                     SourceTree(repo="acme/shop", root=shop)])
    placed = {(a.source.repo, a.source.path): (a.component, a.owner_by) for a in system.http}
    assert placed == {
        ("acme/mono", "built/api/openapi.yaml"): ("builder", "code"),
        ("acme/mono", "services/cart/openapi.yaml"): ("cart", "directory"),
        ("acme/mono", "api/pricing.openapi.yaml"): ("pricing", "file-name"),
        ("acme/mono", "loose/openapi.yaml"): ("mono", "repository"),
        ("acme/shop", "openapi.yaml"): ("shop", "repository"),
        ("acme/shop", "client.yaml"): ("cart", "servers"),
    }
    repository = system.component("mono")
    assert repository.kind == "repository"
    assert [(c.repo, c.path) for c in repository.declared_by] == [("acme/mono",
                                                                   "loose/openapi.yaml")]


def test_a_description_two_components_share_is_said_not_given_to_one(tmp_path):
    (tmp_path / "openapi.yaml").write_text(
        "openapi: 3.0.0\ninfo: {title: t}\npaths: {/p: {get: {operationId: o}}}\n")
    (tmp_path / "compose.yml").write_text(
        "services:\n  api:\n    build: .\n  worker:\n    build: .\n")
    system = derive([SourceTree(repo="acme/shop", root=tmp_path)])
    assert [(a.component, a.owner_by) for a in system.http] == [("shop", "repository")]
    [note] = system.not_derived
    assert note.kind == AMBIGUOUS and "`api`, `worker`" in note.detail


def test_an_address_joins_by_every_name_the_cluster_resolves(tmp_path):
    """`orders.shop` — the Service in its namespace — joins, because `orders` IS a Service; a
    two-label host that names no Service is an outside host and joins nothing."""
    (tmp_path / "k8s.yaml").write_text(
        "apiVersion: v1\nkind: Service\nmetadata: {name: orders}\nspec: {selector: {app: o}}\n"
        "---\napiVersion: apps/v1\nkind: Deployment\nmetadata: {name: orders-v1}\n"
        "spec:\n  template:\n    metadata: {labels: {app: o}}\n    spec:\n"
        "      containers: [{image: acme/orders}]\n---\n"
        "apiVersion: apps/v1\nkind: Deployment\nmetadata: {name: web}\nspec:\n  template:\n"
        "    spec:\n      containers:\n        - image: acme/web\n          env:\n"
        "            - {name: ORDERS_URL, value: 'http://orders.shop:8080'}\n"
        "            - {name: PAY_URL, value: 'https://payments.example'}\n")
    (tmp_path / "compose.yml").write_text(
        "services:\n  web:\n    image: acme/web\n    environment:\n"
        "      ORDERS_URL: http://orders-v1:8080\n")
    system = derive([SourceTree(repo="acme/shop", root=tmp_path)])
    [link] = system.links
    assert (link.from_, link.to, link.via) == ("web", "orders-v1", "env ORDERS_URL")
    # one link, cited by both files that declare it
    assert {s.path for s in link.sources} == {"k8s.yaml", "compose.yml"}
    assert not [n for n in system.not_derived if "payments" in n.detail]


def test_a_component_declared_as_two_kinds_is_ambiguous_not_merged(tmp_path):
    (tmp_path / "compose.yml").write_text("services:\n  store:\n    image: postgres:16\n")
    (tmp_path / "k8s.yaml").write_text("apiVersion: apps/v1\nkind: Deployment\n"
                                       "metadata: {name: store}\nspec:\n  template:\n    spec:\n"
                                       "      containers: [{image: acme/store}]\n")
    system = derive([SourceTree(repo="acme/x", root=tmp_path)])
    assert [(c.name, c.kind) for c in system.components] == [("store", "database")]
    assert [n.kind for n in system.not_derived] == [AMBIGUOUS, NOT_DECLARED]


def test_formats_this_layer_does_not_read_are_named(tmp_path):
    files = {"api.raml": "#%RAML 1.0\n", "db/migrate/001_create.rb": "class X; end\n",
             "db/migrate/002_more.rb": "class Y; end\n", "serverless.yml": "service: x\n",
             "Pulumi.yaml": "name: x\n", "cf.yaml": "AWSTemplateFormatVersion: '2010-09-09'\n",
             "schema.graphql": "type Q { a: Int }\n", "deploy/k.yaml":
             "apiVersion: v1\nkind: Service\nmetadata:\n  name: {{ .Values.name }}\n",
             "kustomization.yaml": "resources: [a.yaml]\n"}
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    system = derive([SourceTree(repo="acme/x", root=tmp_path)])
    assert {(n.kind, n.path) for n in system.not_derived} == {
        (UNKNOWN_FORMAT, "api.raml"), (UNKNOWN_FORMAT, "db/migrate"),
        (UNKNOWN_FORMAT, "serverless.yml"), (UNKNOWN_FORMAT, "Pulumi.yaml"),
        (UNKNOWN_FORMAT, "cf.yaml"), (UNKNOWN_FORMAT, "schema.graphql"),
        (UNKNOWN_FORMAT, "deploy/k.yaml"), (NOT_FOLLOWED, "kustomization.yaml")}


def test_a_file_too_large_and_a_walk_too_long_are_said(tmp_path, monkeypatch):
    (tmp_path / "openapi.yaml").write_bytes(b"openapi: 3.0.0\n" + b"#" * 1_000_001)
    (tmp_path / "plain.yaml").write_bytes(b"#" * 1_000_001)
    system = derive([SourceTree(repo="acme/x", root=tmp_path)])
    assert [(n.kind, n.path) for n in system.not_derived] == [(TOO_LARGE, "openapi.yaml")]
    from openfactory.knowledge.system import tree

    monkeypatch.setattr(tree, "MAX_FILES", 1)
    assert tree.walk(tmp_path).truncated
    system = derive([SourceTree(repo="acme/x", root=tmp_path)])
    assert TRUNCATED in {n.kind for n in system.not_derived}


def test_adrs_are_read_as_they_are_written():
    assert is_adr("docs/adr/0007-use-postgres.md") and is_adr("doc/decisions/ADR-12 x.md")
    assert not is_adr("docs/adr/README.md") and not is_adr("docs/0007-notes.md")
    bold = read_adr("# ADR 0045 — A fingerprint\n\n- **Status:** **Proposed** — half of it\n"
                    "- **Date:** 2026-09-04\n", "docs/adr/0045-a-fingerprint.md")
    assert (bold.number, bold.title, bold.status, bold.date) == (
        "0045", "ADR 0045 — A fingerprint", "Proposed", "2026-09-04")
    section = read_adr("# 3. Queue it\n\nDate: 2025-01-02\n\n## Status\n\nSuperseded by [5](5.md)\n",
                       "doc/adr/0003-queue-it.md")
    assert (section.status, section.date) == ("Superseded", "2025-01-02")
    madr = read_adr("---\nstatus: accepted\ndate: 2024-05-06\ntitle: Front\n---\n# Heading\n",
                    "docs/decisions/0001-front.md")
    assert (madr.title, madr.status, madr.date) == ("Front", "accepted", "2024-05-06")


def test_the_cli_derives_from_local_checkouts_and_writes_the_five_files(quayside, tmp_path):
    """`openfactory knowledge system` — the measurement on a real product: what was not derived
    first, then the counts and the links; `--out` writes what the refresh would publish."""
    import yaml
    from typer.testing import CliRunner

    from openfactory.cli import app

    _, repos = quayside
    args = [f"{name}={path}" for name, (path, _) in sorted(repos.items())]
    result = CliRunner().invoke(app, ["knowledge", "system", *args, str(tmp_path / "gone"),
                                      "--out", str(tmp_path / "out")])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == "not derived: 6"
    assert any("source-unreadable" in ln and "gone" in ln for ln in lines)
    assert "components: 6  links: 7" in result.output
    assert "  billing → orders (http, env ORDERS_URL)" in lines
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == [
        "adr-index.yaml", "api.yaml", "index.md", "schema.yaml", "system.yaml"]
    system = yaml.safe_load((tmp_path / "out" / "system.yaml").read_text())
    # each checkout's own commit, read from its own repository
    assert {s["repo"]: s["commit"] for s in system["sources"] if not s["missing"]} == {
        name: commit for name, (_, commit) in repos.items()}
