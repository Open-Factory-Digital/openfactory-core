"""The ready-for-you message carries the preview's link while one is up (#405's hook, found building
#413): `link_for` compared the registry's project its callers hand it with the record's project
NAME, never equal, so the link was "" for every card."""

TEST = "tests/test_a_preview_starts_itself_when_the_pull_request_opens.py"

MUTATIONS = [
    ("the hook compares the project its callers hand it with a name again", "openfactory/preview/live.py",
     '    project = str(getattr(project, "name", project) or "")\n',
     ""),
]
