"""What the backfill spends, recorded where every other spend is (`observability.metrics`).

THE FIRST LIVE ONBOARDING RAN SIX AGENT PASSES AND RECORDED NONE (2026-09-06): one
citation-checked pass for the five documents and one per budgeted concept, each a harness run on a
client's repository, each with a cost the harness reported — and `context.agent_ask` returned the
text and dropped the `AgentRunResult` that carried it. The cost dashboard, the one instrument every
other decision here is measured on, showed a day with no spend. A platform whose rule is that every
spend is visible cannot keep a door through which money leaves unseen.

ONE RECORDER FOR EVERY TRIGGER, like the authoring it meters: the onboarding's backfill, the
merge-time renewal and the knowledge gate all reach the harness through
`onboard.semantic_pass_for`, so the recorder is bound there and meters all three. A row is the
same shape a job's passes are recorded in (`kind="agent_run"`), under one role the dashboard can
group by, and the ticket names the repository the pass read — a backfill has no ticket.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("openfactory.onboarding.spend")

#: the role every backfill pass is recorded under — one word the cost dashboard groups by
BACKFILL_ROLE = "backfill"


@dataclass
class Spend:
    """The passes one backfill made and what they cost — each recorded as it happens, and
    summed for the sentence the operator reads at the end."""

    project: str
    repo: str
    runs: int = 0
    cost_usd: float = 0.0
    #: how many of the runs reported a cost — a harness that reports none is said, not zeroed
    priced: int = 0

    def note(self, result: object) -> None:
        """One pass: counted, summed, and written as an `agent_run` row."""
        self.runs += 1
        cost = getattr(result, "cost_usd", None)
        if cost is not None:
            self.cost_usd += float(cost)
            self.priced += 1
        record_backfill_run(self.project, self.repo, result)

    def summary(self) -> str:
        """`"3 agent passes, US$ 0.42"` — or "" when no pass was made."""
        if not self.runs:
            return ""
        passes = f"{self.runs} agent pass{'es' if self.runs != 1 else ''}"
        if self.priced == self.runs:
            return f"{passes}, US$ {self.cost_usd:.2f}"
        if self.priced:
            return (f"{passes}, US$ {self.cost_usd:.2f} for the {self.priced} that reported a "
                    f"cost")
        return f"{passes}, cost not reported by the harness"

    def said(self, mode: str) -> str:
        """`mode` with the spend appended when there is one — the outcome sentence."""
        return f"{mode} — {self.summary()}" if self.runs else mode


def record_backfill_run(project: str, repo: str, result: object) -> None:
    """One `agent_run` row, the shape a job's passes are recorded in, through the deployment's
    one sink.

    THE ROW ITSELF IS `observability/job_record.record_one_pass`, because `box prove`'s single
    question is a pass outside a job too and a second copy of this would be a second answer to
    what a pass costs (review of #109). What stays here is what is this door's own: the role a
    backfill is grouped under, and the repository its ticket names."""
    from openfactory.observability.job_record import record_one_pass

    record_one_pass(project=project, ticket=f"backfill:{repo}", role=BACKFILL_ROLE, result=result)
