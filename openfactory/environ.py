"""The environment variables this platform answers to, and the deployment facts nobody may assume.

Every configuration variable carries the product's name (`OPENFACTORY_*`, #106 item 8). The
surface used to carry an acronym, and for a while each entrypoint's composition root copied the
old spelling onto the new one at boot; that shim left on 2026-08-25 with the decision that the
public repository has no old installation to serve. Code reads `OPENFACTORY_*` and nothing else,
and the guard in `tests/test_the_environment_carries_the_products_name.py` holds every module to
it — a second read path for a second spelling is how a secret ends up under two names, one of
which every scrub list forgets.
"""

from __future__ import annotations

import ast
import functools
import logging
import os
import re
from pathlib import Path

from openfactory import namespace

log = logging.getLogger("openfactory.environ")

#: The prefix every configuration variable of this platform carries.
ENV_PREFIX = "OPENFACTORY_"

#: What it used to be — served by nothing, and RESERVED so no add-on takes it up. The adoption
#: shim that copied the old spelling onto the new one left on 2026-08-25; a variable under this
#: prefix is now read by no module at all, which is exactly why an add-on may not name its own
#: after it: an operator's environment still carries the old names, and a role whose model
#: override were `SDLC_QA_MODEL` would bind that leftover the day it is set. Derived from the
#: one place the former name is spelled (`namespace.py`, in order to refuse it) — the directory
#: was `.<name>/`, the environment prefix `<NAME>_` — so this module never spells it.
RETIRED_ENV_PREFIX = namespace.RETIRED_DIR.lstrip(".").upper() + "_"

#: What an environment variable's name looks like. A bare word (`HOME`, `PATH`) is the operating
#: system's and never a configuration key of anything here, so a key is an upper-case word with
#: at least one underscore — the same shape `RoleSpec` demands of an add-on's own two names.
ENV_NAME_SHAPE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)+$")

#: The mapping methods a read goes through, by literal key.
_READ_METHODS = frozenset({"get", "getenv", "pop", "setdefault"})


def _env_shaped(node: ast.AST) -> str | None:
    """The env-shaped string this constant node is, or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str) \
            and ENV_NAME_SHAPE.match(node.value):
        return node.value
    return None


def _reads_environ(node: ast.AST) -> ast.AST | None:
    """The KEY expression when `node` reads `os.environ` / `os.getenv` by any key, else None."""
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) \
            and node.value.attr == "environ":
        return node.slice
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args:
        owner = node.func.value
        if node.func.attr == "getenv" and isinstance(owner, ast.Name) and owner.id == "os":
            return node.args[0]
        if node.func.attr in _READ_METHODS and isinstance(owner, ast.Attribute) \
                and owner.attr == "environ":
            return node.args[0]
    return None


def _callee(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _key_of(expr: ast.AST, bound: dict[str, str]) -> str | None:
    """The env-shaped name a read's key expression spells: the literal itself (shape 1) or the
    module-level constant it names (shape 4)."""
    if isinstance(expr, ast.Name):
        return bound.get(expr.id)
    return _env_shaped(expr)


@functools.cache
def names_read(root: Path | None = None) -> frozenset[str]:
    """Every environment variable the code under `root` reads BY NAME — derived, once, cached.

    THIS IS A DERIVATION AND NOT A TABLE, because the table was measured twice and was wrong
    both times. A table of twelve names in the harness registry sat beside fifty-eight other
    `OPENFACTORY_*` reads it did not know about (2026-08-25); its replacement, a table of the
    twenty-one foreign names an AST scan could see, was EXACTLY the set the scan could see — so the
    guard that "kept it complete" could never fail, and the six names the platform reads through
    a table or a default argument (`OPENAI_API_KEY`, `SLACK_BOT_TOKEN`, …) were handed to a
    harness as a model name by an add-on that claimed them (2026-08-26). A name is reserved the
    day a module reads it, with nothing to remember to update.

    FOUR SHAPES OF READ — two of them are how the misses above happened, and the fourth is
    where the next one would have been:

      1. a literal key at the read — `os.environ.get("X")`, `os.environ["X"]`, `os.getenv("X")`,
         and `<anything>.get("X")` — the receiver is deliberately not checked, since the
         environment travels under aliases (`e`, `env`, `present`) and a false reservation costs
         an add-on one spelling while a missed one hands it a secret;
      2. a NAMES TABLE — a tuple, list, set or dict-of-values made only of env-shaped strings —
         which is how a route says what it requires, how a scrub list says what may not pass, and
         how the vendor-default credentials are spelled; `__all__` is a list of exports and is
         skipped;
      3. a literal handed to a function that reads ITS PARAMETER from the environment
         (`_resolve_token(configured, "SLACK_BOT_TOKEN")`), found by name across the package;
      4. a literal bound to a module-level name that a read in the same module uses
         (`ENDPOINT_OVERRIDE = "…"; e.get(ENDPOINT_OVERRIDE)`).

    Names built at runtime from a project's configuration (`box.env`, a `*_env` option) are that
    deployment's and are not here: the reservation is about what the CODE reads.

    `root` is the package by default and a parameter so a test can plant a read in a scratch tree
    and watch the reservation grow — the proof that this is live and not another list. It may
    also be ONE FILE: a row asking what its own module reads (`plugins.environment`)."""
    base = root if root is not None else Path(__file__).resolve().parent
    paths = [base] if base.is_file() else sorted(base.rglob("*.py"))
    trees = [ast.parse(path.read_text(encoding="utf-8")) for path in paths]

    # pass 1: functions that read whichever name they are handed
    readers: set[str] = set()
    for tree in trees:
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            params = {a.arg for a in (*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs)}
            for node in ast.walk(fn):
                key = _reads_environ(node)
                if key is not None and params & {n.id for n in ast.walk(key)
                                                 if isinstance(n, ast.Name)}:
                    readers.add(fn.name)

    # pass 2: the names
    names: set[str] = set()
    for tree in trees:
        exports = {id(node.value) for node in ast.walk(tree)
                   if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)}
        bound = {node.targets[0].id: _env_shaped(node.value) for node in tree.body
                 if isinstance(node, ast.Assign) and len(node.targets) == 1
                 and isinstance(node.targets[0], ast.Name) and _env_shaped(node.value)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in _READ_METHODS and node.args:
                names.add(_key_of(node.args[0], bound))                            # shapes 1, 4
            elif isinstance(node, ast.Subscript):
                names.add(_key_of(node.slice, bound))                              # shapes 1, 4
            elif isinstance(node, (ast.Tuple, ast.List, ast.Set)) and node.elts \
                    and id(node) not in exports:
                found = [_env_shaped(e) for e in node.elts]
                if all(found):
                    names.update(found)                                            # shape 2
            elif isinstance(node, ast.Dict) and node.values:
                found = [_env_shaped(v) for v in node.values]
                if all(found):
                    names.update(found)                                            # shape 2
            if isinstance(node, ast.Call) and _callee(node) in readers:
                names.update(_env_shaped(a) for a in node.args)                    # shape 3
    names.discard(None)
    return frozenset(names)


def reserved(name: str, *, root: Path | None = None) -> str | None:
    """Why `name` may not be an add-on's own variable — or None, which means it may.

    Two reasons, and neither is a list of our names. Anything under `ENV_PREFIX` is this
    platform's configuration surface whether or not a module reads it today — an add-on whose
    model override were `OPENFACTORY_HOME` would bind a path as a model the day one is set — and
    the old spelling of that prefix is reserved with it: nothing serves it any more, and a name
    that nothing serves is the one an operator's leftover environment fills. And a foreign tool's
    variable this platform reads (`names_read`, derived from the code) already means what that
    tool says it means: two facts in one value.

    AN INSTALLATION THAT SHIPS NO SOURCES CANNOT ANSWER, and says so instead of reserving
    nothing: a scan that finds no reads is a broken install, not a platform that reads nothing
    (this module alone reads three names), and an add-on refused for that reason is the safe
    direction — every shipped role still resolves from its tables."""
    for prefix, whose in ((ENV_PREFIX, "this platform's own configuration namespace"),
                          (RETIRED_ENV_PREFIX, "the old spelling of this platform's namespace, "
                                               "which nothing serves and no add-on may take up")):
        if name.startswith(prefix):
            return f"under {prefix}*, {whose}"
    read = names_read(root)
    if not read:
        return ("unverifiable: this installation ships no readable sources, so the variables the "
                "platform reads cannot be derived and none is free until they can")
    if name in read:
        return "a variable of a tool this platform drives, read with the meaning that tool gives it"
    return None


class NotDeclared(RuntimeError):
    """A deployment-varying value nobody declared (#163).

    ITS OWN TYPE so a caller can tell it apart from the thing failing. The alternative — a
    literal default — is what put the FIRST deployment's region and SSM tree inside neutral code:
    a second install reads somebody else's parameter tree, or nothing, and the failure it sees is
    "not found" rather than "you did not say".
    """


#: Both names AWS itself answers to. One module read the second as a fallback and the other four
#: never did, so a deployment that set only `AWS_REGION` — which boto3 honours — was read as
#: having declared nothing by four of the five.
REGION_VARS = ("AWS_DEFAULT_REGION", "AWS_REGION")


def cloud_region(*, required: bool = False) -> str:
    """The cloud region this deployment declared, or `""` — never another one's (#163).

    `eu-west-2` was the literal in four modules, and it is the first deployment's. Two of those
    four are the panel, where a region only decides a LINK and an invented one merely points an
    operator at the wrong console; the other two are boto3 clients, where it decides WHICH ACCOUNT
    IS READ. `required=True` is for the second kind.

    A REGION IS A CLOUD'S WORD, and this product's default shape has no cloud at all (2026-08-14:
    *"I never set up anything on amazon… this scenario here is 100% free"*), so absence is an
    ordinary answer and not an error until somebody is about to make a cloud call.
    """
    for var in REGION_VARS:
        found = (os.environ.get(var) or "").strip()
        if found:
            return found
    if not required:
        return ""
    raise NotDeclared(
        "this deployment does not say which cloud region it runs in: set "
        + " or ".join(f"`{v}`" for v in REGION_VARS)
        + ". Nothing is assumed, because the default that used to be here was the first "
        "deployment's, and a second install would have read that account's resources or none.")


#: What the terraform in this repository calls the same thing (`var.ssm_prefix`). Named here so
#: the two spellings of one value are visible from each other.
SSM_PREFIX_VAR = "OPENFACTORY_SSM_PREFIX"


def ssm_prefix() -> str:
    """Where this deployment keeps its parameters, or `""` when it never said (#163).

    `/openfactory/agent-tokens` was a literal in `api/app.py` while the terraform beside it built
    that path from `var.ssm_prefix` — so a deployment that set the variable, as it is meant to,
    had its panel read a tree that does not exist in its account. Empty means the caller must not
    guess: the panel falls back to the pool it can see in its own environment, which is a
    different and honestly-labelled answer.
    """
    return (os.environ.get(SSM_PREFIX_VAR) or "").strip().rstrip("/")
