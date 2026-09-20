"""#163: a tail wrapped without an indent is the bullet's, as far as the renderer goes and no further."""

TEST = "tests/test_what_the_card_shows_inside_a_bullet_is_what_is_read.py"
PARSE = "openfactory/adapters/tracker/parse.py"
MACHINE = "openfactory/orchestrator/machine.py"

MUTATIONS = [
    ("THE DEFECT ITSELF: only an INDENTED line is a tail, so the unindented wrap is truncated again",
     PARSE,
     "    return line[:1].isspace() or not _STARTS_A_BLOCK.match(stripped)",
     "    return line[:1].isspace()"),

    ("the criteria join a lazy tail only when it is indented — the scope lists read it, the "
     "criteria do not", PARSE,
     "        tail = (line[:1].isspace() or item_open) and _continues_the_item(line)",
     "        tail = line[:1].isspace() and _continues_the_item(line)"),

    ("everything under a bullet is its tail: a heading, a fence, a table, another list", PARSE,
     "    return line[:1].isspace() or not _STARTS_A_BLOCK.match(stripped)",
     "    return True"),

    ("a quotation and an HTML block are tails", PARSE,
     r"|=+\s*$|>|[-*+](\s|$)|1[.)](\s|$)|\||<[A-Za-z/!?]",
     r"|=+\s*$|[-*+](\s|$)|1[.)](\s|$)|\|"),

    ("a numbered list glued under a bullet is swallowed into it", PARSE,
     r"|[-*+](\s|$)|1[.)](\s|$)|",
     r"|[-*+](\s|$)|"),

    ("a blank line no longer ends the item, so a separate paragraph is swallowed", PARSE,
     "            item_open = False                            # …a list item does not\n",
     ""),

    ("a scenario opened on a plain line inherits the open item of the bullet above it, and "
     "swallows the sentence after it", PARSE,
     "            item_open = bulleted    # on a plain line it is no list item, whatever was above",
     "            item_open = bulleted or item_open"),

    ("…and so does a `Given` on a plain line", PARSE,
     '            state, stepped = "given", bulleted\n            item_open = bulleted\n',
     '            state, stepped = "given", bulleted\n'),

    ("a table row the scenario took leaves the item open, and the line under it becomes a tail",
     PARSE,
     "            item_open = bulleted or (item_open and _continues_the_item(line))",
     "            item_open = bulleted or item_open"),

    ("a scenario on plain lines swallows the next unindented sentence: no bullet was ever open",
     PARSE,
     "        tail = (line[:1].isspace() or item_open) and _continues_the_item(line)",
     "        tail = _continues_the_item(line)"),

    ("a tail that begins with `E` or `And` falls out of its bullet, because it looks like a step",
     PARSE,
     '        elif kind == "step" and state == "bullet" and not bulleted and tail:',
     "        elif False:"),

    ("the parser stops saying which lines it did not read", PARSE,
     "            fell.append(n)\n",
     ""),

    ("a `Scenario:` sentence with nothing under it is not reported as unread", PARSE,
     "    unread = sorted(fell + [n for ns, keep in zip(at, counted, strict=True) if not keep\n"
     "                            for n in ns])",
     "    unread = sorted(fell)"),

    ("the refusal goes back to denying what is on the author's screen", MACHINE,
     '            + _what_was_not_read(unread_criteria_lines(ticket.raw or ""))\n',
     ""),

    ("the refusal quotes the whole section, however long", MACHINE,
     "    more = len(lines) - show\n",
     "    show = len(lines)\n    more = 0\n"),
]
