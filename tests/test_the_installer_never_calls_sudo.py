"""The one-line install never needs root, on any host, and never sends a byte anywhere.

TWO PROMISES THE README MAKES UNPROMPTED, both because Hacker News finds them anyway and being
first is worth more than the sentences cost. A promise printed on a page and checked by nothing is
a promise that lasts until the next convenient `sudo`.

**`sudo`.** The old first-run path opened with `sudo mkdir -p /var/lib/openfactory-work`, and P0.4
removed the need for it by writing a work directory under the user's own `$HOME`. That fix is
undone the first time a script reaches for root to create a directory, chown a file or install a
package — and it would be undone for a *good local reason* every time. The measurable form of the
success metric "`sudo` invocations on the first-run path: 0, Linux and macOS" is this file.

**Telemetry.** *The installer sends nothing anywhere. There is no telemetry in this project.* The
script talks to exactly two hosts — github.com for the release assets, ghcr.io for the images — and
every other outbound destination is an offence. This is deliberately a whitelist rather than a
blacklist of known analytics domains: a blacklist is a list somebody has to keep, and the first
endpoint nobody thought of passes it.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "install.sh"
SCRIPT = INSTALLER.read_text()


def _code_lines() -> list[str]:
    """The lines that RUN, without the comments."""
    out = []
    for line in SCRIPT.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append(line)
    return out


#: A double- or single-quoted span. Removed before scanning for COMMANDS, because a quoted string
#: in this script is a MESSAGE and messages are the opposite of invocations.
_STRING_LITERAL = re.compile(r'"[^"]*"|\'[^\']*\'')


def _commands_only(line: str) -> str:
    """The line with its message strings taken out.

    THIS DISTINCTION IS THE WHOLE TEST AND IT COST A FALSE POSITIVE TO FIND (2026-08-31). The
    daemon check refuses with

        die "Docker is installed but its daemon is not answering." \\
            "Start Docker Desktop, or `sudo systemctl start docker`, then run this again."

    — which is the script TELLING somebody how to start their own daemon, in a remedy, which is
    the house rule working exactly as intended. A scan that reads that as "the installer calls
    sudo" reports the correct behaviour as the defect, and would be deleted the first time
    somebody looked at it. What is forbidden is INVOKING root, and an invocation is not inside
    quotes."""
    return _STRING_LITERAL.sub("", line)


def test_the_scan_can_see_the_code_and_skips_the_prose():
    """Verify the verifier. A scan that found nothing would pass every assertion below."""
    code = _code_lines()

    assert len(code) > 80, f"only {len(code)} code lines — the scan has lost its subject"
    assert any("docker run" in line for line in code), "the scan is not reading the real script"
    assert not any(line.strip().startswith("#") for line in code)


def test_the_installer_never_calls_sudo():
    """THE metric. Zero, on Linux and macOS, on the first-run path."""
    offenders = [line.strip() for line in _code_lines()
                 if re.search(r"(^|[;&|(]|\s)(sudo|doas|pkexec)\s", _commands_only(line))]

    assert not offenders, (
        "install.sh invokes a privilege escalation: " + "; ".join(offenders) +
        "\nEverything it writes belongs inside the target directory, which the user owns. If a "
        "step seems to need root, the step is wrong — that is how the job workspace moved out of "
        "/var/lib in the first place.")


def test_nothing_it_writes_lands_outside_the_target_directory():
    """The property `sudo` was the symptom of. A script that writes to /usr/local, /etc or
    /var/lib does not need root because of an unlucky default — it needs root because it is
    writing where it should not."""
    system_paths = re.compile(r"(?<![\w$/])/(?:usr|etc|opt|var/lib|Library|System)/")
    offenders = []
    for line in _code_lines():
        # the docker socket is READ, not written, and it is the whole docker-out-of-docker design
        if "/var/run/docker.sock" in line:
            continue
        if system_paths.search(line):
            offenders.append(line.strip())

    assert not offenders, (
        "install.sh touches a system path: " + "; ".join(offenders) +
        "\nEverything goes inside the target directory or into a Docker volume.")


def test_the_promise_is_printed_where_somebody_reading_the_script_will_see_it():
    """The claim and the check ship together, or the claim is decoration."""
    header = SCRIPT[:SCRIPT.index("set -eu")]

    assert re.search(r"never needs? `?sudo`?", header, re.I), (
        "install.sh's header no longer promises it needs no `sudo` — the guard below is the proof "
        "of a sentence nobody is making")


# ── telemetry ───────────────────────────────────────────────────────────────────────────────────

#: The only two hosts this script may talk to. A WHITELIST, deliberately: a list of known analytics
#: domains is a list somebody has to maintain, and the first endpoint nobody thought of passes it.
ALLOWED_HOSTS = {
    "github.com",           # the release: the assets and the tag this install is pinned to
    "ghcr.io",              # the registry: the three images
    "localhost",            # the panel, once it is up — this machine talking to itself
    "docs.docker.com",      # named in a REMEDY, never fetched: where to go if docker is missing
    "openfactory.digital",  # the headline in this script's own header. `curl` fetches THIS FILE
                            # from there; the file itself never calls back to it, which is the
                            # distinction that matters and the reason it is listed rather than
                            # scrubbed out of the comment a reader is meant to recognise.
}

_URL = re.compile(r"https?://([A-Za-z0-9.\-]+)")


def test_the_installer_sends_nothing_anywhere():
    """*The installer sends nothing anywhere. There is no telemetry in this project.* Every URL in
    the file — code and prose alike, because a comment is where a beacon would be least noticed —
    has to be one of the two hosts the install genuinely needs."""
    hosts = {m.group(1) for m in _URL.finditer(SCRIPT)}
    stray = sorted(hosts - ALLOWED_HOSTS)

    assert not stray, (
        f"install.sh names hosts outside the release and the registry: {stray}. The README "
        f"promises this script sends nothing anywhere, and that promise is only worth making "
        f"because it is checked.")


@pytest.mark.parametrize("beacon", [
    r"\bcurl\b[^\n|]*-X\s*POST", r"\bcurl\b[^\n|]*--data", r"\bcurl\b[^\n|]*-d\s",
    r"\bwget\b[^\n]*--post", r"\bnc\b\s+-", r"/dev/tcp/",
])
def test_it_never_sends_anything_even_to_a_host_it_is_allowed_to_reach(beacon):
    """The whitelist above bounds WHERE; this bounds WHAT. `curl -X POST https://github.com/...`
    passes a host check and is still a report about somebody's machine leaving it."""
    offenders = [line.strip() for line in _code_lines() if re.search(beacon, line)]

    assert not offenders, (
        f"install.sh sends data out: {offenders}. Every network call it makes is a DOWNLOAD.")


#: `NAME="value"` / `name=value` at any indentation — the script's own assignments.
_ASSIGNMENT = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)=(?:"([^"]*)"|([^\s;|&]+))', re.M)


def _expand(line: str) -> str:
    """`line` with the script's own variables substituted in, as far as they resolve.

    WITHOUT THIS THE GUARD BELOW READS ONE LINE AND UNDERSTANDS NOTHING. The asset download is
    `curl -fsSL "${base}/${asset}"`, and `base` is built two lines earlier out of `RELEASES`, which
    is built at the top out of `ORG` and `REPO`. A scan that only pattern-matched the literal text
    would have to be taught each new variable name by hand — and the first `curl "$SOMETHING"` that
    nobody taught it about is precisely the one worth catching."""
    values = {m.group(1): (m.group(2) if m.group(2) is not None else m.group(3))
              for m in _ASSIGNMENT.finditer(SCRIPT)}
    for _ in range(5):  # enough for ORG -> RELEASES -> base; a cycle simply stops resolving
        expanded = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}",
                          lambda m: values.get(m.group(1), m.group(0)), line)
        if expanded == line:
            break
        line = expanded
    return line


def test_the_expansion_resolves_the_chain_the_asset_download_is_built_from():
    """Verify the verifier. If `_expand` silently stopped resolving, every URL would come back
    unrecognised and the guard below would fail loudly rather than pass quietly — but the reverse
    (an expansion that produced an allowed string from anything) would be invisible."""
    assert "github.com" in _expand('curl "${RELEASES}/latest"')
    assert "releases/download" in _expand('curl "${base}/${asset}"')
    assert _expand('curl "${NOT_A_VARIABLE_HERE}/x"') == 'curl "${NOT_A_VARIABLE_HERE}/x"'


def test_every_download_is_a_release_asset_or_an_image():
    """The positive twin: what the two allowed hosts are actually used for. A fetch of anything
    else from github.com — a script, a gist — would pass the host check and be an arbitrary
    payload."""
    fetches = [line.strip() for line in _code_lines() if re.search(r"\bcurl\b", line)]
    assert fetches, "nothing is downloaded — this guard has lost its subject"

    for line in fetches:
        assert re.search(r"releases/(latest|download)|localhost", _expand(line)), (
            f"this fetches something that is neither a release asset nor the local panel: {line}")
