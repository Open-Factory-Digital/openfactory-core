"""#168: the chat's fences are its own and ordered, and what a question costs is recorded.

Step 1 of the tool-calling plan. The reverses matter here because every fence is a trade: one too
tight truncates a real answer, one too loose is not a fence at all.
"""

TEST = "tests/test_the_chat_has_its_own_fences.py"
LAYER = "tests/test_the_action_layer.py"
CC = "openfactory/adapters/agent/claude_code.py"
CONV = "openfactory/techlead/conversation.py"
CATALOG = "openfactory/actions/catalog.py"
ACT = "openfactory/runtime/temporal/activities.py"

MUTATIONS = [
    # ── the fences ──────────────────────────────────────────────────────────────────────────────
    ("the chat inherits the executor's four-hour wall again — outside the activity's budget", CC,
     '            timeout=_CHAT_TIMEOUT if phase == "chat" else _EXECUTE_TIMEOUT,',
     "            timeout=_EXECUTE_TIMEOUT,"),

    ("…and the reverse: every pass takes the chat's wall, truncating real execution", CC,
     '            timeout=_CHAT_TIMEOUT if phase == "chat" else _EXECUTE_TIMEOUT,',
     "            timeout=_CHAT_TIMEOUT,"),

    ("the chat wall is set OUTSIDE the activity budget — a fence nobody can reach", CC,
     '_CHAT_TIMEOUT = int(os.environ.get("OPENFACTORY_CHAT_TIMEOUT", "300"))',
     '_CHAT_TIMEOUT = int(os.environ.get("OPENFACTORY_CHAT_TIMEOUT", "3600"))'),

    ("the chat takes the executor's 200-turn cap again", CC,
     '            "--max-turns", str(_CHAT_MAX_TURNS if phase == "chat" else self.max_turns),',
     '            "--max-turns", str(self.max_turns),'),

    ("…and the reverse: an execution pass is capped at conversation length", CC,
     '            "--max-turns", str(_CHAT_MAX_TURNS if phase == "chat" else self.max_turns),',
     '            "--max-turns", str(_CHAT_MAX_TURNS),'),

    ("the phase never reaches the command builder, so the fences are decoration", CC,
     "                              phase=phase,\n", ""),

    # ── what it cost ────────────────────────────────────────────────────────────────────────────
    ("the pass's numbers are dropped again — the one role a person talks to stays unpriced",
     CONV, "        spend = _spent(res)\n        _record_chat_spend(project, spend)\n",
     '        spend = {}\n'),

    ("an absent number becomes a zero — the pass reads as free", CONV,
     "    return {f: getattr(res, f, None) for f in fields if getattr(res, f, None) is not None}",
     "    return {f: getattr(res, f, None) or 0 for f in fields}"),

    ("nothing measured still writes a row saying a pass cost nothing", CONV,
     "    if not spend:\n        return", "    if False:\n        return"),

    ("a sink that refuses costs the ANSWER instead of the row", CONV,
     "    except Exception as exc:  # noqa: BLE001 — a lost row is a bad day, a lost answer is "
     "worse", "    except ZeroDivisionError as exc:"),

    ("the spend is recorded and then dropped on the hop to the surface", ACT,
     '            "spend": dict(answer.spend or {})}', "            }", LAYER),

    # ── two askers, two answers ─────────────────────────────────────────────────────────────────
    ("the workflow id goes back to a per-process hash of the question", CATALOG,
     'id=f"openfactory-ask-{found.name}-{uuid.uuid4().hex[:12]}",',
     'id=f"openfactory-ask-{found.name}-{abs(hash(text)) % 10**8}",'),
]
