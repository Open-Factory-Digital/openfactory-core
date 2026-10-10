"""A job the attended driver ran says how it ended, in its journal, where `outcomes()` reads it
(#551), proven by breaking it.

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/551_the_attended_driver_records_how_a_job_ended.py

`openfactory run` and `openfactory poll`, a one-machine deployment's scheduler, wrote no ending
line, so every job there read as never ended and `jobs` was 0. The claims, each a row:

  1. the attended driver writes the ending, signed as itself (rows 1, 4);
  2. the line is the one `outcomes()` reads — `by` on it — with the job's reason (rows 2-3);
  3. a journal that cannot be written never changes what happened to the job (row 5).
"""

TEST = "tests/test_the_attended_driver_records_how_a_job_ended.py"

CLI = "openfactory/cli.py"
JOB_RECORD = "openfactory/observability/job_record.py"

MUTATIONS = [
    ("TODAY'S DEFECT: the attended driver journals no ending", CLI,
     '        record_ending(view, str(issue), state, by=BY_THE_ATTENDED_DRIVER, note=result.note '
     'or "")\n',
     "        pass\n"),
    ("the ending carries no `by`, so it reads as the box's progress", JOB_RECORD,
     '        data={"reason": (note or "").strip() or None, "by": by}))\n',
     '        data={"reason": (note or "").strip() or None}))\n'),
    ("the ending drops why the job ended", JOB_RECORD,
     '        data={"reason": (note or "").strip() or None, "by": by}))\n',
     '        data={"reason": None, "by": by}))\n'),
    ("the attended driver signs as the workflow", JOB_RECORD,
     'BY_THE_ATTENDED_DRIVER = "the attended driver"\n',
     'BY_THE_ATTENDED_DRIVER = "the workflow"\n'),
    ("a journal that cannot be written fails the job", CLI,
     "    except Exception as exc:  # noqa: BLE001 — the job ended; the record failing must not "
     "undo it\n        log.warning(\"OPENFACTORY_OUTCOME_NOT_JOURNALLED %s#%s",
     "    except ValueError as exc:\n        log.warning(\"OPENFACTORY_OUTCOME_NOT_JOURNALLED %s#%s"),
]
