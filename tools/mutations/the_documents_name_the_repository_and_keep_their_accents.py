"""The documents name the repository and keep their accents — the cuts that put the first live
backfill's two blemishes back (2026-09-06).

ROW 1 IS THE SLUG CUTTING LETTERS OUT: `superf-cie` again.

ROW 2 IS THE LABEL DEFAULTING TO THE FULL PATH — the survey never had a name, only a directory.

ROWS 3-5 ARE THE THREE PLACES A READER SAW THE TEMP PATH: the survey's first line, every agent
document's header, and the report.

ROW 6 IS THE CALLER KEEPING THE NAME TO ITSELF: the backfill clones by the declared name and
surveys without handing it over, so the fallback (the temp directory's own name) is what gets
published.
"""

TEST = "tests/test_the_documents_name_the_repository_and_keep_their_accents.py"

MUTATIONS = [
    ("the slug keeps [a-z0-9] only, cutting every accented letter out — `superf-cie`",
     "openfactory/knowledge/okf.py",
     '    folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore")'
     '.decode("ascii")\n',
     '    folded = title\n'),

    ("the label falls back to the full checkout path",
     "openfactory/onboarding/context.py",
     "        label=label or resolved.name,\n",
     "        label=label or str(resolved),\n"),

    ("the survey's first line prints the checkout path again",
     "openfactory/onboarding/context.py",
     "    out.append(f\"- {w['s_repository']}: `{s.label or s.repo}`\")\n",
     "    out.append(f\"- {w['s_repository']}: `{s.repo}`\")\n"),

    ("every agent document's header cites the checkout path again",
     "openfactory/onboarding/context.py",
     '        f"> _(`{survey_result.label or survey_result.repo}`)_",\n',
     '        f"> _(`{survey_result.repo}`)_",\n'),

    ("the report is headed by the checkout path again",
     "openfactory/onboarding/context.py",
     '    out = [f"context proposal · {proposal.label or proposal.repo}"]\n',
     '    out = [f"context proposal · {proposal.repo}"]\n'),

    ("the backfill surveys without handing the declared name over",
     "openfactory/onboarding/onboard.py",
     "        survey = ctx.survey(str(source), history=history, label=repo_of(project))\n",
     "        survey = ctx.survey(str(source), history=history)\n"),
]
