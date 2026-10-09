"""The developer's guide runs, and `openfactory explain` says what the job does (#81).

A guide about the surface that is meant to change most often rots fastest, so this one is held to
the rule the rest of the tree is: every command it prints is run here and its output compared
with the page, and every path it names in backticks exists.

Four properties are load-bearing and each has a test that fails if it is lost:

  1. THE PAGE IS WHAT THE PLATFORM PRINTS. Every `$ openfactory` block of `docs/developer-guide.md`
     is run with CliRunner from the repository's root and must equal the block under it.
  2. THE EXPLANATION IS THE JOB'S OWN. The texts the trace carries, in order, ARE the context's
     guidelines and constraints — with no profile, under `prototype`, under `regulated`, on the
     worked example, and with an operator directory. A trace that drifted from `build_context`
     would explain a prompt nobody is given.
  3. A REFUSAL IS ONE SENTENCE, in the reader's language, with a non-zero exit and no traceback.
  4. IT WRITES NOTHING AND CALLS NOTHING: the checkout and HOME are byte-identical after a run, no
     harness, forge, socket or subprocess is reached, no card moves, and the fenced brief — whose
     marker is random — is never printed.
"""

from __future__ import annotations

import hashlib
import re
import shlex
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from openfactory import cli
from openfactory.contracts import Manifest
from openfactory.orchestrator import context as ctx
from openfactory.orchestrator import explain as ex
from openfactory.orchestrator import operator_guidelines
from openfactory.policy import profiles as prof

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "developer-guide.md"
EXAMPLE = ROOT / "docs" / "examples" / "profiled-project"
OPERATOR_EXAMPLE = ROOT / "docs" / "examples" / "operator-guidelines"

#: A console block's command: optional `NAME=value` assignments, then `openfactory …`.
_ASSIGNMENT = re.compile(r"^[A-Z][A-Z0-9_]*=")
#: A fenced block, its info string and its body.
_FENCE = re.compile(r"^```([^\n]*)\n(.*?)^```\s*$", re.M | re.S)


def _blocks(text: str) -> list[tuple[str, str]]:
    return [(m.group(1).strip(), m.group(2)) for m in _FENCE.finditer(text)]


def runnable_blocks() -> list[tuple[str, str]]:
    """`(command line, expected output)` for every console block whose command is `openfactory`,
    paired with the fenced block that follows it."""
    blocks = _blocks(GUIDE.read_text(encoding="utf-8"))
    pairs = []
    for i, (info, body) in enumerate(blocks):
        line = body.strip()
        if info != "console" or not line.startswith("$ "):
            continue
        words = shlex.split(line[2:])
        command = [w for w in words if not _ASSIGNMENT.match(w)]
        if not command or command[0] != "openfactory":
            continue
        assert i + 1 < len(blocks), f"`{line}` has no block under it to compare with"
        pairs.append((line[2:], blocks[i + 1][1]))
    return pairs


def run(command_line: str, monkeypatch) -> tuple[int, str]:
    """Run one guide command the way a reader at the repository's root would — with no `.env` of
    this machine's, and the operator's directory exactly as the line sets it."""
    words = shlex.split(command_line)
    env = dict(w.split("=", 1) for w in words if _ASSIGNMENT.match(w))
    args = [w for w in words if not _ASSIGNMENT.match(w)][1:]
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(cli, "_load_environment", lambda: None)
    monkeypatch.delenv(operator_guidelines.ENV_VAR, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    result = CliRunner().invoke(cli.app, args)
    assert result.exception is None or isinstance(result.exception, SystemExit), (
        f"`{command_line}` raised {result.exception!r}")
    return result.exit_code, result.output


# ── 1. the page is what the platform prints ──────────────────────────────────────────────────────

@pytest.mark.parametrize("command_line,expected", runnable_blocks(),
                         ids=[c for c, _ in runnable_blocks()])
def test_every_command_in_the_guide_prints_the_block_under_it(command_line, expected,
                                                               monkeypatch):
    _, output = run(command_line, monkeypatch)
    assert output.rstrip("\n") == expected.rstrip("\n"), (
        f"`{command_line}` no longer prints what docs/developer-guide.md shows. Run it from the "
        f"repository's root and paste its output under the command:\n\n{output}")


def test_the_guide_runs_enough_to_be_a_guide():
    """A parser gone blind would pass the test above on zero blocks."""
    pairs = runnable_blocks()
    assert len(pairs) >= 3, [c for c, _ in pairs]
    assert any(operator_guidelines.ENV_VAR in c for c, _ in pairs), (
        "no block runs with an operator directory, the tier a reader cannot see otherwise")
    assert any("--language pt-BR" in c for c, _ in pairs)


def _backticked_paths(text: str) -> list[str]:
    """Every inline code span that names a path: a slash, no spaces, no placeholder."""
    prose = _FENCE.sub("", text)
    spans = re.findall(r"`([^`\n]+)`", prose)
    return [s for s in spans if "/" in s and not re.search(r"[\s<>${}=:]", s)
            and not s.startswith(("-", "http"))]


def test_every_path_the_guide_names_exists():
    """A path resolves from the repository's root — or, for the checkout-relative conventions the
    guide teaches (`.openfactory/profiles/`), from the worked example it describes."""
    paths = _backticked_paths(GUIDE.read_text(encoding="utf-8"))
    assert len(paths) >= 10, paths
    missing = []
    for path in paths:
        found = any((bool(list(base.glob(path))) if "*" in path else (base / path).exists())
                    for base in (ROOT, EXAMPLE))
        if not found:
            missing.append(path)
    assert not missing, f"docs/developer-guide.md names paths that do not exist: {missing}"


def test_the_backtick_scan_sees_what_it_guards():
    found = _backticked_paths("see `openfactory/cli.py`, `docs.guidelines`, `$X/reference/`, "
                              "`components.<n>.guidelines`, `a b/c`\n```\n`in/a/block`\n```\n")
    assert found == ["openfactory/cli.py"]


def test_the_guide_is_linked_from_the_documentation_it_belongs_to():
    for page in (ROOT / "docs" / "README.md", ROOT / "CONTRIBUTING.md"):
        assert "developer-guide.md" in page.read_text(encoding="utf-8"), page
    assert "openfactory explain" in (ROOT / "docs" / "reference" / "cli.md").read_text()


# ── 2. the explanation is the job's own ──────────────────────────────────────────────────────────

def _project(tmp_path: Path, manifest: dict, files: dict[str, str] | None = None) -> Path:
    repo = tmp_path / "repo"
    (repo / ".openfactory").mkdir(parents=True, exist_ok=True)
    (repo / ".openfactory" / "project.yaml").write_text(yaml.safe_dump(manifest))
    for rel, body in (files or {}).items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(body)
    return repo


def _traced_context(repo: Path):
    manifest = Manifest.model_validate(
        yaml.safe_load((repo / ".openfactory" / "project.yaml").read_text()))
    profile = prof.resolve_profile(manifest.profile, project_dir=repo)
    trace: list[ctx.Traced] = []
    traced = ctx.build_context(manifest, repo, ctx._BLANK_CARD, knowledge_map="",
                               profile=profile, trace=trace)
    plain = ctx.build_context(manifest, repo, ctx._BLANK_CARD, knowledge_map="", profile=profile)
    return trace, traced, plain


_HOUSE = {"docs": {"constraints": "docs/adr/**",
                   "guidelines": ["HOUSE.md", "../outside.md", "NOT-THERE.md"]},
          "components": {"api": {"path": "api/**", "stack": "python",
                                 "guidelines": ["api/STYLE.md"]}}}
_HOUSE_FILES = {"HOUSE.md": "HOUSE RULE", "api/STYLE.md": "API STYLE",
                "docs/adr/0001-a.md": "# ADR A", "docs/adr/0002-b.md": "# ADR B"}


@pytest.mark.parametrize("case", ["no profile", "prototype", "regulated", "worked example",
                                  "operator directory"])
def test_the_trace_is_the_context_the_job_builds(case, tmp_path, monkeypatch):
    monkeypatch.delenv(operator_guidelines.ENV_VAR, raising=False)
    if case == "worked example":
        repo = EXAMPLE
    elif case == "operator directory":
        operator = tmp_path / "operator"
        (operator / "reference").mkdir(parents=True)
        (operator / "security.md").write_text("CENTRAL SECURITY")
        (operator / "style.md").write_text("CENTRAL STYLE")
        (operator / "reference" / "long.md").write_text("# A long standard")
        monkeypatch.setenv(operator_guidelines.ENV_VAR, str(operator))
        repo = _project(tmp_path, {**_HOUSE, "profile": "local"}, {
            **_HOUSE_FILES, "OURS.md": "OUR SECURITY",
            ".openfactory/profiles/local.yaml": yaml.safe_dump({
                "name": "local", "extends": "prototype",
                "guidelines": {"waive": ["style.md", "nope.md"],
                               "replace": {"security.md": "OURS.md",
                                           "engineering.md": "GONE.md"},
                               "extend": ["HOUSE.md", "ALSO-GONE.md"]}})})
    else:
        manifest = dict(_HOUSE)
        if case != "no profile":
            manifest["profile"] = case
        repo = _project(tmp_path, manifest, _HOUSE_FILES)

    trace, traced, plain = _traced_context(repo)

    guidelines = [t.text for t in trace if t.text is not None and t.layer != "docs.constraints"]
    constraints = [t.text for t in trace if t.text is not None and t.layer == "docs.constraints"]
    assert guidelines == traced.guidelines == plain.guidelines
    assert constraints == traced.constraints == plain.constraints
    assert traced.doc_index == plain.doc_index, "a trace changed what the job is given"
    kinds = [t.layer == "docs.constraints" for t in trace if t.text is not None]
    assert kinds == sorted(kinds, reverse=True), "the constraints lead, as the brief has them"


def test_every_fate_is_traced_where_it_is_decided(tmp_path, monkeypatch):
    """The operator-directory fixture exercises every branch; each row says what the job did."""
    operator = tmp_path / "operator"
    operator.mkdir()
    (operator / "security.md").write_text("CENTRAL SECURITY")
    (operator / "style.md").write_text("CENTRAL STYLE")
    monkeypatch.setenv(operator_guidelines.ENV_VAR, str(operator))
    repo = _project(tmp_path, {**_HOUSE, "profile": "local"}, {
        **_HOUSE_FILES, "OURS.md": "OUR SECURITY",
        ".openfactory/profiles/local.yaml": yaml.safe_dump({
            "name": "local", "extends": "prototype",
            "guidelines": {"waive": ["style.md", "nope.md"],
                           "replace": {"security.md": "OURS.md", "engineering.md": "GONE.md"},
                           "extend": ["HOUSE.md", "ALSO-GONE.md", "../out.md"]}})})
    trace, _, _ = _traced_context(repo)
    rows = {(t.layer, t.name): (t.fate, t.detail) for t in trace}

    assert rows[(ctx.FRAMEWORK, "tdd.md")] == (ctx.WAIVED, "prototype → local")
    assert rows[(ctx.FRAMEWORK, "engineering.md")] == (ctx.KEPT, "GONE.md")
    assert rows[(ctx.OPERATOR, "security.md")] == (ctx.REPLACED, "OURS.md")
    assert rows[(ctx.OPERATOR, "style.md")] == (ctx.WAIVED, "prototype → local")
    assert rows[(ctx.PROFILE, "nope.md")] == (ctx.MISSING, "waive")
    assert rows[(ctx.PROFILE, "HOUSE.md")] == (ctx.KEPT, "")
    assert rows[(ctx.PROFILE, "ALSO-GONE.md")] == (ctx.MISSING, "")
    assert rows[(ctx.PROFILE, "../out.md")] == (ctx.REFUSED, ctx.OUTSIDE)
    assert rows[("docs.guidelines", "HOUSE.md")] == (ctx.KEPT, "")
    assert rows[("docs.guidelines", "../outside.md")] == (ctx.REFUSED, ctx.OUTSIDE)
    assert rows[("docs.guidelines", "NOT-THERE.md")] == (ctx.MISSING, "")
    assert rows[("components.api.guidelines", "api/STYLE.md")] == (ctx.KEPT, "")
    assert rows[("docs.constraints", "docs/adr/0001-a.md")] == (ctx.KEPT, "")


def test_a_directory_the_operator_named_and_did_not_fill_is_a_row(tmp_path, monkeypatch):
    repo = _project(tmp_path, {"docs": {"constraints": "nowhere/**"}})
    monkeypatch.setenv(operator_guidelines.ENV_VAR, str(tmp_path / "absent"))
    trace, _, _ = _traced_context(repo)
    assert (ctx.OPERATOR, ctx.MISSING) in {(t.layer, t.fate) for t in trace}
    assert ("docs.constraints", "nowhere/**", ctx.MISSING) in {
        (t.layer, t.name, t.fate) for t in trace}
    (tmp_path / "empty").mkdir()
    monkeypatch.setenv(operator_guidelines.ENV_VAR, str(tmp_path / "empty"))
    trace, _, _ = _traced_context(repo)
    assert (ctx.OPERATOR, ctx.EMPTY) in {(t.layer, t.fate) for t in trace}


def test_explain_prints_one_line_per_block_in_the_order_the_job_inlines_them(monkeypatch):
    code, output = run("openfactory explain docs/examples/profiled-project", monkeypatch)
    assert code == 0
    rows = [line.split()[0:2] for line in output.splitlines() if line.startswith("  ")]
    firsts = [" ".join(r) if r[0] == "role" else r[0] for r in rows]
    order = ["role prompt", "role prompt", "docs.constraints", "framework", "framework",
             "docs.guidelines", "index", "knowledge"]
    assert [f for f in firsts if f in order] == order, output
    assert "openfactory/org_defaults/roles/planner.md" in output
    assert "waived by prototype → house-style" in output
    assert "replaced by docs/engineering.md" in output


def test_the_role_prompt_names_the_one_layer_it_comes_from(monkeypatch, tmp_path):
    from openfactory.adapters.agent import registry, roles
    from openfactory.adapters.agent.roles import RoleSpec

    kind, path = roles.role_prompt_source("planner")
    assert kind == roles.SHIPPED and path.read_text() == roles.role_prompt("planner")
    spec = RoleSpec(name="qa", prompt="QA PROMPT", harness_env="ACME_QA_HARNESS",
                    model_env="ACME_QA_MODEL", human_facing=True)
    monkeypatch.setattr(registry, "addon_role", lambda role: spec if role == "qa" else None)
    assert roles.role_prompt_source("qa") == (roles.ADD_ON, None)
    assert roles.role_prompt("qa") == "QA PROMPT"
    assert roles.role_prompt_source("nobody")[0] == roles.NOWHERE


def test_full_prints_the_texts_and_never_the_brief(monkeypatch):
    code, output = run("openfactory explain docs/examples/profiled-project --full", monkeypatch)
    assert code == 0
    assert "Amounts are integer cents everywhere" in output     # the house rules, inlined
    assert "Small changes, each one reviewable" in output       # the replacement, inlined
    assert "<<<data" not in output and "<<<end data" not in output
    assert "How to read this brief" not in output
    _, short = run("openfactory explain docs/examples/profiled-project", monkeypatch)
    assert "Amounts are integer cents everywhere" not in short


# ── 3. a refusal is one sentence ─────────────────────────────────────────────────────────────────

def _one_sentence(output: str) -> bool:
    text = output.strip()
    return "\n" not in text and "Traceback" not in text and not re.search(r"[.!?]\s+[A-Z]", text)


@pytest.mark.parametrize("language", ["en", "pt-BR"])
def test_each_refusal_is_one_sentence_with_a_non_zero_exit(language, tmp_path, monkeypatch):
    bare = tmp_path / "bare"
    bare.mkdir()
    typo = _project(tmp_path, {"profile": "zzz-typo"})
    said = {}
    for case, target in (("no manifest", str(bare)), ("profile", str(typo)),
                         ("url", "https://github.com/acme/shop"),
                         ("not a directory", str(tmp_path / "nowhere"))):
        code, output = run(f"openfactory explain {shlex.quote(target)} --language {language}",
                           monkeypatch)
        assert code == 1, (case, output)
        assert _one_sentence(output), (case, output)
        said[case] = output
    looked = [str(typo / prof.PROJECT_PROFILES_SUBDIR / "zzz-typo.yaml"),
              "openfactory/org_defaults/profiles/zzz-typo.yaml"]
    assert all(p in said["profile"] for p in looked), said["profile"]
    assert "zzz-typo" in said["profile"]
    english = {"no manifest": "has no manifest", "profile": "no such profile exists",
               "url": "is an address", "not a directory": "is not a directory"}
    portuguese = {"no manifest": "não tem manifesto", "profile": "esse perfil não existe",
                  "url": "é um endereço", "not a directory": "não é um diretório"}
    for case, output in said.items():
        assert (english if language == "en" else portuguese)[case] in output, (case, output)


def test_a_language_nobody_wrote_is_refused(monkeypatch):
    code, output = run("openfactory explain docs/examples/profiled-project --language fr",
                       monkeypatch)
    assert code == 1 and _one_sentence(output) and "pt-BR" in output


def test_a_manifest_that_does_not_load_is_one_sentence(tmp_path, monkeypatch):
    repo = _project(tmp_path, {"docs": {"guidelines": "not-a-list"}, "nonsense": 1})
    code, output = run(f"openfactory explain {repo}", monkeypatch)
    assert code == 1 and _one_sentence(output), output


# ── pt-BR: every label, every refusal ────────────────────────────────────────────────────────────

def test_every_entry_of_the_catalogue_is_written_in_both_languages():
    same_by_design = {"layer.framework"}       # the word is the same in both
    for key, entry in ex.SAY.items():
        assert set(entry) == set(ex.LANGUAGES), key
        if key not in same_by_design:
            assert entry["en"] != entry["pt-BR"], f"{key} is not translated"


def _fragments(template: str) -> list[str]:
    """The fixed words of an English template — what must not appear in a Portuguese run."""
    pieces = re.split(r"\{[^}]*\}|`[^`]*`|\(ADR-\d+\)", template)
    return [p.strip(" —,.:;()") for p in pieces if len(p.strip(" —,.:;()")) >= 8]


def test_a_portuguese_run_prints_no_english_label(tmp_path, monkeypatch):
    central = tmp_path / "central"       # not a word the catalogue's English uses
    (central / "reference").mkdir(parents=True)
    (central / "security.md").write_text("CENTRAL")
    (central / "reference" / "long.md").write_text("# long")
    repo = _project(tmp_path, {**_HOUSE, "profile": "local",
                               "docs": {**_HOUSE["docs"], "architecture": "arch/**"}}, {
        **_HOUSE_FILES, "OURS.md": "OURS",
        ".openfactory/profiles/local.yaml": yaml.safe_dump({
            "name": "local", "extends": "prototype",
            "guidelines": {"waive": ["nope.md"], "replace": {"security.md": "OURS.md",
                                                             "engineering.md": "GONE.md"},
                           "extend": ["HOUSE.md", "GONE-TOO.md"]}})})
    _, output = run(f"{operator_guidelines.ENV_VAR}={central} openfactory explain {repo} "
                    f"--language pt-BR", monkeypatch)
    labels = output.split("O log do job diz")[0]      # the log quotes the job's own English lines
    for key, entry in ex.SAY.items():
        for fragment in _fragments(entry["en"]):
            if fragment not in entry["pt-BR"]:
                assert fragment not in labels, f"{key}: {fragment!r} printed in a pt-BR run"
    for word in ("mantido", "dispensado por", "substituído por", "recusado", "ausente",
                 "prompt do papel", "documento(s)", "O log do job diz"):
        assert word in output, word


# ── 4. it writes nothing and calls nothing ───────────────────────────────────────────────────────

def _snapshot(*roots: Path) -> dict[str, str]:
    out = {}
    for root in roots:
        for p in sorted(root.rglob("*")):
            key = str(p)
            out[key] = (hashlib.sha256(p.read_bytes()).hexdigest() + str(p.stat().st_mtime_ns)
                        if p.is_file() else "dir")
    return out


def test_explain_writes_nothing_and_calls_nothing(tmp_path, monkeypatch):
    import socket
    import subprocess

    from openfactory.adapters.agent import registry
    from openfactory.lifecycle import card, executor

    checkout = tmp_path / "profiled-project"
    shutil.copytree(EXAMPLE, checkout)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    def _forbidden(*_a, **_k):
        raise AssertionError("explain reached something it must never call")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    monkeypatch.setattr(registry, "build_executor", _forbidden)
    monkeypatch.setattr(card, "transition", _forbidden)
    monkeypatch.setattr(executor, "apply", _forbidden)
    monkeypatch.setattr(ctx, "load_agent_knowledge", _forbidden)

    before = _snapshot(checkout, home)
    code, output = run(f"openfactory explain {checkout} --full", monkeypatch)
    assert code == 0, output
    assert _snapshot(checkout, home) == before, "explain wrote into the checkout or HOME"
