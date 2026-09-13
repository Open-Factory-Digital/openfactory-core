"""Issue #125: the product panel must carry the action's diagnosis and corpus findings."""

TEST = "tests/test_the_product_role_lives_outside_slack.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    (
        "the failed-read branch discards the action's diagnosis",
        PANEL,
        '_prod.reqMessage=(out&&out.message)||"I could not read the requirements.";',
        '_prod.reqMessage="I could not read the requirements.";',
    ),
    (
        "the success branch discards corpus findings",
        PANEL,
        "_prod.reqFindings=(out&&out.ok&&out.data&&Array.isArray(out.data.findings))?out.data.findings:[];",
        "_prod.reqFindings=[];",
    ),
    (
        "the empty requirements branch hides its findings",
        PANEL,
        "nothing written yet${findings}",
        "nothing written yet",
    ),
    (
        "the populated requirements branch hides its findings",
        PANEL,
        '}).join("")+findings;',
        '}).join("");',
    ),
]
