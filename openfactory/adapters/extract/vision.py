"""The row that reads an image — a diagram, a chart, a photographed whiteboard — by having a model
describe it (#269 slice 1).

THE WEAKEST CASE, AND THE RECORD SAYS SO. A chart's message is understood; the exact numbers read
off its pixels may be wrong. So the extraction is marked as coming from an image AND as a model's
words (`from_image`, `model`), and the record's note — written by the dispatcher for every image,
whichever row read it (`product/documents/ingest.py::FROM_AN_IMAGE`) — says the source data placed
beside it would make the numbers exact (#269, "What happens when someone drops a PDF or a chart").

ONCE PER FILE VERSION. The row is asked only when the dispatcher found no record for this path and
these bytes (`product/documents/ingest.py`); a question about the image later reads the record,
never the model.

ON THE REPO'S MODEL SEAM (`model.py`): the configured role's harness, read-only, in a room holding
the image and nothing else. A deployment that wants OCR for images instead, or a stranger's vision
model, configures another row for the `image` type (`OPENFACTORY_EXTRACT_ROWS`) — this one is
the default, not the only one.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from openfactory.adapters.extract import model as seam
from openfactory.adapters.extract.base import Extraction, Source, unreadable
from openfactory.adapters.extract.text import TITLE_CHARS, normalise

#: The phase the harness is asked under — its telemetry label, and a phase a person reads, so the
#: project's language directive applies (`adapters/agent/roles.py::needs_language_directive`).
PHASE = "documents_vision"

#: What the model answers when there is nothing to read in the picture.
ILLEGIBLE = "ILLEGIBLE"


def prompt(name: str) -> str:
    return (
        f"The file `{name}` in this directory is an image from a product's documentation — a "
        f"diagram, a chart, a screenshot, or a photograph of a whiteboard or a page. Open it and "
        f"describe it so that somebody who cannot see it can answer questions about it later:\n\n"
        f"- what it is and what it shows, in one or two sentences first;\n"
        f"- every label and every piece of text in it, word for word;\n"
        f"- for a diagram, what connects to what, and what each connection says;\n"
        f"- for a chart, its title, its axes, its series and the values you can read — saying "
        f"that they were read from the picture.\n\n"
        f"Describe only what you can see; never complete what is cut off or illegible. If "
        f"nothing in the image can be read, answer exactly {ILLEGIBLE}. Answer in plain text, "
        f"with nothing before or after the description.")


class VisionRow:
    """An image, described once per version by the configured role's model."""

    kind = "vision"

    def __init__(self, *, project=None, harness=None) -> None:
        self.project = project
        self._harness = harness

    def extract(self, source: Source) -> Extraction:
        harness, why = ((self._harness, "") if self._harness is not None
                        else seam.asker(self.project))
        if harness is None:
            return unreadable(f"no model could describe this image: {why}", row=self.kind,
                              from_image=True)
        suffix = Path(source.path).suffix.lower() or ".png"
        with tempfile.TemporaryDirectory(prefix="openfactory-vision-") as scratch:
            room = Path(scratch)
            name = f"image{suffix}"
            (room / name).write_bytes(source.data)
            said, why = seam.ask(harness, self.project, room, prompt(name), phase=PHASE)
        if said is None:
            return unreadable(f"the image could not be described: {why}", row=self.kind,
                              from_image=True)
        text = normalise(said)
        if text.strip().strip(".").upper() == ILLEGIBLE or not text:
            return unreadable("an illegible image: the model found nothing in it to read",
                              row=self.kind, from_image=True)
        return Extraction(readable=True, text=text, row=self.kind, from_image=True,
                          model=seam.described(harness, self.project),
                          title=text.split("\n", 1)[0][:TITLE_CHARS])
