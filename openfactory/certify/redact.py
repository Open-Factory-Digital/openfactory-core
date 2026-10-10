"""What never leaves the deployment, and the pseudonyms that stand for it (#356).

A PACK IS ANONYMISED BEFORE IT IS WRITTEN, AND CHECKED AFTER. The partners page promises a customer
that a pack never contains organisation, repository, project or person names, URLs, hostnames,
e-mail addresses or any credential. Each of those is one rule below, and every rule has a guard in
`tests/test_a_pack_names_nobody.py`. And because a rule that is applied is not a rule that held,
`pack.assemble` asks `Redactor.survivors` of every file it is about to write, and refuses to write a
pack in which anything survived — the pack is checked by the same classifier that scrubbed it.

THE RULES, in the order `scrub` applies them:

    variables     the NAME of every variable the registry declares that is not the platform's
                  own — a customer's `CASTELLO_ADO_PAT` names the customer
    credentials   the VALUE of every credential-shaped variable in this environment — the names
                  SECURITY.md lists, the box's deny and allow lists, and any name shaped like one —
                  then every string matching the patterns `org_defaults/floor.yaml`'s security
                  gate scans committed code for (read from the floor, never copied) and the whole
                  PEM block a key header opens, then any long token-shaped run of letters and
                  digits
    urls, e-mail  any scheme://… and any user@host:path, any address
    identifiers   every organisation, repository, project and person the deployment names,
                  replaced by `org-1`, `repo-3`, `project-2`, `person-1`
    paths, hosts  any token with a `/` in it, any dotted name ending in letters, any IPv4 address
                  — a file path inside a customer repository is never carried, and a hostname is
                  dropped whether it is the forge's, the registry's or a file's

PSEUDONYMS ARE STABLE WITHIN A PACK AND UNRELATED ACROSS PACKS. Each category's identifiers are
numbered in the order of an HMAC over a per-pack random salt, so the same repository is `repo-2`
everywhere in one pack and the numbering of the next pack says nothing about this one. The salt is
NEVER written — only `salt_id`, a digest of it — because the salt would let anybody holding a list
of candidate names test them against the pack.

ONE NAME IS KEPT: the practitioner's (`--practitioner`), the partner's engineer who answers for the
deployment. It is the partner's own data and the reason a pack can be attributed at all.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections import Counter
from collections.abc import Iterable, Mapping

from openfactory.certify.controls import Pseudonyms

#: Each category, and the prefix its pseudonyms carry.
CATEGORIES: dict[str, str] = {
    "organisation": "org",
    "repository": "repo",
    "project": "project",
    "person": "person",
}

#: The credential names SECURITY.md lists: its measured "reaches the agent" table and the container
#: box's allow list. HELD EQUAL TO THE DOCUMENT by `tests/test_a_pack_names_nobody.py`, which reads
#: both regions and fails when a name there is not here.
SECURITY_NAMES = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "OPENAI_API_KEY",
    "AZURE_API_KEY", "AZURE_DEVOPS_PAT", "JIRA_API_TOKEN", "OPENFACTORY_PANEL_TOKEN",
    "OPENFACTORY_PANEL_TOKENS", "OPENFACTORY_PRODUCT_TOKEN", "OPENFACTORY_PRODUCT_TOKENS",
    "TEMPORAL_API_KEY", "TEMPORAL_TLS_KEY",
)

#: The words that make a variable's NAME say it holds a secret, and the last words that say it
#: holds something ABOUT one (the variable's name, a file path, an address).
_SECRET_WORDS = frozenset({"TOKEN", "TOKENS", "KEY", "SECRET", "PASSWORD", "PAT", "PASS",
                           "CREDENTIALS", "CONTENT"})
_ABOUT_A_SECRET = frozenset({"ENV", "FILE", "PATH", "URL", "NAME", "VAR"})

#: The shortest value treated as a secret. A three-character value is not a credential, and
#: dropping every "123" from a report would make it unreadable without protecting anything.
_SHORTEST_SECRET = 6

#: The platform's own words a token rule would otherwise drop: its file names, its paths, its
#: schema ids, the pack's own file names. None of them names a customer.
PLATFORM_WORDS = frozenset({
    ".env.compose", ".env.compose.example", "~/.openfactory/env", ".openfactory/**",
    ".openfactory/project.yaml", "project.yaml", "docker-compose.yml", "registry.yaml",
    "org_defaults/floor.yaml", "floor.yaml", "box.env", "platform.version", "pack.json",
    "pack.sig", "summary.md", "redactions.json", "n/a", "SECURITY.md",
})
_PLATFORM_SHAPES = re.compile(
    r"(diagnostics/[a-z0-9.-]+\.(json|txt)(#[a-z_]+)?|openfactory\.[a-z.-]+/\d+"
    r"|(linux|darwin|windows)/[a-z0-9_]+)")

#: A whole PEM block, header to footer: the floor's pattern finds the header, and the body between
#: it and the footer is the key itself.
_PEM = re.compile(r"-----BEGIN [A-Z ]+-----.*?-----END [A-Z ]+-----", re.S)
_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"`<>]+")
_SCP = re.compile(r"\b[\w.-]+@[\w.-]+:[\w./~-]+")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_HOST = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_IPV4 = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?")
_LONG_TOKEN = re.compile(r"(?<![A-Za-z0-9_+=/-])[A-Za-z0-9_+=/-]{32,}(?![A-Za-z0-9_+=/-])")
_DIGEST = re.compile(r"sha256:[0-9a-f]{12,64}…?")
_EDGE = "`'\"()[]{}<>,;:!?"
_TOKEN = re.compile(r"\S+")


def credential_names() -> frozenset[str]:
    """Every variable name this core treats as a credential: SECURITY.md's, and the box's lists."""
    from openfactory.adapters.sandbox.container import _AUTH_ENV_VARS
    from openfactory.adapters.sandbox.worktree import (
        _AGENT_CRED_VARS,
        _AWS_CRED_VARS,
        _FORGE_CRED_VARS,
        _PANEL_SECRET_VARS,
    )

    return frozenset(SECURITY_NAMES + tuple(_AUTH_ENV_VARS) + _AWS_CRED_VARS + _FORGE_CRED_VARS
                     + _AGENT_CRED_VARS + _PANEL_SECRET_VARS)


def holds_a_credential(name: str) -> bool:
    """Whether a variable NAMED this holds a secret — listed, or shaped like one."""
    if name in credential_names():
        return True
    words = name.upper().split("_")
    return bool(set(words) & _SECRET_WORDS) and words[-1] not in _ABOUT_A_SECRET


def floor_credential_pattern() -> re.Pattern[str]:
    """The pattern `org_defaults/floor.yaml`'s security gate greps committed code for — READ FROM
    THE FLOOR, so a format the gate learns is a format the pack drops, with no second list.

    RAISES when the floor cannot be read or no longer carries a `git grep -nIE "…"`: a pack that
    could not know which strings are credentials is a pack that must not be written."""
    from openfactory.policy.presets import org_default_validation

    gate = (org_default_validation() or {}).get("security")
    command = gate.get("command", "") if isinstance(gate, dict) else str(gate or "")
    found = re.search(r'git grep -nIE\s+"([^"]+)"', command)
    if not found:
        raise ValueError("the deployment's floor (org_defaults/floor.yaml) carries no credential "
                         "pattern to drop by, so no pack can be written safely")
    return re.compile(found.group(1), re.M)


def salt_id(salt: bytes) -> str:
    """What the pack records about its salt: a digest, never the salt."""
    return hashlib.sha256(b"openfactory.certify/salt-id\0" + salt).hexdigest()[:16]


class Redactor(Pseudonyms):
    """The pack's pseudonyms, its scrubber, and the log of everything it replaced or dropped.

    `identifiers` is `{category: {identity: aliases}}` — the repository `acme/web` with the
    aliases `web` and its proof key. Every identity and alias in a category maps to that identity's
    one pseudonym. `secrets` are values that must never appear, whatever surrounds them."""

    def __init__(self, *, salt: bytes, identifiers: Mapping[str, Mapping[str, Iterable[str]]],
                 secrets: Iterable[str] = (), variables: Iterable[str] = (),
                 keep: str = "") -> None:
        self.salt = salt
        self.salt_id = salt_id(salt)
        self.keep = keep
        self.pseudonyms: dict[str, str] = {}  # pseudonym → category
        self._identity: dict[tuple[str, str], str] = {}  # (category, identity) → pseudonym
        self._matches: dict[str, str] = {}  # lowercased identifier or alias → pseudonym
        self.replaced: Counter[tuple[str, str]] = Counter()  # (file, category)
        self.dropped: Counter[tuple[str, str]] = Counter()  # (file, category)
        self.fields_dropped: list[dict] = []
        # PRIORITY, for a bare string two categories claim (a project named like its repository's
        # leaf): whichever is matched first hides it, and the project's own name wins.
        for category in ("project", "repository", "organisation", "person"):
            given = identifiers.get(category) or {}
            order = sorted((i for i in given if len(i.strip()) >= 2), key=lambda i: hmac.new(
                salt, f"{category}\0{i}".encode(), hashlib.sha256).digest())
            for n, identity in enumerate(order, start=1):
                pseudonym = f"{CATEGORIES[category]}-{n}"
                self.pseudonyms[pseudonym] = category
                self._identity[(category, identity)] = pseudonym
                for name in (identity, *given[identity]):
                    name = (name or "").strip()
                    if len(name) >= 2:
                        self._matches.setdefault(name.lower(), pseudonym)
        names = sorted(self._matches, key=len, reverse=True)
        self._names = re.compile(
            r"(?<![A-Za-z0-9_])(" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z0-9_])",
            re.I) if names else None
        self._secrets = sorted({s for s in secrets if s and len(s) >= _SHORTEST_SECRET},
                               key=len, reverse=True)
        chosen = sorted({v for v in variables if v and len(v) >= 2}, key=len, reverse=True)
        self._variables = re.compile(
            r"(?<![A-Za-z0-9_])(" + "|".join(re.escape(v) for v in chosen) + r")(?![A-Za-z0-9_])"
        ) if chosen else None
        self._floor = floor_credential_pattern()

    # ── pseudonyms (`controls.Pseudonyms`) ──────────────────────────────────────────────────────

    def project(self, name: str) -> str:
        return self._identity.get(("project", name)) or self._unnamed("project")

    def repository(self, identity: str) -> str:
        return self._identity.get(("repository", identity)) or self._unnamed("repository")

    def person(self, name: str) -> str:
        return self._identity.get(("person", name)) or self._unnamed("person")

    def _unnamed(self, category: str) -> str:
        # A NAME NOBODY REGISTERED IS STILL NOT PRINTED. Reaching here is a defect in gathering;
        # the answer is a placeholder, never the original.
        return f"{CATEGORIES[category]}-unnamed"

    # ── the scrubber ────────────────────────────────────────────────────────────────────────────

    def scrub(self, text: str, *, where: str) -> str:
        """`text` with every rule applied, the replacements and drops counted under `where`."""
        return self._apply(text, where=where, record=True)

    def survivors(self, text: str) -> list[str]:
        """The categories of everything in `text` that `scrub` would still replace — `[]` for a
        clean text. The practitioner's name is taken out first: it is the one name a pack keeps."""
        if self.keep:
            # AS A WHOLE NAME, never as letters: a practitioner called `x` must not take every `x`
            # out of the text before it is read.
            text = re.sub(r"(?<![A-Za-z0-9_])" + re.escape(self.keep) + r"(?![A-Za-z0-9_])", " ",
                          text)
        found: Counter[str] = Counter()
        self._apply(text, where="", record=False, found=found)
        return sorted(found)

    def _apply(self, text: str, *, where: str, record: bool,
               found: Counter[str] | None = None) -> str:
        def drop(category: str, mark: str):
            def replace(_match: re.Match[str]) -> str:
                if record:
                    self.dropped[(where, category)] += 1
                if found is not None:
                    found[category] += 1
                return mark
            return replace

        for secret in self._secrets:
            if secret in text:
                count = text.count(secret)
                if record:
                    self.dropped[(where, "credential")] += count
                if found is not None:
                    found["credential"] += count
                text = text.replace(secret, "[credential]")
        if self._variables is not None:
            text = self._variables.sub(drop("variable", "[variable]"), text)
        text = _PEM.sub(drop("credential", "[credential]"), text)
        text = self._floor.sub(drop("credential", "[credential]"), text)
        text = _URL.sub(drop("url", "[url]"), text)
        text = _SCP.sub(drop("url", "[url]"), text)
        text = _EMAIL.sub(drop("email", "[email]"), text)
        if self._names is not None:
            def rename(match: re.Match[str]) -> str:
                pseudonym = self._matches[match.group(1).lower()]
                category = self.pseudonyms[pseudonym]
                if record:
                    self.replaced[(where, category)] += 1
                if found is not None:
                    found[category] += 1
                return pseudonym
            text = self._names.sub(rename, text)
        return _TOKEN.sub(lambda m: self._token(m.group(0), drop), text)

    def _token(self, token: str, drop) -> str:
        """One whitespace-delimited token: a path, a host, an address or a long secret-shaped run
        is dropped; the platform's own words and the pack's own names are kept."""
        core = token.strip(_EDGE).rstrip(".")
        if not core or core in PLATFORM_WORDS or core in self.pseudonyms \
                or _PLATFORM_SHAPES.fullmatch(core):
            return token
        start = token.find(core)
        before, after = token[:start], token[start + len(core):]
        if "/" in core and not re.fullmatch(r"[\d/]+", core):
            return before + drop("path", "[path]")(None) + after
        if _IPV4.fullmatch(core) or _HOST.fullmatch(core):
            return before + drop("host", "[host]")(None) + after
        long = _LONG_TOKEN.search(core)
        if long and re.search(r"\d", long.group(0)) and re.search(r"[A-Za-z]", long.group(0)) \
                and not _DIGEST.fullmatch(core) and not _is_a_digest(core, long):
            return before + core[:long.start()] + drop("credential", "[credential]")(None) \
                + core[long.end():] + after
        return token

    def scrub_document(self, document, *, where: str):
        """Every string in a JSON-shaped document scrubbed — keys and values alike."""
        if isinstance(document, dict):
            return {self.scrub(str(k), where=where): self.scrub_document(v, where=where)
                    for k, v in document.items()}
        if isinstance(document, list):
            return [self.scrub_document(v, where=where) for v in document]
        if isinstance(document, str):
            return self.scrub(document, where=where)
        return document

    def drop_field(self, *, where: str, field: str, why: str) -> None:
        self.fields_dropped.append({"file": where, "field": field, "why": why})

    def log(self) -> dict:
        """`redactions.json`: every pseudonym and its category — NEVER the original — every count
        of what was replaced and dropped, file by file, and every field left out on purpose."""
        return {
            "schema": "openfactory.certify.redactions/1",
            "salt_id": self.salt_id,
            "pseudonyms": dict(sorted(self.pseudonyms.items())),
            "replaced": [{"file": f, "category": c, "count": n}
                         for (f, c), n in sorted(self.replaced.items())],
            "dropped": [{"file": f, "category": c, "count": n}
                        for (f, c), n in sorted(self.dropped.items())],
            "fields_dropped": sorted(self.fields_dropped,
                                     key=lambda d: (d["file"], d["field"])),
            # EVERY FIELD CARRIED VERBATIM (review of #549): a reader auditing a pack against
            # this log found the partner and the profile in it and no line accounting for them
            "kept": list(KEPT),
        }


def what_a_name_carries(name: str) -> list[str]:
    """What a pack would drop from `name` — an e-mail address, a URL, a host, a path, a credential —
    by the very rules every other string of it passes; `[]` for a person's name.

    THE ONE FIELD THE RULES DO NOT READ (review of #549). The practitioner is kept verbatim and
    taken out WHOLE before a text is classified, so whatever was typed into `--practitioner` passed
    every rule: `helena.prado@altiva.io` reached `pack.json` and `summary.md`, and `redactions.json`
    called it a kept name, in a pack whose own promise is "no URLs, hostnames, e-mail addresses or
    any credential". So the rules are asked of it before it is kept."""
    return Redactor(salt=b"practitioner", identifiers={}).survivors(name)


#: What a pack carries as it was typed, past every rule, and why each is not a customer's: the
#: practitioner is the partner's engineer (`what_a_name_carries` holds it to a name), the partner
#: a slug the partners repository gave it, the profile one of the program's own words.
KEPT = ("practitioner", "partner", "profile")


def _is_a_digest(core: str, long: re.Match[str]) -> bool:
    """A content digest (`sha256:` and hex) is the proof's pin, not a secret."""
    return core[:long.start()].endswith("sha256:") and re.fullmatch(r"[0-9a-f]+", long.group(0)) \
        is not None
