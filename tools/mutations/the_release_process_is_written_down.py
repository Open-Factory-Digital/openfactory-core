"""A release candidate is published as a pre-release, and the release process is tracked.

Run:  .venv/bin/python tools/mutate.py tools/mutations/the_release_process_is_written_down.py

Rows 1-2 publish a candidate the way every release was published before docs/RELEASING.md: as a
final release, or as Latest, which is what `install.sh` resolves with no `--version`. Row 3 stops
the version check reading the tag the way the document declares it. Row 4 ignores the release
agent again with the rest of `.claude/`.
"""

TEST = "tests/test_a_release_candidate_is_published_as_a_pre_release.py"

WORKFLOW = ".github/workflows/release.yml"

MUTATIONS = [
    ("a candidate is published as a final release", WORKFLOW,
     "          prerelease: ${{ contains(github.ref_name, '-') }}\n",
     ""),

    ("a candidate becomes Latest, the version install.sh resolves", WORKFLOW,
     "          make_latest: ${{ !contains(github.ref_name, '-') }}\n",
     ""),

    ("the version check reads the tag with its v", WORKFLOW,
     '          tagged="${GITHUB_REF_NAME#v}"\n',
     '          tagged="${GITHUB_REF_NAME}"\n'),

    ("the release agent is ignored with the rest of .claude/", ".gitignore",
     ".claude/*\n!.claude/agents/\n",
     ".claude/\n"),
]
