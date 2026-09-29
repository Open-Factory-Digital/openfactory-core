"""Mutation plan for #403 — a card's pull request is recorded, and asked about, in the FORGE's
repository, never in the tracker's namespace (`Ticket.repo`).

Each row puts back one way the tracker's name for the card's container reached a place where a
repository belongs; every row must turn `tests/test_a_pull_request_lives_in_the_forges_repository.py`
red.
"""

TEST = "tests/test_a_pull_request_lives_in_the_forges_repository.py"
DEMAND = "openfactory/preview/demand.py"
SIBLINGS = "openfactory/preview/siblings.py"
STEPS = "openfactory/preview/steps.py"
MACHINE = "openfactory/orchestrator/machine.py"

MUTATIONS = [
    ("the offer records the ticket's repo again — the board's name as the pull request's", DEMAND,
     '    repo = str(repo if repo is not None else (repo_of(project) or ""))',
     '    repo = str(getattr(ticket, "repo", "") or "")'),
    ("the offer ignores the repository its caller named", DEMAND,
     '    repo = str(repo if repo is not None else (repo_of(project) or ""))',
     '    repo = str(repo_of(project) or "")'),
    ("the job hands the offer no repository", MACHINE,
     "                         branch=branch, repo=self._change_repo(),",
     "                         branch=branch,"),
    ("the job's repository is the ticket's again", MACHINE,
     '        return repo_of(self.project) if self.project is not None else ""',
     '        return "shop"'),
    ("a record naming the board is read as a repository again", DEMAND,
     "    return {url: repo for url, repo in repos.items() if repo not in board}",
     "    return repos"),
    ("the board's names include one that is also the forge's repository", DEMAND,
     "    return {n for n in names if n and not (own and repo_match(n, own))}",
     "    return {n for n in names if n}"),
    ("the start reads the record's repositories raw", SIBLINGS,
     "    repos = (repos_of(project, was) if project is not None",
     "    repos = (dict(getattr(was, 'repos', {}) or {}) if project is not None"),
    ("the start writes the board's name back onto the record", STEPS,
     "                repos={**demand.repos_of(project, was), **{c.url: c.repo for c in live}},",
     "                repos={**(was.repos if was else {}), **{c.url: c.repo for c in live}},"),
    ("the knowledge gate reads the bundle of the ticket's repo", MACHINE,
     "            self._card_repo = self._change_repo()",
     '            self._card_repo = getattr(ticket, "repo", "") or ""'),
]
