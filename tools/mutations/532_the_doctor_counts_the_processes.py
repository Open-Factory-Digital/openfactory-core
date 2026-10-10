"""`openfactory doctor` sees a container of the stack filling up with processes (#532), proven by
breaking it.

Run:  .venv/bin/python tools/mutate.py tools/mutations/532_the_doctor_counts_the_processes.py

A panel held 17,420 zombies against a `pids.max` of 17,435, stopped, and the doctor passed the whole
time. The claims, each a row:

  1. a deployment's doctor asks, and its verdict carries the line (rows 1-2);
  2. half the ceiling fails, and so do a hundred zombies whatever the ceiling (rows 3-4);
  3. a container that could not be ASKED is a note, never counted as read; one that was asked and
     did NOT ANSWER fails — timed out, or could not start the shell (rows 5-8; review of #572);
  4. the one reader, run: a zombie after the command's last parenthesis, cgroup v1 as well as v2,
     `max` as unlimited, and no process forked per process counted (rows 9-12);
  5. which containers: the one the doctor runs in only inside a pids cgroup, named as its service
     declares, never asked twice from the panel; a stopped panel is not asked (rows 13-17).
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

    # REWRITTEN 2026-10-10, review of #572: one reader for every container, and a container that
    # was asked and did not answer fails
    ("an unread container is reported as read", DOCTOR,
     "    read = [c for c in counts if not c.unread and not c.silent]\n",
     "    read = list(counts)\n"),
    ("a container that did not answer passes, with a note at most", DOCTOR,
     '    full += [f"the {c.container} was asked how many processes it holds and did not answer "\n'
     '             f"({c.silent})" for c in counts if c.silent]\n',
     ""),
    ("a container that timed out is read as one that could not be asked", DOCTOR,
     "    except subprocess.TimeoutExpired:\n        return PidCount(container, silent=",
     "    except subprocess.TimeoutExpired:\n        return PidCount(container, unread="),
    ("a container that could not start the shell is read as one that could not be asked", DOCTOR,
     "        return PidCount(container, silent=(done.stderr or done.stdout).strip()[:120]",
     "        return PidCount(container, unread=(done.stderr or done.stdout).strip()[:120]"),

    ("a command named with a parenthesis hides its state", DOCTOR,
     """'case "${l##*)}" in " Z "*) z=$((z+1));; esac; done; echo "$z"')""",
     """'case "${l#*)}" in " Z "*) z=$((z+1));; esac; done; echo "$z"')"""),
    ("a cgroup v1 host reads no pids", DOCTOR,
     """    'for b in "$c" "$c/pids"; do if [ -r "$b/pids.current" ]; then '""",
     """    'for b in "$c"; do if [ -r "$b/pids.current" ]; then '"""),
    ("`max` is read as a number", DOCTOR,
     '                            limit=None if raw == "max" else int(raw), zombies=zombies)',
     "                            limit=int(raw), zombies=zombies)"),
    ("a process is forked per process counted, again", DOCTOR,
     """{ read -r l < "$s"; } 2>/dev/null; '""",
     """l=$(cat "$s" 2>/dev/null); '"""),

    ("any machine is read as a container", DOCTOR,
     '    return any((base / "pids.current").is_file() for base in (root, root / "pids"))',
     "    return True"),
    ("the container it runs in is read on a machine that is not one", DOCTOR,
     "    if in_container:\n        out.append(_asked(here,",
     "    if True:\n        out.append(_asked(here,"),
    ("whatever container it runs in is called the worker", DOCTOR,
     '    return role or f"container {socket.gethostname()}"',
     '    return "worker"'),
    ("run in the panel, the panel is asked twice", DOCTOR,
     '    if panel and not (in_container and here == "panel"):',
     "    if panel:"),
    ("a stopped panel is asked anyway", DOCTOR,
     '    return "" if done.stdout.strip() == "true" else "it is not running"',
     '    return ""'),
]
