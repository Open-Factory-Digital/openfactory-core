"""A release candidate is published as a pre-release, and the release process is tracked.

Run:  .venv/bin/python tools/mutate.py tools/mutations/the_release_process_is_written_down.py

Rows 1-2 publish a candidate the way every release was published before docs/RELEASING.md: as a
final release, or as Latest, which is what `install.sh` resolves with no `--version`. Row 3 stops
the version check reading the tag the way the document declares it. Row 4 ignores the release
agent again with the rest of `.claude/`. Rows 5-9 come from the review of #510: a candidate's
images under a tag `install.sh` never pulls, a candidate moving the floating `1`, `latest` pushed
on every final tag, a hyphenated version refused by the declared-version guard, and SECURITY.md
stating a policy of its own again.
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

    # anchored on the base image's block, whose `images:` line is the one that is unique
    ("a candidate's images are published without their own tag", WORKFLOW,
     "          images: ${{ env.REGISTRY }}/${{ env.ORG }}/openfactory-base\n          tags: |\n            type=ref,event=branch\n"
     "            type=raw,value=${{ github.ref_name }},enable=${{ startsWith(github.ref, 'refs/tags/') }}\n",
     "          images: ${{ env.REGISTRY }}/${{ env.ORG }}/openfactory-base\n          tags: |\n            type=ref,event=branch\n"
     "            type=semver,pattern=v{{version}}\n"),

    ("a candidate moves the floating major tag", WORKFLOW,
     "          images: ${{ env.REGISTRY }}/${{ env.ORG }}/openfactory-base\n          tags: |\n            type=ref,event=branch\n"
     "            type=raw,value=${{ github.ref_name }},enable=${{ startsWith(github.ref, 'refs/tags/') }}\n"
     "            type=semver,pattern={{major}}.{{minor}},enable=${{ !contains(github.ref_name, '-') }}\n"
     "            type=semver,pattern={{major}},enable=${{ !contains(github.ref_name, '-') }}\n",
     "          images: ${{ env.REGISTRY }}/${{ env.ORG }}/openfactory-base\n          tags: |\n            type=ref,event=branch\n"
     "            type=raw,value=${{ github.ref_name }},enable=${{ startsWith(github.ref, 'refs/tags/') }}\n"
     "            type=semver,pattern={{major}}.{{minor}},enable=${{ !contains(github.ref_name, '-') }}\n"
     "            type=semver,pattern={{major}}\n"),

    ("every final tag pushes latest again", WORKFLOW,
     "          images: ${{ env.REGISTRY }}/${{ env.ORG }}/openfactory-base\n          tags: |\n            type=ref,event=branch\n"
     "            type=raw,value=${{ github.ref_name }},enable=${{ startsWith(github.ref, 'refs/tags/') }}\n"
     "            type=semver,pattern={{major}}.{{minor}},enable=${{ !contains(github.ref_name, '-') }}\n"
     "            type=semver,pattern={{major}},enable=${{ !contains(github.ref_name, '-') }}\n"
     "          flavor: latest=false\n",
     "          images: ${{ env.REGISTRY }}/${{ env.ORG }}/openfactory-base\n          tags: |\n            type=ref,event=branch\n"
     "            type=raw,value=${{ github.ref_name }},enable=${{ startsWith(github.ref, 'refs/tags/') }}\n"
     "            type=semver,pattern={{major}}.{{minor}},enable=${{ !contains(github.ref_name, '-') }}\n"
     "            type=semver,pattern={{major}},enable=${{ !contains(github.ref_name, '-') }}\n",
     "tests/test_every_image_the_compose_file_names_is_one_the_release_builds.py::"
     "test_the_release_never_publishes_a_moving_tag_a_user_could_pin_to"),

    ("a candidate's hyphenated version is refused by the declared-version guard",
     "tests/test_the_wheel_is_published_under_the_name_the_docs_tell_you_to_install.py",
     '_A_TAG_COULD_CARRY = re.compile(r"\\d+\\.\\d+\\.\\d+([-abrc.dev+][0-9A-Za-z.+-]*)?")',
     '_A_TAG_COULD_CARRY = re.compile(r"\\d+\\.\\d+\\.\\d+([abrc.dev+][0-9A-Za-z.+-]*)?")',
     "tests/test_the_wheel_is_published_under_the_name_the_docs_tell_you_to_install.py::"
     "test_what_a_tag_could_carry_includes_a_candidate"),

    ("SECURITY.md states a supported-versions policy of its own again", "SECURITY.md",
     "Which release lines receive security fixes, and how a fix is released, is\n",
     "Pre-1.0: only the `main` branch receives fixes. Which release lines receive security fixes, "
     "and how a fix is released, is\n"),
]
