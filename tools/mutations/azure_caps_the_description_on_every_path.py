"""The vendor's ceiling, on both paths that write a description.

Azure DevOps refuses a description over 4000 characters outright — a 400, not a truncation. The
rule was written down and enforced on `set_pr_body` (the UPDATE) and missing from `open_pr` (the
CREATE), which is the path that runs on EVERY job before any other can. Found live on the first
Azure DevOps ticket to reach the PR station: every station green, then a job that had done all of
its work could not hand it in.

THE LAST TWO ROWS ARE THE NEAR-MISSES, not the defect: a cut that appends its marker ON TOP of
the limit is still a 400, and a cut with no marker reads as a body that simply ends there.
"""

TEST = "tests/test_the_pull_request_says_what_the_card_says.py"

MUTATIONS = [
    # ── both callers reach the one method ───────────────────────────────────────────────────────
    ("the create path sends the body verbatim — the defect exactly as it shipped",
     "openfactory/adapters/forge/azure_devops.py",
     '            "description": self._fit_description(body),',
     '            "description": body,'),

    ("the update path stops measuring and the ceiling is enforced on one side only",
     "openfactory/adapters/forge/azure_devops.py",
     "        body = self._fit_description(body)",
     "        body = body"),

    # ── what the method does ────────────────────────────────────────────────────────────────────
    ("nothing is ever cut, so a long description reaches the vendor and comes back 400",
     "openfactory/adapters/forge/azure_devops.py",
     "        if len(body) <= cls._DESCRIPTION_MAX:",
     "        if True:"),

    ("it cuts to the ceiling and then appends the marker past it — a long body turned into a 400 "
     "by the very code that exists to prevent one",
     "openfactory/adapters/forge/azure_devops.py",
     "        return body[: cls._DESCRIPTION_MAX - len(cls._CUT_NOTE)] + cls._CUT_NOTE",
     "        return body[: cls._DESCRIPTION_MAX] + cls._CUT_NOTE"),

    ("it cuts silently, so a description that stops mid-sentence reads as one that ends there",
     "openfactory/adapters/forge/azure_devops.py",
     "        return body[: cls._DESCRIPTION_MAX - len(cls._CUT_NOTE)] + cls._CUT_NOTE",
     "        return body[: cls._DESCRIPTION_MAX]"),
]
