"""ADR-0049 slice 4d, proven by breaking it — the doctor tells the truth about the machine it is on.

THREE CLAIMS:

  1. **The login is the credential where the box isolates nothing.** A worktree box runs the
     harness as the person who started the worker; a token variable is what a box that ISOLATES
     needs, and the note has to keep saying so.
  2. **Only a box that runs the project's image HERE needs a container runtime.** The probe is not
     even called otherwise — `docker info` for a worktree is a question nobody asked, answered
     "no job can run" over jobs that run fine.
  3. **A row whose vendor needs no credential says so**, in the probe's own words rather than
     under "reachable with the configured token".

AND THE SAFE DIRECTION: a box this build has never heard of must read as the world before this
probe existed. An exemption granted by accident is the shape this whole slice exists to remove.

The guard under test is `tests/test_the_doctor_tells_the_truth_about_this_machine.py`; the rest of
the doctor suite (`tests/test_doctor.py` and friends, all built on `tests/pinned_probes.py`) is the
pin that must keep passing unedited.
"""

TEST = "tests/test_the_doctor_tells_the_truth_about_this_machine.py"

DOC = "openfactory/doctor.py"

MUTATIONS = [
    # ── 1. the credential a box that isolates nothing already has ──────────────────────────────
    ("the login stops counting, so a correct one-machine install is NOT ready again", DOC,
     '    traits = _traits(p)\n'
     '    if traits is not None and not traits.isolates_resources:\n'
     '        return Finding(\n'
     '            "agent_credential", True,\n',
     '    traits = _traits(p)\n'
     '    if False:\n'
     '        return Finding(\n'
     '            "agent_credential", True,\n', TEST),

    ("every box is treated as if it could see this machine's login", DOC,
     '    if traits is not None and not traits.isolates_resources:',
     '    if True:', TEST),

    ("the pass stops saying the other half — what an isolating box still needs", DOC,
     '            note="a token variable is what a box that ISOLATES needs — the container and the "',
     '            note="" or (\n                  "a token variable is what a box that needs — the container and the "',
     TEST),

    # ── 2. the container runtime ───────────────────────────────────────────────────────────────
    ("`docker info` is run for a box that containerises nothing", DOC,
     '    traits = _traits(p)\n'
     '    if traits is not None and not (traits.honours_image and not traits.remote):',
     '    traits = _traits(p)\n'
     '    if False:', TEST),

    ("the exemption reaches the box that DOES run the image here", DOC,
     '    if traits is not None and not (traits.honours_image and not traits.remote):',
     '    if traits is not None:', TEST),

    # ── 3. the row that needs no credential ────────────────────────────────────────────────────
    ("the finding says 'reachable with the configured token' over a forge nobody asked", DOC,
     '        return Finding("forge_access", True,\n'
     '                       detail or "the forge is reachable with the configured token")',
     '        return Finding("forge_access", True,\n'
     '                       "the forge is reachable with the configured token")', TEST),

    ("the probe stops saying what it measured, so the finding has nothing to render", DOC,
     '            kind = getattr(axis, "kind", "") or "this"\n'
     '            return True, (f"the {kind} forge needs no credential — nothing was asked of a '
     'vendor "\n'
     '                          f"and nothing has to be configured")',
     '            return True, ""', TEST),

    # ── 4. the wiring, and the safe direction ──────────────────────────────────────────────────
    ("the real probes name no box at all", DOC, '        sandbox=_sandbox,\n', "", TEST),

    ("the box is read once at construction instead of at ask time", DOC,
     '        sandbox=_sandbox,', '        sandbox=(lambda box=_sandbox(): box),', TEST),

    ("a box this build has never heard of is granted the host door's exemptions", DOC,
     '                  "existed (%s)", kind, exc)\n        return None',
     '                  "existed (%s)", kind, exc)\n'
     '        return installed_box_traits("worktree")', TEST),
]
