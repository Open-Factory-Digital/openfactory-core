"""The repair memory was int-typed end to end (#162, `activities.py:3182`).

The card was filed against a tracker whose refs look like `CONT-412`: `_repoint_facts` skipped
anything failing `.isdigit()`, so on such a board the memory was structurally empty — every repair
announced for ever, or never remembered at all.

MEASURING IT FOUND SOMETHING WORSE, AND IT WAS LIVE ON GITHUB. `_card_number` reduced a
`WriteResult`'s ref to the integer it contained, and the orphans it was matched against are
`Ticket.number`, which is a `str`:

    written = {_card_number(r.ref) …}                 # {510}
    fresh   = {card: succ for (card, …) in orphans if card in written}   # "510" in {510} → False

So `fresh` was empty on EVERY board, on every vendor. The repair ran — cards were re-pointed on
the client's board — and the round then reported `clean`, logging `ORPHANS_UNPAIRED` to blame a
race ("repaired on the board after this round read it") that had not happened. Nobody was ever
told the promise under their cards had changed, which is the one thing this whole repair exists to
say.

Reproduced before the fix: two orphans, both written, round returns `"clean"`.

WHY EVERY GUARD IN `test_orphaned_cards_are_repointed.py` PASSED THROUGH ALL OF IT: its fake
returned integer refs. Thirty-five fixture literals modelling a shape `ProductModule` cannot
return, and twelve tests asserting the round's summary line — which read `clean` for exactly the
same reason production did.
"""

from __future__ import annotations

import types

import pytest

from openfactory.runtime.temporal import activities as acts


class _Ok:
    def __init__(self, ref: str, ok: bool = True):
        self.ref, self.ok = ref, ok


class _Module:
    def __init__(self, orphans, refuses=()):
        self.orphans, self.refuses = list(orphans), set(refuses)

    def orphaned_cards(self):
        return list(self.orphans)

    def repoint_orphans(self, *, actor: str = ""):
        return [_Ok(f"#{c}" if str(c).isdigit() else str(c), c not in self.refuses)
                for c, _cited, _succ in self.orphans]


@pytest.fixture()
def wired(monkeypatch):
    """The round, with its board write and its channel replaced — and nothing else."""
    import openfactory.product.module as pm

    posts: list[str] = []
    remembered: list[tuple] = []
    monkeypatch.setattr(acts, "_repoint_memory", lambda name: ({}, set()))
    monkeypatch.setattr(acts, "_remember_repoint",
                        lambda name, rep, ann: remembered.append((dict(rep), set(ann))))
    monkeypatch.setattr(acts, "_product_post", lambda ch, pr, cfg, text: posts.append(text) or True)
    monkeypatch.setattr("openfactory.adapters.channel.build_channel", lambda p: object())
    return types.SimpleNamespace(pm=pm, posts=posts, remembered=remembered,
                                 monkeypatch=monkeypatch)


def _project(language="pt-BR", channel="C1"):
    cfg = types.SimpleNamespace(enabled=True, docs_repo="d/r", channel_id=channel, agent_name="")
    return types.SimpleNamespace(name="books", product=cfg, language=language)


def _run(wired, module):
    wired.monkeypatch.setattr(wired.pm, "ProductModule", lambda project: module)
    return acts._repoint_product_orphans(_project())


# ── 1. the defect that was live on every vendor ─────────────────────────────────────────────────

def test_a_repaired_GITHUB_card_is_remembered_and_announced(wired):
    """The regression that mattered most: the pilot's own vendor. This returned `"clean"`."""
    got = _run(wired, _Module([("510", 4, 6)]))

    assert got == "repointed:1 announced:1", got
    assert wired.posts, "the client was never told the promise under their card changed"


def test_and_the_round_does_not_blame_a_RACE_that_did_not_happen(wired, caplog):
    """`ORPHANS_UNPAIRED` names cards repaired inside the read/write window. With the comparison
    always false, every repaired card landed there — an error log about a window that never
    opened, which is worse than silence because it sends somebody looking for a race."""
    with caplog.at_level("ERROR"):
        _run(wired, _Module([("510", 4, 6)]))

    assert "UNPAIRED" not in caplog.text


def test_a_CONT_412_card_is_announced_too(wired):
    """The card as filed. A tracker that does not number its tickets had every fact dropped."""
    got = _run(wired, _Module([("CONT-412", 4, 6)]))

    assert got == "repointed:1 announced:1", got
    assert "CONT-412" in wired.posts[0]


def test_and_the_sentence_does_not_put_GITHUBS_HASH_on_it(wired):
    """`#` is GitHub's punctuation. `#CONT-412` is not how anybody on that board writes a ticket,
    and it is not a ref a reader can paste back."""
    _run(wired, _Module([("CONT-412", 4, 6)]))

    assert "#CONT-412" not in wired.posts[0]


def test_a_numeric_card_KEEPS_the_hash(wired):
    """The positive twin: dropping the `#` everywhere would be the same defect facing the other
    way, on the vendor that does use it."""
    _run(wired, _Module([("510", 4, 6)]))

    assert "#510" in wired.posts[0]


def test_both_vendors_shapes_in_one_round(wired):
    """One deployment, two clients, one hourly round."""
    got = _run(wired, _Module([("510", 4, 6), ("CONT-412", 4, 6)]))

    assert got == "repointed:2 announced:2", got
    assert "#510" in wired.posts[0] and "CONT-412" in wired.posts[0]


def test_the_cards_are_ordered_as_a_person_reads_them(wired):
    """`sorted` on strings puts "#510" before "#59". Board order is what somebody reads."""
    _run(wired, _Module([("510", 4, 6), ("59", 4, 6), ("6", 4, 6)]))

    said = wired.posts[0]
    assert said.index("#6,") < said.index("#59") < said.index("#510")


def test_a_write_the_board_REFUSED_is_still_not_announced(wired):
    """The pairing has to keep discriminating — a comparison that is always TRUE would announce
    repairs that never happened, which is the opposite failure and the worse one."""
    got = _run(wired, _Module([("510", 4, 6), ("512", 4, 6)], refuses={"512"}))

    assert got == "repointed:1 refused:1 announced:1", got
    assert "#512" not in wired.posts[0]


def test_a_write_that_NAMES_NOTHING_is_not_a_card(wired, caplog):
    """A `WriteResult` whose ref is empty pairs with no orphan by construction, so it must not
    reach the round as a card at all — left in, it becomes an `ORPHANS_UNPAIRED` error naming a
    card called "" and a number in a count nobody can trace to a ticket. Survivor of the first
    mutation round: every result in these fixtures names one."""
    class _Nameless(_Module):
        def repoint_orphans(self, *, actor: str = ""):
            return [*super().repoint_orphans(actor=actor), _Ok("")]

    with caplog.at_level("ERROR"):
        got = _run(wired, _Nameless([("510", 4, 6)]))

    assert got == "repointed:1 announced:1", got
    assert "UNPAIRED" not in caplog.text


# ── 2. the memory carries the provider's own string ─────────────────────────────────────────────

def test_a_non_numeric_card_SURVIVES_the_memory(monkeypatch):
    """`_repoint_facts` skipped anything failing `.isdigit()`, so this pair could be written and
    never read back — and a memory that always reads empty announces every repair for ever."""
    rows: list = []
    monkeypatch.setattr(acts, "_metrics_sink",
                        lambda: types.SimpleNamespace(
                            record=lambda rec: rows.append({"kind": rec.kind, "role": rec.role,
                                                            "pk": rec.project, "ts": rec.ts,
                                                            "extra": dict(rec.extra)})))
    monkeypatch.setattr("openfactory.api.metrics_view.scan_records", lambda: list(rows))

    acts._remember_repoint("books", {"CONT-412": 6}, {("CONT-412", 6)})

    assert acts._repoint_memory("books") == ({"CONT-412": 6}, {("CONT-412", 6)})


def test_a_row_written_BEFORE_this_shipped_still_reads(monkeypatch):
    """Rows in the live table spell the card as bare digits. They must read back as the same
    string `Ticket.number` carries for that card, or the memory silently starts over and every
    repair already announced is announced again."""
    monkeypatch.setattr("openfactory.api.metrics_view.scan_records", lambda: [
        {"kind": acts._WATCH_KIND, "role": acts._REPOINT_ROLE, "pk": "books",
         "ts": "2026-08-01T00:00:00+00:00", "extra": {"repaired": "510:6", "announced": "510:6"}},
    ])

    assert acts._repoint_memory("books") == ({"510": 6}, {("510", 6)})


def test_a_ref_that_would_CORRUPT_the_row_is_dropped_loudly(monkeypatch, caplog):
    """`|` and `:` are this field's own punctuation. A ref carrying one would not merely lose
    itself — it would split into two unrecognisable facts and desynchronise the whole memory."""
    rows: list = []
    monkeypatch.setattr(acts, "_metrics_sink",
                        lambda: types.SimpleNamespace(
                            record=lambda rec: rows.append(dict(rec.extra))))

    with caplog.at_level("ERROR"):
        acts._remember_repoint("books", {"OK-1": 6, "BAD:2": 6}, set())

    assert "UNSTORABLE" in caplog.text and "BAD:2" in caplog.text
    assert rows and "BAD" not in rows[0].get("repaired", "")
    assert "OK-1:6" in rows[0].get("repaired", ""), "the storable fact went down with the bad one"


def test_a_round_with_ONLY_unstorable_refs_writes_nothing(monkeypatch):
    """The reverse: dropping every fact must not leave an empty row behind, which reads on the
    next round as a delta that recorded something."""
    rows: list = []
    monkeypatch.setattr(acts, "_metrics_sink",
                        lambda: types.SimpleNamespace(record=lambda rec: rows.append(rec)))

    acts._remember_repoint("books", {"BAD:2": 6}, set())

    assert rows == []


# ── 3. the shape the fixtures could not model ───────────────────────────────────────────────────

def test_the_module_really_does_hand_back_STRINGS():
    """The claim everything above rests on, read off the contract rather than assumed — the old
    fixtures assumed the opposite for thirty-five literals and nothing contradicted them."""
    from openfactory.product.triage import Ticket

    assert Ticket.model_fields["number"].annotation is str
