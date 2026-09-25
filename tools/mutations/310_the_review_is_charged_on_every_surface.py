"""Proven by breaking it — the review is charged on every surface (#310).

#263 made the rule: a ticket costs one number, and every surface says it. The review broke it on
two surfaces. The `review` event carried no `cost_usd`, so the journal — and `/api/jobs` and the
panel's live counter, which sum it — never heard of the review: 0.01 against a result of 0.26.
And `_pr_body` read the total before the review was charged, so the pull request said
`Cost: $0.0100`. After the pull request was open it got worse: `repair_ci` reported `rep.cost_usd`
without the review that followed it and carried no rows, `review_pr` carried no rows, and neither
moved the pull request's `Cost:` line at all.

SIX CLAIMS:

  1. **Every review's line carries its price** — the first review, the re-review, the review after
     a CI repair and a re-review somebody asked for.
  2. **The pull request is opened with the charged total**, the review included.
  3. **A CI repair and a re-review carry their rows and their charged total**, each call its own.
  4. **The `Cost:` line catches up on every way out of a CI repair and after a re-review** — by
     what the pass spent, once, and never by its review section's replacement.
  5. **The panel's live counter sums what `/api/jobs` sums.**
  6. **The four surfaces are one number** on the advisory path, the blocking path and through a CI
     repair — the guard that holds the other five together.

The guard is `tests/test_the_review_is_charged_on_every_surface.py`.
"""

TEST = "tests/test_the_review_is_charged_on_every_surface.py"

MACHINE = "openfactory/orchestrator/machine.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    # ── claim 1: every review's line carries its price ────────────────────────────────────────
    ("THE DEFECT ITSELF: the first review reaches the journal without its price", MACHINE,
     "                    detail=_review_event_detail(result.review),\n"
     "                    cost_usd=result.review.cost_usd,\n",
     "                    detail=_review_event_detail(result.review),\n"),

    ("the re-review on the blocking path reaches the journal without its price", MACHINE,
     "                        detail=_review_event_detail(result.review),\n"
     "                        cost_usd=result.review.cost_usd,\n",
     "                        detail=_review_event_detail(result.review),\n"),

    ("the review after a CI repair reaches the journal without its price", MACHINE,
     "                    findings=len(review.findings), detail=_review_event_detail(review),\n"
     "                    cost_usd=review.cost_usd,\n",
     "                    findings=len(review.findings), detail=_review_event_detail(review),\n"),

    ("a re-review somebody asked for reaches the journal without its price", MACHINE,
     "                findings=len(review.findings), detail=_review_event_detail(review),\n"
     "                cost_usd=review.cost_usd,\n",
     "                findings=len(review.findings), detail=_review_event_detail(review),\n"),

    # ── claim 2: the pull request is opened with the charged total ────────────────────────────
    ("THE SECOND DEFECT: the body is written from the total as it stood before the review",
     MACHINE,
     # re-pinned 2026-09-25: #265 reads `preview_required` between the charge and the body, so
     # the charge is cut where it now stands, claim unchanged
     "            self._charged(result)\n"
     "            # READ BEFORE THE BODY IS WRITTEN: the body says why a person must merge (D9).\n",
     "            # READ BEFORE THE BODY IS WRITTEN: the body says why a person must merge (D9).\n"),

    # ── claim 3: a CI repair and a re-review carry their rows and charged total ───────────────
    ("THE CI REPAIR AS IT WAS: the repair's own price, no review, no rows", MACHINE,
     "            return as_left(self._charged(RunResult(\n"
     "                ticket_id=ticket.id, state=JobState.PR_OPEN, branch=branch,\n"
     "                auto_merge=True, review=review,\n"
     "            )))\n",
     "            return as_left(RunResult(\n"
     "                ticket_id=ticket.id, state=JobState.PR_OPEN, branch=branch,\n"
     "                auto_merge=True, total_cost_usd=rep.cost_usd, review=review,\n"
     "            ))\n"),

    ("THE RE-REVIEW AS IT WAS: the total, and not the row it is made of", MACHINE,
     "            return self._charged(RunResult(\n"
     "                ticket_id=ticket.id, state=JobState.PR_OPEN, branch=branch, review=review,\n"
     "                code_changed=False,\n"
     "            ))\n",
     "            return RunResult(\n"
     "                ticket_id=ticket.id, state=JobState.PR_OPEN, branch=branch, review=review,\n"
     "                code_changed=False, total_cost_usd=self._reported_cost(),\n"
     "            )\n"),

    ("a CI repair keeps the rows a previous call on the same runner counted", MACHINE,
     "        self._agent_runs = []\n"
     "        self._cost_on_the_pr = 0.0\n"
     "        ticket = self.tracker.get_ticket(ticket_ref)\n"
     "        owner = self._owner_of(ticket_ref)\n",
     "        self._cost_on_the_pr = 0.0\n"
     "        ticket = self.tracker.get_ticket(ticket_ref)\n"
     "        owner = self._owner_of(ticket_ref)\n"),

    # ── claim 4: the Cost line catches up, once, and survives the review section ──────────────
    ("the Cost line moves only where a verdict was republished — a pass that stopped is lost",
     MACHINE,
     "                self._republish_review(pr_url)\n"
     "                now = self._pr_diff(ws, base)\n",
     "                now = self._pr_diff(ws, base)\n"),

    ("the Cost line is restated by everything this runner spent, whatever it already said",
     MACHINE,
     "        owed = (spent or 0.0) - getattr(self, \"_cost_on_the_pr\", 0.0)\n",
     "        owed = spent or 0.0\n"),

    ("the Cost line is rewritten and never moved", MACHINE,
     "                rows[cost_at] = f\"{_COST_LINE}{stood + owed:.4f}\"\n",
     "                rows[cost_at] = f\"{_COST_LINE}{stood:.4f}\"\n"),

    ("the review section runs over the Cost line again, to the next heading or the end", MACHINE,
     "                        if rows[i].startswith(\"## \") or i == cost_at), len(rows))\n",
     "                        if rows[i].startswith(\"## \")), len(rows))\n"),

    # ── claim 5: the panel's live counter sums what the dashboard sums ────────────────────────
    ("the panel's running total counts `note` events alone again", PANEL,
     "  if(e.data&&typeof e.data.cost_usd==\"number\"){focus.cost+=e.data.cost_usd;\n",
     "  if(e.kind==\"note\"&&e.data&&e.data.cost_usd){focus.cost+=e.data.cost_usd;\n"),
]
