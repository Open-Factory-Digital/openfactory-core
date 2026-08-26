"""HandOff — the tech-lead's impediment diagnosis: parse + render to both surfaces (ADR-0015)."""

from __future__ import annotations

import add_ons

from openfactory.contracts import HandOff, handoff_to_markdown, handoff_to_plain, parse_handoff

_SAMPLE = """
Here is my read.

```json
{
  "headline": "#412 needs you — CI/CD change blocked by policy",
  "what_happened": "The push was rejected because the diff edits .github/workflows/ci.yml.",
  "why": "A GitHub App without workflows permission cannot push workflow files. Verified ci.yml only defines pytest/vitest.",
  "correction": "The earlier note that e2e.yml covers the catalog specs is wrong: e2e.yml runs the default config, not playwright.catalog.config.ts.",
  "recommendation": "Descope the visual-regression suite into a separate human-owned ticket.",
  "alternatives": "A human wires the CI job + regenerates baselines, then the agent re-runs code-only."
}
```
"""


def test_parse_handoff_pulls_last_json_block():
    ho = parse_handoff(_SAMPLE)
    assert ho is not None
    assert ho.headline.startswith("#412 needs you")
    assert "workflows permission" in ho.why
    assert "wrong" in ho.correction
    assert ho.recommendation.startswith("Descope")


def test_parse_handoff_degrades_to_none():
    assert parse_handoff("") is None
    assert parse_handoff("no json here, just prose") is None
    assert parse_handoff('```json\n{"unrelated": 1}\n```') is None  # missing headline/what_happened


def test_render_github_has_headers_and_collapsed_raw():
    ho = parse_handoff(_SAMPLE)
    md = handoff_to_markdown(ho, raw_note="box failed: push failed")
    assert "### Tech-lead triage" in md
    assert "**What happened.**" in md and "**Why.**" in md
    assert "**Correction.**" in md and "**Recommendation.**" in md
    assert "<details><summary>Raw error</summary>" in md
    assert "box failed: push failed" in md


def test_render_slack_is_mrkdwn_and_concise():
    ho = parse_handoff(_SAMPLE)
    msg = handoff_to_plain(ho, ref="https://github.com/x/y/issues/412")
    assert msg.startswith("*#412 needs you")  # single-asterisk mrkdwn bold, no '#' header
    assert "### " not in msg  # markdown headers are not valid Slack mrkdwn
    assert "→ https://github.com/x/y/issues/412" in msg


def test_handoff_defaults_are_empty_strings():
    ho = HandOff()
    assert ho.headline == "" and ho.recommendation == "" and ho.suggested_command == ""


# ── resolution-driving: the executable one-command next step (ADR-0015, proactive) ──────────────

_WITH_CMD = """
```json
{
  "headline": "#386 needs you — a resume would re-run it clean",
  "what_happened": "The box crashed mid-run.",
  "why": "A transient prepare failure; the code and ticket are fine (verified).",
  "recommendation": "Resume it — a fresh run will land.",
  "suggested_command": "resume #386"
}
```
"""


def test_parse_handoff_pulls_suggested_command():
    ho = parse_handoff(_WITH_CMD)
    assert ho is not None and ho.suggested_command == "resume #386"


def test_render_surfaces_the_executable_command():
    ho = parse_handoff(_WITH_CMD)
    slack = handoff_to_plain(ho)
    gh = handoff_to_markdown(ho)
    # the operator gets a concrete one-command resolution, not just a diagnosis to rot
    # "Pra eu resolver" was asserted here for as long as the scaffold was hardcoded Portuguese —
    # this guard was PINNING the weld (#159): a neutral renderer shipped pt-BR labels to every
    # deployment in every language, and the suite defended it.
    assert "resume #386" in slack and "To resolve, reply:" in slack
    assert "resume #386" in gh and "To resolve" in gh


def test_no_command_when_fix_is_manual():
    # a genuinely-manual fix (empty suggested_command) renders no executable CTA
    ho = HandOff(headline="#9 needs you", what_happened="x", recommendation="a human wires ci.yml")
    assert "Pra eu resolver" not in handoff_to_plain(ho)
    assert "To resolve" not in handoff_to_markdown(ho)


# ── the promise must be executable: suggested_command is validated, never taken on faith ────────

def _handoff_with(cmd: str) -> str:
    return (
        '```json\n{"headline": "#447 needs you", "what_happened": "x", '
        f'"suggested_command": "{cmd}"}}\n```'
    )


def test_unexecutable_suggested_command_is_dropped():
    """The command is free-form LLM output that we then render as a promise ("reply this and I
    resolve it"). If the Slack listener can't parse it, the operator is sent to a dead end and
    the ticket rots — the exact failure the executable-next-step was meant to end."""
    for prose in ("wire the CI workflow", "resume", "merge #447", "ask the owner"):
        ho = parse_handoff(_handoff_with(prose))
        assert ho is not None and ho.suggested_command == "", prose
        assert "To resolve" not in handoff_to_markdown(ho)


def test_suggested_command_for_another_ticket_is_dropped():
    """A hallucinated issue number would have the bot instruct an admin — in its own voice — to
    act on an unrelated job. Only a command targeting THIS ticket survives."""
    assert parse_handoff(_handoff_with("skip #123"), issue="447").suggested_command == ""
    assert parse_handoff(_handoff_with("skip #447"), issue="447").suggested_command == "skip #447"


def test_suggested_command_is_normalized_to_what_the_listener_accepts():
    # a synonym verb + a bare number still round-trips to the canonical, executable spelling
    ho = parse_handoff(_handoff_with("please retry 447 now"), issue="447")
    assert ho.suggested_command == "resume #447"


def test_the_listener_and_the_handoff_share_one_grammar():
    """Guard against the drift that made this a bug: whatever the HandOff tells a human to type
    must be exactly what the Slack listener parses."""
    bot = add_ons.module("openfactory.runtime.slack.bot")

    cmd = parse_handoff(_handoff_with("skip #447"), issue="447").suggested_command
    assert bot._parse_action(cmd) == ("skip", "447")
