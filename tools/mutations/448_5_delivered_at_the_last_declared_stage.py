"""Delivered means delivered (#448, slice 5, behaviour 6). The claims:

  · a project whose watched deploy is its last stage leaves the card In review at the merge, said
    on the card, and the watch settles it: Done and announced when green, held for a person — and
    nothing delivered — when it failed or was never seen to finish; a watch that could not start
    leaves the card settled at the merge, as before;
  · the requester hears at the merge that a stage follows;
  · a project with no stage is delivered at the merge, and a chain with production once it is
    released, exactly as before;
  · every new command is behind its marker, so a job or a watch in flight replays as recorded;
  · `--promote` on a manifest that declares a watched deploy and no chain takes the same path —
    the deploy is the last stage, and no empty promotion ends the card Done first — while a
    declared chain is still walked with the flag (#501);
  · the forge is not asked to close at the merge a card a stage still waits on;
  · a "did not work" about a delivery stages a defect linked to the cards it was about, with the
    person's words, titled from the card, citing the requirement it was owed against; the yes of
    the person it was delivered to files it, anybody else's waits for an approver as any report
    does; the defect says what it followed and the delivered card says which defect followed it.
"""

TEST = "tests/test_delivered_means_the_last_declared_stage.py"
WORKFLOW = "openfactory/runtime/temporal/workflow.py"
IO = "openfactory/runtime/temporal/io.py"
MACHINE = "openfactory/orchestrator/machine.py"
FOLLOWUP = "openfactory/product/followup.py"
ENGINE = "openfactory/product/engine.py"
CONFIRM = "openfactory/product/confirm.py"
MODULE = "openfactory/product/module.py"
AUTHORING = "openfactory/product/authoring.py"
STAGING = "openfactory/product/staging.py"
VOICE = "openfactory/product/voice.py"

MUTATIONS = [
    # ── the job at the merge ─────────────────────────────────────────────────────────────────
    ("a watched deploy is never the last stage: Done at the merge again", WORKFLOW,
     '                          and workflow.patched("delivered-at-the-last-declared-stage"))\n',
     "                          and False)\n"),
    ("the new commands run on a history that never recorded them", WORKFLOW,
     '                          and workflow.patched("delivered-at-the-last-declared-stage"))\n',
     "                          and True)\n"),
    ("the card is settled Done at the merge with the deploy still ahead", WORKFLOW,
     "                await self._settle(params, JobState.MERGED,\n",
     "                await self._settle(params, JobState.DONE,\n"),
    ("the merge still settles Done under the watch", WORKFLOW,
     "            if result.state == JobState.MERGED and not (deploy_is_last and watched):\n",
     "            if result.state == JobState.MERGED:\n"),
    ("a card whose watch never started is left In review", WORKFLOW,
     "            if result.state == JobState.MERGED and not (deploy_is_last and watched):\n",
     "            if result.state == JobState.MERGED and not deploy_is_last:\n"),
    ("the watch is never told the deploy is the last stage", WORKFLOW,
     '                    url=getattr(cfg, "url", "") or "", delivers=delivers,\n',
     '                    url=getattr(cfg, "url", "") or "", delivers=False,\n'),
    ("the requester is told nothing follows a watched deploy", WORKFLOW,
     "                params, result, stages_follow=should_promote or deploy_is_last)\n",
     "                params, result, stages_follow=should_promote)\n"),

    # ── `--promote` on a deploy-only manifest (#501) ─────────────────────────────────────────
    ("--promote on a deploy-only manifest walks an empty promotion and ends Done first again",
     WORKFLOW,
     '                and workflow.patched("promote-on-a-deploy-only-manifest-watches-it")):\n',
     "                and False):\n"),
    ("--promote skips the empty promotion on a history that recorded it", WORKFLOW,
     '                and workflow.patched("promote-on-a-deploy-only-manifest-watches-it")):\n',
     "                and True):\n"),
    ("--promote skips a chain the manifest declares when a deploy is watched beside it",
     WORKFLOW,
     "        if (should_promote and not result.environments and "
     "result.state == JobState.MERGED\n",
     "        if (should_promote and result.state == JobState.MERGED\n"),

    # ── the watch at the deploy's outcome ────────────────────────────────────────────────────
    ("the watch settles nothing", WORKFLOW,
     '        if not inp.delivers or not workflow.patched("the-watch-settles-the-last-stage"):\n',
     "        if True:\n"),
    ("a watch in flight settles on a history that never recorded it", WORKFLOW,
     '        if not inp.delivers or not workflow.patched("the-watch-settles-the-last-stage"):\n',
     "        if not inp.delivers:\n"),
    ("a red deploy is delivered", WORKFLOW,
     "        state = JobState.DONE if green else JobState.ON_HOLD\n",
     "        state = JobState.DONE\n"),
    ("a deploy never seen to finish is delivered", WORKFLOW,
     '        green = status == "success"\n',
     '        green = status != "failure"\n'),
    ("every watch settles the card, one that only informs too", IO,
     "    delivers: bool = False\n",
     "    delivers: bool = True\n"),

    # ── the forge's closing word ─────────────────────────────────────────────────────────────
    ("the forge closes at the merge a card a stage still waits on", MACHINE,
     '    keyword = closing_keyword(getattr(runner, "forge", None)) if owned and not staged '
     'else ""\n',
     '    keyword = closing_keyword(getattr(runner, "forge", None)) if owned else ""\n'),
    ("a chain is not counted as a stage", MACHINE,
     '        environments=getattr(manifest, "environments", None) or ())\n',
     "        environments=())\n"),

    # ── "it did not work" ────────────────────────────────────────────────────────────────────
    ("the acceptance forgets the cards it delivered", FOLLOWUP,
     '                              **({"issues": cards} if cards else {}),\n',
     "                              **({}),\n"),
    ("a card cancelled out of the delivery is linked", FOLLOWUP,
     "                     if n.strip() and canonical_ref(n) not in gone)\n",
     "                     if n.strip())\n"),
    ("a \"did not work\" stages nothing", ENGINE,
     '            if verdict == "did-not-work":\n',
     "            if False:\n"),
    ("the person the delivery was for needs an approver", ENGINE,
     '    theirs = bool(ctx.get("requester")) and sealed(user) == str(ctx.get("requester"))\n',
     "    theirs = False\n"),
    ("anybody's report counts as the requester's", ENGINE,
     '    theirs = bool(ctx.get("requester")) and sealed(user) == str(ctx.get("requester"))\n',
     "    theirs = True\n"),
    ("the approvers are not named where they may confirm for the reporter", ENGINE,
     "    if not theirs and not may_act(project, user):\n",
     "    if False:\n"),
    ("a requirement's defect cites no promise", ENGINE,
     "    violates = (int(owed) if owed.isdigit() and not ctx.get(\"defect\") "
     "and not ctx.get(\"ticket\")\n",
     "    violates = (None if owed.isdigit() and not ctx.get(\"defect\") "
     "and not ctx.get(\"ticket\")\n"),
    ("the requester's own yes is refused like a stranger's", CONFIRM,
     '    if _their_delivery_did_not_work(entry, user):\n        return ""\n',
     '    if False:\n        return ""\n'),
    ("any reporter of a delivery's defect files it without an approver", CONFIRM,
     '            and bool(entry.get("their_delivery")) and _is_requester(entry, user))\n',
     "            and _is_requester(entry, user))\n"),
    ("the yes files a defect linked to nothing", CONFIRM,
     '        shown.update(linked=entry["linked"], title=entry.get("title", "") or '
     'shown.get("title", ""))\n',
     "        pass\n"),
    ("the defect is titled with the person's words", CONFIRM,
     '        shown.update(linked=entry["linked"], title=entry.get("title", "") or '
     'shown.get("title", ""))\n',
     '        shown.update(linked=entry["linked"])\n'),
    ("the pen never says what delivery the defect followed", MODULE,
     "                                 linked=linked,\n",
     '                                 linked="",\n'),
    ("the delivered card is never told which defect followed it", MODULE,
     "            self._said_on_the_delivered_cards(tracker, linked, ref, lang)\n",
     "            pass\n"),
    ("the defect's body drops the delivery it followed", AUTHORING,
     '        lines.append(said["after_delivery"].format(cards=", ".join(f"#{r}" for r in refs)))\n',
     "        pass\n"),
    ("two cards' reports in the same words share one button", STAGING,
     "        parts.append(f\"{said['linked']}: {entry['linked']}\")\n",
     "        pass\n"),
    ("two cards are spoken of as one", VOICE,
     '    return said["one" if len(refs) == 1 else "many"].format(sig=_sig(agent_name), '
     "cards=named)\n",
     '    return said["one"].format(sig=_sig(agent_name), cards=named)\n'),
    ("a long title runs past the board's limit", VOICE,
     "    if len(text) > room:\n        text = text[:room - 1].rstrip() + \"…\"\n",
     "    if False:\n        text = text[:room - 1].rstrip() + \"…\"\n"),
]
