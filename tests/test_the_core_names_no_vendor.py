"""No vendor in the core: a chat vendor's name outside a comment in `openfactory/` fails here.

#266 slice 6, ADR-0051 D16 — and the repository owner's standing rule: *no vendor in the core; the
chat vendor is an add-on only*. ADR-0038 moved the transport out as code and its SHAPE stayed: an
event parser for one vendor's threads, a channel id read as "this project is on that vendor", admin
lists documented as that vendor's user ids, `via` defaulting to its name, its mention syntax written
into requirement files. The slice took each out; this is what keeps them out.

WHAT IS HELD, AND WHAT IS NOT. Everything the core RUNS or SHOWS is held: every identifier, import,
attribute, keyword and string constant in every Python file, the panel's page with its markup and
its script, and the role prompts and defaults the package ships. Comments are not held, and neither
are docstrings — the house rule `test_kernel_names_no_vendor.py` wrote down first: a comment here
carries the measurement that earned it, and the measurement usually has a vendor's name in it. A
docstring is a comment in Python's own clothes — nothing in `openfactory/` reads one at run time,
and the last test in this file holds that, because the day something does, a docstring becomes
something the core shows and this exemption becomes a hole.

WHICH VENDORS. The chat vendors — the transports ADR-0038 made add-ons. Not the forges, trackers,
harnesses or the durable engine: the core ships those adapters as built-in rows on purpose, and
the cloud has a guard of its own (`test_the_cloud_is_a_directory_delete.py`). Matched as WORDS, so
a Portuguese verb that happens to start like one of them is not a vendor, and a vendor spelled in
camel case, snake case or a dotted kind still is.

THE ALLOW-LIST IS DATA, AND SHORT. A vendor's name may appear in code only where it is a value a
deployment or a package supplies — never where the core decides anything by it. Each entry is one
exact string in one file, with the reason; an identifier is never allowed, and a new string in an
allowed file is not allowed by being there.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "openfactory"

#: The chat vendors, as words. A new transport that becomes an add-on joins this list.
VENDORS = frozenset({"slack", "telegram", "discord", "whatsapp", "mattermost", "msteams",
                     "zulip", "rocketchat"})
#: The ones whose name is two words, each ordinary on its own.
VENDOR_PHRASES = (("microsoft", "teams"), ("ms", "teams"), ("rocket", "chat"))

#: `(file, exact string) → why the vendor's name is DATA there`. Nothing else is allowed.
ALLOWED: dict[tuple[str, str], str] = {
    # The old configuration keys (ADR-0051 decision 6): the spellings a deployment's registry may
    # still hold, read as aliases with a deprecation warning until `aliases.READ_UNTIL`. They are
    # the keys the core must recognise to fold them away, not a vendor the core talks to.
    ("openfactory/contracts/aliases.py", "slack_channel"):
        "an old registry key, read as an alias for one minor version (decision 6)",
    ("openfactory/contracts/aliases.py", "slack_admins"):
        "an old registry key, read as an alias for one minor version (decision 6)",
    ("openfactory/contracts/aliases.py", "slack_bot_token_env"):
        "an old registry key, read as an alias for one minor version (decision 6)",
    ("openfactory/contracts/aliases.py", "slack_app_token_env"):
        "an old registry key, read as an alias for one minor version (decision 6)",
    # The install hint (`plugins.SHIPS_IN`): the kinds the maintainers' own chat add-on package
    # registers through the entry-point group, and that package's name — so that a deployment
    # declaring `channel: <kind>` without the package is refused with the package to install.
    # The kind is the add-on's registered name, supplied by the add-on; the core builds nothing by
    # it.
    ("openfactory/plugins.py", "channel.slack"):
        "an add-on's registered kind, named only to point a refusal at its package",
    ("openfactory/plugins.py", "notifier.slack"):
        "an add-on's registered kind, named only to point a refusal at its package",
    ("openfactory/plugins.py", "notifier.telegram"):
        "an add-on's registered kind, named only to point a refusal at its package",
    ("openfactory/plugins.py", "openfactory-slack"):
        "the add-on package's distribution name, which a refusal tells the operator to install",
}


def vendor_in(text: str) -> str:
    """The vendor `text` names, as a word — or "" when it names none."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text or ""))
    words = re.findall(r"[a-z0-9]+", spaced.lower())
    for word in words:
        if word in VENDORS:
            return word
    for first, second in zip(words, words[1:], strict=False):
        if (first, second) in VENDOR_PHRASES:
            return f"{first} {second}"
    return ""


# ── what the core runs: Python ──────────────────────────────────────────────────────────────────

def _docstrings(tree: ast.AST) -> set[int]:
    """The ids of every string that is a statement of its own — a docstring, or a string written
    as a comment. Both are prose nobody executes."""
    return {id(node.value) for node in ast.walk(tree)
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)}


def python_findings(source: str) -> list[tuple[int, str, str]]:
    """`(line, what, text)` for every vendor name the code itself carries — identifiers, imports,
    attributes, keywords, and every string that is a value. Comments are not in the tree, and
    docstrings are skipped (see the module's docstring)."""
    tree = ast.parse(source)
    prose = _docstrings(tree)
    found: list[tuple[int, str, str]] = []

    def check(node, what: str, text: str) -> None:
        if vendor_in(text):
            found.append((getattr(node, "lineno", 0), what, text))

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            check(node, "name", node.id)
        elif isinstance(node, ast.Attribute):
            check(node, "attribute", node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            check(node, "definition", node.name)
        elif isinstance(node, ast.arg):
            check(node, "argument", node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            check(node, "keyword", node.arg)
        elif isinstance(node, ast.alias):
            check(node, "import", f"{node.name} {node.asname or ''}")
        elif isinstance(node, ast.ImportFrom):
            check(node, "import", node.module or "")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in prose:
            check(node, "string", node.value)
    return found


# ── what the core shows: the page, the prompts, the defaults ────────────────────────────────────

def _blank(text: str) -> str:
    """What a comment is replaced with: its line breaks, so every line keeps its number."""
    return "\n" * text.count("\n")


def _without_markup_comments(text: str) -> str:
    """`<!-- … -->` removed — wherever it sits, a JavaScript template included: a comment in markup
    is a comment in the page it becomes."""
    return re.sub(r"<!--.*?-->", lambda m: _blank(m.group(0)), text, flags=re.S)


#: The words after which a `/` starts a regular expression rather than a division.
_BEFORE_A_REGEX = frozenset({"return", "typeof", "case", "in", "of", "do", "else", "void",
                             "delete", "throw", "new", "yield", "await"})


def _starts_a_regex(code: str, at: int) -> bool:
    """Whether the `/` at `at` opens a regular expression literal — read from what precedes it,
    the way a JavaScript tokenizer reads it."""
    j = at - 1
    while j >= 0 and code[j] in " \t\r\n":
        j -= 1
    if j < 0:
        return True
    if code[j] in ")]":
        return False
    if code[j].isalnum() or code[j] in "_$":
        k = j
        while k >= 0 and (code[k].isalnum() or code[k] in "_$"):
            k -= 1
        return code[k + 1:j + 1] in _BEFORE_A_REGEX
    return True


def _without_script_comments(code: str) -> str:
    """A script's `//` and `/* */` comments blanked, everything else kept — READ AS TOKENS: a `//`
    inside a string (an address) is not a comment, a backtick inside a regular expression opens
    no template, and a template's `${…}` is code with templates of its own inside."""
    out: list[str] = []
    i, n = 0, len(code)
    stack: list[list] = []   # ["tpl"] inside a template's text; ["expr", depth] inside its ${…}
    while i < n:
        c = code[i]
        if stack and stack[-1][0] == "tpl":
            if c == "\\":
                out.append(code[i:i + 2])
                i += 2
            elif c == "`":
                stack.pop()
                out.append(c)
                i += 1
            elif code.startswith("${", i):
                stack.append(["expr", 0])
                out.append("${")
                i += 2
            else:
                out.append(c)
                i += 1
            continue
        if c in "'\"":
            j = i + 1
            while j < n and code[j] != c and code[j] != "\n":
                j += 2 if code[j] == "\\" else 1
            out.append(code[i:j + 1])
            i = j + 1
            continue
        if c == "`":
            stack.append(["tpl"])
            out.append(c)
            i += 1
            continue
        if code.startswith("//", i):
            end = code.find("\n", i)
            i = n if end < 0 else end
            continue
        if code.startswith("/*", i):
            end = code.find("*/", i + 2)
            end = n if end < 0 else end + 2
            out.append(_blank(code[i:end]))
            i = end
            continue
        if c == "/" and _starts_a_regex(code, i):
            j, in_class = i + 1, False
            while j < n and code[j] != "\n":
                if code[j] == "\\":
                    j += 2
                    continue
                if code[j] == "[":
                    in_class = True
                elif code[j] == "]":
                    in_class = False
                elif code[j] == "/" and not in_class:
                    break
                j += 1
            j += 1
            while j < n and code[j].isalpha():
                j += 1
            out.append(code[i:j])
            i = j
            continue
        if stack and c == "{":
            stack[-1][1] += 1
        elif stack and c == "}":
            if stack[-1][1] == 0:
                stack.pop()
            else:
                stack[-1][1] -= 1
        out.append(c)
        i += 1
    return "".join(out)


def page_findings(html: str) -> list[tuple[int, str, str]]:
    """Vendor names in a page OUTSIDE its comments: the markup's text and attributes, and every
    script's code and strings. Styles are read for their comments too."""
    html = _without_markup_comments(html)
    found: list[tuple[int, str, str]] = []
    pos = 0
    pieces: list[tuple[int, str]] = []
    for match in re.finditer(r"(<script\b[^>]*>)(.*?)(</script>)|(<style\b[^>]*>)(.*?)(</style>)",
                             html, flags=re.S):
        pieces.append((pos, html[pos:match.start()]))
        body_at = match.start(2) if match.group(2) is not None else match.start(5)
        body = match.group(2) if match.group(2) is not None else match.group(5)
        kept = _without_script_comments(body)
        pieces.append((body_at, kept))
        pos = match.end()
    pieces.append((pos, html[pos:]))
    for start, text in pieces:
        for number, line in enumerate(text.splitlines(), start=html.count("\n", 0, start) + 1):
            if vendor_in(line):
                found.append((number, "page", line.strip()[:160]))
    return found


def yaml_findings(text: str) -> list[tuple[int, str, str]]:
    """Vendor names in a YAML file outside its `#` comments."""
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        code = re.split(r"(?:^|\s)#", line, maxsplit=1)[0]
        if vendor_in(code):
            found.append((number, "yaml", line.strip()[:160]))
    return found


def text_findings(text: str) -> list[tuple[int, str, str]]:
    """Vendor names in a prompt or a template the package ships — read by a model or a person, so
    every word counts, except a markup comment."""
    text = _without_markup_comments(text)
    return [(number, "text", line.strip()[:160])
            for number, line in enumerate(text.splitlines(), start=1) if vendor_in(line)]


def findings(path: pathlib.Path) -> list[tuple[int, str, str]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        return python_findings(text)
    if path.suffix == ".html":
        return page_findings(text)
    if path.suffix in (".yaml", ".yml"):
        return yaml_findings(text)
    return text_findings(text)


def _files() -> list[pathlib.Path]:
    return sorted(p for p in PACKAGE.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")


def offenders(root: pathlib.Path = ROOT) -> list[str]:
    """Every vendor name in the core outside a comment and outside the allow-list, as
    `path:line — what: text`."""
    out = []
    for path in sorted(p for p in (root / "openfactory").rglob("*")
                       if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"):
        rel = path.relative_to(root).as_posix()
        for line, what, text in findings(path):
            if (rel, text) in ALLOWED:
                continue
            out.append(f"{rel}:{line} — {what}: {text!r}")
    return out


# ── the tree ────────────────────────────────────────────────────────────────────────────────────

def test_the_guard_reads_the_whole_package():
    """A guard that walks nothing passes for ever — and one that walks only Python misses the
    page every person reads."""
    files = _files()
    assert len([p for p in files if p.suffix == ".py"]) >= 200
    assert any(p.name == "panel.html" for p in files)
    assert any(p.suffix == ".md" for p in files) and any(p.suffix == ".yaml" for p in files)


def test_no_vendor_is_named_outside_a_comment_in_the_core():
    """THE GUARD (#266 slice 6, ADR-0051 D16). A vendor's name the core runs or shows is a core
    with a default vendor: the chat vendor is an add-on, and the core names nobody."""
    found = offenders()
    assert not found, (
        "the core names a chat vendor outside a comment — move it to the add-on, or, where it is "
        "DATA a deployment or a package supplies, add it to ALLOWED with the reason:\n  "
        + "\n  ".join(found))


def test_every_allowed_entry_is_still_in_the_tree():
    """An allow-list entry that no longer matches anything is a hole waiting for the next
    string with that spelling — and a record that says something is data when it is gone."""
    live = set()
    for (rel, _text) in ALLOWED:
        path = ROOT / rel
        assert path.exists(), f"{rel} is allowed a vendor's name and no longer exists"
        live |= {(rel, t) for _l, _w, t in findings(path)}
    stale = sorted(set(ALLOWED) - live)
    assert not stale, f"allowed and no longer present — remove them: {stale}"


def test_nothing_in_the_core_reads_a_docstring_at_run_time():
    """What makes a docstring a comment. The day the core shows one — a help text, a tool's
    description handed to a model — this exemption turns into a hole, and this fails first."""
    readers = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "__doc__":
                readers.append(f"{path.relative_to(ROOT)}:{node.lineno} — .__doc__")
            if isinstance(node, (ast.Attribute, ast.Name)) and \
                    getattr(node, "attr", getattr(node, "id", "")) in ("getdoc", "cleandoc"):
                readers.append(f"{path.relative_to(ROOT)}:{node.lineno} — inspect.getdoc")
    assert not readers, "the core reads docstrings at run time:\n  " + "\n  ".join(readers)


# ── the guard goes red where it must, and stays green where it must ─────────────────────────────

@pytest.mark.parametrize("source", [
    'via = "slack"\n',
    'def slack_handler():\n    pass\n',
    'x = project.slack_channel\n',
    'f(bot=SlackBot())\n',
    'from slack_sdk import WebClient\n',
    'import openfactory.runtime.telegram\n',
    'kind = f"notifier.{name}" if name else "channel.Discord"\n',
    'log.info("posted to MS Teams")\n',
    'def f(*, whatsapp_token=""):\n    return 1\n',
], ids=["string", "definition", "attribute", "class", "import", "module", "fstring", "phrase",
        "argument"])
def test_a_planted_vendor_name_in_python_is_RED(source):
    assert python_findings(source), f"the guard missed a vendor in: {source!r}"


@pytest.mark.parametrize("source", [
    '# the slack add-on reads this\nx = 1\n',
    'def f():\n    """What the Slack listener used to do."""\n    return 1\n',
    'x = "discordarem"  # a Portuguese verb, not a vendor\n',
    'teams = ["backend", "frontend"]\n',
], ids=["comment", "docstring", "not-a-word", "ordinary-teams"])
def test_what_is_a_comment_or_not_a_vendor_stays_GREEN(source):
    assert not python_findings(source), python_findings(source)


def test_the_page_is_held_outside_its_comments():
    page = ("<html><body><p>Talk to us on Slack</p>\n"
            "<!-- the Slack add-on renders this -->\n"
            "<script>\n"
            "// what a Slack bot reads\n"
            "/* the telegram row */\n"
            "const url = 'https://example.org//path';\n"
            "const kind = \"slack\";\n"
            "</script></body></html>\n")
    found = [text for _l, _w, text in page_findings(page)]
    assert any("Talk to us on Slack" in t for t in found), found
    assert any('const kind = "slack"' in t for t in found), found
    assert not any("renders this" in t or "bot reads" in t or "telegram row" in t
                   for t in found), found


def test_yaml_and_prompts_are_held_outside_their_comments():
    assert yaml_findings("channel: slack\n") and not yaml_findings("# channel: slack\nx: 1\n")
    assert text_findings("Answer in the Slack thread.\n")
    assert not text_findings("<!-- the Slack add-on -->\nAnswer here.\n")


def test_a_planted_name_in_the_TREE_is_found_by_the_guard(tmp_path):
    """Red with a planted vendor name, by the same walk the tree is held to: a copy of one real
    file of the core, one string changed."""
    tree = tmp_path / "openfactory" / "product"
    tree.mkdir(parents=True)
    source = (PACKAGE / "product" / "door.py").read_text(encoding="utf-8")
    assert 'EVENT = "event"' in source
    (tree / "door.py").write_text(source, encoding="utf-8")
    assert offenders(tmp_path) == []
    (tree / "door.py").write_text(source.replace('EVENT = "event"', 'EVENT = "slack"'),
                                  encoding="utf-8")
    found = offenders(tmp_path)
    assert found and "openfactory/product/door.py" in found[0] and "'slack'" in found[0], found


def test_an_allowed_file_is_not_a_free_pass(tmp_path):
    """The allow-list names STRINGS, not files: a new vendor-named value in `plugins.py` is caught
    like anywhere else — by the same walk the tree is held to."""
    tree = tmp_path / "openfactory"
    tree.mkdir()
    source = (PACKAGE / "plugins.py").read_text(encoding="utf-8")
    (tree / "plugins.py").write_text(source, encoding="utf-8")
    assert offenders(tmp_path) == [], "the allowed strings of the real file are not allowed"
    (tree / "plugins.py").write_text(source + '\nDEFAULT_CHANNEL = "slack"\n', encoding="utf-8")
    found = offenders(tmp_path)
    assert len(found) == 1 and "'slack'" in found[0], found
