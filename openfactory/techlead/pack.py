"""The facts as FILES, so the tech-lead can open the one it needs (#169).

Everything the tech-lead knew was frozen into one prompt string before its process started, and
that string is capped — 30 tickets, 8 comment threads, 8 verdicts. The caps are logged when they
bite and INVISIBLE to the model, so it answered thin and confident about a floor it had been shown
a truncation of. Measured, the prompt is ~20-25k characters and most of it is not what any given
question is about.

WHY FILES AND NOT A PROTOCOL. Every judging harness this platform supports already runs a
read-only agentic loop with filesystem reads over the checkout — `claude Read,Grep,Glob`,
`codex -s read-only`, kimi's plan mode, opencode's read-only profile. A fact written as a file is
therefore a tool on ALL FOUR, today, with no new flag, no new dependency and no new process. MCP
buys laziness and a structured channel on top of this; it does not replace it, and it would work
on one harness out of four.

PURE TEXT OVER WHAT `gather_jobs` ALREADY READ. Every provider call was made and caught there.
This module renders and writes; it never reaches a vendor, so `answer()` can keep its promise
never to raise.

THE MANIFEST NAMES THE GAPS. A directory listing is exactly where "UNREADABLE is not absence"
would quietly break: a missing `comments/87.md` is indistinguishable from a ticket nobody has
commented on unless the manifest says which it was. So `README.md` names every file AND every fact
that could not be gathered, with the reason.
"""

from __future__ import annotations

import logging
import secrets
import shutil
from pathlib import Path

log = logging.getLogger("openfactory.techlead")

#: The pack lives beside the checkout under a RANDOM name, and both halves matter. `.openfactory/`
#: is the CLIENT'S manifest directory (`.openfactory/project.yaml`) — writing there would put our
#: scratch inside their configuration. And a fixed name that somehow already exists in a client's
#: tree would be overwritten by us; a random one that exists means something is wrong, so the
#: writer refuses and the caller falls back to the full inline render.
_PREFIX = ".openfactory-facts-"

#: What a file is worth writing at all. A file whose body is one sentence saying nothing is a file
#: the model spends a turn opening to learn it wasted the turn.
_MIN_BODY = 12


def pack_dir(root: Path) -> Path:
    return root / f"{_PREFIX}{secrets.token_hex(4)}"


def write_pack(root: Path, *, floor: str, board: str, thread: str,
               comments: dict[str, str], verdicts: dict[str, str],
               diffs: dict[str, str] | None = None,
               gaps: list[str] | None = None,
               bundle: Path | None = None) -> Path | None:
    """Write the pack and return its directory, or None if it could not be written.

    NONE IS A REAL ANSWER AND THE CALLER MUST HONOUR IT: an unwritable pack means the full inline
    render goes back into the prompt. A shrunk prompt plus an absent pack is a tech-lead answering
    from nothing while believing it has files to open — the worst of both, and the exact shape of
    "absence reads as compliance".

    `bundle` IS THE KNOWLEDGE BUNDLE, COPIED IN WHOLE. The tech-lead clones the SOURCE repository;
    the concepts live in the project's CONTEXT repository, so they have to be carried here or the
    role has no way to reach them. Copied rather than linked, and whole rather than
    file-by-file, because the index's links are relative — a partial copy would hand the role an
    index whose entries do not open. `None` means the caller had no bundle to give, and the
    difference between that and "there is none" is the caller's to state in `gaps`.
    """
    try:
        into = pack_dir(root)
        if into.exists():  # a collision on 8 random hex is not a collision, it is a wrong tree
            log.warning("refusing to write the fact pack: %s already exists", into)
            return None
        (into / "comments").mkdir(parents=True)
        (into / "verdicts").mkdir(parents=True)
        (into / "diffs").mkdir(parents=True)

        written: list[str] = []
        for name, body in (("floor.md", floor), ("board.md", board), ("thread.md", thread)):
            if body and len(body.strip()) >= _MIN_BODY:
                (into / name).write_text(body, encoding="utf-8")
                written.append(name)
        for folder, rows in (("comments", comments), ("verdicts", verdicts),
                             ("diffs", diffs or {})):
            for ref, body in (rows or {}).items():
                if not body or len(body.strip()) < _MIN_BODY:
                    continue
                safe = _safe(ref)
                (into / folder / f"{safe}.md").write_text(body, encoding="utf-8")
                written.append(f"{folder}/{safe}.md")

        if bundle is not None and Path(bundle).is_dir():
            # WHOLE, so the index's relative links open. Named in the manifest below like every
            # other file — a bundle copied in and not listed is a fact the role never learns it
            # has, which is the same silence this manifest exists to prevent.
            shutil.copytree(Path(bundle), into / "okf", dirs_exist_ok=True)
            index = into / "okf" / "index.md"
            written.append("okf/index.md" if index.is_file() else "okf/")

        (into / "README.md").write_text(manifest(into.name, written, gaps or []),
                                        encoding="utf-8")
        _exclude(root, into.name)
        return into
    except OSError as exc:  # noqa: BLE001 — an unwritable disk costs the pack, never the answer
        log.warning("could not write the fact pack (%s) — answering from the inline render", exc)
        return None


def _safe(ref: str) -> str:
    """A tracker ref as a filename. Refs are the PROVIDER'S strings (C-05) — `CONT-412`, `#87`,
    `Deskline/ui#15` — so anything that is not a plain word becomes a dash rather than a
    directory somebody did not intend."""
    import re

    cleaned = "".join(c if (c.isalnum() or c in "-_.") else "-" for c in str(ref).lstrip("#"))
    # RUNS COLLAPSED AND EDGES STRIPPED. `../../etc/passwd` survives the substitution as
    # `..-..-etc-passwd` — safe, since there is no separator left to traverse with, and a name
    # opening with `..` is a name a reader has to think about. `.` and `..` themselves must never
    # come out of here at all.
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-.")
    return cleaned or "unknown"


def manifest(dirname: str, written: list[str], gaps: list[str]) -> str:
    """The one file the prompt names, and the map to every other.

    IT NAMES WHAT IS MISSING, WITH THE REASON. A model reading a directory resolves an absent
    `comments/87.md` the same way it resolves an empty one — as "nobody commented" — which is a
    claim about the client's ticket made from a read that failed. The gaps section is what keeps
    that from being said.
    """
    lines = [
        "# The facts for this question",
        "",
        f"These files sit at `{dirname}/` in the workspace root. Open the ones the question is "
        "about — do not guess at what is in them, and do not answer from the index alone when the "
        "question turns on a detail.",
        "",
        "## Files",
    ]
    lines += [f"- `{dirname}/{name}`" for name in written] or ["- (none were written)"]
    lines += ["", "## What could NOT be read"]
    if gaps:
        lines += [f"- {g}" for g in gaps]
        lines += ["", "These are FAILED READS, not absences. Do not report any of them as "
                  "'nothing to show' — say the platform could not look."]
    else:
        lines.append("- Everything asked for was read.")
    return "\n".join(lines) + "\n"


def _exclude(root: Path, name: str) -> None:
    """Keep the pack out of the client's `git status`.

    The workspace is a checkout of the CLIENT'S repository. Our scratch appearing as an untracked
    directory is noise in every `git` read the agent makes, and — on any path that ever learned to
    commit — a file of ours in their history. Best-effort: a repository without `.git/info` is a
    reason to skip this, never to lose the pack.
    """
    try:
        info = root / ".git" / "info"
        info.mkdir(parents=True, exist_ok=True)
        exclude = info / "exclude"
        prior = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if name not in prior:
            exclude.write_text(f"{prior.rstrip()}\n{name}/\n".lstrip("\n"), encoding="utf-8")
    except OSError as exc:  # noqa: BLE001
        log.info("could not exclude the fact pack from git (%s) — it is scratch either way", exc)
