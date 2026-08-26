"""#171: the tech-lead can read the change it is asked to approve.

The reverses are the option type in both directions — a failed read must not become "no changes",
and an empty pull request must not become a failed read — plus the bound that keeps a diff from
dwarfing every other fact beside it.
"""

TEST = "tests/test_the_techlead_can_see_the_change_it_judges.py"
BASE = "openfactory/adapters/forge/base.py"
GH = "openfactory/adapters/forge/github.py"
CONV = "openfactory/techlead/conversation.py"
PACK = "openfactory/techlead/pack.py"
FACTS = "tests/test_the_facts_are_files_the_techlead_can_open.py"

MUTATIONS = [
    # ── the option type ─────────────────────────────────────────────────────────────────────────
    ("a refused read becomes 'this pull request changes nothing'", GH,
     "        if got.returncode != 0:\n"
     '            log.warning("could not read the diff of %s (%s)", pr,\n'
     '                        (got.stderr or "").strip()[:160])\n'
     "            return None", "        if False:\n            return None"),

    ("…and the reverse: an empty pull request reads as a failed read", GH,
     '        return _truncated(_redact(got.stdout or ""), max_chars)',
     '        return _truncated(_redact(got.stdout or ""), max_chars) or None'),

    ("the neutral contract stops declaring the read at all", BASE,
     "    def pr_diff(self, *, pr: str, repo: str = \"\", max_chars: int = 60000) -> str | None:",
     "    def _pr_diff_removed(self, *, pr: str) -> str | None:"),

    # ── the bound, and its marker ───────────────────────────────────────────────────────────────
    ("a large diff is cut with nothing saying so — the change reads as ending there", BASE,
     '    return (text[:max_chars]\n'
     '            + f"\\n\\n[... this diff was cut here: {len(text)} characters in total, "\n'
     '              f"{max_chars} shown. It is NOT the whole change.]\\n")',
     "    return text[:max_chars]"),

    ("…and the reverse: nothing is ever cut, so one diff dwarfs every other fact", BASE,
     "    if len(text) <= max_chars:\n        return text",
     "    return text\n    if len(text) <= max_chars:\n        return text"),

    ("the TAIL is kept instead of the head — the change is dropped for the lockfiles", BASE,
     "    return (text[:max_chars]", "    return (text[-max_chars:]"),

    # ── fetched where the question is asked ─────────────────────────────────────────────────────
    ("no diff is fetched at all — it judges a change it has never seen", CONV,
     "    _attach_diffs(project, jobs)\n", ""),

    ("every job is paid for, not just the one at a gate", CONV,
     '                   if (j.get("action") or {}).get("kind") == _MERGE_WAIT_KIND\n'
     '                   and (j.get("action") or {}).get("pr_url")]',
     "                   ]"),

    ("the pull request is read with NO credential — every diff on a private repo is None", CONV,
     "        forge = build_forge(project,\n"
     "                            token=forge_token_for(project) or github_app_token_from_env() "
     "or None)", "        forge = build_forge(project)"),

    ("…or with the TRACKER's credential, on a deployment where the two axes differ", CONV,
     "token=forge_token_for(project) or github_app_token_from_env() or None)",
     "token=__import__('openfactory.credentials', fromlist=['x']).tracker_token_for(project))"),

    ("a forge that raises loses the ANSWER instead of the diff", CONV,
     "        except Exception as exc:  # noqa: BLE001\n"
     '            log.warning("could not read the diff of %s (%s)", pr_url, str(exc)[:160])\n'
     "            got = None", "        except ZeroDivisionError:\n            got = None"),

    ("a failed read is silently forgotten rather than named", CONV,
     '        if got is None:\n            job["diff_unread"] = True',
     "        if got is None:\n            pass"),

    ("no forge at all is a silence rather than an unread", CONV,
     '        for job in at_the_gate:\n            job["diff_unread"] = True\n        return',
     "        return"),

    # ── the pack keeps the two apart ────────────────────────────────────────────────────────────
    ("an empty diff gets no file, so it reads as a diff nobody fetched", CONV,
     '        if not ref or ref in out or "diff" not in job:',
     '        if not ref or ref in out or not job.get("diff"):'),

    ("a failed diff read stops being named in the gaps", CONV,
     '        if job.get("diff_unread"):', "        if False:"),

    ("the pack stops writing the diffs it is handed", PACK,
     '                             ("diffs", diffs or {})):', "                             ):"),
]
