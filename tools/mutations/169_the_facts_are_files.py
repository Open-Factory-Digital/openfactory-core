"""#169: the facts are files the tech-lead can open — on every harness, not one.

The reverses carry the pair that matters: the prompt may shrink ONLY when the pack landed, and a
gap must never render as an absence.
"""

TEST = "tests/test_the_facts_are_files_the_techlead_can_open.py"
PACK = "openfactory/techlead/pack.py"
CONV = "openfactory/techlead/conversation.py"

MUTATIONS = [
    # ── the pair: shrink only when it landed ────────────────────────────────────────────────────
    ("the prompt shrinks whether or not the pack was written", CONV,
     "    if facts is not None:", "    if True:"),

    ("…and the reverse: the pack is written and the prompt never mentions it", CONV,
     "    if facts is not None:", "    if False:"),

    ("an unwritable pack raises instead of falling back", PACK,
     "    except OSError as exc:  # noqa: BLE001 — an unwritable disk costs the pack, never the "
     "answer", "    except ZeroDivisionError as exc:"),

    ("a name that already exists is overwritten instead of refused", PACK,
     "        if into.exists():", "        if False:"),

    # ── the manifest ────────────────────────────────────────────────────────────────────────────
    ("the manifest stops naming what could not be read", PACK,
     '    lines += ["", "## What could NOT be read"]', '    lines += []'),

    ("the gaps are listed and not EXPLAINED — a model reads them as nothing to show", PACK,
     '        lines += ["", "These are FAILED READS, not absences. Do not report any of them as "\n'
     '                  "\'nothing to show\' — say the platform could not look."]', "        pass"),

    ("a clean read renders nothing, so 'no gaps' and 'gaps we forgot' look identical", PACK,
     '        lines.append("- Everything asked for was read.")', "        pass"),

    ("the manifest stops naming the files, so the model cannot find them", PACK,
     '    lines += [f"- `{dirname}/{name}`" for name in written] or ["- (none were written)"]',
     "    lines += []"),

    # ── the client's tree ───────────────────────────────────────────────────────────────────────
    ("the pack moves into the client's own config directory", PACK,
     '_PREFIX = ".openfactory-facts-"', '_PREFIX = ".openfactory"'),

    ("the pack name stops being random, so two questions collide", PACK,
     'return root / f"{_PREFIX}{secrets.token_hex(4)}"', 'return root / f"{_PREFIX}fixed"'),

    ("a provider ref can walk out of the pack directory", PACK,
     '    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-.")\n    return cleaned or "unknown"',
     '    return str(ref) or "unknown"'),

    ("an empty body is written as a file the model wastes a turn opening", PACK,
     "            if body and len(body.strip()) >= _MIN_BODY:", "            if True:"),

    # ── the gaps are gathered at all ────────────────────────────────────────────────────────────
    ("an unreadable ticket thread stops being reported as a failed read", CONV,
     '        if parked(job) and job.get("comments") is None:\n'
     '            gaps.append(f"the ticket thread for {ref} could not be read")', "        pass"),

    ("an unreadable verdict stops being reported as a failed read", CONV,
     '        if job.get("verdict_unread"):\n'
     '            gaps.append(f"the review verdict for {ref} could not be read")', "        pass"),
]
