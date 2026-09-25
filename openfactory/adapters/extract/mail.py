"""The row that reads an e-mail saved as `.eml` (#269 slice 1) — with the standard library's
`email` package, and nothing else.

WHAT AN E-MAIL IS TO A GUARDIAN. Who wrote it, to whom, when, about what, and what it said: the
headers give the first four exactly (`From`, `To`/`Cc`, `Date`, `Subject`) and the body the last.
The date is the header's, which is when it was SENT — not when somebody dropped the file into the
repository, which is the difference between "decided in 2021" and "filed in 2024".

THE PLAIN PART IS PREFERRED; AN HTML-ONLY MESSAGE IS REDUCED TO ITS WORDS by the standard
library's HTML parser, with scripts and styles dropped whole. Nothing in the message is run,
loaded or followed — no remote image, no link.

ATTACHMENTS ARE NAMED, NOT READ. An attachment is a document of its own; reading it here would
hide it inside another document's record, where its type, its audience and its unreadability
would all be somebody else's. The record's notes list each by name, so "the contract was attached
to the e-mail of 3 March" is still knowable, and saying so is never "there was no contract".
"""

from __future__ import annotations

import email
from email import policy
from email.utils import getaddresses, parsedate_to_datetime

from openfactory.adapters.extract.base import Extraction, Source, unreadable
from openfactory.adapters.extract.text import TITLE_CHARS, html_words, normalise


def _addresses(message, *names: str) -> list[str]:
    """Every person in these headers, as `Name <address>` — or the address alone."""
    found = []
    for header in names:
        for name, address in getaddresses(message.get_all(header, []) or []):
            if address or name:
                found.append(f"{name} <{address}>" if name and address else (address or name))
    return found


class EmailRow:
    """An `.eml` file: its headers as the record's facts, its body as the text."""

    kind = "eml"

    def extract(self, source: Source) -> Extraction:
        try:
            message = email.message_from_bytes(source.data, policy=policy.default)
        except Exception as exc:  # noqa: BLE001 — a message the parser cannot hold is unreadable
            return unreadable(f"not an e-mail message this parser can read ({exc})",
                              row=self.kind)
        try:
            return self._read(message)
        except Exception as exc:  # noqa: BLE001 — a malformed header or part, said by name
            return unreadable(f"an e-mail whose parts could not be read ({exc})", row=self.kind)

    def _read(self, message) -> Extraction:
        subject = " ".join(str(message.get("subject", "") or "").split())
        senders = _addresses(message, "from")
        recipients = _addresses(message, "to", "cc")
        date = ""
        if message.get("date"):
            try:
                date = parsedate_to_datetime(str(message["date"])).date().isoformat()
            except (TypeError, ValueError, IndexError):
                date = ""
        body_part = message.get_body(preferencelist=("plain", "html"))
        body = ""
        if body_part is not None:
            content = body_part.get_content()
            body = html_words(content) if body_part.get_content_type() == "text/html" else content
        notes = [f"attachment not read here: {part.get_filename() or '(unnamed)'}"
                 for part in message.iter_attachments()]
        if not subject and not body.strip() and not senders:
            return unreadable("an .eml file with no headers and no body — not an e-mail",
                              row=self.kind)
        head = [f"Subject: {subject}" if subject else "",
                f"From: {', '.join(senders)}" if senders else "",
                f"To: {', '.join(recipients)}" if recipients else "",
                f"Date: {date}" if date else ""]
        text = normalise("\n".join([*(h for h in head if h), "", body]))
        return Extraction(readable=True, text=text, row=self.kind,
                          title=(subject or "(an e-mail with no subject)")[:TITLE_CHARS],
                          date=date, date_from="header" if date else "", authors=senders,
                          notes=notes)
