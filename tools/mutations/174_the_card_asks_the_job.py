"""The deciding surface asks the job, instead of reading the engine's status."""

TEST = "tests/test_the_card_says_what_the_floor_says.py"
VIEW = "openfactory/runtime/temporal/view.py"

MUTATIONS = [
    ("the card reads the engine's status again", VIEW,
     "        state, action, _live = await _domain_state(client, desc)",
     '        state, action, _live = "running", None, True'),

    ("…and returns before it asks anything at all", VIEW,
     "        # ASK THE JOB, DO NOT READ ITS TEMPORAL STATUS",
     '        out["state"], out["why"] = "running", "Still running."\n'
     "        return out\n"
     "        # ASK THE JOB, DO NOT READ ITS TEMPORAL STATUS"),

    ("the verdict stops travelling with the gate", VIEW,
     "            out[\"review\"] = await handle.query(JobWorkflow.verdict)",
     '            out["review"] = None'),

    ("…and the explanation stops naming the rejection", VIEW,
     '        out["why"] = _why("pr_open" if state == "awaiting_your_merge" else state,\n'
     '                          {"note": (action or {}).get("note") or "",\n'
     '                           "review": out["review"] or {}})',
     '        out["why"] = _why(state, {"note": (action or {}).get("note") or ""})'),

    ("the pull request the gate is about is dropped", VIEW,
     '        if action and action.get("pr_url"):\n            out["pr_url"] = action["pr_url"]',
     "        pass"),

    ("a genuinely running job is reported as parked", VIEW,
     '        out["state"] = state',
     '        out["state"] = state if state != "running" else "on_hold"'),

    ("the running branch blocks on a result that will not arrive for days", VIEW,
     "        state, action, _live = await _domain_state(client, desc)",
     "        await handle.result()\n"
     "        state, action, _live = await _domain_state(client, desc)"),

    ("an unqueryable workflow 500s the card instead of degrading", VIEW,
     "        except Exception as exc:  # noqa: BLE001 — the card degrades, it never 500s\n"
     "            log.info(\"could not read %s's review verdict (%s)\", wf_id, str(exc)[:120])\n"
     '            out["review"] = None',
     "        except ZeroDivisionError:\n            pass"),
]
