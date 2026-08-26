"""#165: a leftover box from an interrupted attempt is removed before the fresh start.

The reverses matter as much as the forwards: a reconcile that always fires is a delete on every
start, and one that reattaches a non-idempotent box races two agents on one branch.
"""

TEST = "tests/test_two_projects_do_not_share_a_box.py"
BOX = "openfactory/adapters/sandbox/container.py"

MUTATIONS = [
    ("the leftover is not reconciled — the resume collides with the corpse again", BOX,
     '        probe_rc, _ = _host(["docker", "inspect", "--format", "{{.Id}}", cname])\n'
     "        if probe_rc == 0:",
     '        probe_rc, _ = _host(["docker", "inspect", "--format", "{{.Id}}", cname])\n'
     "        if False:"),

    ("…and the reverse: the reconcile fires on EVERY start — a delete waiting for a reason", BOX,
     "        if probe_rc == 0:", "        if True:"),

    ("the removal goes silent — debris with no trail", BOX,
     '            print(f"OPENFACTORY: removing the leftover box {cname!r} from an interrupted "\n'
     '                  f"attempt before starting fresh", flush=True)\n', ""),

    ("an unremovable corpse is reported as removed", BOX,
     '            rm_rc, rm_out = _host(["docker", "rm", "-f", cname])\n'
     "            if rm_rc != 0:",
     '            rm_rc, rm_out = _host(["docker", "rm", "-f", cname])\n'
     "            if False:"),
]
