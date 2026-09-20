"""The listeners a deployment runs, defined ONCE: where each starts, and how it is reached (#183).

NOBODY OWNED A DEPLOYMENT'S ADDRESSES. Every listener was STARTED in one place with a literal port
and REACHED from others that each re-derived the address on their own — a literal, a fallback, a
variable nothing guaranteed matched what was started. Read on `main` at `1512d0a`:

    engine     started by `up` on a literal 7233   reached by `TEMPORAL_ADDRESS`, raising unset
    engine UI  started on a literal 8080          reached by `TEMPORAL_UI_URL`, else GUESSED 8233
    panel      `--panel-port`, literal 8787       `OPENFACTORY_PANEL_URL`, else GUESSED 8787

`up` started the engine's UI on 8080 and the panel linked to 8233, so **Engine ↗** on a running
card answered `ERR_CONNECTION_REFUSED` beside a healthy engine. It was the third time: #163 made
the engine ADDRESS refuse to guess, and the compose file patched its own copy of the UI link by
hand (`TEMPORAL_UI_URL`, with a comment saying every engine link 404'd until it was set). Each fix
taught one consumer one address; the two sides still agreed only by coincidence.

SO THE TABLE LIVES HERE AND EVERYTHING ELSE READS IT. It grew out of `preflight.PUBLISHED_PORTS`,
which already named the three listeners and the variable that moves each port — and which only
preflight read. `PUBLISHED_PORTS` is now derived from `LISTENERS`, so there is still one table.

THE STARTER SAYS WHAT IT STARTED. `started_by_up` resolves, from the deployment's own environment,
the port each listener `openfactory up` starts on AND the address every consumer is handed — one
computation, so they cannot differ — and `Started.env` is what `up` gives each child. What the
operator declared is honoured (`TEMPORAL_ADDRESS=localhost:7300` starts the engine on 7300) or
refused in a sentence (`CannotHonour`); it is never started on one port while its consumers look
at another.

A LEAF ON PURPOSE: the standard library and nothing else. `connection.py` imports `temporalio`,
`preflight.py` imports the onboarding package, and this is read by both of them, by the local
board's rows, by the doctor and by `init` — the only module all of those can import without a
cycle or an engine client is one that imports none of them.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class Listener:
    """One thing a deployment listens on: where it starts, and how a consumer reaches it."""

    #: What a sentence calls it.
    name: str
    #: The variable that moves the port it is STARTED on (`docker-compose.yml` publishes through
    #: it, `openfactory up` starts on it).
    port_var: str
    #: The port it starts on when nobody said otherwise — the ONE place this number is written.
    default_port: int
    #: The variables a consumer reads to REACH it, in precedence order. Setting one is what
    #: "declared" means everywhere in this module.
    reach_vars: tuple[str, ...]
    #: `""` for a `host:port` a client dials (gRPC); `"http"` for a URL a person opens.
    scheme: str = ""

    def local(self, port: int | None = None) -> str:
        """How this listener is reached on the machine that started it."""
        where = f"localhost:{port or self.default_port}"
        return f"{self.scheme}://{where}" if self.scheme else where

    def declared(self, env: Mapping[str, str] | None = None) -> str:
        """What this deployment said about reaching it, or `""` when nobody said anything.

        READ AT CALL TIME, and never defaulted: "nobody said" is a fact about the deployment, and
        each consumer decides what it honestly means — the engine's client raises (#163), a link
        a person clicks is not drawn."""
        source = os.environ if env is None else env
        for var in self.reach_vars:
            found = (source.get(var) or "").strip()
            if found:
                return found
        return ""

    def where(self, value: str) -> tuple[str, int | None]:
        """`(host, port)` of a declared value; the port is None when it names none.

        Raises `ValueError` for a value that cannot be read — a port that is not a number, a URL
        with no host — which `started_by_up` turns into a sentence."""
        parts = urlsplit(value if self.scheme else f"//{value}")
        if not parts.hostname or (self.scheme and parts.scheme not in ("http", "https")):
            raise ValueError(value)
        port = parts.port   # raises ValueError itself on `localhost:abc`
        if port is None and self.scheme:
            port = 443 if parts.scheme == "https" else 80
        return parts.hostname, port

    def unsaid(self) -> str:
        """The sentence for a surface that has no address to show — what to set, and who sets it
        for you."""
        return (f"nobody said where this deployment's {self.name} is — set "
                f"`{self.reach_vars[0]}` (for one on this machine, `{self.local()}`); "
                f"`openfactory up` says it to everything it starts")

    def elsewhere(self, value: str) -> bool:
        """Whether a declared value names ANOTHER machine. False for `""` and for a value that
        cannot be read — neither says the listener is somebody else's to start."""
        try:
            return bool(value) and self.where(value)[0] not in _THIS_MACHINE
        except ValueError:
            return False

    def moved_to(self, value: str, port: int) -> str:
        """`value` with its port replaced — the host, scheme and path as they were declared."""
        parts = urlsplit(value if self.scheme else f"//{value}")
        host = parts.hostname or "localhost"
        netloc = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
        moved = urlunsplit(parts._replace(netloc=netloc))
        return moved if self.scheme else moved.removeprefix("//")


ENGINE = Listener("engine", "TEMPORAL_PORT", 7233, ("TEMPORAL_ADDRESS", "TEMPORAL_ENDPOINT"))
ENGINE_UI = Listener("engine UI", "TEMPORAL_UI_PORT", 8080, ("TEMPORAL_UI_URL",), "http")
PANEL = Listener("panel", "PANEL_PORT", 8787, ("OPENFACTORY_PANEL_URL",), "http")

#: Every listener, in the order preflight has always listed them: 8080 is the single most contended
#: port on a developer machine — on the machine this stack was first run on it was already held by
#: a client's own web app — which is why every port is movable and why a collision is named BEFORE
#: the stack starts rather than after.
LISTENERS: tuple[Listener, ...] = (PANEL, ENGINE_UI, ENGINE)

#: The spellings of "this machine" a declaration may use. A name `up` cannot prove is this machine
#: (a proxy, a tunnel's far end) is not in here, and is treated as somewhere else.
_THIS_MACHINE = frozenset({"localhost", "127.0.0.1", "::1"})


class CannotHonour(ValueError):
    """The deployment declared an address `openfactory up` cannot start a listener on.

    ITS OWN TYPE so the front end can say the sentence and exit, instead of starting a listener
    its consumers will not look at — the split this module exists to end."""


@dataclass(frozen=True)
class Started:
    """What `openfactory up` starts, and what it tells everything it starts."""

    #: The port each listener starts on, by `Listener.name`. Only what is actually started.
    ports: dict[str, int] = field(default_factory=dict)
    #: How each started listener is reached, by `Listener.name`.
    reach: dict[str, str] = field(default_factory=dict)
    #: The variables to ADD to every child's environment: the first reach variable of each
    #: listener whose address the deployment did not already say, or said differently from the
    #: port this run was told to use.
    env: dict[str, str] = field(default_factory=dict)
    #: Sentences for the person who ran `up` — one per declaration this run did not follow.
    said: tuple[str, ...] = ()

    def child_env(self, env: Mapping[str, str] | None = None) -> dict[str, str]:
        """The environment a child is started with: the parent's, plus what was just resolved."""
        return {**(os.environ if env is None else env), **self.env}


def _port(listener: Listener, env: Mapping[str, str]) -> int | None:
    raw = (env.get(listener.port_var) or "").strip()
    if not raw:
        return None
    if not raw.isdigit() or not 0 < int(raw) < 65536:
        raise CannotHonour(
            f"`{listener.port_var}` is `{raw}`, which is not a port — it is where the "
            f"{listener.name} starts, so say a number (the default is {listener.default_port}) "
            f"or remove the line")
    return int(raw)


def _resolve(listener: Listener, env: Mapping[str, str], *, asked: int | None = None
             ) -> tuple[int, str, str, bool]:
    """`(port, reach, said, publish)` for one listener `up` is about to start."""
    wanted = _port(listener, env)
    declared = listener.declared(env)
    var = next((v for v in listener.reach_vars if (env.get(v) or "").strip()),
               listener.reach_vars[0])
    if not declared:
        port = asked or wanted or listener.default_port
        return port, listener.local(port), "", True
    try:
        host, at = listener.where(declared)
    except ValueError:
        shape = "a URL such as" if listener.scheme else "`host:port`, such as"
        raise CannotHonour(
            f"`{var}` is `{declared}`, which does not say where the {listener.name} is — write "
            f"{shape} `{listener.local()}`, or remove the line and `up` says it for "
            f"you") from None
    if host not in _THIS_MACHINE:
        if not listener.scheme:
            # A CLIENT DIALS THIS ONE. Starting a second engine here would leave the worker and
            # the panel talking to the declared one while this one ran unused — the split.
            raise CannotHonour(
                f"`{var}` is `{declared}`, which is not this machine, and `up` starts the "
                f"{listener.name} HERE — the worker and the panel would talk to that one while "
                f"this one ran unused. Say `{var}={listener.local(at)}` to run it here, or pass "
                f"`--no-engine` to serve the panel against the one you declared")
        # A URL A PERSON OPENS may be a name in front of this machine (a proxy, a tunnel). `up`
        # cannot know the mapping, so the declaration stands and the listener starts where the
        # port variable says.
        return asked or wanted or listener.default_port, declared, "", False
    if at is None:
        raise CannotHonour(
            f"`{var}` is `{declared}`, which names no port — say `{var}="
            f"{listener.local()}`, or remove the line and `up` says it for you")
    if asked and asked != at:
        # THE COMMAND LINE IS THE MOST RECENT THING THE PERSON SAID, and it is about the same
        # listener on the same machine — so this run follows it, out loud, and hands its children
        # the moved address rather than the one the file still carries.
        moved = listener.moved_to(declared, asked)
        return asked, moved, (
            f"`{var}` says {declared} and this run was asked for port {asked}: the "
            f"{listener.name} starts on {asked} and every link this run writes uses {moved} — "
            f"change `{var}` to make it permanent"), True
    if wanted and wanted != at:
        raise CannotHonour(
            f"`{listener.port_var}={wanted}` and `{var}={declared}` are both about the "
            f"{listener.name} on this machine and name different ports — `up` would start it on "
            f"one while everything that reaches it looked at the other. Make them agree, or "
            f"remove one")
    return at, declared, "", False


def started_by_up(env: Mapping[str, str] | None = None, *, panel_port: int | None = None,
                  durable: bool = True) -> Started:
    """What `openfactory up` starts in this environment, and what it tells its children.

    ONE COMPUTATION FOR BOTH SIDES. The port a listener starts on and the address its consumers
    are handed come out of the same call, which is the whole fix: they used to be two literals in
    two files. `durable=False` is an `up` with no engine to start — only the panel is resolved,
    and nothing is said about an engine this run does not own.

    Raises `CannotHonour`, with the sentence to print, for a declaration it cannot start on.
    """
    source = os.environ if env is None else env
    ports: dict[str, int] = {}
    reach: dict[str, str] = {}
    publish: dict[str, str] = {}
    said: list[str] = []
    wanted = [(ENGINE, None), (ENGINE_UI, None)] if durable else []
    for listener, asked in (*wanted, (PANEL, panel_port)):
        port, where, sentence, tell = _resolve(listener, source, asked=asked)
        ports[listener.name], reach[listener.name] = port, where
        if tell:
            publish[listener.reach_vars[0]] = where
        if sentence:
            said.append(sentence)
    return Started(ports=ports, reach=reach, env=publish, said=tuple(said))
