"""Checking an evidence pack offline: `openfactory certify verify <pack.tgz>` (#356).

THE SUBMISSIONS BOT RUNS EXACTLY THIS, so a partner who runs it first sees the bot's answer before
submitting. It reads the tarball in memory — nothing is extracted, nothing is fetched — and
answers four questions about the pack itself, then each threshold:

    contents    every member a regular file under a plain relative name, none twice
    schema      `pack.json` against the published schema (`schema.validate`, the one the writer
                validated against before writing)
    checksums   `SHA256SUMS` lists every other file and each digest holds; `pack.json`'s own
                `checksums` hold too, and the two lists agree
    signature   not built yet: an unsigned pack is a finding, unless `--allow-unsigned`
    T-*         every threshold in `thresholds.yaml` (or the `--thresholds` file), BY ID

Exit 0: everything held. Exit 1: one finding per failure, each under the id of what failed. Exit
2: the pack cannot be read at all (not a gzipped tarball, no `pack.json`, `pack.json` not JSON) or
the thresholds file cannot be used — no answer about the pack is given then, rather than a
partial one.

TWO RULES NO THRESHOLD FILE CAN BEND. An `unknown` control is never a pass: `required_controls`
accepts `pass` and `info` at most, and a file asking it to accept anything else is refused. An
outcome the pack says was not measured fails its threshold as "not measured", with the pack's
reason — never as a zero, which would say the deployment did nothing.

THE SIGNATURE. Minisign signs with Ed25519, which the standard library does not have, and this
package takes no cryptography dependency for one command. Until that decision is made (a
dependency, or the `minisign` binary), every pack is unsigned and `verify` says so as a finding.
`--allow-unsigned` exists so a partner can rehearse everything else; the submissions bot must
never pass it.
"""

from __future__ import annotations

import hashlib
import json
import re
import tarfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from openfactory.certify import controls as c

#: The thresholds the core ships, read when no `--thresholds` file is given.
THRESHOLDS_FILE = Path(__file__).with_name("thresholds.yaml")

#: The schema id a thresholds file carries.
THRESHOLDS_SCHEMA = "openfactory.certify.thresholds/1"

#: The pack's own files `verify` reads by name.
PACK_JSON, SUMS_FILE, SIGNATURE_FILE = "pack.json", "SHA256SUMS", "pack.sig"

#: Past this, a "pack" is not one: a real pack is a few hundred kilobytes.
MAX_BYTES = 64 * 1024 * 1024

#: The finding every pack gets until signing is built.
UNSIGNED = "the pack is not signed (signing is not built yet)"
ALLOWED_UNSIGNED = ("not checked: --allow-unsigned was given, for a rehearsal — the submissions "
                    "bot never passes it")

#: What a control may answer and still meet `required_controls`. `unknown`, `fail` and `n/a` are
#: never among them, whatever a thresholds file says.
_MAY_BE_ACCEPTED = frozenset({c.PASS, c.INFO})

_SUMS_LINE = re.compile(r"([0-9a-f]{64})  (\S.*)")
_THRESHOLD_ID = re.compile(r"T-[A-Z0-9][A-Z0-9-]*")


class Unreadable(ValueError):
    """The pack cannot be read at all — exit 2, and no answer about it."""


class ThresholdsError(ValueError):
    """The thresholds file cannot be used — exit 2, before any pack is judged by it."""


@dataclass(frozen=True)
class Result:
    """One line of the answer: what was checked (`id`), whether it held, and in what words."""

    id: str
    ok: bool
    message: str
    #: Not checked at all — `--allow-unsigned`'s signature line. Neither a pass nor a finding.
    skipped: bool = False


@dataclass(frozen=True)
class Threshold:
    id: str
    check: str
    params: dict


@dataclass
class Bundle:
    """The pack as read: every regular member's bytes, `pack.json` parsed, and what was wrong with
    the members that were not read."""

    name: str
    files: dict[str, bytes]
    document: dict
    problems: list[str] = field(default_factory=list)


# ── reading the pack ────────────────────────────────────────────────────────────────────────────

def read(path: Path) -> Bundle:
    """The pack's members, in memory. Raises `Unreadable` when it is not a pack at all."""
    path = Path(path)
    files: dict[str, bytes] = {}
    problems: list[str] = []
    total = 0
    try:
        with tarfile.open(path, mode="r:gz") as tar:
            for member in tar.getmembers():
                name = member.name
                parts = PurePosixPath(name).parts
                if not member.isfile():
                    problems.append(f"{name}: not a regular file")
                    continue
                if name.startswith("/") or ".." in parts or str(PurePosixPath(name)) != name:
                    problems.append(f"{name}: not a plain relative name")
                    continue
                if name in files:
                    problems.append(f"{name}: in the pack twice")
                    continue
                total += member.size
                if total > MAX_BYTES:
                    raise Unreadable(f"{path.name} holds more than {MAX_BYTES // 2**20} MiB — "
                                     f"not an evidence pack")
                handle = tar.extractfile(member)
                files[name] = handle.read() if handle is not None else b""
    except Unreadable:
        raise
    except FileNotFoundError:
        raise Unreadable(f"{path} does not exist") from None
    except (OSError, EOFError, tarfile.TarError, zlib.error) as exc:
        raise Unreadable(f"{path.name} is not a gzipped tarball ({str(exc)[:120]})") from None
    if PACK_JSON not in files:
        raise Unreadable(f"{path.name} holds no {PACK_JSON}")
    try:
        document = json.loads(files[PACK_JSON].decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Unreadable(f"{PACK_JSON} is not JSON ({str(exc)[:120]})") from None
    if not isinstance(document, dict):
        raise Unreadable(f"{PACK_JSON} is not a JSON object")
    return Bundle(name=path.name, files=files, document=document, problems=problems)


# ── the thresholds ──────────────────────────────────────────────────────────────────────────────

def _strings(allowed: frozenset[str] | tuple[str, ...]):
    def check(value) -> str:
        if not isinstance(value, list) or not value or \
                not all(isinstance(v, str) and v in allowed for v in value):
            return f"a non-empty list drawn from {', '.join(sorted(allowed))}"
        return ""
    return check


def _number(low: float, high: float | None = None, *, integer: bool = False):
    def check(value) -> str:
        kinds = int if integer else (int, float)
        if isinstance(value, bool) or not isinstance(value, kinds) or value < low or \
                (high is not None and value > high):
            span = f"from {low} to {high}" if high is not None else f"of at least {low}"
            return f"{'a whole number' if integer else 'a number'} {span}"
        return ""
    return check


def load_thresholds(path: Path | None = None) -> list[Threshold]:
    """The thresholds in `path`, or the core's own. Raises `ThresholdsError` for a file this build
    cannot enforce whole: an unknown check, a parameter a check does not take, one it needs and
    is not given, a value of the wrong kind, an id twice."""
    where = Path(path) if path is not None else THRESHOLDS_FILE
    import yaml

    try:
        data = yaml.safe_load(where.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ThresholdsError(f"{where} could not be read ({exc.strerror or exc})") from None
    except yaml.YAMLError as exc:
        raise ThresholdsError(f"{where} is not YAML ({str(exc)[:160]})") from None
    if not isinstance(data, dict) or data.get("schema") != THRESHOLDS_SCHEMA:
        raise ThresholdsError(f"{where} does not say `schema: {THRESHOLDS_SCHEMA}`")
    listed = data.get("thresholds")
    if not isinstance(listed, list) or not listed:
        raise ThresholdsError(f"{where} lists no thresholds")
    out: list[Threshold] = []
    for n, item in enumerate(listed, start=1):
        if not isinstance(item, dict):
            raise ThresholdsError(f"threshold {n} in {where} is not a mapping")
        ident, check = item.get("id"), item.get("check")
        if not isinstance(ident, str) or not _THRESHOLD_ID.fullmatch(ident):
            raise ThresholdsError(f"threshold {n} in {where}: its id must look like T-JOBS")
        if any(t.id == ident for t in out):
            raise ThresholdsError(f"{ident} is listed twice in {where}")
        if check not in CHECKS:
            raise ThresholdsError(f"{ident}: `{check}` is not a check this build performs "
                                  f"({', '.join(sorted(CHECKS))})")
        wants, _run = CHECKS[check]
        params = {k: v for k, v in item.items() if k not in ("id", "check")}
        unknown = sorted(set(params) - set(wants))
        if unknown:
            raise ThresholdsError(f"{ident}: `{check}` takes no `{unknown[0]}`")
        for name, rule in wants.items():
            if name not in params:
                raise ThresholdsError(f"{ident}: `{check}` needs `{name}`")
            wrong = rule(params[name])
            if wrong:
                raise ThresholdsError(f"{ident}: `{name}` must be {wrong}")
        out.append(Threshold(ident, check, params))
    return out


# ── the checks a threshold can name ─────────────────────────────────────────────────────────────

Check = Callable[[Threshold, dict, str], list[Result]]


def _control(document: dict, ident: str) -> dict | None:
    for entry in document.get("controls") or []:
        if isinstance(entry, dict) and entry.get("id") == ident:
            return entry
    return None


def _said(entry: dict) -> str:
    detail = str(((entry.get("evidence") or {}).get("detail")) or "").strip()
    return f" — {detail[:200]}" if detail else ""


def _outcomes(document: dict) -> dict:
    found = document.get("outcomes")
    return found if isinstance(found, dict) else {}


def _not_measured(t: Threshold, outcomes: dict, *measures: str) -> Result | None:
    """The finding for a threshold whose outcome was not measured, in the pack's own reason —
    or None when every measure it reads carries a value."""
    for measure in measures:
        if outcomes.get(measure) is None:
            reason = ((outcomes.get("not_measured") or {}).get(measure)
                      or outcomes.get("reason") or "the pack gives no reason")
            return Result(t.id, False, f"{measure.replace('_', ' ')}: not measured — {reason}")
    return None


def _required_controls(t: Threshold, document: dict, profile: str) -> list[Result]:
    """Every control the PROFILE TABLE requires — the core's `controls.PROFILES`, never the pack's
    own `required` flags, which the pack's writer chose — answers one of `accept`."""
    if profile not in c.PROFILES:
        return [Result(t.id, False, f"the pack claims the profile {profile!r}, which this build "
                                    f"does not know — pass --profile")]
    accept = [a for a in t.params["accept"] if a in _MAY_BE_ACCEPTED]
    failed = []
    required = [ident for ident in c.CONTROL_IDS if ident in c.PROFILES[profile]]
    for ident in required:
        entry = _control(document, ident)
        if entry is None:
            failed.append(Result(t.id, False, f"{ident}: missing from the pack"))
        elif entry.get("result") not in accept:
            failed.append(Result(t.id, False, f"{ident}: {entry.get('result')}{_said(entry)}"))
    return failed or [Result(t.id, True, f"all {len(required)} control(s) the {profile} profile "
                                         f"requires answer {' or '.join(accept)}")]


def _never_fail(t: Threshold, document: dict, _profile: str) -> list[Result]:
    failed = []
    for ident in t.params["controls"]:
        entry = _control(document, ident)
        if entry is None:
            failed.append(Result(t.id, False, f"{ident}: missing from the pack"))
        elif entry.get("result") == c.FAIL:
            failed.append(Result(t.id, False, f"{ident}: fail{_said(entry)}"))
    return failed or [Result(t.id, True, f"none of {', '.join(t.params['controls'])} fails")]


def _min_jobs(t: Threshold, document: dict, _profile: str) -> list[Result]:
    outcomes = _outcomes(document)
    missing = _not_measured(t, outcomes, "jobs")
    if missing:
        return [missing]
    jobs, least = outcomes["jobs"], t.params["min"]
    if jobs < least:
        return [Result(t.id, False, f"{jobs} job(s) ended in the window; at least {least} are "
                                    f"required")]
    return [Result(t.id, True, f"{jobs} job(s) ended in the window (at least {least})")]


def _share(part: int, whole: int) -> str:
    return f"{part} of {whole} ({round(100 * part / whole)}%)"


def _min_merged_share(t: Threshold, document: dict, _profile: str) -> list[Result]:
    outcomes = _outcomes(document)
    missing = _not_measured(t, outcomes, "jobs", "past_the_merge")
    if missing:
        return [missing]
    jobs, merged, least = outcomes["jobs"], outcomes["past_the_merge"], t.params["min"]
    if not jobs:
        return [Result(t.id, False, "no job ended in the window, so no share of them merged")]
    if merged / jobs < least:
        return [Result(t.id, False, f"{_share(merged, jobs)} job(s) reached the merge; at least "
                                    f"{round(100 * least)}% must")]
    return [Result(t.id, True, f"{_share(merged, jobs)} job(s) reached the merge")]


def _unknown_parks_below(t: Threshold, document: dict, _profile: str) -> list[Result]:
    outcomes = _outcomes(document)
    missing = _not_measured(t, outcomes, "jobs", "parks")
    if missing:
        return [missing]
    jobs, unknown, below = outcomes["jobs"], outcomes["parks"].get("unknown"), t.params["share"]
    if not isinstance(unknown, int):
        return [Result(t.id, False, "parks: the pack does not count the unknown parks")]
    if not jobs:
        return [Result(t.id, False, "no job ended in the window, so there is no share to take")]
    if unknown / jobs >= below:
        return [Result(t.id, False, f"{unknown} park(s) the tech-lead could not classify against "
                                    f"{jobs} job(s); under {round(100 * below)}% is required")]
    return [Result(t.id, True, f"{unknown} unclassified park(s) against {jobs} job(s)")]


def _needs_action_within(t: Threshold, document: dict, _profile: str) -> list[Result]:
    outcomes = _outcomes(document)
    missing = _not_measured(t, outcomes, "needs_action")
    if missing:
        return [missing]
    waiting, days = outcomes["needs_action"], t.params["days"]
    oldest = waiting.get("oldest_days")
    if not isinstance(oldest, int | float) or isinstance(oldest, bool):
        return [Result(t.id, False, "needs action: the pack does not say how long a card waited")]
    if oldest > days:
        return [Result(t.id, False, f"a card has waited {oldest} days in Needs Action; none may "
                                    f"wait more than {days}")]
    return [Result(t.id, True, f"{waiting.get('cards', 0)} card(s) in Needs Action, the oldest "
                               f"{oldest} days")]


def _proofs_current(t: Threshold, document: dict, _profile: str) -> list[Result]:
    proofs = [p for p in document.get("proofs") or [] if isinstance(p, dict)]
    if not proofs:
        return [Result(t.id, False, "the pack carries no box proof")]
    failed = [Result(t.id, False, f"{p.get('repository')} ({p.get('project')}): "
                                  f"{p.get('status')}")
              for p in proofs if p.get("status") != "valid"]
    return failed or [Result(t.id, True, f"all {len(proofs)} box proof(s) are valid")]


def _version_current(t: Threshold, document: dict, _profile: str) -> list[Result]:
    entry = _control(document, "C-VERSION")
    if entry is None:
        return [Result(t.id, False, "C-VERSION: missing from the pack")]
    if entry.get("result") != c.PASS:
        return [Result(t.id, False, f"C-VERSION: {entry.get('result')}{_said(entry)}")]
    return [Result(t.id, True, f"C-VERSION: pass{_said(entry)}")]


def _practitioner_named(t: Threshold, document: dict, _profile: str) -> list[Result]:
    named = str(document.get("practitioner") or "").strip()
    if not named:
        return [Result(t.id, False, "the pack names no practitioner (--practitioner)")]
    return [Result(t.id, True, f"practitioner: {named}")]


#: Every check a threshold may name: the parameters it takes, each with its rule, and the check.
CHECKS: dict[str, tuple[dict[str, Callable[[object], str]], Check]] = {
    "required_controls": ({"accept": _strings(_MAY_BE_ACCEPTED)}, _required_controls),
    "never_fail": ({"controls": _strings(c.CONTROL_IDS)}, _never_fail),
    "min_jobs": ({"min": _number(0, integer=True)}, _min_jobs),
    "min_merged_share": ({"min": _number(0, 1)}, _min_merged_share),
    "unknown_parks_below": ({"share": _number(0, 1)}, _unknown_parks_below),
    "needs_action_within": ({"days": _number(0)}, _needs_action_within),
    "proofs_current": ({}, _proofs_current),
    "version_current": ({}, _version_current),
    "practitioner_named": ({}, _practitioner_named),
}


# ── the pack itself ─────────────────────────────────────────────────────────────────────────────

def _contents(bundle: Bundle) -> list[Result]:
    if bundle.problems:
        return [Result("contents", False, p) for p in bundle.problems]
    return [Result("contents", True, f"{len(bundle.files)} file(s), each a regular file")]


def _schema(bundle: Bundle) -> list[Result]:
    from openfactory.certify.schema import PACK_SCHEMA, validate

    errors = validate(bundle.document)
    if errors:
        return [Result("schema", False, e) for e in errors]
    return [Result("schema", True, f"{PACK_JSON} matches {PACK_SCHEMA}")]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _checksums(bundle: Bundle) -> list[Result]:
    """`SHA256SUMS` covers every file but itself and a signature; `pack.json`'s `checksums` cover
    every file but `pack.json`, `SHA256SUMS` and a signature. Both must hold, file by file."""
    files, failed = bundle.files, []

    def fail(message: str) -> None:
        failed.append(Result("checksums", False, message))

    listed: dict[str, str] = {}
    if SUMS_FILE not in files:
        fail(f"the pack carries no {SUMS_FILE}")
    else:
        for n, line in enumerate(files[SUMS_FILE].decode("utf-8", "replace").splitlines(), 1):
            found = _SUMS_LINE.fullmatch(line)
            if not found:
                fail(f"{SUMS_FILE} line {n} is not `<sha256>  <file>`")
                continue
            listed[found.group(2)] = found.group(1)
        for name, digest in sorted(listed.items()):
            if name not in files:
                fail(f"{name}: listed in {SUMS_FILE} and not in the pack")
            elif _sha256(files[name]) != digest:
                fail(f"{name}: its SHA-256 is not the one {SUMS_FILE} lists")
        for name in sorted(set(files) - set(listed) - {SUMS_FILE, SIGNATURE_FILE}):
            fail(f"{name}: in the pack and not listed in {SUMS_FILE}")

    inside = bundle.document.get("checksums")
    inside = inside if isinstance(inside, dict) else {}
    for name, digest in sorted(inside.items()):
        if name not in files:
            fail(f"{name}: listed in {PACK_JSON}'s checksums and not in the pack")
        elif f"sha256:{_sha256(files[name])}" != digest:
            fail(f"{name}: its SHA-256 is not the one {PACK_JSON} lists")
    for name in sorted(set(files) - set(inside) - {PACK_JSON, SUMS_FILE, SIGNATURE_FILE}):
        fail(f"{name}: not listed in {PACK_JSON}'s checksums")
    return failed or [Result("checksums", True, f"{len(listed)} file(s) match {SUMS_FILE} and "
                                                f"{PACK_JSON}'s checksums")]


def _signature(bundle: Bundle, allow_unsigned: bool) -> list[Result]:
    if allow_unsigned:
        return [Result("signature", True, ALLOWED_UNSIGNED, skipped=True)]
    if SIGNATURE_FILE in bundle.files:
        return [Result("signature", False, f"{SIGNATURE_FILE} is present and this build cannot "
                                           f"check a signature (signing is not built yet)")]
    return [Result("signature", False, UNSIGNED)]


def verify(bundle: Bundle, *, thresholds: list[Threshold], profile: str | None = None,
           allow_unsigned: bool = False) -> list[Result]:
    """Every check, in the order the answer reads: the pack itself, then each threshold by id.
    `profile` is the one to verify against — the pack's own claim when not given."""
    judged = profile or str(bundle.document.get("profile") or "")
    out = [*_contents(bundle), *_schema(bundle), *_checksums(bundle),
           *_signature(bundle, allow_unsigned)]
    for t in thresholds:
        _wants, run = CHECKS[t.check]
        out.extend(run(t, bundle.document, judged))
    return out


def findings(results: list[Result]) -> list[Result]:
    return [r for r in results if not r.ok]
