"""What a template shows, a reader pastes — so every line of one must work on the CORE.

THE CHAT CUT MOVED THE CODE AND LEFT THE TEMPLATES BEHIND (pre-launch audit, 2026-08-26). Six
reader-facing surfaces still configured a chat channel that no longer exists in this tree, eight
lines from a Telegram block that had been updated correctly:

  · `docs/reference/configuration.md`'s registry example carried `channel_id: C0XXXXXXXXX` —
    a coordinate that SELECTS the chat kind, so the entry a stranger copies is refused with
    "unknown channel 'slack'" the moment its channel is built;
  · `deploy/registry.yaml.example` documented the same coordinates in its header;
  · `.env.compose.example` carried two live rows for variables the core reads nowhere, and
    `docker-compose.yml` forwarded the same two into the worker — a capability the file claimed
    and did not have;
  · the reference table said the core reads them and falls back to a null notifier. It reads
    neither, and the notifier is the panel's.

THREE PROPERTIES, EACH MEASURED RATHER THAN READ — and each widened on 2026-08-26, when a
reviewer walked through all three by hand.

  1. Every registry key a shipped file SHOWS — in its YAML or in the comments around it — still
     builds a channel on a core with no add-on row installed. That is the whole test: not "the
     word slack is absent", which the next vendor's name would walk straight past, but the
     paste itself, through the real code. Over EVERY tracked file that stays in the public tree,
     not over two named ones: the two-item list left `docs/configuration.md` shipping a copyable
     `product:` block with the retired chat spellings in it.

  2. No variable an add-on package's row DECLARES (`plugins.environment`, asked of the rows the
     packages under `addons/` register) is DOCUMENTED in the core's own environment templates —
     commented out or not, because a commented row in a template is an instruction a reader
     uncomments — or in its compose file. The names are derived from the packages, so a package
     that adds a variable tomorrow is covered tomorrow.

  3. And no core document's environment TABLE declares one either. That table is what an operator
     reads to find out what this deployment honours; the markdown row that said the core reads
     the chat variables was restored by hand and no test noticed.

The key spellings come from `ProjectRegistry._RENAMED` and `Project.model_fields`, never a list
written here: one chat coordinate is still a LIVE ALIAS (`slack_channel` → `channel_id`), and a
guard that hard-coded today's spellings would miss the one an operator's old file still uses.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import add_ons
import pytest
import vendor_addons
import yaml
from vendor_addons import install

from openfactory import plugins
from openfactory.adapters.channel.registry import build_channel
from openfactory.contracts.project import Project
from openfactory.registry import ProjectRegistry

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"

#: The templates a reader is told to copy, and the file the stack itself runs.
ENV_TEMPLATES = (".env.example", ".env.compose.example")
REGISTRY_EXAMPLE = "deploy/registry.yaml.example"
REGISTRY_REFERENCE = "docs/reference/configuration.md"

#: The suffixes of a file somebody reads and copies out of.
_COPYABLE = (".md", ".yaml", ".yml", ".example", ".toml", ".txt", ".cfg")


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True,
                         timeout=120)
    assert out.returncode == 0, out.stderr[:200]
    return [p for p in out.stdout.split("\0") if p]


def _stays_in_the_public_tree(rel: str) -> bool:
    """False for a path docs/STATUS.md's table removes from the export — the add-on packages'
    own documents are theirs to keep true, and they are the one place a chat coordinate is
    exactly right."""
    return not any(rel == path or (path.endswith("/") and rel.startswith(path))
                   for path in add_ons.excluded_paths())


# ── the spellings, derived ──────────────────────────────────────────────────────────────────────

def registry_keys() -> set[str]:
    """Every spelling a registry entry may use for a field of a project — the current names, the
    aliases the model still accepts, and the renamed keys the loader still reads."""
    names: set[str] = set(ProjectRegistry._RENAMED)
    for name, field in Project.model_fields.items():
        names.add(name)
        alias = field.validation_alias
        for choice in getattr(alias, "choices", None) or ([alias] if isinstance(alias, str) else []):
            names.add(str(choice))
    for target in ProjectRegistry._RENAMED.values():
        names.add(target.split(".", 1)[0])
    return names


def _documented_settings(text: str) -> list[tuple[int, str, object]]:
    """`(line number, key, value)` for every `key: value` a template SHOWS — inside its YAML and
    inside the comments, because a commented coordinate is an instruction like any other.

    Only keys the registry actually knows are returned: prose in a comment is not a setting."""
    known = registry_keys()
    found: list[tuple[int, str, object]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        bare = line.lstrip().lstrip("#").strip()
        match = re.match(r"^([a-z_][a-z0-9_]*)\s*:\s*(\S.*?)\s*$", bare)
        if not match or match.group(1) not in known:
            continue
        try:
            value = yaml.safe_load(match.group(2))
        except yaml.YAMLError:
            continue
        found.append((number, match.group(1), value))
    return found


def _first_project(text: str) -> dict:
    data = (yaml.safe_load(text) or {}).get("projects") or {}
    assert data, "the example declares no project at all"
    return dict(data[next(iter(data))])


def _yaml_blocks(markdown: str) -> list[str]:
    return re.findall(r"^```yaml\n(.*?)^```", markdown, re.M | re.S)


def _registry_documents(rel: str, text: str) -> list[str]:
    """The parts of `rel` that are a REGISTRY entry, as opposed to the other YAML a page shows.

    ONE SECTION OF `docs/configuration.md` SHOWS FOUR BLOCKS: the registry's `product:` entry, the
    source repository's `.openfactory/project.yaml`, the documentation repository's
    `.openfactory/product.yaml` and a bare `language:`. Only the first and the last are registry
    entries, and a line-by-line scan read `product: myapp` out of the third — the documentation
    repo naming its product — as if it were `Project.product`, and reported the page for a defect
    it does not have (measured while this walk was written).

    A chunk counts when it parses as a mapping whose top-level keys the registry knows: the file's
    own root (`projects:`) or fields of a project. A template is one chunk; a document is one per
    fenced block."""
    chunks = _yaml_blocks(text) if rel.endswith(".md") else [text]
    known = registry_keys() | {"projects"}
    documents = []
    for chunk in chunks:
        try:
            data = yaml.safe_load(chunk)
        except yaml.YAMLError:
            continue
        if isinstance(data, dict) and data and set(data) <= known:
            documents.append(chunk)
    return documents


def _registry_settings(rel: str, text: str) -> list[tuple[int, str, object]]:
    """`_documented_settings`, over the registry entries of `rel` alone, with the line numbers
    counted from the top of the FILE so a failure names a line somebody can open."""
    found: list[tuple[int, str, object]] = []
    for chunk in _registry_documents(rel, text):
        offset = text.count("\n", 0, text.index(chunk))
        found += [(offset + number, key, value)
                  for number, key, value in _documented_settings(chunk)]
    return found


@pytest.fixture
def core_only(monkeypatch):
    """A core with no add-on row served — what somebody who cloned the public tree runs."""
    install(monkeypatch, declared_rows=False)


# ── 1. the paste works ──────────────────────────────────────────────────────────────────────────

def test_the_shipped_registry_example_builds_its_channel_on_the_core(core_only):
    """The active YAML, through the real code."""
    project = Project(**_first_project((ROOT / REGISTRY_EXAMPLE).read_text()))
    assert type(build_channel(project)).__name__ == "PanelChannel"


def files_that_show_a_registry_setting() -> list[str]:
    """Every tracked file that STAYS in the public tree and shows a registry setting — derived
    over the whole tree, never a list.

    A TWO-ITEM LIST IS WHY THIS RULE HAD A HOLE. Parametrised over the registry example and the
    reference page, it said nothing about `docs/configuration.md`, whose product section shipped a
    copyable block carrying `slack_channel: C0ABCDEF` and `slack_admins: [U0123ABCD]` — the
    retired chat spellings, live aliases both. Pasted under `product:` on a panel deployment they
    resolve to `ProductConfig.channel_id`, and `channel_destination` then answers with a chat id
    where the project's own name belongs: the product surface addressing a channel nobody is in
    (audit, 2026-08-26). The blast radius is small and measured — 7 files, 22 settings on the day
    this was written — because a line only counts when its key is one `registry_keys()` derives
    AND it sits in a chunk `_registry_documents` reads as a registry entry."""
    return sorted(rel for rel in _tracked()
                  if rel.endswith(_COPYABLE) and _stays_in_the_public_tree(rel)
                  and _registry_settings(rel, (ROOT / rel).read_text()))


@pytest.mark.parametrize("rel", files_that_show_a_registry_setting())
def test_every_registry_setting_a_shipped_file_shows_still_builds_a_channel(core_only, rel):
    """Including the ones in comments. A template's header is where an operator looks for the
    key they do not have yet, so a coordinate documented there is a coordinate they will paste.

    Applied to the project the shipped registry example declares: a document showing one line of
    an entry is showing a line somebody pastes INTO an entry, and the platform's own example is
    what that entry looks like."""
    base = _first_project((ROOT / REGISTRY_EXAMPLE).read_text())
    settings = _registry_settings(rel, (ROOT / rel).read_text())

    refused = []
    for number, key, value in settings:
        try:
            build_channel(Project(**{**base, key: value}))
        except Exception as exc:  # noqa: BLE001 — any refusal is the failure being measured
            refused.append(f"{rel}:{number}  {key}: {value!r} → {exc}")

    assert not refused, (
        "these lines are shown to a reader and are refused on a core with no add-on installed — "
        "the entry they paste does not load, and the refusal names a package they do not have:\n  "
        + "\n  ".join(refused))


def test_the_walk_over_shipped_files_still_has_the_two_it_was_written_for():
    """The floor, and it names the two the rule started as: a derived walk that quietly stops
    matching parametrises over nothing and passes in silence."""
    files = files_that_show_a_registry_setting()
    assert len(files) >= 5, f"only {files} show a registry setting — this measures nothing"
    for rel in (REGISTRY_EXAMPLE, REGISTRY_REFERENCE):
        assert rel in files, f"{rel} shows no registry setting the walk can see — it is unjudged"


def test_the_guard_can_SEE_a_coordinate_that_selects_an_absent_kind(core_only):
    """Verify the verifier: the line that shipped, under BOTH spellings — the current one and
    the alias an old registry still uses — since the alias is the half a hard-coded list loses."""
    base = _first_project((ROOT / REGISTRY_EXAMPLE).read_text())
    for spelling in ("channel_id", "slack_channel"):
        assert spelling in registry_keys(), f"{spelling} is not derived from the model at all"
        with pytest.raises(ValueError) as err:
            build_channel(Project(**{**base, spelling: "C0XXXXXXXXX"}))
        assert "unknown channel 'slack'" in str(err.value), str(err.value)


def test_a_chat_coordinate_is_NOT_refused_where_the_package_is_installed(monkeypatch):
    """The positive twin, and the reason the fix is a template change rather than a code change:
    the same line an operator with the package pastes is exactly right for them."""
    vendor_addons.require("channel.slack")
    install(monkeypatch, "channel.slack")
    base = _first_project((ROOT / REGISTRY_EXAMPLE).read_text())
    built = build_channel(Project(**{**base, "channel_id": "C0XXXXXXXXX"}))
    assert type(built).__name__ == "SlackChannel"


# ── 2. the core's templates name no add-on's variable ───────────────────────────────────────────

def package_variables() -> dict[str, str]:
    """`{variable: entry point}` — every environment variable the rows the packages under
    `addons/` declare say they read. Asked of the rows themselves (`plugins.environment`), so
    this file keeps no copy of any vendor's variable names."""
    vendor_addons.require()
    found: dict[str, str] = {}
    for point, target in vendor_addons.declared().items():
        builder = vendor_addons.Point(point, target).load()
        for name in plugins.environment(builder):
            found[name] = point
    return found


def _active_rows(text: str) -> set[str]:
    """The variables a template really SETS — used only by the positive twin, which has to know
    that the negative rule below was not satisfied by emptying the file."""
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, re.M))


def _documented_rows(text: str) -> set[str]:
    """Every variable a template DOCUMENTS — commented out or not.

    A COMMENTED ROW IN A TEMPLATE IS AN INSTRUCTION. Half of `.env.example` is commented on
    purpose: `# CLAUDE_CODE_OAUTH_TOKEN=`, `# OPENFACTORY_BOT_TOKEN=`, the whole optional block.
    A reader uncomments the line they need — that is what the file is for — so a row is documented
    whether or not its `#` is there. Reading only the active rows made this rule blind in exactly
    the place the chat cut left its debris: re-adding `# SLACK_BOT_TOKEN=xoxb-…` to the chat block
    left the gate green (reviewer's cut, 2026-08-26), and the operator who uncomments it gets a
    variable this core reads nowhere.

    `export` is allowed in front because a commented row a reader is meant to paste into a shell
    carries it, and a scan that stopped at the keyword would be blind to exactly that row."""
    return set(re.findall(r"^\s*(?:#\s*)*(?:export\s+)?([A-Z][A-Z0-9_]*)=", text, re.M))


def _service_environment(name: str) -> dict:
    return yaml.safe_load(COMPOSE.read_text())["services"][name].get("environment") or {}


@pytest.mark.parametrize("rel", ENV_TEMPLATES)
def test_no_environment_template_DOCUMENTS_a_variable_only_an_add_on_reads(rel):
    declared = package_variables()
    assert declared, "no package row declares a variable — this measures nothing"
    rows = _documented_rows((ROOT / rel).read_text())
    assert rows, f"{rel} documents nothing at all"

    offenders = {name: declared[name] for name in sorted(rows) if name in declared}
    assert not offenders, (
        f"{rel} documents variables the core reads nowhere — they belong to the rows named beside "
        f"them, and a template that carries them tells a reader the core has a capability it "
        f"does not: {offenders}")


def test_the_row_scan_reads_a_commented_instruction_the_way_a_reader_does():
    """Verify the verifier. The commented block is the half `_active_rows` could not see, and it
    is the half the chat cut left behind."""
    planted = ("ACTIVE=1\n"
               "# COMMENTED=\n"
               "#   SPACED=xoxb-secret   # with a remark\n"
               "# export EXPORTED=xoxb-secret\n"
               "# a sentence that says CHATTY= mid-line is prose\n"
               "  INDENTED=2\n")
    assert _active_rows(planted) == {"ACTIVE"}
    assert _documented_rows(planted) == {"ACTIVE", "COMMENTED", "SPACED", "EXPORTED", "INDENTED"}


@pytest.mark.parametrize("service", ["worker", "panel"])
def test_the_compose_file_forwards_no_add_on_variable_by_name(service):
    declared = package_variables()
    named = _service_environment(service)
    assert named, f"the {service} service sets no environment at all"

    offenders = {name: declared[name] for name in sorted(named) if name in declared}
    assert not offenders, (
        f"docker-compose.yml names an add-on package's variables in the {service} service's "
        f"environment: {offenders}. The core reads none of them, and a deployment that installs "
        f"the package delivers them through `.env.compose`, which the env_file forwards whole.")


def test_what_an_installed_package_needs_still_reaches_the_worker():
    """The positive twin of the two above, and the reason removing those rows costs nothing: the
    path an add-on's variable takes is the same one every client-invented `token_env` takes."""
    compose = yaml.safe_load(COMPOSE.read_text())
    for service in ("worker", "panel"):
        entries = compose["services"][service].get("env_file") or []
        paths = [e["path"] if isinstance(e, dict) else e for e in entries]
        assert ".env.compose" in paths, (
            f"{service} no longer reads .env.compose, so a variable removed from `environment:` "
            f"is now unreachable — that is the trade this pair of guards depends on")


def test_the_core_templates_still_carry_the_core_variables():
    """…and the negative rule is not satisfied by an empty file: what the CORE reads is still
    there to fill in."""
    for rel in ENV_TEMPLATES:
        rows = _active_rows((ROOT / rel).read_text())
        assert len(rows) >= 3, f"{rel} now sets almost nothing: {rows}"
    worker = _service_environment("worker")
    assert "OPENFACTORY_SANDBOX" in worker and "OPENFACTORY_REGISTRY" in worker, worker


# ── 3. and no core document's environment TABLE declares one either ────────────────────────────
#
# A MARKDOWN TABLE IS READ BY NOTHING, which is how the reference page's chat rows survived the
# chat cut and how they came back: restoring the old row in `docs/reference/configuration.md`'s
# environment table left the whole gate green (reviewer's cut, 2026-08-26). That table is where an
# operator goes to find out what this deployment reads — a row there is a promise the core honours
# the variable, and for a variable only an add-on's row reads, the promise is false in the
# direction that costs most: the operator sets it, nothing happens, and nothing says why.
#
# The names are DERIVED from the rows the packages declare (`plugins.environment`), never listed
# here, so a package that adds a variable tomorrow is covered tomorrow. What is forbidden is the
# DECLARING cell — the left-hand column, where a table says "this is a variable" — and not the
# prose beside it: `OPENFACTORY_NOTIFIER_FALLBACK`'s own row names the two variables its
# `telegram` kind reads in order to say the core reads neither, which is the sentence a reader
# needs rather than one to forbid.

#: An environment variable as a table declares one.
_VARIABLE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")


def _table_declarations(text: str) -> dict[str, int]:
    """`variable → line number` for every environment-variable-shaped name in the FIRST cell of a
    markdown table row — the column that says what the row is about."""
    found: dict[str, int] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        row = line.strip()
        if not (row.startswith("|") and row.endswith("|")):
            continue
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        if len(cells) < 2:
            continue
        for name in _VARIABLE.findall(cells[0]):
            found.setdefault(name, number)
    return found


def core_documents() -> list[str]:
    """Every tracked document that STAYS in the public tree — the pages somebody who cloned it is
    handed. Decision records are history on the same terms the rest of this suite gives them."""
    return sorted(rel for rel in _tracked()
                  if rel.endswith(".md") and _stays_in_the_public_tree(rel)
                  and not rel.startswith("docs/adr/"))


def test_no_core_documents_environment_table_declares_an_add_on_packages_variable():
    declared = package_variables()
    assert declared, "no package row declares a variable — this measures nothing"

    offenders, seen = [], 0
    for rel in core_documents():
        table = _table_declarations((ROOT / rel).read_text())
        seen += len(table)
        offenders += [f"{rel}:{line}  {name} (declared by the {declared[name]} row)"
                      for name, line in sorted(table.items()) if name in declared]

    assert seen >= 20, (
        f"the walk found {seen} variable-shaped names in table rows across {len(core_documents())} "
        f"documents — it has stopped reading the tables it was written for")
    assert not offenders, (
        "these table rows tell a reader the core reads a variable that only an add-on package's "
        "row reads — the operator sets it, the deployment does not change, and the page they "
        "checked said it would:\n  " + "\n  ".join(offenders))


def test_a_core_document_still_declares_the_CORES_own_variables():
    """The positive twin: the rule above is satisfied by a tree with no environment table at all,
    which is the same operator with nowhere to look. What the core reads is still written down."""
    from openfactory import environ

    ours = {name for rel in core_documents()
            for name in _table_declarations((ROOT / rel).read_text())
            if name.startswith(environ.ENV_PREFIX)}
    reads = environ.names_read()
    assert ours & reads, (
        f"no document's environment table names a variable the core actually reads — it reads "
        f"{len(reads)} of them, and the tables declare {sorted(ours)[:5]}")


def test_the_table_scan_can_SEE_a_declaring_row_and_leaves_the_prose_beside_it_alone():
    """Verify the verifier, on the shape the reference page uses — and on a name built from the
    derived set, so this file spells no vendor's variable of its own."""
    name = next(iter(package_variables()))
    planted = (f"| | |\n|---|---|\n"
               f"| `{name}` | the chat bot token |\n"
               f"| `OPENFACTORY_NOTIFIER_FALLBACK` | the fallback; `telegram` reads {name} |\n"
               f"a paragraph naming {name} outside any table\n")
    table = _table_declarations(planted)
    assert name in table and table[name] == 3, table
    assert "OPENFACTORY_NOTIFIER_FALLBACK" in table
    assert set(_table_declarations(f"| `OPENFACTORY_X` | reads {name} |\n")) == {"OPENFACTORY_X"}


# ── 4. and a count written beside a derived rule is a second copy of it ────────────────────────

#: Number words, so a sentence's own arithmetic can be checked against the tree's.
_CARDINALS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
              "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _alias_sentence(text: str) -> str:
    """The ASIDE of a template's header that states the alias rule — the parenthesis carrying a
    `slack_*`-shaped wildcard for the retired spellings.

    The parenthesis and not the sentence around it: that sentence runs on past the rule ("a
    project carrying one is refused by name"), and a number in a later clause is not a count of
    the aliases. The claim being measured is the one made where they are listed."""
    flat = re.sub(r"\s+", " ", re.sub(r"^\s*#\s?", "", text, flags=re.M))
    for aside in re.findall(r"\(([^()]*)\)", flat):
        if re.search(r"`[a-z_]+\*`", aside):
            return aside
    return ""


def test_every_renamed_registry_key_is_still_accepted_under_its_old_spelling():
    """The measured fact the sentence below is held to. All four, not two."""
    base = _first_project((ROOT / REGISTRY_EXAMPLE).read_text())
    for old, new in ProjectRegistry._RENAMED.items():
        value = ["U0123ABCD"] if new.split(".", 1)[0] == "admins" else "VALUE"
        project = Project(**{**base, old: value})
        head = new.split(".", 1)[0]
        assert getattr(project, head, None), (
            f"`{old}` is in ProjectRegistry._RENAMED and the model did not carry it to `{new}` — "
            f"an operator's old file loses the setting silently")


def test_the_registry_examples_alias_sentence_counts_what_the_loader_renames():
    """`deploy/registry.yaml.example`'s header said the chat coordinates' "first two [are] still
    accepted under their old spellings". MEASURED, by the test above: all four are. The table it
    describes DERIVES; the prose beside it hard-coded, and hard-coded the wrong number — the
    two-facts-in-one-value class, in a file an operator copies.

    So any cardinal in that sentence has to be the number of aliases there really are. Saying it
    without a number — "all of them" — is the shape that cannot go stale, and is what it says."""
    sentence = _alias_sentence((ROOT / REGISTRY_EXAMPLE).read_text())
    assert sentence, (
        f"{REGISTRY_EXAMPLE}'s header no longer states the retired-spelling rule as a family "
        f"(`slack_*`) — an operator with an old file has nowhere to read that it still loads")
    live = len(ProjectRegistry._RENAMED)
    wrong = [word for word, number in _CARDINALS.items()
             if re.search(rf"\b{word}\b", sentence, re.I) and number != live]
    assert not wrong, (
        f"{REGISTRY_EXAMPLE}'s alias sentence says {wrong} and the loader renames {live} keys "
        f"({sorted(ProjectRegistry._RENAMED)}) — a reader with the other two in their file is "
        f"told those are gone. Say it without a number: the rule is about all of them.\n"
        f"  {sentence.strip()[:200]}")


def test_the_alias_sentence_scan_can_SEE_the_count_that_was_wrong():
    """Verify the verifier, on the sentence that shipped and on the one that replaced it."""
    was_here = ("#   (`channel_id`, `admins` — the first two\n"
                "#   still accepted under their old `slack_*` spellings) select that kind\n")
    now = ("#   (`channel_id`, `admins` — all of them\n"
           "#   still accepted under their old `slack_*` spellings) select that kind\n")
    assert "two" in _alias_sentence(was_here) and _alias_sentence(now)
    assert not any(re.search(rf"\b{word}\b", _alias_sentence(now), re.I) for word in _CARDINALS)
    assert _alias_sentence("a header with no wildcard at all") == ""
