"""One product, N repositories — and N proofs, because a proof is about ONE toolchain.

The gap, measured before it was fixed (C-18 fact sheet, 2026-08-13): the box proof was keyed by
PROJECT NAME and the pickup gate ran before the board was read, so a qualified card
(`owner/web#5`) was admitted on the strength of a proof taken against `owner/api` — a different
codebase, a different toolchain, possibly a different image contract. The gate looked closed
and stood open, on exactly the shape an enterprise client arrives in (front + back, one product).

What holds now:

  1. the DEFAULT repo's proof keeps today's filename byte for byte — no existing single-repo
     deployment re-proves anything (the `_checkout_key` contract, same as the repo cache);
  2. a foreign-repo card is admitted only on ITS OWN repo's proof; missing one HOLDS that card
     — and only that card — with a reason naming `box prove <project> --repo <owner/name>`;
  3. default-repo cards keep flowing while a foreign repo is held (one repo's gap must not
     silence the whole product);
  4. the gate announcement is per proof key, so two repos cannot overwrite each other's marker.
"""

from __future__ import annotations

import json

import pytest

from openfactory import box_prove
from openfactory.contracts.project import Project, ProviderRef


def _product() -> Project:
    return Project(name="dsk", repo_path="/tmp/dsk",
                   tracker=ProviderRef(kind="github", repo="acme/api",
                                       options={"board_owner": "acme", "board_number": "1"}),
                   forge=ProviderRef(kind="github", repo="acme/api"))


def _proof_file(tmp_path, key: str, *, ok: bool = True) -> None:
    (tmp_path / f"{key}.json").write_text(json.dumps({
        "project": key, "image": "img:1", "ok": ok, "digest": "sha256:abc",
        "toolbox": "linux-amd64-glibc", "commands_hash": "cafe", "at": "2026-08-13"}))


@pytest.fixture
def proofs(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_PROOFS", str(tmp_path))
    monkeypatch.setattr(box_prove, "PROOF_DIR", tmp_path)
    return tmp_path


def test_the_default_repos_proof_keeps_todays_filename(proofs):
    """The migration that must not exist: byte-for-byte the same key as before."""
    from openfactory.runtime.card_repo import _checkout_key

    assert _checkout_key(_product(), "acme/api") == "dsk"


def test_a_foreign_repo_without_a_proof_is_held_BY_NAME(proofs, monkeypatch):
    monkeypatch.setattr(box_prove, "_current_digest", lambda image: "sha256:abc")
    reason = box_prove.gate_reason(_product(), sandbox="container", repo="acme/web")

    assert reason is not None
    assert "acme/web" in reason
    assert "--repo acme/web" in reason, "the remedy must name the per-repo prove"


def test_a_foreign_repo_with_its_own_proof_passes(proofs, monkeypatch):
    from openfactory.runtime.card_repo import _checkout_key

    key = _checkout_key(_product(), "acme/web")
    _proof_file(proofs, key)
    monkeypatch.setattr(box_prove, "_current_digest", lambda image: "sha256:abc")
    monkeypatch.setattr(box_prove.tb if hasattr(box_prove, "tb") else box_prove,
                        "read_stamp", lambda: {"variant": "linux-amd64-glibc"}, raising=False)

    class _Stamp:
        @staticmethod
        def read_stamp():
            return {"variant": "linux-amd64-glibc"}

    monkeypatch.setattr("openfactory.runtime.toolbox.read_stamp", _Stamp.read_stamp)
    # the foreign manifest hash degrades to the proof's own on an unreachable checkout — the
    # gate must not block on a question it cannot ask (same arm the default path has)
    reason = box_prove.gate_reason(_product(), sandbox="container", repo="acme/web")

    assert reason is None, reason


def test_the_default_repos_gate_never_pays_the_foreign_lookup(proofs, monkeypatch):
    """repo="" (or the default repo) must take exactly the old path — no _runner_view, no cache
    sync. Pinned by making the foreign arm explode if entered."""
    _proof_file(proofs, "dsk")

    def _boom(*a, **kw):
        raise AssertionError("the default-repo gate entered the foreign arm")

    monkeypatch.setattr("openfactory.runtime.card_repo._runner_view", _boom)
    monkeypatch.setattr(box_prove, "_current_digest", lambda image: "sha256:abc")
    monkeypatch.setattr("openfactory.runtime.toolbox.read_stamp",
                        lambda: {"variant": "linux-amd64-glibc"})
    # a manifest that hashes to exactly what the proof recorded — the gate passes on freshness;
    # an OSError (not FileNotFoundError: that one now means "manifest not merged yet" and holds)
    # keeps the degrade arm covered too
    monkeypatch.setattr("openfactory.loader.load_manifest",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("unreachable")))

    assert box_prove.gate_reason(_product(), sandbox="container") is None


def test_a_proven_repo_whose_manifest_is_not_merged_yet_is_held_and_says_merge(proofs,
                                                                               monkeypatch):
    """Onboarding deliberately mints this state: proof saved, manifest riding an un-merged PR.
    Admitting the card sent it into a job whose first act fails on this exact file — the gate
    says the true sentence instead (adversarial review, 2026-08-13)."""
    from openfactory.runtime.card_repo import _checkout_key

    _proof_file(proofs, _checkout_key(_product(), "acme/web"))
    monkeypatch.setattr(box_prove, "_current_digest", lambda image: "sha256:abc")
    monkeypatch.setattr("openfactory.runtime.toolbox.read_stamp",
                        lambda: {"variant": "linux-amd64-glibc"})
    monkeypatch.setattr("openfactory.factory.resolve_repo_path",
                        lambda *a, **kw: proofs / "nowhere")
    monkeypatch.setattr("openfactory.loader.load_manifest",
                        lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError("no manifest")))

    reason = box_prove.gate_reason(_product(), sandbox="container", repo="acme/web")

    assert reason is not None, "an unmerged manifest was admitted"
    assert "merge" in reason and "proven" in reason, reason


def test_announcements_are_per_key_so_repos_do_not_overwrite_each_other(proofs):
    assert box_prove.announce_gate("dsk--acme--web", "held for web")
    assert box_prove.announce_gate("dsk", "held for api")

    assert (proofs / "dsk--acme--web.gate").exists()
    assert (proofs / "dsk.gate").exists()
    assert "web" in (proofs / "dsk--acme--web.gate").read_text()


def test_scan_todo_holds_ONLY_the_foreign_card_and_admits_the_default(monkeypatch, proofs):
    """The whole point, end to end through the activity: web has no proof, api flows —
    one repo's gap must not silence the whole product, and must not leak through either."""
    import asyncio

    import openfactory.adapters.board as board_pkg
    import openfactory.runtime.temporal.activities as acts
    from openfactory.runtime.temporal.io import ScanInput

    project = _product()
    monkeypatch.setattr(acts.ProjectRegistry, "get", lambda self, name: project)

    class _Board:
        def items_in_status(self, status):
            return ["7", "acme/web#9"]

    class _Ticket:
        state = "open"

    class _Tracker:
        def get_ticket(self, ref):
            return _Ticket()

    monkeypatch.setattr(board_pkg, "build_board", lambda *a, **kw: _Board())
    monkeypatch.setattr(acts, "_tracker_for", lambda p: _Tracker())
    monkeypatch.setattr("openfactory.credentials.tracker_token_for", lambda p: "tok")

    def _gate(project, *, sandbox, repo=""):
        return None if not repo else "the box for acme/web has never been proven — run …"

    monkeypatch.setattr("openfactory.box_prove.gate_reason", _gate)

    got = asyncio.run(acts.scan_todo(ScanInput(project="dsk", board_owner="acme",
                                               board_number="1", pickup_status="TO-DO")))

    assert got == ["7"], f"the foreign card leaked through (or the default was held): {got}"
    assert (proofs / "dsk--acme--web.gate").exists(), "the hold did not announce itself"


def test_an_ado_qualified_spelling_of_the_default_repo_keys_to_the_project_name():
    """Azure registry rows are BARE (`fx-ado`) while C-18 mints refs qualified
    (`Deskline/fx-ado`). String equality read the default repo as foreign: its proof
    recorded away from the project name and every default card held on a proof that can never
    exist (adversarial review, 2026-08-13). The qualifier still has to MATCH — a same-named
    repository in another ADO project is genuinely foreign."""
    from openfactory.runtime.card_repo import _checkout_key

    ado = Project(name="fx", repo_path="https://dev.azure.com/org/Deskline/_git/fx-ado",
                  tracker=ProviderRef(kind="azure_devops", repo="Deskline"),
                  forge=ProviderRef(kind="azure_devops", repo="fx-ado",
                                    options={"organization": "org", "project": "Deskline"}))

    assert _checkout_key(ado, "fx-ado") == "fx"
    assert _checkout_key(ado, "Deskline/fx-ado") == "fx"
    assert _checkout_key(ado, "OtherProject/fx-ado") == "fx--OtherProject--fx-ado"
    assert _checkout_key(ado, "Deskline/other-repo") == "fx--Deskline--other-repo"


def test_scan_todo_a_stale_default_proof_does_not_hold_the_proven_foreign_repo(monkeypatch,
                                                                              proofs):
    """The other direction of independence: front must not wait on back's paperwork. The
    default repo's expired proof used to blank the WHOLE project before the board was even
    read (adversarial review, 2026-08-13). The foreign proof is ON DISK — that is what tells
    the scan the board is worth reading at all (the quota short-circuit for a fully unproven
    project is test_the_proof_gates_pickup's contract, and it stands)."""
    import asyncio

    import openfactory.adapters.board as board_pkg
    import openfactory.runtime.temporal.activities as acts
    from openfactory.runtime.temporal.io import ScanInput

    project = _product()
    _proof_file(proofs, "dsk--acme--web")
    monkeypatch.setattr(acts.ProjectRegistry, "get", lambda self, name: project)

    class _Board:
        def items_in_status(self, status):
            return ["7", "acme/web#9"]

    class _Ticket:
        state = "open"

    class _Tracker:
        def get_ticket(self, ref):
            return _Ticket()

    monkeypatch.setattr(board_pkg, "build_board", lambda *a, **kw: _Board())
    monkeypatch.setattr(acts, "_tracker_for", lambda p: _Tracker())
    monkeypatch.setattr("openfactory.credentials.tracker_token_for", lambda p: "tok")

    def _gate(project, *, sandbox, repo=""):
        return None if repo else "the image changed — run `openfactory box prove dsk`"

    monkeypatch.setattr("openfactory.box_prove.gate_reason", _gate)

    got = asyncio.run(acts.scan_todo(ScanInput(project="dsk", board_owner="acme",
                                               board_number="1", pickup_status="TO-DO")))

    assert got == ["acme/web#9"], (
        f"the proven foreign repo was held on the default repo's stale proof: {got}")


def test_a_foreign_repo_hold_reaches_the_channel_through_the_PROJECT(proofs, monkeypatch):
    """announce_gate is handed the checkout KEY for the marker file — but the registry cannot
    resolve `dsk--acme--web`, so the notifier lookup KeyError'd into the catch-all and the
    channel was never told a repo was held (adversarial review, 2026-08-13). The registry name
    travels separately."""
    looked_up: list[str] = []
    spoken: list[str] = []

    class _Reg:
        def get(self, name):
            looked_up.append(name)
            if "--" in name:
                raise KeyError(name)
            return _product()

    class _Notifier:
        def notify(self, *, message, level=""):
            spoken.append(message)

    monkeypatch.setattr("openfactory.registry.ProjectRegistry", lambda: _Reg())
    monkeypatch.setattr("openfactory.factory.notifier_for_project", lambda p: _Notifier())

    assert box_prove.announce_gate("dsk--acme--web", "held: no proof", registry_name="dsk")

    assert looked_up == ["dsk"], f"the notifier was looked up by the wrong name: {looked_up}"
    assert spoken and "dsk--acme--web" in spoken[0], (
        "the channel was not told which repo is held")
