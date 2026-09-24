"""Proven by breaking it — a ticket costs one number, and every surface says that number.

`RunResult` is a pydantic model, so `agent_runs=self._agent_runs` at construction COPIES the list.
The result is built before the review runs, and `total_cost_usd` was refreshed only inside the
repair loops that run BEFORE it — so on the default `advisory` path the review was charged to
nobody. And `/api/jobs` took the most recent event carrying a cost, which is the LAST pass rather
than the ticket: `Cost: $4.0265` on the pull request against `cost_usd: 0.6126` on the dashboard,
for the same job.

FOUR CLAIMS:

  1. **The result carries every pass this runner counted**, the review included — charged at the
     one door it leaves through, not at each of the ten places a pass is counted.
  2. **The total is the sum of what was reported**, and the two cannot drift.
  3. **Unknown stays unknown.** A harness that reports no price must not read as `$0.00`, or it
     wins every cost comparison the telemetry exists to make.
  4. **The dashboard reports the ticket**, not one of its passes.

The guard is `tests/test_one_cost_for_a_ticket_on_every_surface.py`.
"""

TEST = "tests/test_one_cost_for_a_ticket_on_every_surface.py"

MACHINE = "openfactory/orchestrator/machine.py"
API = "openfactory/api/app.py"

MUTATIONS = [
    # ── claim 1: the result carries every pass ────────────────────────────────────────────────
    ("THE DEFECT ITSELF: the result keeps the copy it was built with, so the review is invisible",
     MACHINE,
     "        result.agent_runs = list(getattr(self, \"_agent_runs\", []))\n",
     "        result.agent_runs = result.agent_runs\n"),

    # RE-PINNED (#265 slice 3): the human gate now offers a preview between the notify and the
    # return, so the row cuts the success path's own return, the one at this depth before `finally:`
    ("THE SUCCESS PATH hands back a result nobody charged — the one the review ran on", MACHINE,
     "            return self._charged(result)\n        finally:\n",
     "            return result\n        finally:\n"),

    # ── claim 2: the total is the sum, and cannot drift from the rows ─────────────────────────
    ("the rows are refreshed and the total is not — the two drift, which is how this began",
     MACHINE,
     "        result.total_cost_usd = self._reported_cost()\n        return result\n",
     "        return result\n"),

    # ── claim 3: unknown is not free ──────────────────────────────────────────────────────────
    ("a pass that reported no price is counted as zero, so a harness with no cost looks FREE",
     MACHINE,
     "        costs = [m.cost_usd for m in getattr(self, \"_agent_runs\", []) "
     "if m.cost_usd is not None]\n        return sum(costs) if costs else None\n",
     "        costs = [m.cost_usd or 0.0 for m in getattr(self, \"_agent_runs\", [])]\n"
     "        return sum(costs)\n"),

    # ── claim 4: the dashboard reports the ticket ─────────────────────────────────────────────
    ("the dashboard goes back to the last pass that reported a cost", API,
     "            charged = [(e.get(\"data\") or {}).get(\"cost_usd\") for e in evs]\n",
     "            charged = [(e.get(\"data\") or {}).get(\"cost_usd\") for e in evs[-1:]]\n"),

    ("…and a job nobody charged is rendered as free rather than as unknown", API,
     "            cost = sum(charged) if charged else None\n",
     "            cost = sum(charged)\n"),
]
