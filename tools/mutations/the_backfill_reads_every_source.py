"""The backfill reads every source (defects ledger #9) — the cuts that would read half a product
and say it read all of it."""

TEST = "tests/test_the_backfill_reads_every_source.py"

MUTATIONS = [
    ("the loop reads the default repository only",
     "openfactory/onboarding/onboard.py",
     "        for repo in wanted:\n",
     "        for repo in wanted[:1]:\n"),

    ("the second source's documents are dropped — the first proposal is written alone",
     "openfactory/onboarding/onboard.py",
     "    if len(proposals) == 1:\n        return proposals[0]\n",
     "    if proposals:\n        return proposals[0]\n"),

    ("a failed clone stops the others",
     "openfactory/onboarding/onboard.py",
     '                            else f"skipped: could not clone the source repository ({why})")\n'
     "                continue\n",
     '                            else f"skipped: could not clone the source repository ({why})")\n'
     "                break\n"),

    ("a failed clone is not named",
     "openfactory/onboarding/onboard.py",
     '                said[repo] = (f"{repo}: skipped, could not clone ({why})" if several\n',
     '                said[repo] = (f"skipped, could not clone ({why})" if several\n'),

    ("the map's folder is keyed by the default repository again",
     "openfactory/onboarding/onboard.py",
     "        home = _bundle_home(project, docs_clone, repo=repo)\n",
     "        home = _bundle_home(project, docs_clone)\n"),

    ("the concepts' folder is keyed by the default repository again",
     "openfactory/onboarding/onboard.py",
     "        here = _bundle_home(project, docs_clone, repo=repo)\n",
     "        here = _bundle_home(project, docs_clone)\n"),

    ("every source's questions are carried under the default repository",
     "openfactory/onboarding/onboard.py",
     "            _carry_questions(project, proposal, surveyed=True, repo=repo)\n",
     "            _carry_questions(project, proposal, surveyed=True)\n"),

    ("a repository's own headings are not demoted beneath its section",
     "openfactory/onboarding/onboard.py",
     '            parts += ["", f"## {label}", "", _demoted(rest).strip("\\n")]\n',
     '            parts += ["", f"## {label}", "", rest.strip("\\n")]\n'),

    # review of #76: the sentence read "every failure, then every success"
    ("the outcome is joined in the order things happened, not the declared one",
     "openfactory/onboarding/onboard.py",
     '        return "; ".join(said[repo] for repo in wanted if repo in said)\n',
     '        return "; ".join(said.values())\n'),
]
