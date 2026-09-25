"""`make eval-product`: the battery asked of the live product role, and the record written.

    python -m openfactory.product.evaluation [--fixture DIR] [--questions FILE] [--results DIR]

Exit 0 when every question was asked and scored — whatever the score: the battery measures, and a
low number is a finding, not a failed run. Non-zero when there was nothing to run (no questions, a
question file that does not validate, a fixture the module does not accept) or nowhere to run it.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from openfactory.product.evaluation.battery import BatteryRefused, load_battery
from openfactory.product.evaluation.run import (
    DEFAULT_FIXTURE,
    DEFAULT_RESULTS,
    QUESTIONS_FILE,
    Answer,
    FixtureRefused,
    LiveRunRefused,
    run,
    write_record,
)

_NAMES = (("correct", "correct"), ("cited", "cited"), ("abstained_correctly",
                                                         "abstained correctly"))


def _progress(n: int, of: int, answer: Answer) -> None:
    marks = "  ".join(f"{name}: {_mark(getattr(answer, key).passed)}" for key, name in _NAMES)
    print(f"[{n}/{of}] {answer.id}  {marks}  ({answer.seconds:.0f}s)", flush=True)


def _mark(passed: bool | None) -> str:
    return "—" if passed is None else ("yes" if passed else "no")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m openfactory.product.evaluation",
        description="Ask the product role the evaluation battery — a LIVE model, which spends "
                    "tokens — and write a dated record of the score.")
    ap.add_argument("--fixture", default=str(DEFAULT_FIXTURE),
                    help="the fixture product: a directory holding context/ and source/")
    ap.add_argument("--questions", default=None,
                    help=f"the question file (default: <fixture>/{QUESTIONS_FILE})")
    ap.add_argument("--results", default=str(DEFAULT_RESULTS),
                    help="where the dated record is written")
    args = ap.parse_args(argv)

    fixture = Path(args.fixture)
    questions = Path(args.questions) if args.questions else fixture / QUESTIONS_FILE
    if not (fixture / "context").is_dir() or not (fixture / "source").is_dir():
        # a wheel does not carry the suite's tree, and the battery's fixture lives there
        print(f"no fixture at {fixture}: the battery runs from a checkout of the core, where "
              f"tests/fixtures/evaluation/ holds it", file=sys.stderr)
        return 1
    try:
        battery = load_battery(questions, fixture=fixture)
        with tempfile.TemporaryDirectory(prefix="openfactory-evaluation-") as workdir:
            record = run(battery, fixture=fixture, workdir=Path(workdir),
                         questions_file=questions, on_answer=_progress)
    except (BatteryRefused, FixtureRefused, LiveRunRefused) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    as_json, as_md = write_record(record, args.results)
    for key, name in _NAMES:
        t = record.totals[key]
        print(f"{name}: {t.passed} passed, {t.failed} failed, {t.undecided} undecided, "
              f"{t.not_applicable} not applicable")
    print(f"written: {as_json}\n         {as_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
