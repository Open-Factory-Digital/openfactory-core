"""What a repository says it STORES: the schema its migrations leave, applied in order, as text.

A migration set is one directory of migrations and the tool that wrote it. Its schema is what
applying every migration IN ORDER leaves: a table created, a column added by a later file, a column
dropped, a table renamed, a table dropped. The order is the tool's own — a version in the file
name for SQL tools, the chain of `down_revision` for Alembic — so the map says what the database
holds today, not what the first migration created.

NOTHING HERE RUNS A MIGRATION. SQL is split into statements and matched by pattern; an Alembic or
Django migration is Python, and it is read with `ast.parse`, which builds a syntax tree and executes
nothing — a migration whose module body would do harm when imported does nothing when parsed.
A migration tool whose files are a program (Rails, Knex, TypeORM, Entity Framework, Ecto) is listed
as a format this layer does not read, rather than guessed at.

WHAT A STATEMENT DOES NOT SAY, THE MAP DOES NOT SAY. `CREATE TABLE t AS SELECT …` has no column
list, so it has none here; a `op.create_table(name)` whose name is not a literal is named as not
derived; a SQL dialect's statement this reader does not know changes nothing, rather than being
half-applied.
"""

from __future__ import annotations

import ast
import posixpath
import re
from dataclasses import dataclass, field

from openfactory.knowledge.system.contracts import (
    AT_RUN_TIME,
    Cite,
    Column,
    NotDerived,
    Table,
)
from openfactory.knowledge.system.text import (
    Lines,
    blank_comments,
    bodies,
    clip,
    matching,
    pairs,
)

# ── which files are migrations, and of which tool ───────────────────────────────────────────────

#: Directory names under which a `.sql` file is a migration. Anywhere else a `.sql` file is a query
#: or a seed, and is not read as a schema — except a dump named as one (`_SCHEMA_DUMPS`).
_MIGRATION_DIRS = frozenset({"migrations", "migration", "migrate", "flyway", "changelog",
                             "changelogs", "schema", "schemas", "ddl", "initdb",
                             "docker-entrypoint-initdb.d", "sql"})
_SCHEMA_DUMPS = frozenset({"schema.sql", "structure.sql"})
_FLYWAY = re.compile(r"^(?P<kind>[VUR])(?P<version>[\d._]*)__.+\.sql$", re.IGNORECASE)
_GOLANG_MIGRATE = re.compile(r"^\d+_.+\.(?P<dir>up|down)\.sql$", re.IGNORECASE)
_DJANGO = re.compile(r"^\d{4}_\w+\.py$")

#: Migration layouts whose files are programs in a language this layer does not parse — named, so
#: a Rails service is "its schema is not derived", never "it has no database".
_UNREAD_TOOLS = (
    (re.compile(r"(^|/)db/migrate/[^/]+\.rb$"), "Rails migrations (Ruby)"),
    (re.compile(r"(^|/)db/schema\.rb$"), "a Rails schema file (Ruby)"),
    (re.compile(r"(^|/)priv/repo/migrations/[^/]+\.exs$"), "Ecto migrations (Elixir)"),
    (re.compile(r"(^|/)migrations?/[^/]+\.(js|mjs|cjs|ts)$"),
     "JavaScript migrations (Knex, TypeORM, Sequelize)"),
    (re.compile(r"(^|/)Migrations/[^/]+\.cs$"), "Entity Framework migrations (C#)"),
    (re.compile(r"(^|/)db/migration/[^/]*V\d[^/]*\.(java|kt)$"),
     "Flyway migrations written in Java or Kotlin"),
    (re.compile(r"(^|/)[^/]*changelog[^/]*\.(xml|ya?ml|json)$", re.IGNORECASE),
     "a Liquibase changelog"),
)


@dataclass
class MigrationSet:
    """One directory's migrations, in the order they apply, and the tool that orders them."""

    directory: str
    tool: str
    files: list[str] = field(default_factory=list)


def _natural(name: str) -> tuple:
    """`V2__` before `V10__`, `0002_` before `0010_`: digits compared as numbers."""
    return tuple(int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", name))


def _migration_dir(rel: str) -> str:
    """The directory a migration belongs to: the nearest ancestor named like a migration directory,
    or its own directory."""
    parts = rel.split("/")[:-1]
    for i in range(len(parts), 0, -1):
        if parts[i - 1].lower() in _MIGRATION_DIRS:
            return "/".join(parts[:i])
    return "/".join(parts) or "."


def unread_tool(rel: str) -> str:
    """The migration tool a file belongs to, when it is one whose files this layer does not read."""
    for pattern, what in _UNREAD_TOOLS:
        if pattern.search(rel):
            return what
    return ""


def migration_sets(files: list[str], *, alembic_dirs: set[str]) -> list[MigrationSet]:
    """Every migration set in a list of repository-relative files, each ordered by its tool.

    `alembic_dirs` are the `versions/` directories an Alembic environment owns (the caller knows
    from the `env.py` beside them). A directory's SQL tool is named by its files: Flyway's
    `V<version>__`, golang-migrate's `.up.sql`, dbmate's `-- migrate:up` (read when applied), else
    plain SQL in file-name order."""
    sets: dict[tuple[str, str], MigrationSet] = {}
    for rel in files:
        name = posixpath.basename(rel)
        low = name.lower()
        parent = posixpath.dirname(rel)
        if low.endswith(".py") and parent in alembic_dirs and not name.startswith("__"):
            key = (parent, "alembic")
        elif (low.endswith(".py") and posixpath.basename(parent) == "migrations"
              and _DJANGO.match(name)):
            key = (parent, "django")
        elif low.endswith(".sql"):
            if low in _SCHEMA_DUMPS:
                key = (parent or ".", "sql")
            elif any(p.lower() in _MIGRATION_DIRS for p in rel.split("/")[:-1]) \
                    or _FLYWAY.match(name):
                key = (_migration_dir(rel), "sql")
            else:
                continue
        elif low.endswith(".prisma"):
            key = (parent or ".", "prisma")
        else:
            continue
        sets.setdefault(key, MigrationSet(directory=key[0], tool=key[1])).files.append(rel)
    out = []
    for (_, tool), mset in sorted(sets.items()):
        if tool == "sql":
            mset.tool = _sql_tool(mset.files)
            mset.files = _sql_order(mset.files)
        else:
            mset.files.sort(key=lambda r: _natural(posixpath.basename(r)))
        out.append(mset)
    return out


def _sql_tool(files: list[str]) -> str:
    names = [posixpath.basename(f) for f in files]
    if any(_FLYWAY.match(n) for n in names):
        return "flyway"
    if any(_GOLANG_MIGRATE.match(n) for n in names):
        return "golang-migrate"
    return "sql"


def _sql_order(files: list[str]) -> list[str]:
    """The files that CHANGE the schema forward, in the order they apply.

    A `.down.sql` and a Flyway `U` (undo) file reverse a migration and are left out; Flyway's
    repeatable `R__` files apply after every versioned one."""
    keep = []
    for rel in files:
        name = posixpath.basename(rel)
        if (m := _GOLANG_MIGRATE.match(name)) and m.group("dir").lower() == "down":
            continue
        if (m := _FLYWAY.match(name)) and m.group("kind").upper() == "U":
            continue
        keep.append(rel)

    def order(rel: str) -> tuple:
        name = posixpath.basename(rel)
        m = _FLYWAY.match(name)
        repeatable = 1 if m and m.group("kind").upper() == "R" else 0
        return (repeatable, _natural(name), rel)

    return sorted(keep, key=order)


# ── the schema a set leaves ─────────────────────────────────────────────────────────────────────

@dataclass
class _TableState:
    name: str
    source: Cite
    columns: dict[str, str] = field(default_factory=dict)
    references: set[str] = field(default_factory=set)
    altered_in: list[Cite] = field(default_factory=list)


class Schema:
    """Tables as a sequence of migrations leaves them: keyed case-insensitively, named as
    written."""

    def __init__(self) -> None:
        self._tables: dict[str, _TableState] = {}

    def _get(self, name: str) -> _TableState | None:
        """The table `name` names — exactly, or by its last segment when that is unambiguous:
        `CREATE TABLE public.orders` and a later `ALTER TABLE orders` are one table."""
        found = self._tables.get(name.lower())
        if found is not None:
            return found
        leaf = name.lower().rsplit(".", 1)[-1]
        same = [s for k, s in self._tables.items() if k.rsplit(".", 1)[-1] == leaf]
        return same[0] if len(same) == 1 else None

    def create(self, name: str, cite: Cite, columns: list[tuple[str, str]] | None = None,
               references: set[str] | None = None) -> None:
        state = _TableState(name=name, source=cite)
        for col, typ in columns or []:
            state.columns[col] = typ
        state.references = set(references or ())
        self._tables[name.lower()] = state

    def _touch(self, name: str, cite: Cite) -> _TableState | None:
        state = self._get(name)
        if state is not None and cite not in state.altered_in and cite != state.source:
            state.altered_in.append(cite)
        return state

    def add_column(self, table: str, column: str, typ: str, cite: Cite) -> None:
        if state := self._touch(table, cite):
            state.columns[column] = typ

    def drop_column(self, table: str, column: str, cite: Cite) -> None:
        if state := self._touch(table, cite):
            key = next((c for c in state.columns if c.lower() == column.lower()), None)
            if key is not None:
                del state.columns[key]

    def rename_column(self, table: str, old: str, new: str, cite: Cite) -> None:
        if state := self._touch(table, cite):
            key = next((c for c in state.columns if c.lower() == old.lower()), None)
            if key is not None:
                state.columns = {(new if c == key else c): t for c, t in state.columns.items()}

    def set_type(self, table: str, column: str, typ: str, cite: Cite) -> None:
        if state := self._touch(table, cite):
            key = next((c for c in state.columns if c.lower() == column.lower()), None)
            if key is not None:
                state.columns[key] = typ

    def reference(self, table: str, target: str, cite: Cite) -> None:
        if state := self._touch(table, cite):
            state.references.add(target)

    def rename(self, old: str, new: str, cite: Cite) -> None:
        state = self._touch(old, cite)
        if state is not None:
            del self._tables[state.name.lower()]
            state.name = new
            self._tables[new.lower()] = state

    def drop(self, name: str) -> None:
        state = self._get(name)
        if state is not None:
            del self._tables[state.name.lower()]

    def tables(self) -> list[Table]:
        return [Table(name=s.name, columns=[Column(name=c, type=t) for c, t in s.columns.items()],
                      references=sorted(s.references), source=s.source,
                      altered_in=list(s.altered_in))
                for s in sorted(self._tables.values(), key=lambda s: s.name.lower())]


# ── SQL ─────────────────────────────────────────────────────────────────────────────────────────

_IDENT = r'(?:"[^"]+"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][\w$]*)'
_QNAME = rf"{_IDENT}(?:\s*\.\s*{_IDENT}){{0,2}}"
_CREATE = re.compile(
    rf"^\s*create\s+(?:or\s+replace\s+)?(?:(?:global|local)\s+)?(?:(?:temp|temporary|unlogged)\s+)?"
    rf"table\s+(?:if\s+not\s+exists\s+)?(?P<name>{_QNAME})", re.IGNORECASE)
_ALTER = re.compile(rf"^\s*alter\s+table\s+(?:if\s+exists\s+)?(?:only\s+)?(?P<name>{_QNAME})\s+",
                    re.IGNORECASE)
_DROP = re.compile(r"^\s*drop\s+table\s+(?:if\s+exists\s+)?(?P<names>.+)$",
                   re.IGNORECASE | re.DOTALL)
_DROP_TAIL = re.compile(r"\s+(?:cascade|restrict)\s*$", re.IGNORECASE)
_RENAME_TABLE = re.compile(rf"^\s*rename\s+table\s+(?P<old>{_QNAME})\s+to\s+(?P<new>{_QNAME})",
                           re.IGNORECASE)
_REFERENCES = re.compile(rf"\breferences\s+(?P<name>{_QNAME})", re.IGNORECASE)
#: Words that end a column's type: what follows is a constraint or an option, not the type.
_TYPE_ENDS = frozenset({"not", "null", "default", "primary", "references", "unique", "check",
                        "constraint", "collate", "generated", "auto_increment", "autoincrement",
                        "identity", "comment", "on", "as", "encode", "sortkey", "distkey",
                        "character", "charset"})
_CONSTRAINT_STARTS = frozenset({"constraint", "primary", "foreign", "unique", "check", "exclude",
                                "key", "index", "fulltext", "spatial", "like", "period"})
_DOLLAR = re.compile(r"\$([A-Za-z_]\w*)?\$")


def _unquote(ident: str) -> str:
    """One identifier as a name: quotes removed, an unquoted one folded to lower case — which is
    what PostgreSQL, and every reader comparing names, does with it."""
    ident = ident.strip()
    if len(ident) >= 2 and ident[0] + ident[-1] in ('""', "``", "[]"):
        return ident[1:-1]
    return ident.lower()


def _qname(text: str) -> str:
    return ".".join(_unquote(p) for p in re.findall(_IDENT, text))


def sql_statements(text: str) -> list[tuple[int, str]]:
    """`(line, statement)` for every statement in `text` — split at `;`, never inside a string, a
    quoted identifier, a comment or a dollar-quoted body (a PostgreSQL function is full of `;`)."""
    out: list[tuple[int, str]] = []
    buf: list[str] = []
    start: int | None = None
    line = 1
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "-" and text.startswith("--", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        if ch == "/" and text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            line += text.count("\n", i, end)
            buf.append(" ")
            i = end
            continue
        if ch in "'\"`":
            end = i + 1
            while end < n:
                if text[end] == ch:
                    if end + 1 < n and text[end + 1] == ch:   # a doubled quote is an escape
                        end += 2
                        continue
                    break
                end += 1
            chunk = text[i:end + 1]
            if start is None:
                start = line
            buf.append(chunk)
            line += chunk.count("\n")
            i = end + 1
            continue
        if ch == "$" and (m := _DOLLAR.match(text, i)):
            tag = m.group(0)
            end = text.find(tag, i + len(tag))
            end = n if end < 0 else end + len(tag)
            chunk = text[i:end]
            if start is None:
                start = line
            buf.append(chunk)
            line += chunk.count("\n")
            i = end
            continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                out.append((start or line, stmt))
            buf, start = [], None
            i += 1
            continue
        if ch == "\n":
            line += 1
        elif start is None and not ch.isspace():
            start = line
        buf.append(ch)
        i += 1
    stmt = "".join(buf).strip()
    if stmt:
        out.append((start or line, stmt))
    return out


def _split_top(body: str) -> list[str]:
    """`body` split at commas that are not inside brackets or quotes."""
    parts, depth, quote, cur = [], 0, "", []
    for ch in body:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"`":
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur).strip())
    return parts


def _column(element: str) -> tuple[str, str] | None:
    """`(name, type)` of a column definition, or None when the element is a constraint."""
    m = re.match(rf"\s*(?P<name>{_IDENT})\s*(?P<rest>.*)$", element, re.DOTALL)
    if not m or _unquote(m.group("name")).lower() in _CONSTRAINT_STARTS \
            and not m.group("name").startswith(('"', "`", "[")):
        return None
    words, depth, typ = m.group("rest").split(), 0, []
    for word in words:
        if depth == 0 and word.lower().strip(",") in _TYPE_ENDS:
            break
        typ.append(word)
        depth += word.count("(") - word.count(")")
    return _unquote(m.group("name")), " ".join(" ".join(typ).lower().split())


def _apply_create(stmt: str, m: re.Match, schema: Schema, cite: Cite) -> None:
    name = _qname(m.group("name"))
    rest = stmt[m.end():]
    open_at = rest.find("(")
    if open_at < 0 or re.match(r"\s*as\b", rest[:open_at], re.IGNORECASE):
        schema.create(name, cite)       # `AS SELECT …` — no column list declared
        return
    close = matching(rest, open_at, "()")
    body = rest[open_at + 1: close if close > 0 else len(rest)]
    columns, refs = [], set()
    for element in _split_top(body):
        if re.match(r"\s*like\b", element, re.IGNORECASE):
            continue
        for r in _REFERENCES.finditer(element):
            refs.add(_qname(r.group("name")))
        col = _column(element)
        if col is not None:
            columns.append(col)
    schema.create(name, cite, columns, refs)


def _apply_alter(stmt: str, m: re.Match, schema: Schema, cite: Cite) -> None:
    table = _qname(m.group("name"))
    for action in _split_top(stmt[m.end():]):
        low = action.lower()
        for r in _REFERENCES.finditer(action):
            schema.reference(table, _qname(r.group("name")), cite)
        if a := re.match(r"\s*rename\s+to\s+(?P<new>.+)$", action, re.IGNORECASE | re.DOTALL):
            schema.rename(table, _qname(a.group("new")), cite)
            table = _qname(a.group("new"))
        elif a := re.match(rf"\s*rename\s+(?:column\s+)?(?P<old>{_IDENT})\s+to\s+(?P<new>{_IDENT})",
                           action, re.IGNORECASE):
            schema.rename_column(table, _unquote(a.group("old")), _unquote(a.group("new")), cite)
        elif re.match(r"\s*add\s+(constraint|primary|foreign|unique|check|index|key|exclude)\b",
                      low):
            continue
        elif a := re.match(r"\s*add\s+(?:column\s+)?(?:if\s+not\s+exists\s+)?(?P<def>.+)$",
                           action, re.IGNORECASE | re.DOTALL):
            if col := _column(a.group("def")):
                schema.add_column(table, col[0], col[1], cite)
        elif re.match(r"\s*drop\s+(constraint|index|key|primary|foreign|default)\b", low):
            continue
        elif a := re.match(rf"\s*drop\s+(?:column\s+)?(?:if\s+exists\s+)?(?P<col>{_IDENT})",
                           action, re.IGNORECASE):
            schema.drop_column(table, _unquote(a.group("col")), cite)
        elif a := re.match(rf"\s*(?:alter|modify)\s+(?:column\s+)?(?P<col>{_IDENT})\s+"
                           rf"(?:set\s+data\s+)?(?:type\s+)?(?P<typ>.+)$", action,
                           re.IGNORECASE | re.DOTALL):
            typ = a.group("typ").strip()
            if not re.match(r"(set|drop|add|reset|restart)\b", typ, re.IGNORECASE):
                if col := _column(f"{a.group('col')} {typ}"):
                    schema.set_type(table, col[0], col[1], cite)
        elif a := re.match(rf"\s*change\s+(?:column\s+)?(?P<old>{_IDENT})\s+(?P<def>.+)$", action,
                           re.IGNORECASE | re.DOTALL):
            if col := _column(a.group("def")):
                schema.rename_column(table, _unquote(a.group("old")), col[0], cite)
                schema.set_type(table, col[0], col[1], cite)


def apply_sql(text: str, schema: Schema, cite: Cite, *, dbmate: bool = True) -> int:
    """Apply one SQL file's statements to `schema`. Returns how many changed it.

    A dbmate file's `-- migrate:down` half reverses its `-- migrate:up` half and is left out."""
    if dbmate and re.search(r"^--\s*migrate:up\b", text, re.MULTILINE | re.IGNORECASE):
        up = re.split(r"^--\s*migrate:down\b.*$", text, maxsplit=1,
                      flags=re.MULTILINE | re.IGNORECASE)[0]
        text = up
    changed = 0
    for line, stmt in sql_statements(text):
        at = cite.model_copy(update={"line": line})
        if m := _CREATE.match(stmt):
            _apply_create(stmt, m, schema, at)
        elif m := _ALTER.match(stmt):
            _apply_alter(stmt, m, schema, at)
        elif m := _DROP.match(stmt):
            for name in _split_top(_DROP_TAIL.sub("", m.group("names"))):
                schema.drop(_qname(name))
        elif m := _RENAME_TABLE.match(stmt):
            schema.rename(_qname(m.group("old")), _qname(m.group("new")), at)
        else:
            continue
        changed += 1
    return changed


# ── Alembic and Django: Python, read as a tree ─────────────────────────────────────────────────

def _literal(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _call_name(node: ast.AST) -> str:
    """`sa.Column(...)` → `Column`; `Column(...)` → `Column`."""
    func = node.func if isinstance(node, ast.Call) else node
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _type_name(node: ast.AST | None) -> str:
    """`sa.String(length=40)` → `string`; `postgresql.UUID` → `uuid`."""
    if node is None:
        return ""
    return _call_name(node).lower()


def alembic_revision(tree: ast.Module) -> tuple[str, tuple[str, ...]]:
    """`(revision, down_revisions)` of an Alembic migration, from its module-level literals."""
    rev, down = "", ()
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, ast.AnnAssign) else [])
        value = getattr(node, "value", None)
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id == "revision" and _literal(value):
                rev = _literal(value) or ""
            elif target.id == "down_revision":
                if isinstance(value, ast.Tuple | ast.List):
                    down = tuple(v for v in (_literal(e) for e in value.elts) if v)
                elif _literal(value):
                    down = (_literal(value) or "",)
    return rev, down


def alembic_order(parsed: dict[str, ast.Module]) -> tuple[list[str], bool]:
    """The files of one Alembic `versions/` directory in the order their revisions chain, and
    whether that chain is one line. A branching or broken chain falls back to file-name order and
    says so (`False`) — the map applies them, and names the order as unproven."""
    by_rev: dict[str, str] = {}
    down_of: dict[str, tuple[str, ...]] = {}
    for rel, tree in parsed.items():
        rev, down = alembic_revision(tree)
        if not rev or rev in by_rev:
            return sorted(parsed, key=lambda r: _natural(posixpath.basename(r))), False
        by_rev[rev], down_of[rev] = rel, down
    roots = [r for r, d in down_of.items() if not d]
    children: dict[str, list[str]] = {}
    for rev, down in down_of.items():
        for d in down:
            children.setdefault(d, []).append(rev)
    if len(roots) != 1 or any(len(d) > 1 for d in down_of.values()) \
            or any(len(c) > 1 for c in children.values()):
        return sorted(parsed, key=lambda r: _natural(posixpath.basename(r))), False
    order, cur = [], roots[0]
    while cur and len(order) <= len(by_rev):
        order.append(by_rev[cur])
        nxt = children.get(cur, [])
        cur = nxt[0] if nxt else ""
    if len(order) != len(by_rev):
        return sorted(parsed, key=lambda r: _natural(posixpath.basename(r))), False
    return order, True


def _column_call(node: ast.AST) -> tuple[str, str, set[str]] | None:
    """`sa.Column("name", sa.Type(), sa.ForeignKey("t.id"))` → `(name, type, {t})`."""
    if not (isinstance(node, ast.Call) and _call_name(node) == "Column" and node.args):
        return None
    name = _literal(node.args[0])
    if name is None:
        return None
    typ = _type_name(node.args[1]) if len(node.args) > 1 else ""
    refs = set()
    for arg in node.args[1:]:
        if isinstance(arg, ast.Call) and _call_name(arg) == "ForeignKey" and arg.args:
            target = _literal(arg.args[0]) or ""
            if target:
                refs.add(target.rsplit(".", 1)[0])
    return name, typ, refs


def apply_alembic(tree: ast.Module, schema: Schema, cite: Cite, *, repo: str, rel: str
                  ) -> list[NotDerived]:
    """Apply one Alembic migration's `upgrade()` to `schema` — never its `downgrade()`."""
    notes: list[NotDerived] = []
    upgrade = next((n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == "upgrade"), None)
    if upgrade is None:
        return notes
    batch: dict[str, str] = {}
    for node in ast.walk(upgrade):
        if isinstance(node, ast.With):
            for item in node.items:
                call = item.context_expr
                if isinstance(call, ast.Call) and _call_name(call) == "batch_alter_table" \
                        and isinstance(item.optional_vars, ast.Name) and call.args \
                        and _literal(call.args[0]):
                    batch[item.optional_vars.id] = _literal(call.args[0]) or ""
    for node in ast.walk(upgrade):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)):
            continue
        owner, op = node.func.value.id, node.func.attr
        at = cite.model_copy(update={"line": getattr(node, "lineno", 0)})
        args = list(node.args)
        if owner in batch:
            args = [ast.Constant(batch[owner]), *args]
        elif owner != "op":
            continue
        table = _literal(args[0]) if args else None
        if op == "execute":
            if table is not None:
                apply_sql(table, schema, at, dbmate=False)
            else:
                notes.append(NotDerived(kind=AT_RUN_TIME, repo=repo, path=rel,
                                        detail=f"`op.execute` at line {at.line} runs SQL the "
                                               f"migration builds as it runs; what it changes is "
                                               f"not derived"))
            continue
        if op not in ("create_table", "drop_table", "add_column", "drop_column", "rename_table",
                      "alter_column", "create_foreign_key"):
            continue
        if table is None:
            notes.append(NotDerived(kind=AT_RUN_TIME, repo=repo, path=rel,
                                    detail=f"`op.{op}` at line {at.line} names its table with an "
                                           f"expression, not a literal; it was not applied"))
            continue
        if op == "create_table":
            cols, refs = [], set()
            for arg in args[1:]:
                if col := _column_call(arg):
                    cols.append((col[0], col[1]))
                    refs |= col[2]
                elif isinstance(arg, ast.Call) and _call_name(arg) == "ForeignKeyConstraint" \
                        and len(arg.args) > 1 and isinstance(arg.args[1], ast.List | ast.Tuple):
                    for e in arg.args[1].elts:
                        if _literal(e):
                            refs.add((_literal(e) or "").rsplit(".", 1)[0])
            schema.create(table, at, cols, refs)
        elif op == "drop_table":
            schema.drop(table)
        elif op == "add_column" and len(args) > 1 and (col := _column_call(args[1])):
            schema.add_column(table, col[0], col[1], at)
            for ref in col[2]:
                schema.reference(table, ref, at)
        elif op == "drop_column" and len(args) > 1 and _literal(args[1]):
            schema.drop_column(table, _literal(args[1]) or "", at)
        elif op == "rename_table" and len(args) > 1 and _literal(args[1]):
            schema.rename(table, _literal(args[1]) or "", at)
        elif op == "alter_column" and len(args) > 1 and _literal(args[1]):
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            if _literal(kw.get("new_column_name")):
                schema.rename_column(table, _literal(args[1]) or "",
                                     _literal(kw["new_column_name"]) or "", at)
            if kw.get("type_") is not None:
                schema.set_type(table, _literal(args[1]) or "", _type_name(kw["type_"]), at)
        elif op == "create_foreign_key" and len(args) > 2 and _literal(args[2]):
            schema.reference(_literal(args[1]) or table, _literal(args[2]) or "", at)
    return notes


def apply_django(tree: ast.Module, schema: Schema, cite: Cite, *, app: str,
                 models: dict[str, str]) -> None:
    """Apply one Django migration's `operations` to `schema`. A model's table is its `db_table`
    when a migration set one, else Django's default, `<app>_<model>`; `models` carries that
    mapping from one migration of the set to the next, so a later `AddField` finds the table an
    earlier `CreateModel` named."""
    ops: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "operations"
                                                for t in node.targets) \
                and isinstance(node.value, ast.List | ast.Tuple):
            ops = list(node.value.elts)

    def table_of(model: str | None) -> str:
        key = (model or "").lower()
        return models.get(key) or f"{app}_{key}"

    for op in ops:
        if not isinstance(op, ast.Call):
            continue
        kind = _call_name(op)
        kw = {k.arg: k.value for k in op.keywords if k.arg}
        at = cite.model_copy(update={"line": getattr(op, "lineno", 0)})
        if kind == "CreateModel":
            model = _literal(kw.get("name")) or (_literal(op.args[0]) if op.args else None)
            if not model:
                continue
            table = f"{app}_{model.lower()}"
            options = kw.get("options")
            if isinstance(options, ast.Dict):
                for k, v in zip(options.keys, options.values, strict=False):
                    if _literal(k) == "db_table" and _literal(v):
                        table = _literal(v) or table
            models[model.lower()] = table
            cols, refs = [], set()
            fields = kw.get("fields") or (op.args[1] if len(op.args) > 1 else None)
            for f in getattr(fields, "elts", []) or []:
                if not (isinstance(f, ast.Tuple) and len(f.elts) == 2 and _literal(f.elts[0])):
                    continue
                name, fcall = _literal(f.elts[0]) or "", f.elts[1]
                ftype = _call_name(fcall)
                if ftype == "ManyToManyField":
                    continue
                if ftype in ("ForeignKey", "OneToOneField"):
                    name = f"{name}_id"
                    if target := _foreign_target(fcall):
                        refs.add(_django_table(target, app))
                cols.append((name, ftype.lower()))
            schema.create(table, at, cols, refs)
        elif kind == "DeleteModel":
            model = _literal(kw.get("name")) or (_literal(op.args[0]) if op.args else "")
            schema.drop(table_of(model))
        elif kind == "AddField":
            model, name = _literal(kw.get("model_name")), _literal(kw.get("name"))
            field_call = kw.get("field")
            if not (model and name and isinstance(field_call, ast.Call)):
                continue
            ftype = _call_name(field_call)
            if ftype == "ManyToManyField":
                continue
            if ftype in ("ForeignKey", "OneToOneField"):
                name = f"{name}_id"
                if target := _foreign_target(field_call):
                    schema.reference(table_of(model), _django_table(target, app), at)
            schema.add_column(table_of(model), name, ftype.lower(), at)
        elif kind == "RemoveField":
            model, name = _literal(kw.get("model_name")), _literal(kw.get("name"))
            if model and name:
                schema.drop_column(table_of(model), name, at)
        elif kind == "RenameModel":
            old, new = _literal(kw.get("old_name")), _literal(kw.get("new_name"))
            if old and new:
                before = table_of(old)
                after = f"{app}_{new.lower()}" if before == f"{app}_{old.lower()}" else before
                schema.rename(before, after, at)
                models.pop(old.lower(), None)
                models[new.lower()] = after
        elif kind == "RenameField":
            model = _literal(kw.get("model_name"))
            old, new = _literal(kw.get("old_name")), _literal(kw.get("new_name"))
            if model and old and new:
                schema.rename_column(table_of(model), old, new, at)
        elif kind == "AlterModelTable":
            model, table = _literal(kw.get("name")), _literal(kw.get("table"))
            if model and table:
                schema.rename(table_of(model), table, at)
                models[model.lower()] = table
        elif kind == "RunSQL":
            sql = _literal(kw.get("sql")) or (_literal(op.args[0]) if op.args else None)
            if sql:
                apply_sql(sql, schema, at, dbmate=False)


def _foreign_target(call: ast.Call) -> str:
    """The model a Django `ForeignKey` points at: `to="app.Model"` or its first argument."""
    kw = {k.arg: k.value for k in call.keywords if k.arg}
    return _literal(kw.get("to")) or (_literal(call.args[0]) if call.args else "") or ""


def _django_table(target: str, app: str) -> str:
    """`"orders.Order"` → `orders_order`; `"Order"` → `<app>_order`."""
    if "." in target:
        other, model = target.split(".", 1)
        return f"{other.lower()}_{model.lower()}"
    return f"{app}_{target.lower()}"


# ── Prisma: a declarative schema, read as text ─────────────────────────────────────────────────

_PRISMA_BLOCK = re.compile(r"^[ \t]*(model|datasource)[ \t]+(\w+)[ \t]*\{", re.MULTILINE)
_PRISMA_SCALARS = frozenset({"string", "int", "bigint", "float", "decimal", "boolean", "datetime",
                             "json", "bytes", "unsupported"})


def apply_prisma(text: str, schema: Schema, cite: Cite) -> str:
    """Every `model` of a Prisma schema as a table; returns the datasource's provider, the engine.

    A field whose type is another model is a relation: a reference, not a column."""
    code = blank_comments(text, line=("//",), block=None, quotes='"')
    closes, lines = pairs(code, quotes='"'), Lines(code)
    engine = ""
    found = list(_PRISMA_BLOCK.finditer(code))
    models = {m.group(2) for m in found if m.group(1) == "model"}
    for m, end in bodies(code, found, closes):
        body = code[m.end(): end]
        if m.group(1) == "datasource":
            if p := re.search(r'\bprovider\s*=\s*"([^"]+)"', body):
                engine = clip(p.group(1), 40)
            continue
        table = m.group(2)
        if mapped := re.search(r'@@map\(\s*(?:name\s*:\s*)?"([^"]+)"', body):
            table = mapped.group(1)
        cols, refs = [], set()
        for line in body.splitlines():
            f = re.match(r"\s*([A-Za-z_]\w*)\s+([A-Za-z_]\w*)(\[\])?(\?)?", line)
            if not f:
                continue
            name, typ, many = f.group(1), f.group(2), f.group(3)
            if typ in models:
                if not many:
                    refs.add(typ)
                continue
            if many:
                continue
            column = re.search(r'@map\(\s*(?:name\s*:\s*)?"([^"]+)"', line)
            cols.append((column.group(1) if column else name,
                         typ.lower() if typ.lower() in _PRISMA_SCALARS else typ))
        schema.create(table, cite.model_copy(update={"line": lines.at(m.start())}), cols, refs)
    return engine


__all__ = ["MigrationSet", "Schema", "alembic_order", "alembic_revision",
           "apply_alembic", "apply_django", "apply_prisma", "apply_sql", "migration_sets",
           "sql_statements", "unread_tool"]
