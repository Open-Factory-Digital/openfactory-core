"""The sizer names the files or directories it expects the change to touch (#33, decision 2).

The card has no notion of the area it touches — `Ticket` carries no paths, and every path-based
judgement downstream (the risk assessment, the knowledge gate) is derived from the DIFF, which does
not exist before execution. The sizer already reads the checkout to judge INVEST; naming where the
change would land costs it nothing and is what lets the plan ask, before anything is spent, how
much the bundle already knows about that area. Not a sizing criterion: `fit` with many touches is
still `fit` (the owner's rule — file count is not a criterion).
"""

from __future__ import annotations

from openfactory.runtime.temporal.activities import _parse_verdict
from openfactory.runtime.temporal.io import PreflightVerdict

VERDICT = '''Some prose.
```json
{"verdict": "fit", "reasons": "one outcome",
 "touches": ["services/api/src/routes/", "./packages/shared/src/domain.ts", "  ", "apps\\\\web\\\\x.ts"]}
```'''


def test_touches_ride_the_verdict_normalised():
    v = _parse_verdict(VERDICT)
    assert v is not None and v.verdict == "fit"
    assert v.touches == ["services/api/src/routes/", "packages/shared/src/domain.ts",
                         "apps/web/x.ts"], v.touches


def test_a_verdict_without_touches_is_still_a_verdict():
    v = _parse_verdict('```json\n{"verdict": "fit", "reasons": "r"}\n```')
    assert v is not None and v.touches == []
    assert PreflightVerdict().touches == [], "the wire shape defaults to 'could not tell'"


def test_touches_are_bounded():
    many = ", ".join(f'"f{i}.py"' for i in range(60))
    v = _parse_verdict('```json\n{"verdict": "fit", "touches": [' + many + ']}\n```')
    assert v is not None and len(v.touches) == 30


def test_the_sizer_prompt_asks_for_it_and_says_it_is_not_a_criterion():
    from openfactory.adapters.agent.roles import role_prompt

    prompt = role_prompt("sizer")
    assert '"touches": ["<the files or directories you expect the change to touch' in prompt, (
        "the schema names the key but does not say what goes in it")
    assert "NOT a sizing criterion" in prompt
