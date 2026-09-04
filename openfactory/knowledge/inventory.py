"""The structural inventory of a source repository — every file, its kind, and why (OKF §6.1).

THE ONLY ADMISSIBLE ANSWER TO "WHAT IS IN THIS REPOSITORY". A bundle's coverage table divides
concepts by *what exists*, and until now the denominator was the module map — modules, not files.
A module row that says "5 of 412 described" cannot say which files were never asked about, and
the pilot that produced the reference format showed why that matters: a convention glob over
`Functions/**/*.cs` returned fifteen files that were 100 % commented out and missed the sixty-four
live entry points beside them. An exhaustive walk with a COUNTED remainder is loudly incomplete
instead of quietly wrong — a file no rule places becomes `unclassified` and is a row, a directory
the walk could not open is named, a walk that hit its ceiling says so.

THE SAME WALK AS THE SURVEY, on purpose. `onboarding/context._collect_files` is the walk the module
map is built from; the inventory reuses it rather than owning a second one, so the two cannot
describe two different repositories — the survey's own C-49 lesson (an unread stack reading as an
absent one) would come straight back the day their pruning rules drifted apart.

KINDS ARE GENERIC AND THE SET IS OPEN. The reference taxonomy names one company's stack
(`serverless-function`, `activity-task`, `ui-webpart`); what a kind AUTHORISES is that company's
policy and never reaches the core (the fifth port decision). What is generic is the MECHANISM: an
ordered rule set, first match wins, and `kind_reason` names the rule — so a wrong kind is visible
where it was decided, which is the inventory's one failure mode (§6.1). Content shape is consulted
where a name is not itself the convention: a file of comments is `dead-code` whatever it is
called; a file of imports is a `re-export`.

NEVER A VALUE. The credential scan records the path, the key's NAME, the line and a severity. A
bundle that quoted a secret while reporting it would be the leak it reports.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from openfactory.knowledge.contracts import (
    Concept,
    CoverageRow,
    FileRow,
    Gap,
    Inventory,
    SecretRisk,
)

log = logging.getLogger("openfactory.knowledge.inventory")

INVENTORY_FILE = "inventory.json"
INVENTORY_SUMMARY_FILE = "inventory.md"
SCHEMA_VERSION = "1"

#: bytes of a file the classifier and the credential scan will read; beyond it a file is
#: classified by name alone (a 40 MB fixture is not read to learn that it is a fixture)
READ_CEILING = 1_000_000

# --- the rules, in the order they are asked -------------------------------------------------

_VENDORED_DIRS = frozenset({"node_modules", "vendor", "vendors", "third_party", "third-party",
                            "bower_components", "jspm_packages", "packages/vendor"})
_LOCKFILES = frozenset({"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
                        "pipfile.lock", "cargo.lock", "go.sum", "composer.lock", "gemfile.lock",
                        "uv.lock", "packages.lock.json", "flake.lock", "bun.lockb"})
_GENERATED_TAILS = (".min.js", ".min.css", ".designer.cs", ".g.cs", ".g.i.cs", "_pb2.py",
                    "_pb2_grpc.py", ".pb.go", ".pb.cc", ".pb.h", ".generated.ts",
                    ".generated.cs", ".g.dart", ".freezed.dart")
_GENERATED_MARK = re.compile(r"(?i)\b(?:auto-?generated|generated (?:by|from|code|file)|do not "
                             r"edit(?: this file)?|code generated)\b")
_METADATA_NAMES = frozenset({".gitignore", ".gitattributes", ".gitmodules", ".editorconfig",
                             ".dockerignore", ".npmrc", ".nvmrc", ".python-version",
                             ".ruby-version", ".tool-versions", ".prettierrc", ".prettierignore",
                             ".eslintignore", ".mailmap", "codeowners", "license", "license.txt",
                             "license.md", "licence", "licence.txt", "notice", "notice.txt",
                             "copying", "authors", ".gitkeep", ".keep", "funding.yml", ".git",
                             "dependabot.yml", "renovate.json", ".releaserc"})
_METADATA_DIRS = frozenset({".vscode", ".idea", ".devcontainer", "issue_template",
                            "pull_request_template"})
_PIPELINE_DIRS = frozenset({".github/workflows", ".circleci", ".azure-pipelines", ".buildkite",
                            ".gitlab/ci"})
_PIPELINE_NAMES = frozenset({"jenkinsfile", ".gitlab-ci.yml", "bitbucket-pipelines.yml",
                             ".travis.yml", ".drone.yml", "cloudbuild.yaml", "cloudbuild.yml",
                             "appveyor.yml", ".appveyor.yml"})
_PIPELINE_PREFIXES = ("azure-pipelines",)
_BUILD_NAMES = frozenset({"dockerfile", "makefile", "gnumakefile", "cmakelists.txt", "justfile",
                          "taskfile.yml", "pyproject.toml", "setup.py", "setup.cfg", "tox.ini",
                          "noxfile.py", "manifest.in", "pipfile", "package.json", "tsconfig.json",
                          "build.gradle", "build.gradle.kts", "settings.gradle",
                          "settings.gradle.kts", "pom.xml", "build.sbt", "cargo.toml", "go.mod",
                          "gemfile", "rakefile", "mix.exs", "composer.json", "podfile",
                          "directory.build.props", "directory.build.targets",
                          "directory.packages.props", "global.json", "nuget.config",
                          "webpack.config.js", "webpack.config.ts", "rollup.config.js",
                          "rollup.config.mjs", "vite.config.ts", "vite.config.js",
                          "babel.config.js", "babel.config.json", ".babelrc", "jest.config.js",
                          "jest.config.ts", "vitest.config.ts", "gulpfile.js", "gruntfile.js",
                          ".eslintrc", ".eslintrc.js", ".eslintrc.json", ".eslintrc.cjs",
                          "eslint.config.js", "eslint.config.mjs", ".pre-commit-config.yaml",
                          "constraints.txt", "environment.yml", "conda.yaml", "meson.build",
                          "build.zig", "sconstruct", "wsgi.ini"})
_BUILD_PREFIXES = ("dockerfile.", "docker-compose", "compose.y", "requirements", "tsconfig.",
                   "jest.config", "vitest.config", "webpack.", "makefile.")
_BUILD_SUFFIXES = frozenset({".csproj", ".fsproj", ".vbproj", ".sln", ".nuspec", ".props",
                             ".targets", ".pubxml", ".gradle", ".cmake", ".mk", ".dockerfile"})
#: `x.yaml.example` is an example of a `.yaml` — classified by the suffix under the veil
_EXAMPLE_SUFFIXES = frozenset({".example", ".sample", ".template", ".tmpl", ".dist", ".default"})
_DATA_SUFFIXES = frozenset({".sql", ".proto", ".graphql", ".gql", ".avsc", ".xsd", ".prisma",
                            ".dbml", ".edmx", ".ddl", ".thrift", ".avdl"})
_DATA_DIRS = frozenset({"migrations", "migration", "alembic", "db/migrate", "schemas", "schema"})
_DOC_NAMES = ("readme", "changelog", "changes", "history", "contributing", "code_of_conduct",
              "security", "support", "governance", "maintainers", "roadmap", "faq")
_UI_SUFFIXES = frozenset({".jsx", ".tsx", ".vue", ".svelte", ".astro"})
_MARKUP_SUFFIXES = frozenset({".html", ".htm", ".xml", ".svg", ".xaml", ".cshtml", ".razor",
                              ".xslt", ".xsl", ".hbs", ".handlebars", ".ejs", ".pug", ".jade",
                              ".jinja", ".jinja2", ".j2", ".liquid", ".mustache", ".twig",
                              ".erb", ".haml", ".slim", ".aspx", ".ascx", ".master", ".jsp"})
_STYLE_SUFFIXES = frozenset({".css", ".scss", ".sass", ".less", ".styl", ".pcss"})
_SCRIPT_SUFFIXES = frozenset({".sh", ".bash", ".zsh", ".fish", ".ps1", ".psm1", ".psd1", ".bat",
                              ".cmd", ".awk", ".sed"})
_CONFIG_SUFFIXES = frozenset({".yaml", ".yml", ".json", ".json5", ".jsonc", ".toml", ".ini",
                              ".cfg", ".conf", ".properties", ".env", ".config", ".resx",
                              ".plist", ".settings", ".runsettings", ".editorconfig", ".htaccess",
                              ".npmrc", ".yarnrc", ".tfvars", ".hcl", ".tf"})
_ASSET_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp", ".tif",
                             ".tiff", ".psd", ".ai", ".pdf", ".woff", ".woff2", ".ttf", ".eot",
                             ".otf", ".zip", ".gz", ".tgz", ".tar", ".7z", ".rar", ".dll", ".exe",
                             ".pdb", ".so", ".dylib", ".bin", ".jar", ".war", ".ear", ".nupkg",
                             ".whl", ".egg", ".mp3", ".mp4", ".wav", ".ogg", ".mov", ".avi",
                             ".xlsx", ".xls", ".docx", ".doc", ".pptx", ".ppt", ".csv", ".tsv",
                             ".parquet", ".sqlite", ".db", ".pkl", ".npy", ".npz", ".h5",
                             ".onnx", ".pt", ".pth", ".class", ".o", ".a", ".lib", ".obj",
                             ".snap", ".map", ".log", ".cache"})
_ENTRY_NAMES = frozenset({"main.py", "__main__.py", "app.py", "wsgi.py", "asgi.py", "manage.py",
                          "index.js", "index.ts", "index.mjs", "server.js", "server.ts",
                          "main.js", "main.ts", "program.cs", "startup.cs", "main.go", "main.rs",
                          "main.java", "application.java", "main.kt", "main.swift", "main.c",
                          "main.cpp", "main.dart", "app.js", "app.ts", "cli.py"})
_COMMENT_STARTS = ("//", "#", "*", "/*", "--", "<!--", "'", ";", "rem ", "///", "%")
_ONLY_IMPORTS = re.compile(r"^(?:(?:import|from|export|module\.exports|exports\.|__all__|"
                           r"pub use|use|using|require\(|@import|include|#include|package|"
                           r"namespace)\b.*|[{}()\[\]*]|[A-Za-z_][\w.]*,?)$")
DEAD_CODE_SHARE = 0.9
DEAD_CODE_FLOOR = 5

# --- the credential scan ---------------------------------------------------------------------

_KEY_VALUE = re.compile(
    r"(?i)(?P<key>[a-z0-9_.\-]*?(?:password|passwd|pwd|secret|token|api[_\-]?key|apikey|"
    r"private[_\-]?key|client[_\-]?secret|connection[_\-]?string|access[_\-]?key)s?)"
    r"\s*[\"']?\s*[:=]>?\s*[\"'](?P<value>[^\"'\n]{8,})[\"']")
#: a value that is an identifier in capitals NAMES a variable; it is not the variable's value
_NAMES_A_VARIABLE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")
_AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_PLACEHOLDER = re.compile(r"(?i)^(?:\$\{|\$\(|%\(|\{\{|<|\[|your[_ \-]|change[_\-]?me|example|"
                          r"placeholder|xxx|\*\*\*|dummy|sample|todo|redacted|secret\b|password\b|"
                          r"fake|test|none|null|undefined|\.\.\.|-+$)")


# --- the exemption table ---------------------------------------------------------------------

#: What the coverage table says beside a kind that earned no concept, and whether that EXCUSES
#: the kind. An excused kind is represented by the inventory alone (OKF §6.2's "never"/"none"
#: rows); an unexcused one is still owed — every file behind it is a concept, an exclusion with
#: a reason, or a gap, and a gate that reads `excused` treats it as in scope. `unclassified` is
#: never excused: the reference draft that checked nothing else found that it is the ONE row that
#: must stay visible.
NO_EXEMPTION = ("no exemption — every one of these files is a concept, an exclusion with a "
                "reason, or a gap; the inventory names them")
BUDGET_DID_NOT_REACH = ("the budget did not reach these — see the module row; not an exemption, "
                        "every file here is still owed a concept, an exclusion or a gap")
WHY_NOT: dict[str, tuple[str, bool]] = {
    "generated": ("generated — represented by the inventory alone, never described", True),
    "vendored": ("vendored — somebody else's code; the inventory records that it is here", True),
    "build-definition": ("a build definition — its facts are the inventory's", True),
    "pipeline-definition": ("a pipeline definition — one `deployment` concept per repository is "
                            "authored only where the pipeline encodes a decision", True),
    "repo-metadata": ("repository metadata — represented by the inventory alone", True),
    "documentation": ("documentation — read by the onboarding pass, never re-described", True),
    "markup": ("markup — a surface with no behaviour of its own", True),
    "style": ("style — no behaviour", True),
    "script": ("a script — cited from the concept whose wiring it decides, not described "
               "alone", True),
    "test": ("tests — evidence for a concept's rules, never a concept themselves", True),
    "configuration": ("configuration — keys are recorded in the inventory; a concept is authored "
                      "only where a value's meaning exceeds its name", True),
    "data-definition": ("a data definition — fully described by its declarations", True),
    "asset": ("an asset — nothing to describe", True),
    "re-export": ("a barrel module — a public surface with no behaviour of its own", True),
    "dead-code": ("dead code — recorded as a gap, never described", True),
    "unclassified": (NO_EXEMPTION, False),
    "code": (BUDGET_DID_NOT_REACH, False),
    "entry-point": (BUDGET_DID_NOT_REACH, False),
    "ui-component": (BUDGET_DID_NOT_REACH, False),
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _under(parts: list[str], names: frozenset[str]) -> str:
    """The first directory of the path that is in `names` (a single segment, or `a/b`)."""
    lowered = [p.lower() for p in parts[:-1]]
    for i, part in enumerate(lowered):
        if part in names:
            return parts[i]
        if i + 1 < len(lowered) and f"{part}/{lowered[i + 1]}" in names:
            return f"{parts[i]}/{parts[i + 1]}"
    return ""


def _is_comment(line: str) -> bool:
    stripped = line.strip().lower()
    return bool(stripped) and stripped.startswith(_COMMENT_STARTS)


def _shape(text: str) -> tuple[str, str] | None:
    """What the CONTENT says about a code file, when the name is not the convention."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) >= DEAD_CODE_FLOOR:
        comments = sum(1 for ln in lines if _is_comment(ln))
        if comments / len(lines) >= DEAD_CODE_SHARE:
            return "dead-code", f"{comments} of {len(lines)} non-blank lines are comments"
    live = [ln.strip() for ln in lines if not _is_comment(ln)]
    if live and all(_ONLY_IMPORTS.match(ln) for ln in live):
        return "re-export", "only imports and exports — a barrel module"
    return None


def classify(rel: str, *, text: str | None = None) -> tuple[str, str]:
    """The kind of one repo-relative path and the rule that decided it — first match wins.

    `text` is the file's content when the caller could read it (decoded, up to `READ_CEILING`);
    None means "classify by name alone", which is what a binary or an oversized file gets."""
    from openfactory.onboarding.context import (
        _CODE_SUFFIXES,
        _DOC_DIRS,
        _DOC_SUFFIXES,
        _is_test_path,
    )

    parts = rel.split("/")
    name = parts[-1]
    low = name.lower()
    suffix = Path(name).suffix.lower()
    stem = Path(name).stem.lower()
    if suffix in _EXAMPLE_SUFFIXES and Path(stem).suffix:
        kind, why = classify(rel[: -len(suffix)], text=text)
        return kind, f"an example of `{Path(stem).suffix}` — {why}"
    where = _under(parts, _VENDORED_DIRS)
    if where:
        return "vendored", f"under `{where}/` — somebody else's code"
    if low in _LOCKFILES:
        return "generated", f"`{name}` is a lockfile"
    tail = next((t for t in _GENERATED_TAILS if low.endswith(t)), "")
    if tail:
        return "generated", f"the name ends in `{tail}`"
    if text is not None and _GENERATED_MARK.search(text[:2000]):
        return "generated", "the file says so in its first lines"
    where = _under(parts, _PIPELINE_DIRS)
    if where:
        return "pipeline-definition", f"under `{where}/`"
    if low in _PIPELINE_NAMES or low.startswith(_PIPELINE_PREFIXES):
        return "pipeline-definition", f"`{name}` is a pipeline file by name"
    where = _under(parts, _METADATA_DIRS)
    if where or low in _METADATA_NAMES:
        return "repo-metadata", (f"under `{where}/`" if where
                                 else f"`{name}` is repository metadata")
    if low in _BUILD_NAMES or low.startswith(_BUILD_PREFIXES) or suffix in _BUILD_SUFFIXES:
        return "build-definition", f"`{name}` is a build file by name"
    if _is_test_path(rel) and (suffix in _CODE_SUFFIXES or suffix in {".snap", ".feature"}
                               or "fixture" in rel.lower()):
        return "test", "a test by path or stem"
    where = _under(parts, _DATA_DIRS)
    if suffix in _DATA_SUFFIXES or (where and suffix in _CODE_SUFFIXES):
        return "data-definition", (f"under `{where}/`" if where else f"`{suffix}` declares data")
    if suffix in _DOC_SUFFIXES or (suffix in {"", ".txt"} and stem.startswith(_DOC_NAMES)) \
            or any(p.lower() in _DOC_DIRS for p in parts[:-1]):
        return "documentation", (f"`{suffix or name}` is documentation")
    if suffix in _UI_SUFFIXES:
        return "ui-component", f"`{suffix}` is a component file"
    if suffix in _MARKUP_SUFFIXES:
        return "markup", f"`{suffix}` is markup"
    if suffix in _STYLE_SUFFIXES:
        return "style", f"`{suffix}` is a stylesheet"
    if suffix in _SCRIPT_SUFFIXES:
        return "script", f"`{suffix}` is a shell script"
    if suffix in _CONFIG_SUFFIXES or low.startswith(".env"):
        return "configuration", f"`{suffix or name}` is configuration"
    if suffix in _ASSET_SUFFIXES:
        return "asset", f"`{suffix}` is an asset"
    if suffix in _CODE_SUFFIXES:
        shaped = _shape(text) if text is not None else None
        if shaped:
            return shaped
        if low in _ENTRY_NAMES:
            return "entry-point", f"`{name}` is a conventional entry-point name"
        return "code", f"`{suffix}` is in the read set"
    return "unclassified", f"no rule places `{suffix or name}`"


def _read(path: Path) -> tuple[str | None, bytes | None]:
    """(decoded text or None when binary/oversized, raw bytes or None when unreadable)."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None, None
    if len(raw) > READ_CEILING or b"\0" in raw[:8000]:
        return None, raw
    return raw.decode("utf-8", errors="replace"), raw


def _scan_secrets(rel: str, text: str, kind: str) -> list[SecretRisk]:
    found: list[SecretRisk] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if _PRIVATE_KEY.search(line):
            found.append(SecretRisk(path=rel, key="PRIVATE KEY", line=number, severity="high",
                                    kind=kind))
            continue
        if _AWS_KEY.search(line):
            found.append(SecretRisk(path=rel, key="AWS access key", line=number, severity="high",
                                    kind=kind))
            continue
        hit = _KEY_VALUE.search(line)
        if not hit:
            continue
        value = hit.group("value").strip()
        low = ("low" if (_PLACEHOLDER.match(value) or _NAMES_A_VARIABLE.match(value))
               else "high")
        # A FIXTURE'S PASSWORD IS NOT A DEPLOYMENT'S: still listed, with the kind beside it, but
        # graded low — the seventy-four "high" risks the core's own tree reported were tests and
        # documentation examples, and a list where everything is high ranks nothing.
        if kind in {"test", "documentation"}:
            low = "low"
        found.append(SecretRisk(path=rel, key=hit.group("key"), line=number, severity=low,
                                kind=kind))
    return found


def take_inventory(repo: Path, *, commit: str = "", generated_at: str = "",
                   max_files: int = 20_000) -> Inventory:
    """Walk one repository and classify every file it reaches. Deterministic, no model.

    `max_files` is the survey's own ceiling, and the walk is the survey's own — see the module
    docstring for why a second walk would be a defect."""
    from openfactory.onboarding.context import _collect_files

    root = Path(repo).expanduser().resolve()
    files = _collect_files(root, max_files)
    rows: list[FileRow] = []
    risks: list[SecretRisk] = []
    errors: list[str] = []
    for rel in files.all:
        text, raw = _read(root / rel)
        if raw is None:
            errors.append(rel)
            kind, why = classify(rel)
            rows.append(FileRow(path=rel, kind=kind, kind_reason=why + " (could not be read)"))
            continue
        kind, why = classify(rel, text=text)
        rows.append(FileRow(path=rel, kind=kind, kind_reason=why,
                            lines=(text.count("\n") + (1 if text and not text.endswith("\n")
                                                       else 0)) if text is not None else 0,
                            fingerprint=_sha256(raw)))
        if text is not None and kind != "asset":
            risks.extend(_scan_secrets(rel, text, kind))
    by_kind: dict[str, int] = {}
    for row in rows:
        by_kind[row.kind] = by_kind.get(row.kind, 0) + 1
    return Inventory(schema_version=SCHEMA_VERSION, commit=commit, generated_at=generated_at,
                     files=rows, by_kind=dict(sorted(by_kind.items())),
                     unclassified=[r.path for r in rows if r.kind == "unclassified"],
                     unreadable=list(files.unreadable), errors=errors,
                     truncated=bool(files.truncated), secret_risks=risks)


def inventory_gaps(inventory: Inventory) -> list[Gap]:
    """What the inventory could not settle, as the bundle's own gaps — one entry per fact.

    PER FILE, PER RISK. A gap that says "nine files were unclassified" is a number; nine entries
    naming nine paths are nine decisions somebody can take. The credential entry names the KEY and
    the line and nothing else."""
    gaps: list[Gap] = []
    reasons = {r.path: r.kind_reason for r in inventory.files}
    for path in inventory.unclassified:
        gaps.append(Gap(kind="unclassified", path=path,
                        detail=f"{reasons.get(path, 'no rule places it')} — a concept, an "
                               f"exclusion with a reason, or nothing at all is a decision this "
                               f"bundle has not taken"))
    for row in inventory.files:
        if row.kind == "dead-code":
            gaps.append(Gap(kind="dead-code", path=row.path, detail=row.kind_reason))
    for risk in inventory.secret_risks:
        gaps.append(Gap(kind="credential-risk", path=risk.path,
                        detail=f"`{risk.key}` at line {risk.line} — {risk.severity}, in a "
                               f"{risk.kind or 'file'}; the value is not recorded"))
    for where in inventory.unreadable:
        gaps.append(Gap(kind="unreadable", path=where,
                        detail="the walk could not open this directory — read as UNREAD, not "
                               "as empty"))
    for path in inventory.errors:
        gaps.append(Gap(kind="unreadable", path=path, detail="the file could not be read"))
    if inventory.truncated:
        gaps.append(Gap(kind="truncated",
                        detail=f"the walk stopped at {len(inventory.files)} files — what lies "
                               f"beyond is not inventoried"))
    return gaps


def coverage_by_kind(inventory: Inventory, concepts: list[Concept]) -> list[CoverageRow]:
    """One row per kind in the inventory: how many files, how many concepts cite one of them,
    and — when none does — why, and whether that excuses the kind (OKF §7.2, check 5)."""
    kinds = {r.path: r.kind for r in inventory.files}
    citing: dict[str, int] = {}
    for concept in concepts:
        touched = {kinds[s.path] for s in concept.sources if s.path in kinds}
        for kind in touched:
            citing[kind] = citing.get(kind, 0) + 1
    rows: list[CoverageRow] = []
    for kind, count in sorted(inventory.by_kind.items()):
        described = citing.get(kind, 0)
        if described:
            rows.append(CoverageRow(kind=kind, inventoried=count, concepts=described))
            continue
        reason, excused = WHY_NOT.get(kind, (BUDGET_DID_NOT_REACH, False))
        rows.append(CoverageRow(kind=kind, inventoried=count, concepts=0, reason=reason,
                                excused=excused))
    return rows


def render_inventory_md(inventory: Inventory) -> str:
    """The human-readable summary — the worklist: what is here by kind, and every remainder."""
    total = len(inventory.files)
    lines = [f"# Inventory — {inventory.commit[:8] or '(no commit)'}", ""]
    lines.append(f"{total} files in {len(inventory.by_kind)} kinds — "
                 f"{len(inventory.unclassified)} unclassified, "
                 f"{len(inventory.secret_risks)} credential risks"
                 + (f", taken {inventory.generated_at}" if inventory.generated_at else "") + ".")
    if inventory.truncated:
        lines.append(f"**The walk stopped at {total} files** — what lies beyond is not here.")
    lines.append("")
    lines += ["## By kind", "", "| kind | files | lines |", "|---|---:|---:|"]
    by_lines: dict[str, int] = {}
    for row in inventory.files:
        by_lines[row.kind] = by_lines.get(row.kind, 0) + row.lines
    for kind, count in sorted(inventory.by_kind.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| {kind} | {count} | {by_lines.get(kind, 0)} |")
    lines.append("")
    lines += ["## Unclassified — each one is a decision this bundle has not taken", ""]
    reasons = {r.path: r.kind_reason for r in inventory.files}
    if inventory.unclassified:
        lines += [f"- `{p}` — {reasons.get(p, '')}" for p in inventory.unclassified]
    else:
        lines.append("- None: every file matched a rule.")
    lines.append("")
    lines += ["## Credential risks — path, key and line; never the value", ""]
    if inventory.secret_risks:
        lines += [f"- `{r.path}:{r.line}` — `{r.key}` ({r.severity}, in a {r.kind or 'file'})"
                  for r in inventory.secret_risks]
    else:
        lines.append("- None found by the scan.")
    lines.append("")
    if inventory.unreadable or inventory.errors:
        lines += ["## Could not read — unread, not empty", ""]
        lines += [f"- `{d}/`" for d in inventory.unreadable]
        lines += [f"- `{f}`" for f in inventory.errors]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_inventory(bundle_dir: Path, inventory: Inventory) -> list[Path]:
    """`inventory.json` (the record, verbatim) and `inventory.md` (the worklist) into the bundle."""
    okf = Path(bundle_dir)
    okf.mkdir(parents=True, exist_ok=True)
    record = okf / INVENTORY_FILE
    record.write_text(json.dumps(inventory.model_dump(), indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    summary = okf / INVENTORY_SUMMARY_FILE
    summary.write_text(render_inventory_md(inventory), encoding="utf-8")
    return [record, summary]


def read_inventory(bundle_dir: Path) -> Inventory | None:
    """The inventory a bundle carries, or None when it carries none or the record is unreadable.

    AN UNKNOWN SCHEMA IS NONE, NOT A GUESS: a reader that accepted a schema it does not know
    would report coverage against a denominator it cannot interpret."""
    path = Path(bundle_dir) / INVENTORY_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or str(data.get("schema_version", "")) != SCHEMA_VERSION:
        log.warning("inventory at %s has schema %r, not %r — ignored", path,
                    data.get("schema_version") if isinstance(data, dict) else None,
                    SCHEMA_VERSION)
        return None
    try:
        return Inventory.model_validate(data)
    except ValueError:
        return None


__all__ = [
    "INVENTORY_FILE",
    "INVENTORY_SUMMARY_FILE",
    "NO_EXEMPTION",
    "WHY_NOT",
    "Inventory",
    "classify",
    "coverage_by_kind",
    "inventory_gaps",
    "read_inventory",
    "render_inventory_md",
    "take_inventory",
    "write_inventory",
]
