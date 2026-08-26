"""What is installed in this interpreter is a fact about the bench, not about the case.

`make install` — which is what CI runs — installs the repository's own add-on packages beside the
core; a developer's `pip install -e '.[dev]'` does not. On 2026-08-26 that single difference was
FIVE tests red on CI and green on every laptop: four asserting an exact `FallbackState` (the
platform's own chat rows appeared among the installed kinds) and one asserting that `channel:
slack` is REFUSED before its row is served (it was already served, by the bench). All five read
`importlib.metadata.entry_points()`, which answers the truth about the machine.

The firewall in `conftest.py` filters the platform's own declared rows out of discovery, so the
suite's view of "what is installed" is a controlled input — the same doctrine as the credential
floor, one axis over. A test that wants a row SERVES it (`vendor_addons.install`, which replaces
the function outright and therefore wins); a stranger's real distribution is untouched.

Held from both sides: the filter is fed planted points here (so these guards mean the same thing
on a laptop and on CI), and, where the bench really does carry the packages, discovery is asserted
not to show them.
"""

from __future__ import annotations

import importlib.metadata

import pytest
import vendor_addons
from vendor_addons import Point, install, not_ours

from openfactory import plugins

OURS = {"channel.slack": "openfactory.adapters.channel.slack:build",
        "metrics.dynamodb": "openfactory.observability.dynamo:build"}


# ── the filter, on planted points: the same meaning on every bench ──────────────────────────────

def test_a_row_one_of_our_packages_declares_is_hidden():
    kept = not_ours([Point("channel.slack", OURS["channel.slack"])], OURS)
    assert kept == []


def test_a_strangers_row_is_left_alone():
    stranger = Point("notifier.acme", "acme_addons:build_notifier")
    assert not_ours([stranger], OURS) == [stranger]


def test_a_stranger_that_declares_the_SAME_KIND_from_its_own_module_is_left_alone():
    """Matched on name AND target. A stranger publishing its own `channel.slack` is a real
    packaging case — and hiding it would make the firewall a name blacklist, which is the shape
    this repository refuses everywhere else."""
    theirs = Point("channel.slack", "acme_addons.chat:build")
    assert not_ours([theirs], OURS) == [theirs]


def test_the_filter_has_a_subject_and_is_not_a_no_op():
    """Verify the verifier: fed a mixed list it returns strictly fewer, and exactly the strangers."""
    ours = Point("channel.slack", OURS["channel.slack"])
    theirs = Point("notifier.acme", "acme_addons:build_notifier")
    assert not_ours([ours, theirs, ours], OURS) == [theirs]


# ── the bench where the packages really are installed ───────────────────────────────────────────

def _packages_on_this_bench() -> dict[str, str]:
    """The platform's own rows this interpreter really carries, read from the DISTRIBUTIONS
    rather than from `entry_points`. The firewall filters the latter, and a guard that undid the
    firewall in order to look would be testing the undo — which is what the first version of this
    guard did, and it went red on the very bench it was written for."""
    declared = vendor_addons.declared()
    if not declared:
        return {}
    found: dict[str, str] = {}
    for dist in importlib.metadata.distributions():
        for ep in dist.entry_points:
            if ep.group == plugins.GROUP and declared.get(ep.name) == ep.value:
                found[ep.name] = ep.value
    return found


def test_where_the_bench_carries_our_packages_discovery_does_not_show_them():
    """The half that only has a subject on a bench built by `make install` — CI's bench, and the
    one this defect was found on. It skips BY NAME elsewhere rather than passing for the wrong
    reason."""
    raw = _packages_on_this_bench()
    if not raw:
        pytest.skip("this interpreter carries none of the platform's own add-on packages — "
                    "`make install` builds the bench where this assertion has a subject")
    seen = {p.name for p in importlib.metadata.entry_points(group=plugins.GROUP)}
    assert not (seen & set(raw)), f"the firewall let the bench through: {sorted(seen & set(raw))}"


def test_a_test_that_SERVES_one_of_our_rows_still_sees_it(monkeypatch):
    """The firewall hides; it does not lock. `install` replaces discovery outright, so a test
    that asks for a row gets it on every bench."""
    install(monkeypatch, "channel.slack")
    assert "slack" in plugins.known("channel", {"panel": object()})


def test_the_firewall_starts_every_test_with_an_EMPTY_loader_cache():
    """`plugins._cache` is a module global, and `monkeypatch.undo()` restores whatever was there
    BEFORE a test — which can itself be a dict another test populated. So the firewall clears it
    at every setup, and this asserts the fixture DOES that rather than trusting the line: the
    fixture is called with a recording double, because a cache-order defect between two real
    tests is exactly the kind that only appears under one random seed."""
    import conftest

    if not vendor_addons.declared():
        pytest.skip("no package under addons/ declares a row — the firewall returns early here")

    calls: list[tuple[object, str, object]] = []

    class _Recorder:
        def setattr(self, target, name, value=None, **_kw):
            calls.append((target, name, value))

    conftest._the_bench_is_not_the_case.__wrapped__(_Recorder())

    assert any(target is plugins and name == "_cache" and value is None
               for target, name, value in calls), (
        f"the firewall never cleared the loader cache; it did: "
        f"{[(getattr(t, '__name__', t), n) for t, n, _ in calls]}")
