"""The archaeology, and the sixteen ways it could lie quietly.

`onboarding/history.py` is the backfill's second input — the repository's own log — and almost
every way it can be wrong is SILENT. It answers with a populated object either way; only the
numbers differ, and nobody downstream has a second source to check them against. That is what this
plan is for.

THE FIRST TWO ROWS ARE THE ONE THAT MATTERS. `clone_for_proposal` clones `--depth 1`, so every
caller arriving by the ordinary route hands this module a checkout whose entire log is one commit.
Reported as data rather than as a refusal, that is "every file changed once, everywhere" — and a
caller ranking areas by churn would rank them all identically and be confident about it. It is the
absence-read-as-compliance failure with a new mouth, and it is the reason `unavailable` is a
sentence and `files` is empty beside it.

ROW 4 IS A REGRESSION THAT ACTUALLY HAPPENED, an hour before this file was written: `\\b#101` never
matches, because a space followed by `#` is not a word boundary — neither character is a word
character. The obvious single pattern found every `AB#4412` and silently dropped every bare `#101`
next to it, which on GitHub is most of them. The guard caught it; without the guard the `asked`
tier would have been half-blind on the commonest forge this platform speaks to.

ROW 8 EXISTS BECAUSE THE FIXTURE ALMOST COULD NOT REACH IT. In the first draft the busiest file was
also the alphabetically first, so a `change_surface` that had lost its ranking entirely still
returned the expected order. `billing/audit.py` is in the fixture for no other reason.
"""

TEST = "tests/test_the_history_says_where_the_work_is.py"

MUTATIONS = [
    # ── the shallow clone: the failure this module is written around ────────────────────────────
    ("a shallow checkout is not detected, so a one-commit clone is reported as data — every file "
     "changed once, and a caller ranking areas by churn ranks them all the same",
     "openfactory/onboarding/history.py",
     '    if rc == 0 and shallow.strip() == "true":',
     '    if rc == 0 and shallow.strip() == "never-true":'),

    ("the shallow refusal is written but not returned, so `unavailable` and `files` are both "
     "populated — and a caller can average a refusal with an answer",
     "openfactory/onboarding/history.py",
     '                           "(`clone_for_proposal`) to read the log")\n        return out',
     '                           "(`clone_for_proposal`) to read the log")'),

    # ── the other ways of failing to look ───────────────────────────────────────────────────────
    ("a missing `git` binary raises out of the read instead of naming itself — and the deployed "
     "container is built from the CLIENT'S image, so this platform does not get to assume `git` "
     "is in it",
     "openfactory/onboarding/history.py",
     "    except (OSError, subprocess.SubprocessError) as exc:",
     "    except ValueError as exc:"),

    ("a directory that is not a checkout comes back usable with no files — indistinguishable from "
     "a repository nobody has touched this year",
     "openfactory/onboarding/history.py",
     '        out.unavailable = f"{root} is not a git checkout ({(err or \'\').strip()[-120:]})"',
     '        out.unavailable = ""'),

    # ── the ticket references: the `asked` tier ─────────────────────────────────────────────────
    ("the regex regression as it was actually written: `\\b#101` never matches, so every bare "
     "GitHub reference is dropped and only `AB#…` survives",
     "openfactory/onboarding/history.py",
     '_TICKET_HASH = re.compile(r"(?:\\b(AB)#|(?<![\\w#])#)(\\d{1,7})\\b")',
     '_TICKET_HASH = re.compile(r"\\b(AB)?#(\\d{1,7})\\b")'),

    ("the stoplist is dropped, so `UTF-8`, `SHA-256` and `ADR-0041` are all filed as work items "
     "and the file's strongest evidence tier fills with noise",
     "openfactory/onboarding/history.py",
     "        if key not in _NOT_A_PROJECT_KEY:",
     "        if True:"),

    # ── what the log actually says ──────────────────────────────────────────────────────────────
    # THIS ROW SURVIVED ITS FIRST RUN, and the survivor was the CLAIM, not the code. The guard
    # asserted a per-file count, and `git log --name-only` emits no paths for a merge commit at
    # all — so removing `--no-merges` changed nothing a file could see. What the flag protects is
    # `commits_read`, and that is what the guard asserts now.
    ("merges are counted in `commits_read`, so a merge-commit workflow reports more history than "
     "a squash-merge one on identical work — and this platform serves both, on the same board",
     "openfactory/onboarding/history.py",
     '        "log", "--no-merges", f"--since={since}", f"--max-count={MAX_COMMITS + 1}",',
     '        "log", f"--since={since}", f"--max-count={MAX_COMMITS + 1}",'),

    ("the window is not applied, so fifteen years of history read as this year's work and the "
     "whole point of ranking by recency is gone",
     "openfactory/onboarding/history.py",
     '        "log", "--no-merges", f"--since={since}", f"--max-count={MAX_COMMITS + 1}",',
     '        "log", "--no-merges", f"--max-count={MAX_COMMITS + 1}",'),

    ("the clock is called instead of passed, so two reads an hour apart disagree for a reason no "
     "reader of the diff could find",
     "openfactory/onboarding/history.py",
     "    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)",
     "    stamp = datetime.now(timezone.utc)"),

    ("`--since` walks newest-first and this reads it oldest-first, so every file reports as last "
     "touched on the day it ENTERED the window — the freshest files look the stalest",
     "openfactory/onboarding/history.py",
     ('            if not row["last"]:\n'
      '                row["last"] = date\n'
      '            row["first"] = date'),
     ('            if not row["first"]:\n'
      '                row["first"] = date\n'
      '            row["last"] = date')),

    ("the commit ceiling is hit and not declared, so a monolith's most recent 20,000 commits are "
     "presented as its whole history",
     "openfactory/onboarding/history.py",
     "        out.truncated = True\n        records = records[:MAX_COMMITS]",
     "        records = records[:MAX_COMMITS]"),

    # ── what the object claims about each path ──────────────────────────────────────────────────
    ("a path that no longer exists is reported as present, so the backfill is asked to write a "
     "concept about a file that was deleted in March",
     "openfactory/onboarding/history.py",
     "            present=(root / name).exists(),",
     "            present=True,"),

    ("`author_count` is capped along with the names, so a file thirty people have touched reports "
     "eight owners — and the cap becomes the answer instead of a bound on it",
     "openfactory/onboarding/history.py",
     '            author_count=len(row["authors"]),',
     '            author_count=len(sorted(row["authors"])[:MAX_AUTHORS_PER_FILE]),'),

    ("the files come back unsorted by path, so this object cannot be diffed against last week's — "
     "which is the only way a human reviews it",
     "openfactory/onboarding/history.py",
     "        key=lambda f: f.path)",
     "        key=lambda f: -len(f.path))"),

    # ── the ranking the backfill spends itself by ───────────────────────────────────────────────
    ("the change surface loses its ranking and falls back to alphabetical, so the concept budget "
     "is spent on whichever file sorts first rather than on the one six people changed",
     "openfactory/onboarding/history.py",
     "    rows.sort(key=lambda f: (-f.commits, -f.author_count, f.path))",
     "    rows.sort(key=lambda f: f.path)"),

    ("a file at the repository root reports an EMPTY area, which a renderer prints as a blank row "
     "and a reader reads as a bug in the platform",
     "openfactory/onboarding/history.py",
     '        totals[area or "."] = totals.get(area or ".", 0) + row.commits',
     "        totals[area] = totals.get(area, 0) + row.commits"),
]
