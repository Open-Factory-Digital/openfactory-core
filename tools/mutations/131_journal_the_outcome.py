"""#131: the durable record learns how a job ENDED. Each cut restores a way for it to lie."""

TEST = "tests/test_the_journal_records_how_a_job_ENDED.py"

MUTATIONS = [
    ("the crash path goes silent again — exactly #89's",
     "openfactory/runtime/temporal/workflow.py",
     "            await self._journal_outcome(params, JobState.FAILED.value, "
     "describe(exc, limit=200))\n",
     ""),

    ("a cancelled job's outcome is dropped with the cancellation",
     "openfactory/runtime/temporal/workflow.py",
     '                                        "the workflow was cancelled or terminated", '
     "shield=True)",
     '                                        "the workflow was cancelled or terminated")'),

    ("the normal ending records a guess instead of the result",
     "openfactory/runtime/temporal/workflow.py",
     "        await self._journal_outcome(params, result.state.value, result.note or \"\")",
     '        await self._journal_outcome(params, "done", result.note or "")'),

    ("the new command loses its replay gate",
     "openfactory/runtime/temporal/workflow.py",
     '        if not workflow.patched("journal-the-outcome"):\n            return',
     "        pass"),

    # re-pinned 2026-10-09 (#551): `record_outcome` writes the line through
    # `job_record.record_ending`, which the attended driver and a stop write through too
    ("the reason is dropped and only the bare state survives",
     "openfactory/observability/job_record.py",
     '        data={"reason": (note or "").strip() or None, "by": by}))\n',
     '        data={}))\n'),

    ("a journal that will not write takes the job down with it",
     "openfactory/runtime/temporal/activities.py",
     "    except Exception as exc:  # noqa: BLE001 — the job ended; the record failing must not "
     "undo it",
     "    except ZeroDivisionError as exc:"),

    ("the write rewrites the run's own history instead of appending",
     "openfactory/observability/events.py",
     '        with self.path.open("a") as f:',
     '        with self.path.open("w") as f:'),
]
