"""`openfactory doctor` sees a container of the stack filling up with processes (#532), proven by
breaking it.

Run:  .venv/bin/python tools/mutate.py tools/mutations/532_the_doctor_counts_the_processes.py

A panel held 17,420 zombies against a `pids.max` of 17,435, stopped, and the doctor passed the whole
time. The claims, each a row:

  1. a deployment's doctor asks, and its verdict carries the line (rows 1-2);
  2. half the ceiling fails, and so do a hundred zombies whatever the ceiling (rows 3-4);
  3. an unread container is a note, never counted as read (row 5);
  4. the readings: a zombie after the command's last parenthesis, cgroup v1 as well as v2, `max`
     as unlimited, and the worker read only inside a container (rows 6-9).
"""

TEST = "tests/test_the_doctor_sees_a_container_filling_with_processes.py"

DOCTOR = "openfactory/doctor.py"

MUTATIONS = [
    ("TODAY'S DEFECT: the doctor never reads what a container holds", DOCTOR,
     "        *_pid_findings(probes),\n",
     ""),
    ("a deployment's doctor is not asked", DOCTOR,
     "        pid_counts=pid_counts,\n",
     ""),

    ("only the ceiling itself fails, when nothing can start any more", DOCTOR,
     "c.current >= c.limit * PIDS_SHARE_THAT_FAILS)",
     "c.current >= c.limit)"),
    ("zombies under an unlimited ceiling are never counted", DOCTOR,
     "            or (c.zombies is not None and c.zombies >= ZOMBIES_THAT_FAIL)]\n",
     "            ]\n"),

    ("an unread container is reported as read", DOCTOR,
     "    read = [c for c in counts if not c.unread]\n",
     "    read = list(counts)\n"),

    ("a command named with a parenthesis hides its state", DOCTOR,
     '        count += text[text.rfind(")") + 1:].split()[:1] == ["Z"]\n',
     '        count += text[text.find(")") + 1:].split()[:1] == ["Z"]\n'),
    ("a cgroup v1 host reads no pids", DOCTOR,
     '    for base in (root, root / "pids"):\n',
     "    for base in (root,):\n"),
    ("`max` is read as a number", DOCTOR,
     '            return int(current.read_text().strip()), (None if raw == "max" else int(raw))\n',
     "            return int(current.read_text().strip()), int(raw)\n"),
    ("the worker is read on a machine that is not a container", DOCTOR,
     "    if in_container:\n        current, limit = cgroup_pids()\n",
     "    if True:\n        current, limit = cgroup_pids()\n"),
]
