"""Capabilities, turn-time checks, blind spots, the gap signal and the chain (#268 slice 3, ADR-0052
D19–D23): every guard the slice claims, cut one at a time.

WHAT THE ROWS BREAK, in the acceptance's order:

  ROWS 1-7    THE QUESTION THAT SPANS THREE SERVICES — the flows' door never named, the flows not a
              bundle the bound reads, a flow's sources checked against one repository, a source's
              stale concepts dropped from the sight, the observation's interfaces widened to every
              link, the parts linked whatever they name, a proposed requirement read as a flow.
  ROWS 8-13   A STALE CITED CONCEPT IS NAMED STALE, AND THE BLIND SPOTS ARE SAID — the flows' own
              check dropped, the bound blind to what the turn found, the module handing it nothing,
              the answer not naming it, the blind-spot section gone, a source with no bundle not
              said.
  ROWS 14-26  THE GAP SIGNAL — never raised, raised for what an exemption covers, the second one
              counted as new, a path outside the mounts mapped, a path outside the view resolved, a
              shell command read as a read, a cut path read as a file, the code a reply opened not
              counted, the medium grade of a reading on code alone; the pipeline not recording it,
              recording what was described since, not taking it, taking what it took again.
  ROWS 27-35  THE CHAIN, AND THE MAP IT WALKS — "done" not read as production, a newest tag read as
              this requirement's, a merge read as production without the deploy watch, a card that
              cites another requirement counted, an event read as a call, the chain not handed to
              the pack, the pack refusing it, the flows' paragraph gone from the prompt, a flow
              silent about a source it could not link.
  ROWS 36-45  A CAPABILITY IS CURATED ONLY BY A PERSON — a status with nobody beside it read as a
              confirmation, an observed capability listed as confirmed, the observed flow listed
              again beside its confirmation, the gate before the write removed, a slug that climbs
              out written through (in the module and in the write), the catalogue's yes skipped,
              the capability section gone, a dangling concept or component kept silent.
  ROWS 46-48  THE CHECK NEVER READS OUTSIDE ITS TREE, AND THE PIPELINE WRITES THE FLOWS — the
              containment in `_check_source` removed, a flow's source not named by its repository,
              the flows never published by the refresh.

NOT A ROW: the refresh's own convergence key for the flows (`_published_flows_key`). Cut, the
refresh still publishes nothing on an unchanged round — `publish_dir` commits nothing when the tree
is unchanged — so what the key saves is a clone, and no test here measures a clone. Claimed in the
docstring as an economy, not as a guard.
"""

TEST = "tests/test_capabilities_and_checks.py"

MODULE = "openfactory/product/module.py"
SIGHT = "openfactory/product/sight.py"
FLOWS = "openfactory/knowledge/flows.py"
CHAIN = "openfactory/product/chain.py"
CAPS = "openfactory/product/capabilities.py"

MUTATIONS = [
    # ── 1. the question that spans three services ──────────────────────────────────────────────
    ("the flows' door is never reported, so the prompt never names where the flows are", MODULE,
     "        if flows.is_file():\n"
     "            out[\"flows\"]",
     "        if False:\n"
     "            out[\"flows\"]"),

    ("the flows are not a bundle the bound reads, so a cited flow is 'not in the bundle'", MODULE,
     "        if (flows / OKF_INDEX_FILE).is_file():\n"
     "            dirs.append(flows)",
     "        if False:\n"
     "            dirs.append(flows)"),

    ("a flow's sources are all checked against the first repository's tree",
     "openfactory/knowledge/check.py",
     "            root = next((r for repo, r in roots.items() if repo_match(repo, s.repo)), None)",
     "            root = next(iter(roots.values()), None)"),

    ("the per-source check's stale concepts are dropped from the turn's sight", SIGHT,
     "        for c in report.broken:",
     "        for c in ():"),

    ("the observation takes every link of the flow's components, databases and brokers included",
     FLOWS,
     "            if lk.from_ in components and lk.to in components]",
     "            if lk.from_ in components]"),

    ("every concept of a source is linked to the flow, whatever it names", FLOWS,
     "    for item in named:\n",
     "    return True\n"
     "    for item in named:\n"),

    ("a proposed requirement — nobody agreed to it, nothing may be built — is observed as a flow",
     FLOWS,
     "                   if getattr(r, \"status\", \"\") in FROM_STATUSES",
     "                   if True"),

    # ── 2. a stale cited concept is named stale ─────────────────────────────────────────────────
    ("the flows' own check is dropped, so a flow whose billing part moved reads as current", SIGHT,
     "        for c in check_across(flows_dir, sight.mounts).broken:",
     "        for c in ():"),

    ("the bound ignores what the turn's check found stale", "openfactory/product/reading.py",
     "            elif found.title.strip().lower() in folded:",
     "            elif False:"),

    ("the module hands the bound nothing the turn found stale", MODULE,
     "        bounded = bound(reading, bundle_dir=bundle_dir, corpus=corpus, broken=broken,",
     "        bounded = bound(reading, bundle_dir=bundle_dir, corpus=corpus, broken=(),"),

    ("the answer never names the stale description it rested on", MODULE,
     "    if stale:\n"
     "        text = (text.rstrip() + \"\\n\\n\" + stale_caveat(",
     "    if False:\n"
     "        text = (text.rstrip() + \"\\n\\n\" + stale_caveat("),

    ("the blind spots never reach the prompt", "openfactory/product/role.py",
     "        parts += self._blind_spots_section()\n",
     ""),

    ("a source with no bundle is not said to be one", SIGHT,
     "        if bundle is None:\n"
     "            out.append(",
     "        if bundle is None:\n"
     "            continue\n"
     "            out.append("),

    # ── 3. the gap signal ─────────────────────────────────────────────────────────────────────────
    ("the answer never signals what it read that no concept covers", MODULE,
     "        _signal_gaps(self, answer)\n",
     ""),

    ("everything read is signalled but what a concept covers — exemptions included", SIGHT,
     "if f.verdict == NO_CONCEPT]",
     "if f.verdict != \"clear\"]"),

    ("the second signal about one file is a new request, and the count is lost",
     "openfactory/knowledge/requests.py",
     "            if row is not None:",
     "            if False:"),

    ("a path is mapped to a source without being inside its mount", SIGHT,
     "            if tree in real.parents and real.is_file():",
     "            if real.is_file():"),

    ("a path outside the view is resolved before it is dropped", SIGHT,
     "        if not any(lexical.startswith(b.rstrip(os.sep) + os.sep) for b in bases):\n"
     "            continue\n",
     ""),

    ("a shell command in the harness's stream is read as a read", MODULE,
     "            and len(p.target) < _STREAM_TARGET_CAP and intent_of(p.name) == READ]",
     "            and len(p.target) < _STREAM_TARGET_CAP]"),

    ("a path the stream reader may have cut is read as a file", MODULE,
     "            and len(p.target) < _STREAM_TARGET_CAP and intent_of(p.name) == READ]",
     "            and intent_of(p.name) == READ]"),

    ("the code a reply opened is not counted, so a reading resting on it is low, not medium",
     MODULE,
     "                        code_read=len(code))",
     "                        code_read=0)"),

    ("a reading that cites no concept and stands on code read now is low, not medium",
     "openfactory/product/reading.py",
     "    elif not reading.concepts and code_read:",
     "    elif False:"),

    ("the refresh never records what the role asked for",
     "openfactory/runtime/temporal/activities.py",
     "        recorded = record_in_bundle(dest, wanted) if wanted else []",
     "        recorded = []"),

    ("a request about a file described since it was asked is recorded anyway",
     "openfactory/knowledge/gaps.py",
     "           if g.key not in held and g.path not in cited]",
     "           if g.key not in held]"),

    ("the requests the refresh published are never marked taken",
     "openfactory/runtime/temporal/activities.py",
     "        asked.taken(inbox, repo, [g.key for g in wanted], at=now)\n"
     "        return f\"published+concepts",
     "        return f\"published+concepts"),

    ("a taken request is pending again", "openfactory/knowledge/requests.py",
     "           if not row.get(\"taken\") and isinstance(row.get(\"gap\"), dict)",
     "           if isinstance(row.get(\"gap\"), dict)"),

    # ── 4. the chain ──────────────────────────────────────────────────────────────────────────────
    ("a job that ended `done` is not read as in production", CHAIN,
     "                if state == \"done\":",
     "                if state == \"never\":"),

    ("the newest release tag is said as this requirement's version", CHAIN,
     "                    exact = tag and tag == version_for(step.ref)",
     "                    exact = bool(tag)"),

    ("a merge is read as production without the deploy watch's word", CHAIN,
     "                elif state == \"merged\" and deploy == \"deployed\":",
     "                elif state == \"merged\":"),

    ("every card is counted as executing the requirement, whatever its Source cites", CHAIN,
     "                if _cited_requirement(card.get(\"body\") or \"\") != number:",
     "                if False:"),

    ("a component's event receivers are counted as its callers", CHAIN,
     "if lk.to in names and lk.from_ not in names and lk.kind != \"event\"})",
     "if lk.to in names and lk.from_ not in names})"),

    ("the chain is never handed to the facts pack", MODULE,
     "                                   **({\"chain\": chain} if chain else {}), **read_model)",
     "                                   **read_model)"),

    ("the facts pack refuses `chain.md` as a name it may write", "openfactory/product/facts.py",
     "MODEL_FILES = (\"now.md\", \"history.md\", \"requirements.md\", \"chain.md\")",
     "MODEL_FILES = (\"now.md\", \"history.md\", \"requirements.md\")"),

    ("the flows' paragraph never reaches the prompt", "openfactory/product/role.py",
     "        if flows:\n"
     "            # THE FLOWS ACROSS SERVICES",
     "        if False:\n"
     "            # THE FLOWS ACROSS SERVICES"),

    ("the observation's not-linked sentences are never said on a source with no bundle", FLOWS,
     "            if bundle is None:\n"
     "                missing.append(",
     "            if bundle is None:\n"
     "                continue\n"
     "                missing.append("),

    # ── 5. a capability is curated only by a person ─────────────────────────────────────────────
    ("`confirmed` with nobody or no day beside it is read as a confirmation", CAPS,
     "        return self.status == CONFIRMED and bool(self.confirmed_by.strip()\n"
     "                                                 and self.confirmed_at.strip())",
     "        return self.status == CONFIRMED"),

    ("a capability nobody confirmed is listed as the product's", CAPS,
     "    curated = [c for c in caps if c.curated]",
     "    curated = [c for c in caps if c.status != RETIRED]"),

    ("a confirmed flow is listed again as observed", CAPS,
     "    unconfirmed = [f for f in (flows.flows if flows else []) if f.slug not in taken]",
     "    unconfirmed = list(flows.flows if flows else [])"),

    ("anybody may confirm a capability — the gate before the write is gone", MODULE,
     "        if not may_act(self.project, actor, via=self._via):\n"
     "            return WriteResult(ok=False, detail=unauthorized_message(self.project))\n"
     "        wanted = (slug or \"\").strip().lower()\n",
     "        wanted = (slug or \"\").strip().lower()\n"),

    ("a slug that climbs out of `capabilities/` reaches the module's lookup", MODULE,
     "        if not is_slug(wanted):\n"
     "            # A NAME, NEVER A PATH",
     "        if False:\n"
     "            # A NAME, NEVER A PATH"),

    ("a slug that climbs out of `capabilities/` reaches the write", CAPS,
     "    if not is_slug(slug):\n"
     "        return WriteResult(ok=False, detail=\"esse nome não é o de uma capacidade\")\n"
     "    day = today",
     "    day = today"),

    ("the catalogue confirms with no `yes`", "openfactory/actions/catalog.py",
     "    if not _said_yes(yes):\n"
     "        return refused(INVALID, f\"nothing was confirmed: after this the factory reads "
     "{slug!r} as \"",
     "    if False:\n"
     "        return refused(INVALID, f\"nothing was confirmed: after this the factory reads "
     "{slug!r} as \""),

    ("the capabilities never reach the prompt", "openfactory/product/role.py",
     "        parts += self._capabilities_section()\n",
     ""),

    ("a link to a concept that no longer exists is kept silent", CAPS,
     "        if not any(c.title.strip().lower() == wanted",
     "        if False and not any(c.title.strip().lower() == wanted"),

    ("a link to a component the map no longer derives is kept silent", CAPS,
     "                for name in cap.components if name not in names]",
     "                for name in cap.components if False]"),

    # ── the check stays in its tree, and the pipeline writes the flows ──────────────────────────
    ("a citation that climbs out of its checkout, or a link out of it, is read",
     "openfactory/knowledge/check.py",
     "    if real != root and root not in real.parents:\n"
     "        return SourceCheck(rel, MISSING, \"outside this checkout — not read\")",
     "    if False:\n"
     "        return SourceCheck(rel, MISSING, \"outside this checkout — not read\")"),

    ("a flow's source keeps its bundle's empty repository, and its check cannot find it", FLOWS,
     "                        sourced.append(s.model_copy(update={\"repo\": repo}))",
     "                        sourced.append(s)"),

    ("the refresh never publishes the flows", "openfactory/knowledge/system/refresh.py",
     "                if flowed:\n"
     "                    outcomes.append(publish_dir(",
     "                if False:\n"
     "                    outcomes.append(publish_dir("),
]
