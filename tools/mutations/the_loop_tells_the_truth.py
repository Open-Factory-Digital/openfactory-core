"""ADR-0049 slice 3c, proven by breaking it — the merge path stops asserting what nobody measured.

THREE CLAIMS:

  1. **The forge's own sentence reaches the person**, and today's wording stays as the fallback so
     a hosted deployment keeps its branch-protection hint word for word.
  2. **The new command is behind a replay gate.** Activity results are recorded in history: a job
     parked at this gate today holds a `false` that a `str`-shaped reader cannot deserialise, so
     the old activity stays and the new one is patched in.
  3. **The pull request has a page, through the port**, and the three answers survive it — a diff
     that could not be read is not a pull request that changes nothing.

WHAT IS NOT HERE, AND WHY IT IS NOT. The issue's slice 3 also asks for a `resume` on a
merge-refusal hold to re-enter the MERGE loop instead of re-running the job. Reading the lifecycle
loop, the merge watch sits INSIDE the `result is None` branch that runs the agent, so re-entering
it means restructuring the loop every in-flight job replays — a change of a different kind from
these, and one that deserves a review looking only at it. The hold's mark travels with it: a field
nothing reads is what ADR-0045 is about, so shipping the mark alone would be worse than shipping
neither.

WHAT THE FIRST RUN FOUND, both of them holes in the guard rather than in the code:

  · **the paragraph explaining a change QUOTED the wording it was about**, so an assertion over
    the raw source was satisfied by the comment while the code had lost it. `conftest.code_only`
    exists for exactly this and its docstring lists four earlier instances; this is the fifth. It
    parses, so a method's source has to be dedented first;
  · nothing asserted that an UNREADABLE diff reaches the page as `None`. Every test read the diff
    of a pull request that had one, and `x or ""` is invisible to all of them.

The guard under test is `tests/test_the_loop_tells_the_truth.py`.
"""

TEST = "tests/test_the_loop_tells_the_truth.py"

SLICE = "tests/test_the_loop_tells_the_truth.py"
MERGE = "tests/test_the_merge_is_the_end_of_the_road.py"

WORKFLOW = "openfactory/runtime/temporal/workflow.py"
ACT = "openfactory/runtime/temporal/activities.py"
APP = "openfactory/api/app.py"
FORGE = "openfactory/adapters/forge/local.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    # ── 1. the sentence reaches the person ─────────────────────────────────────────────────────
    ("the gate goes back to naming a cause nobody read — branch protection, on a forge "
     "that is a directory on this machine and has none", WORKFLOW,
     '                note=(f"{who} approved the merge and the forge refused it:\\n{refusal}\\n"\n                      f"Clear what is in the way and answer again."\n                      if refusal else',
     '                note=(f"" if False else', SLICE),

    ("the forge's sentence is swallowed and only the guess is printed", ACT,
     '            said = str(exc).strip() or f"{type(exc).__name__} with no message"\n'
     '            activity.logger.warning("merge refused for %s — %s", inp.pr_url, said)\n'
     "            return said[:2000]",
     '            activity.logger.warning("merge refused for %s", inp.pr_url)\n'
     '            return "refused"', SLICE),

    ("a landed merge answers a sentence, so every successful merge reads as a refusal", ACT,
     '            forge.merge_pr(pr=inp.pr_url)\n            return ""',
     '            forge.merge_pr(pr=inp.pr_url)\n            return "merged"', SLICE),

    ("today's wording is replaced rather than kept as the fallback, so a hosted deployment loses "
     "the hint it has always had", WORKFLOW,
     '                      f"{who} approved the merge but the forge refused it — most likely '
     'branch "\n'
     '                      f"protection this App cannot satisfy (a required review, a required '
     'check). "\n'
     '                      f"Merge it on the forge, or fix the rule and answer again."),',
     '                      f"{who} approved the merge and it was refused."),', SLICE),

    # ── 2. the replay gate ─────────────────────────────────────────────────────────────────────
    ("the new activity is called with no patch gate, so a job replaying its pre-fix history emits "
     "a command that history does not contain — TMPRL1100", WORKFLOW,
     '            if workflow.patched("merge-refusal-says-what-the-forge-said"):',
     "            if True:", SLICE),

    ("the old activity is deleted, so a job parked at this gate before the patch cannot replay",
     ACT,
     "@activity.defn\nasync def merge_pr_now(inp: MergeCheckInput) -> bool:",
     "@activity.defn\nasync def _merge_pr_now_retired(inp: MergeCheckInput) -> bool:", MERGE),

    ("the new activity is never registered on the worker, which fails the loop and parks the job "
     "— the shape that once read as 'the gate never opened'", "openfactory/runtime/temporal/worker.py",
     "    merge_pr_now,\n    merge_pr_saying_why,\n", "    merge_pr_now,\n", SLICE),

    # ── 3. the decision stops guessing ─────────────────────────────────────────────────────────
    ("the dirty decision goes back to calling every unmergeable pull request a textual conflict, "
     "sending the reader to look for one that is not there", WORKFLOW,
     '                context="The forge reports it will not merge. It says why on the pull '
     'request; "\n'
     '                        "the usual causes are a conflict with the base, or something in the '
     'way "\n'
     '                        "in the working copy.",',
     '                context="A textual merge conflict the machine can\'t safely auto-resolve.",',
     SLICE),

    ("the two ways out are cut to one, so a person who cleared their tree cannot say so", WORKFLOW,
     '                    DecisionOption(key="resume", label="I cleared it — re-check",\n'
     '                                   consequence="re-check mergeability and continue",\n'
     "                                   recommended=True),\n",
     "", SLICE),

    # ── 4. the page ────────────────────────────────────────────────────────────────────────────
    ("a diff that could not be read reaches the page as a pull request that changes nothing",
     APP,
     '        "diff": _ask(lambda: forge.pr_diff(pr=ref)),',
     '        "diff": _ask(lambda: forge.pr_diff(pr=ref)) or "",', SLICE),

    ("a pull request that cannot be read is a 500 rather than an answer, so a stale bookmark "
     "reads as the panel being broken", APP,
     "        except Exception:  # noqa: BLE001 — a page must never take the cockpit down\n"
     '            log.info("the pull-request page could not read %r on %s", ref, project.name,\n'
     "                     exc_info=True)\n            return default",
     "        except Exception:  # noqa: BLE001\n            raise", SLICE),

    ("the page reads a pull request nobody asked for, on every board open", APP,
     '    if (asked := (pr or "").strip()):\n        proposal = _pr_detail(proj, asked)',
     '    if True:\n        proposal = _pr_detail(proj, asked or "1")', SLICE),

    ("the refusal is not read back, so the page shows everything except the one sentence a person "
     "can act on", FORGE,
     '    def pr_refusal(self, *, pr: str) -> str:', '    def _pr_refusal_retired(self, *, pr: str) -> str:',
     SLICE),

    ("the review events are dropped", FORGE,
     '    def pr_events(self, *, pr: str) -> list[dict]:',
     '    def _pr_events_retired(self, *, pr: str) -> list[dict]:', SLICE),

    ("the page renders an unreadable diff and an empty one the same way", PANEL,
     "  const diff = p.diff === null", "  const diff = false", SLICE),

    ("the deeper address stops being served, so a pull request nobody can link to", APP,
     '@app.get("/p/{project}/pr/{ref}")\n', "", SLICE),
]
