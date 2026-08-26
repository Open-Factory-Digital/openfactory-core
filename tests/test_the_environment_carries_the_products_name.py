"""The configuration surface carries the product's name — #106 item 8.

Eighty-seven `SDLC_*` variables were the whole way a deployment spoke to this platform. They are
OURS — they live in a deployment's environment, not in a client's repository — so the rename was
flat: code reads `OPENFACTORY_*`. For a while each entrypoint's composition root also COPIED the
old spelling onto the new one at boot, as a courtesy to the one deployment that predated the
rename. That shim left on 2026-08-25 (the public repository has no old installation to serve),
and this file now guards the absence:

    NO ADOPTION. `environ` carries no second prefix and no function that serves one; nothing in
    the package reads `SDLC_*` from the environment or assembles a child's environment under it.

    ONE SPELLING PER SECRET, WHICH IS NOT THE SAME AS ONE NAME PER SECRET. While the shim ran, the
    same token sat under two names and every deny-by-name scrub had to name both or hand the agent
    the other one. That is over. But `credentials.py` still serves ONE bot credential under THREE
    names by FALLBACK — `forge_token()` reads the forge override then the deployment-wide token,
    `tracker_token()` reads the tracker override then that same token — and a deny list that
    carried two of the three had the identical hole for a different reason (measured 2026-08-26,
    with `OPENFACTORY_TRACKER_TOKEN` surviving `_scrubbed_env`; on a personal GitHub account
    `docs/setup/github.md` fills it with a classic PAT scoped `repo`, which pushes). So the guard
    derives the fallback chains from `credentials.py` and holds the scrub to all of each.

AND THE DOCUMENT SAYS WHAT THE CODE DOES. `SECURITY.md` is the first file a security researcher
opens and it has now made a false promise twice: "both current and legacy spellings of every name"
was untrue, and its replacement — the deny lists "name the ONE spelling this platform reads for
each secret … enough only because no second spelling exists" — was untrue too. The honest
guarantee is one-directional (a name the list carries is removed; a name it does not carry is
not), so the document states it that way AND publishes the other half: which credentials a
worktree workload can read. That table is not prose here. It is DERIVED — every credential-shaped
variable the core reads, run through the real `_scrubbed_env` — and compared, name for name,
against the document. A credential added to the platform and not to a deny list turns this file
red until `SECURITY.md` says so.
"""

from __future__ import annotations

import ast
import pathlib
import re
import shutil

import add_ons
import pytest

from openfactory import environ, namespace
from openfactory.adapters.credential.registry import SHIPPED_ENV
from openfactory.adapters.sandbox.container import _AUTH_ENV_VARS, ContainerSandbox
from openfactory.adapters.sandbox.worktree import (
    _AGENT_CRED_VARS,
    _AWS_CRED_VARS,
    _FORGE_CRED_VARS,
    _scrubbed_env,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
SECURITY = ROOT / "SECURITY.md"
CREDENTIALS = ROOT / "openfactory" / "credentials.py"
WORKTREE_MODULE = ROOT / "openfactory" / "adapters" / "sandbox" / "worktree.py"

#: Every name the worktree box's deny lists carry, in one place because the property under test is
#: about the lists TOGETHER: three lists that each keep their own promise still leave a credential
#: in reach if the fourth family has no list at all.
DENIED = frozenset(_AWS_CRED_VARS + _FORGE_CRED_VARS + _AGENT_CRED_VARS)


def test_the_platform_answers_to_its_own_name():
    assert environ.ENV_PREFIX == "OPENFACTORY_"


# ── no adoption: the module serves one spelling ─────────────────────────────────────────────────

def test_the_environment_module_carries_no_second_prefix():
    """The shim's constant and both helpers are GONE, not renamed. A survivor under another name
    would be the same second door with a new label."""
    survivors = [n for n in dir(environ) if "legacy" in n.lower() or "adopt" in n.lower()
                 or "twin" in n.lower()]
    assert not survivors, f"the environment module still serves a second spelling: {survivors}"
    # the positive twin: the module still says what the ONE prefix is, and still reads with it
    assert environ.ENV_PREFIX.startswith("OPENFACTORY")
    assert environ.SSM_PREFIX_VAR.startswith(environ.ENV_PREFIX)
    # the one thing the module may still know about the old spelling is that an add-on may not
    # take it up — the roles axis reserves it, and the spelling comes from `namespace.py`, so
    # this module never writes it
    assert environ.RETIRED_ENV_PREFIX == namespace.RETIRED_DIR.lstrip(".").upper() + "_"
    assert "old spelling" in (environ.reserved(environ.RETIRED_ENV_PREFIX + "QA_MODEL") or "")


def test_an_old_spelling_in_the_environment_is_NOT_served(monkeypatch):
    """Behaviour, not shape: a deployment that sets only the old name gets nothing under the
    new one. A reader that quietly served it would be the shim growing back somewhere else."""
    monkeypatch.delenv("OPENFACTORY_SSM_PREFIX", raising=False)
    monkeypatch.setenv("SDLC_SSM_PREFIX", "/somewhere")

    assert environ.ssm_prefix() == "", "the retired spelling was served under the new name"

    monkeypatch.setenv("OPENFACTORY_SSM_PREFIX", "/here/")
    assert environ.ssm_prefix() == "/here"  # the twin: the real name is read


# ── one spelling per secret: the scrub lists the name the platform reads ────────────────────────

def test_the_worktree_scrub_denies_the_forge_token_and_the_pool(monkeypatch, tmp_path):
    """The property, on the real list: an agent workspace env must hold neither the forge token
    nor the token pool under any spelling the platform reads."""
    monkeypatch.setenv("OPENFACTORY_FORGE_TOKEN", "tok")
    monkeypatch.setenv("OPENFACTORY_AGENT_TOKENS", "pool")
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "worktree")  # not a secret; must survive

    env = _scrubbed_env()

    assert "OPENFACTORY_FORGE_TOKEN" not in env and "OPENFACTORY_AGENT_TOKENS" not in env
    assert env.get("OPENFACTORY_SANDBOX") == "worktree", "the scrub took more than the secrets"
    # Every name of OURS on the deny lists is one another module actually READS. The rule used to
    # be checked as a prefix, which a retired spelling passes just as well as a live one; a list
    # naming something nothing serves is the side door coming back as a precaution. The foreign
    # names are the exception the code cannot vouch for either way — `git` and `gh` read their own
    # variables, and no module here does.
    read = _read_outside(tmp_path, WORKTREE_MODULE)
    for name in (*_FORGE_CRED_VARS, *_AGENT_CRED_VARS):
        if not name.startswith(environ.ENV_PREFIX):
            assert name in ("GH_TOKEN", "GITHUB_TOKEN"), f"{name} is nobody's variable here"
        else:
            assert name in read, (
                f"{name} is withheld from the workload and served by no module in this package — "
                f"a deny list that names a spelling nothing reads is a precaution, not a scrub")


# ── nothing reads the old prefix ────────────────────────────────────────────────────────────────

_ENV_OWNERS = {"environ", "env"}  # os.environ.get / environ.get / env.get(...)


def _legacy_env_reads(path: pathlib.Path) -> list[tuple[int, str]]:
    """Every place a module still asks the ENVIRONMENT for an `SDLC_*` name.

    Position-based, not shape-based, on purpose: what this guard pins is narrow and load-bearing —
    no READ of the old names anywhere. (The wider question, "does any code constant spell the old
    name at all", is `test_the_namespace_is_the_products_name.py`'s, and it walks every constant;
    this one exists because an environment read is where the second spelling did its damage.)"""
    found: list[tuple[int, str]] = []

    def is_env_owner(node: ast.expr) -> bool:
        if isinstance(node, ast.Attribute):
            return node.attr in _ENV_OWNERS
        return isinstance(node, ast.Name) and node.id in _ENV_OWNERS

    def legacy(node: ast.expr) -> str | None:
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node.value.startswith("SDLC_")):
            return node.value
        return None

    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            fn = node.func
            reads_env = (fn.attr in ("get", "pop", "setdefault") and is_env_owner(fn.value)) or \
                        (fn.attr == "getenv")
            if reads_env and node.args and (name := legacy(node.args[0])):
                found.append((node.lineno, name))
        elif isinstance(node, ast.Subscript) and is_env_owner(node.value):
            if name := legacy(node.slice):
                found.append((node.lineno, name))
        elif isinstance(node, ast.Compare) and any(
                isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            if (name := legacy(node.left)) and any(
                    is_env_owner(c) for c in node.comparators):
                found.append((node.lineno, name))
    return found


def test_the_scan_can_SEE_a_legacy_env_read():
    """The positive twin: plant every read shape plus a log marker; the scan must catch the
    reads and leave the marker alone."""
    planted = ROOT / "tests" / "__planted_env_read.py"
    planted.write_text(
        "import os\n"
        "a = os.environ.get('SDLC_SANDBOX')\n"
        "b = os.getenv('SDLC_REGISTRY', '')\n"
        "c = os.environ['SDLC_ISSUE']\n"
        "d = 'SDLC_BOT_TOKEN' in os.environ\n"
        "import logging; logging.getLogger().warning('SDLC_BOARD_MOVE_FAILED %s', 'x')\n"
    )
    try:
        names = sorted(n for _, n in _legacy_env_reads(planted))
    finally:
        planted.unlink()
    assert names == ["SDLC_BOT_TOKEN", "SDLC_ISSUE", "SDLC_REGISTRY", "SDLC_SANDBOX"], names


def test_nothing_reads_the_old_environment_names():
    offenders = {}
    for path in sorted(ROOT.joinpath("openfactory").rglob("*.py")):
        hits = _legacy_env_reads(path)
        if hits:
            offenders[str(path.relative_to(ROOT))] = hits
    assert not offenders, (
        f"these still read SDLC_* from the environment: {offenders}. Code reads OPENFACTORY_*; "
        f"the old spelling is not served by anything")


def test_no_env_dict_is_assembled_with_the_old_names():
    """The write side: the worker hands the box its env as dict literals (`SDLC_ISSUE: …` once).
    A dict key is not an environ read, so the read guard cannot see it — and a box env assembled
    under old names would depend on an adoption shim that no longer exists."""
    offenders = {}
    for path in sorted(ROOT.joinpath("openfactory").rglob("*.py")):
        hits = []
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Dict):
                for key in node.keys:
                    if (isinstance(key, ast.Constant) and isinstance(key.value, str)
                            and key.value.startswith("SDLC_")):
                        hits.append((key.lineno, key.value))
        if hits:
            offenders[str(path.relative_to(ROOT))] = hits
    assert not offenders, f"env dicts still assembled under old names: {offenders}"


# ── what the document promises, measured ────────────────────────────────────────────────────────

#: The last word of a variable's name says what the variable HOLDS, and these words say it holds a
#: secret. A shape rule rather than a list of names, because a list of names is the thing that was
#: wrong twice: SECURITY.md's first claim and its replacement were both tables written in prose,
#: and both went stale the day a credential was added. The rule errs towards INCLUDING — a false
#: positive costs one row in a table, a false negative is a credential nobody measured.
_SECRET_NOUNS = frozenset({
    "TOKEN", "TOKENS", "SECRET", "SECRETS", "KEY", "KEYS", "PASSWORD", "PASSWORDS",
    "PAT", "PATS", "CREDENTIAL", "CREDENTIALS",
})

#: …and a name ending in one of these holds something ABOUT a secret rather than the secret: which
#: source a token pool comes from, which key an id names. A locator (`…_TOKEN_FILE`,
#: `…_CREDENTIALS_URI`) is deliberately NOT here — a path to a credential is reach to it.
_NOT_THE_SECRET = frozenset({
    "SOURCE", "MODE", "KIND", "NAME", "ENABLED", "ID", "COUNT", "TTL", "PROVIDER", "STORE",
})


def _holds_a_credential(name: str) -> bool:
    words = name.split("_")
    return bool(set(words) & _SECRET_NOUNS) and words[-1] not in _NOT_THE_SECRET


def _spelling_groups(path: pathlib.Path) -> list[frozenset[str]]:
    """The groups of environment names that hold ONE credential, read out of a module's own code.

    A FALLBACK CHAIN IS A SECOND SPELLING, and it is the shape the retired-prefix shim left
    behind: `os.environ.get(A) or os.environ.get(B)` means whoever fills A and whoever fills B
    hand the same reader the same secret. Derived from the `or` expressions rather than listed, so
    a third override added to `credentials.py` arrives here without anyone remembering to.
    Overlapping chains are merged: `forge_token` and `tracker_token` share their fallback, so the
    three names are one credential and not two pairs."""
    groups: list[frozenset[str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)):
            continue
        names = []
        for value in node.values:
            key = environ._reads_environ(value)
            if key is not None and (name := environ._env_shaped(key)):
                names.append(name)
        if len(names) > 1:
            groups.append(frozenset(names))
    merged: list[frozenset[str]] = []
    for group in groups:
        touching = [m for m in merged if m & group]
        for m in touching:
            merged.remove(m)
        merged.append(group.union(*touching))
    return merged


def _tree(tmp_path: pathlib.Path, *, leaving: bool) -> pathlib.Path:
    """A copy of `openfactory/` holding either the modules that STAY in the public export or the
    ones that LEAVE with an add-on package (`docs/STATUS.md`'s table, via `add_ons`).

    SECURITY.md travels to the public repository, so its table has to be the truth THERE: a name
    only a leaving module reads would be a row the public suite could not measure. Copied whole
    rather than scanned file by file because `names_read` resolves a literal handed to a reader
    defined in ANOTHER module (its shape 3), and a per-file scan drops those silently — the losing
    direction, since a credential it stops seeing is a credential nobody measures."""
    excluded = add_ons.excluded_paths()
    target = tmp_path / ("leaving" if leaving else "public") / "openfactory"
    for path in sorted((ROOT / "openfactory").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        goes = any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in excluded)
        if goes is not leaving:
            continue
        dest = target / path.relative_to(ROOT / "openfactory")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, dest)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _read_outside(tmp_path: pathlib.Path, module: pathlib.Path) -> frozenset[str]:
    """Every environment variable the package reads with `module` taken out of it.

    A DENY LIST IS ITSELF A NAMES TABLE, and `names_read` counts one — its shape 2, which is how
    a scrub list says what may not pass. So asking the WHOLE package "is this denied name one the
    platform reads" answers yes for any string somebody adds to the list, including a name nothing
    serves: the question and the answer are the same tuple. Measured on 2026-08-26 by a cut that
    put `OPENFACTORY_RETIRED_BOT_TOKEN` on the forge list and watched the guard pass. With the
    list's own module removed the question means something again — a name survives here only
    because a reader elsewhere serves a credential through it."""
    target = tmp_path / "outside" / "openfactory"
    for path in sorted((ROOT / "openfactory").rglob("*.py")):
        if path == module:
            continue
        dest = target / path.relative_to(ROOT / "openfactory")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, dest)
    return environ.names_read(target)


def _credential_names(core: pathlib.Path) -> frozenset[str]:
    """Every credential-shaped variable the platform reads, from three derivations and no table:

      · `environ.names_read(core)` — the AST scan the reservation already trusts, over the tree;
      · the credential registry's `SHIPPED_ENV` — the vendors' own default variables, which reach
        the environment through a dataclass keyword the scan is documented as unable to see;
      · the fallback chains in `credentials.py` — one credential's several spellings.

    The deny lists are unioned in by the callers that need them: this answers "what does the
    platform read", and a name on a deny list that nothing reads is another guard's business."""
    return frozenset(n for n in (set(environ.names_read(core))
                                 | set(SHIPPED_ENV.values())
                                 | set().union(*_spelling_groups(CREDENTIALS)))
                     if _holds_a_credential(n))


def _reaching_the_workload(monkeypatch, universe) -> set[str]:
    """Which of `universe` a worktree workload can actually read — MEASURED, by filling the
    process environment and running the real `_scrubbed_env`. Set arithmetic against the deny
    lists would agree today and would go on agreeing if `keep` grew a default or the loop stopped
    running: the function is the thing under test, not the constants beside it."""
    for name in sorted(universe):
        monkeypatch.setenv(name, f"value-of-{name}")
    env = _scrubbed_env()
    return {name for name in universe if name in env}


_BACKTICKED = re.compile(r"`([A-Z][A-Z0-9_]*)`")


def _names_of(text: str) -> set[str]:
    return {n for n in _BACKTICKED.findall(text) if environ.ENV_NAME_SHAPE.match(n)}


def _region(anchor: str) -> str:
    """The slice of SECURITY.md between `<!-- anchor -->` and `<!-- /anchor -->`.

    Both markers must be present exactly once and in order. A cut that removed them would
    otherwise leave the scan reading the WHOLE document, where the same names are also written in
    prose — absence reading as compliance, in the one place this file exists to prevent it."""
    text = SECURITY.read_text(encoding="utf-8")
    start, end = f"<!-- {anchor} -->", f"<!-- /{anchor} -->"
    assert text.count(start) == 1, f"SECURITY.md must carry `{start}` exactly once"
    assert text.count(end) == 1, f"SECURITY.md must carry `{end}` exactly once"
    assert text.index(start) < text.index(end), f"`{end}` comes before `{start}`"
    return text[text.index(start) + len(start):text.index(end)]


def _outside_the_regions(*anchors: str) -> str:
    """SECURITY.md with each anchored region cut out of it, marker to marker.

    BY POSITION, NOT BY SUBTRACTING NAMES. The first version of this took the document's names
    minus each region's names, which cannot see a name that is in a region AND in the prose —
    exactly the reassuring sentence it was written to catch, measured on 2026-08-26 by a cut that
    added "`AZURE_DEVOPS_PAT` never leaves the framework's own process" and watched it pass."""
    text = SECURITY.read_text(encoding="utf-8")
    spans = []
    for anchor in anchors:
        _region(anchor)  # the markers exist, once each, in order
        start, end = f"<!-- {anchor} -->", f"<!-- /{anchor} -->"
        spans.append((text.index(start), text.index(end) + len(end)))
    kept, cursor = [], 0
    for begins, ends in sorted(spans):
        kept.append(text[cursor:begins])
        cursor = ends
    kept.append(text[cursor:])
    return "".join(kept)


def _documented_reach() -> set[str]:
    """The variables SECURITY.md's table says reach a worktree workload — column ONE of each row.

    Column one only, so the prose in column two may name a scrubbed variable to contrast with
    (the failover pool does exactly that) without joining the claim — and so a cut that hides a
    live credential by demoting it into the explanation fails instead of passing."""
    rows = [line.strip() for line in _region("reaches-the-agent").splitlines()
            if line.strip().startswith("|")]
    rows = [r for r in rows if set(r) - set("|-: ")]  # drop the header separator
    assert len(rows) >= 2, f"SECURITY.md's reach table has no rows: {rows}"
    names: list[str] = []
    for row in rows:
        names += sorted(_names_of(row.strip("|").split("|")[0]))
    assert len(names) == len(set(names)), f"a variable is listed twice in the table: {names}"
    return set(names)


def test_the_credential_scan_SEES_a_new_variable_and_ignores_a_selector(tmp_path):
    """The positive twin for the derivation: plant a credential the platform did not have and it
    must be measured; plant a variable that only NAMES a credential facility and it must not.
    Without this, every assertion below would pass just as well over a scan that had stopped
    scanning — the reach table would simply shrink to the deny lists and look reassuring."""
    planted = tmp_path / "openfactory"
    planted.mkdir()
    (planted / "vault.py").write_text(
        "import os\n"
        "secret = os.environ.get('ACME_DEPLOY_TOKEN')\n"
        "where = os.environ.get('ACME_TOKEN_POOL_SOURCE')\n"
        "keyfile = os.environ.get('ACME_SIGNING_KEY_FILE')\n"
    )

    found = _credential_names(planted)

    assert "ACME_DEPLOY_TOKEN" in found, "a planted credential was not measured"
    assert "ACME_SIGNING_KEY_FILE" in found, "the path to a key is reach to the key"
    assert "ACME_TOKEN_POOL_SOURCE" not in found, "a selector was counted as a secret"


def test_the_fallback_scan_SEES_a_chain_and_leaves_a_single_read_alone(tmp_path):
    """The positive twin for `_spelling_groups`: an `or` between two environment reads is one
    credential under two names, and a lone read is not a group — or every variable with a default
    would be somebody's second spelling and the all-or-nothing rule below would be unfalsifiable."""
    planted = tmp_path / "creds.py"
    planted.write_text(
        "import os\n"
        "def paired():\n"
        "    return os.environ.get('ACME_A_TOKEN') or os.environ.get('ACME_B_TOKEN') or None\n"
        "def alone():\n"
        "    return os.environ.get('ACME_ONLY_TOKEN') or ''\n"
    )

    assert _spelling_groups(planted) == [frozenset({"ACME_A_TOKEN", "ACME_B_TOKEN"})]


def test_a_credential_served_under_several_names_is_denied_under_all_of_them(monkeypatch):
    """THE DEFECT THIS SECTION WAS WRITTEN FOR. `credentials.py` serves one bot credential through
    a fallback chain, and the deny list carried part of that chain — so a deployment that filled
    the tracker override handed the agent the very credential the list exists to withhold, under
    the one name nobody had listed (measured 2026-08-26).

    All-or-nothing per chain, through the real scrub — not "these three names are denied", which
    would move the table from the code into a test and rot in the same way."""
    chains = _spelling_groups(CREDENTIALS)
    assert chains, "credentials.py serves no fallback chain — this scan has stopped scanning"

    reaching = _reaching_the_workload(monkeypatch, frozenset(set().union(*chains)))

    for chain in chains:
        assert len(chain) > 1
        assert reaching >= chain or not reaching & chain, (
            f"{sorted(chain)} are spellings of ONE credential and the workload can read "
            f"{sorted(reaching & chain)} of them — a deny list that names part of a chain is the "
            f"side door standing open under the name nobody listed")


def test_the_deny_lists_remove_the_names_they_carry_and_nothing_else(monkeypatch, tmp_path):
    """The verifier for the measurement below, in both directions: everything denied is gone — or
    the scrub has stopped scrubbing and the table would look reassuring — and nothing else is, or
    the table would look reassuring for the opposite reason, a scrub so wide that the reach set
    empties by accident."""
    universe = _credential_names(_tree(tmp_path, leaving=False)) | DENIED

    reaching = _reaching_the_workload(monkeypatch, universe)

    assert universe - reaching == universe & DENIED


def test_SECURITY_names_every_credential_a_worktree_workload_can_read(monkeypatch, tmp_path):
    """The document's table, name for name, against the measurement.

    This is what the paragraph now stakes: SECURITY.md no longer promises that no credential
    reaches the agent — it promises that a name the deny lists carry is removed, and then names
    the ones that are left. Add a credential to the platform without adding it to a deny list and
    this fails until the document says so; scrub one and it fails until the row goes."""
    universe = _credential_names(_tree(tmp_path, leaving=False)) | DENIED

    reaching = _reaching_the_workload(monkeypatch, universe)

    # The count lives in the SENTENCE, not in the table, and it is the only part of the prose a
    # guard can hold: a rewrite that drops the honest framing drops the anchor with it and this
    # goes red instead of quietly publishing a fresh overclaim beside a correct table.
    assert int(_region("reach-count").strip()) == len(reaching)

    documented = _documented_reach()
    assert documented == reaching, (
        "SECURITY.md's table and the code disagree about which credentials reach a worktree "
        f"workload: only in the document {sorted(documented - reaching)}, only in the code "
        f"{sorted(reaching - documented)}")

    # A credential named ANYWHERE ELSE in the document is a reassurance nothing measures — the
    # shape the first two false promises took. Outside the two anchored regions the only variable
    # this file may name is one the scrub actually removes. (Empty today, which is why the twin
    # below runs: an extractor that had stopped extracting would satisfy this by finding nothing.)
    loose = _names_of(_outside_the_regions(
        "reaches-the-agent", "box-allow-list", "reach-count"))
    assert loose <= DENIED, (
        f"SECURITY.md names {sorted(loose - DENIED)} outside its measured table — a credential "
        f"mentioned in prose is a promise no guard here can keep")
    assert _names_of("`GH_TOKEN`, `box.env`, HOME, `docker-compose.yml`") == {"GH_TOKEN"}


def test_SECURITY_names_the_container_boxs_allow_list(monkeypatch, tmp_path):
    """The other half of the paragraph, and the reason it is not alarmist: the DEFAULT box builds
    the workload's environment by allow list, so the table above is the worktree box's exposure
    and not the platform's floor. Held from both ends — the names the document prints are the
    adapter's own, and the adapter passes those plus the project's `box.env` and nothing else,
    measured with every credential this platform reads sitting in the process environment."""
    universe = _credential_names(_tree(tmp_path, leaving=False)) | DENIED
    for name in sorted(universe):
        monkeypatch.setenv(name, f"value-of-{name}")
    declared = sorted(universe - set(_AUTH_ENV_VARS))[0]

    assert _names_of(_region("box-allow-list")) == set(_AUTH_ENV_VARS)
    assert set(ContainerSandbox(image="i")._passthrough_env()) == set(_AUTH_ENV_VARS)
    assert set(ContainerSandbox(image="i", extra_env=(declared,))._passthrough_env()) == (
        set(_AUTH_ENV_VARS) | {declared})


def test_an_add_on_packages_own_credentials_reach_the_workload_the_same_way(tmp_path):
    """The table is measured over the CORE, and the document says so. The credentials an installed
    add-on package brings are not in it and are not scrubbed either — this proves that omission is
    the export boundary and not a scrub nobody noticed, by showing every extra the private tree
    reads is read by the modules that leave."""
    if add_ons.is_public_tree():
        pytest.skip("the add-on packages' modules are not in this tree to measure")
    extra = (_credential_names(ROOT / "openfactory")
             - _credential_names(_tree(tmp_path, leaving=False)))
    assert extra, "no add-on package in this tree reads a credential — nothing to attribute"

    theirs = {n for n in environ.names_read(_tree(tmp_path, leaving=True))
              if _holds_a_credential(n)}
    assert extra <= theirs, (
        f"{sorted(extra - theirs)} are read by the private tree, are outside the core's table, "
        f"and belong to no leaving module — so they are the core's and the table is short")
