"""The part of a record only a model can write — the summary and the decisions a document
mentions — written ONCE PER VERSION, never per question (#269 slice 1, ADR-0053 point 1).

A PORT OF ITS OWN, PYDANTIC IN AND OUT. A `Reader` is handed the record the parsers already made
(`DocumentRecord`: the normalised text and everything deterministic) and answers a `Reading`. The
default is the configured role's model (`adapters/extract/model.py`: the reviewer's harness, or a
declared role's), in a room holding the document's text and nothing else; a test hands its own.

EVERY FIELD IT WRITES IS MARKED AS A MODEL'S (`contracts/document.py::Derived`), with the harness
and model that wrote it. A reading that failed is recorded as failed, with why, and retried by a
later pass a bounded number of times — the text is not extracted again for it.

THE DOCUMENT IS UNTRUSTED TEXT, AND THE MODEL IS ASKED READ-ONLY. A document that tells the model
to do something can at most bend the summary it writes; the summary is marked as a model's, and it
is evidence to cite, never truth (#266 decision 15: a person confirms before anything is promoted).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from openfactory.contracts.document import Decision, DocumentRecord

#: The phase the harness is asked under.
PHASE = "documents_record"
#: How much of a document's text the model is handed — a summary of a book is written from its
#: opening, and the prompt says so rather than pretending otherwise.
READ_CHARS = 60_000
#: The longest summary kept.
SUMMARY_CHARS = 1_200
#: The most decisions kept from one document.
MAX_DECISIONS = 50


class Reading(BaseModel):
    """What a reader answers: the summary and the decisions — or, with `error`, why it could not."""

    summary: str = ""
    decisions: list[Decision] = Field(default_factory=list)
    #: `harness/model` of what wrote it
    by: str = ""
    error: str = ""


@runtime_checkable
class Reader(Protocol):
    def read(self, record: DocumentRecord) -> Reading:
        ...


def prompt(record: DocumentRecord, *, cut: bool) -> str:
    about = [f"`{record.path}`", f"a {record.type or 'document'}"]
    if record.title:
        about.append(f"titled {record.title!r}")
    if record.date:
        about.append(f"dated {record.date}")
    return (
        f"The file `document.txt` in this directory holds the text of a document from a product's "
        f"context repository: {', '.join(about)}."
        + (f" It holds the first {READ_CHARS} characters only; the document goes on." if cut
           else "")
        + "\n\nRead it and answer with ONE JSON object and nothing else:\n\n"
        '{"summary": "…", "decisions": [{"text": "…", "date": "YYYY-MM-DD or empty"}]}\n\n'
        "- `summary`: at most three sentences — what the document is and what it says that "
        "matters to the product.\n"
        "- `decisions`: every decision the document RECORDS — something decided, agreed, "
        "approved, chosen, dropped or reversed — as close to its own words as you can, each with "
        "the date it was taken when the document gives one. An empty list when it records none. "
        "Never infer a decision the document does not state.")


def _decisions(value) -> list[Decision]:
    out = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, str) and item.strip():
            out.append(Decision(text=item.strip()))
        elif isinstance(item, dict) and str(item.get("text") or "").strip():
            date = str(item.get("date") or "").strip()
            out.append(Decision(text=str(item["text"]).strip(), date=date[:10]))
    return out[:MAX_DECISIONS]


class ModelReader:
    """The default reader: the configured role's model, read-only, one document per room."""

    def __init__(self, *, project=None, harness=None) -> None:
        self.project = project
        self._harness = harness
        self._built = harness is not None
        self._why = ""

    def _asker(self):
        if not self._built:
            from openfactory.adapters.extract import model as seam

            self._harness, self._why = seam.asker(self.project)
            self._built = True
        return self._harness

    def read(self, record: DocumentRecord) -> Reading:
        from openfactory.adapters.agent.base import json_envelope
        from openfactory.adapters.extract import model as seam

        harness = self._asker()
        if harness is None:
            return Reading(error=self._why or "no model can read documents here")
        cut = len(record.text) > READ_CHARS
        with tempfile.TemporaryDirectory(prefix="openfactory-reading-") as scratch:
            room = Path(scratch)
            (room / "document.txt").write_text(record.text[:READ_CHARS], encoding="utf-8")
            said, why = seam.ask(harness, self.project, room, prompt(record, cut=cut),
                                 phase=PHASE)
        by = seam.described(harness, self.project)
        if said is None:
            return Reading(error=why, by=by)
        answer = json_envelope(said)
        if answer is None or not isinstance(answer.get("summary"), str):
            return Reading(error="the model's answer was not the JSON object it was asked for",
                           by=by)
        return Reading(summary=" ".join(answer["summary"].split())[:SUMMARY_CHARS],
                       decisions=_decisions(answer.get("decisions")), by=by)
