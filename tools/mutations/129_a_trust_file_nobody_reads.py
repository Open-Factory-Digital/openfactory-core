"""#129: a variable that is SET is not a variable that is USABLE.

Row 1 is the shipped defect restored — an empty trust file waved through, which is the state the
published `v0.2.0` images were in while `box prove` reported PROVEN. The rest hold the distinctions
the finding is built on: a missing file is not an empty one, a probe that cannot look is not a
probe that found nothing, and the value never leaves the box.
"""

SRC = "openfactory/box_prove.py"
TEST = "tests/test_a_trust_file_nobody_reads_is_a_green_proof.py"

MUTATIONS = [
    ("the shipped defect: a file with no certificate in it is accepted", SRC,
     "        broken = {n: c for n, c in counted.items() if c is not None and c < 1}",
     "        broken = {n: c for n, c in counted.items() if c is not None and c < 0}"),

    ("the file is never read — the variable being set counts as proof, as it did before", SRC,
     """            f'    echo "{n} $(grep -c \\'BEGIN CERTIFICATE\\' "${n}" 2>/dev/null || true)"\\n'""",
     """            f'    echo "{n} 1"\\n'"""),

    ("a variable naming NOTHING and one naming an empty file arrive as the same sentence", SRC,
     '''                ", ".join(f"{n} names {'no file' if c < 0 else 'a file with no certificate in it'}"''',
     '''                ", ".join(f"{n} is not usable"'''),

    ("a probe that cannot look inside reports that nothing is wrong", SRC,
     "    trust_files: Callable[[], dict[str, int | None] | None] = lambda: None",
     "    trust_files: Callable[[], dict[str, int | None] | None] = dict"),

    ("the path is echoed beside the count, so a client's image layout leaves the box", SRC,
     """            f'  else echo "{n} -1"; fi\\n'""",
     """            f'  else echo "{n} -1"; fi\\n'\n            f'echo "# ${n}"\\n'"""),

    ("the network line goes back to claiming more than it probed", SRC,
     '''                f"{route.endpoint} answers ({route.name}) — to curl, from inside the box; the "
                f"harness has its own runtime and is not proven to connect by this"))''',
     '''                f"{route.endpoint} answers ({route.name})"))'''),
]
