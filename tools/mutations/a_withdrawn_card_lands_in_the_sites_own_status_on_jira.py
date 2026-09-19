"""On a Jira site whose word for "withdrawn" is a STATUS, the withdrawn close moves the card into the
status the deployment named, and a closed card sitting in it reads as not delivered (2026-09-19)."""

TEST = "tests/test_a_withdrawn_card_lands_in_the_sites_own_status_on_jira.py"
JIRA = "openfactory/adapters/tracker/jira.py"
REGISTRY = "openfactory/adapters/tracker/registry.py"

MUTATIONS = [
    # ── the close ───────────────────────────────────────────────────────────────────────────────
    ("THE DEFECT ITSELF: the withdrawn close never looks for the status, and the card lands in Done "
     "beside the work that shipped", JIRA,
     "        into = self._transition_for(ref, status=status) if status else None",
     "        into = None"),

    ("`_transition_for` ignores the name it was handed", JIRA,
     "        target = str(status or \"\").strip()\n        if not target:",
     "        target = \"\"\n        if not target:"),

    ("the move into the status carries the resolution too, and the screen's refusal is back in the "
     "one path that had none", JIRA,
     "            refused = self._refusal_of(ref, {\"transition\": {\"id\": into[\"id\"]}})",
     "            refused = self._refusal_of(ref, {\"transition\": {\"id\": into[\"id\"]}, \"fields\": "
     "{\"resolution\": {\"name\": self.not_delivered_resolution}}})"),

    ("a workflow with no move into the status leaves the card open", JIRA,
     "        elif status:\n            met.append(",
     "        elif status:\n            return\n            met.append("),

    ("a card the status could not take is never offered the resolution the deployment also named",
     JIRA,
     "        if wanted:\n            refused = self._refusal_of(",
     "        if wanted and not met:\n            refused = self._refusal_of("),

    ("a status the site files outside Done is used, and the close leaves the card open", JIRA,
     "        if into is not None and not _closes_a_card(into):",
     "        if False:"),

    ("a transitions answer that states no category switches the option off", JIRA,
     "    return not category or str(category).lower() == \"done\"",
     "    return str(category).lower() == \"done\""),

    ("a validator's 400 on the move leaves the card open", JIRA,
     "            if exc.code != 400:\n                raise\n",
     "            raise\n"),

    ("an expired credential is read as a refused move, and the close is retried and noted", JIRA,
     "            if exc.code != 400:\n",
     "            if False:\n"),

    # ── what the log line says ──────────────────────────────────────────────────────────────────
    ("the degraded line no longer says which status had no move into it", JIRA,
     "        elif status:\n            met.append(",
     "        elif False:\n            met.append("),

    ("Jira's own words about the refused move are dropped from the line", JIRA,
     "jira refused the move into the status {status!r} ({refused}) — see what \"",
     "jira refused the move into the status {status!r} — see what \""),

    ("a deployment that named nothing is told about the resolution only", JIRA,
     "                       \"delivered' — set `not_delivered_status` (a status in the site's Done \"",
     "                       \"delivered' — set (a status in the site's Done \""),

    # ── the read ────────────────────────────────────────────────────────────────────────────────
    ("the read side never reads the status: what the close wrote does not come back", JIRA,
     "or (withdrawn and sits_in == withdrawn)",
     "or False"),

    ("the named status is compared by case, and a person's `CANCELADO` reads as delivered", JIRA,
     "        sits_in = str((fields.get(\"status\") or {}).get(\"name\") or \"\").strip().lower()",
     "        sits_in = str((fields.get(\"status\") or {}).get(\"name\") or \"\").strip()"),

    ("delivery is decided from a status name nobody configured", JIRA,
     "or (withdrawn and sits_in == withdrawn)",
     "or (sits_in == (withdrawn or \"cancelado\"))"),

    # ── the option ──────────────────────────────────────────────────────────────────────────────
    ("a literal default pretends every site has a `Cancelado`", JIRA,
     "str(not_delivered_status or \"\").strip()",
     "str(not_delivered_status or \"Cancelado\").strip()"),

    ("the registry row never hands the option to the tracker", REGISTRY,
     "        not_delivered_status=options.get(\"not_delivered_status\", \"\"),",
     "        not_delivered_status=\"\","),

    ("the registry row invents the default the adapter refused", REGISTRY,
     "        not_delivered_status=options.get(\"not_delivered_status\", \"\"),",
     "        not_delivered_status=options.get(\"not_delivered_status\", \"Cancelado\"),"),
]
