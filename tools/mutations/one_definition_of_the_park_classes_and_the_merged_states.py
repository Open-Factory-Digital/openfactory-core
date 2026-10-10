"""The tech-lead's classes and the states past the merge are defined once and read everywhere, and the
autonomy command answers any store's failure with exit 2 (reviews of #545 and #554), proven by
breaking it.

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/one_definition_of_the_park_classes_and_the_merged_states.py

`autonomy.CAUSES` and `query.PARK_CLASSES` were two hand copies of the classifier's classes, and
`autonomy._PAST_THE_MERGE` and `query.PAST_THE_MERGE` two of the job states past the merge; a test
kept a third copy of the classes that had already lost `gate`. The claims, each a row:

  1. the classes are every class the classifier answers, and the states past the merge are the
     machine's own from `MERGED` to `DONE`;
  2. no reader keeps a copy;
  3. a store's own error exits the command 2 with what failed.
"""

TEST = "tests/test_the_outcomes_are_read_never_inferred.py"
CLASSIFY = "openfactory/techlead/classify.py"
STATE = "openfactory/contracts/state.py"
QUERY = "openfactory/observability/query.py"
CLI = "openfactory/cli.py"

MUTATIONS = [
    ("the classifier's list loses its tenth class", CLASSIFY,
     "CLASSES = (TRANSIENT, CREDENTIAL, ENVIRONMENT, REQUIREMENT, CODE, POLICY, PROJECT, TREE, GATE,\n"
     "           UNKNOWN)",
     "CLASSES = (TRANSIENT, CREDENTIAL, ENVIRONMENT, REQUIREMENT, CODE, POLICY, PROJECT, TREE,\n"
     "           UNKNOWN)"),
    ("a state at the end of the merge's tail stops counting as past it", STATE,
     "_ORDER[_ORDER.index(JobState.MERGED):_ORDER.index(JobState.DONE) + 1])",
     "_ORDER[_ORDER.index(JobState.MERGED):_ORDER.index(JobState.DONE)])"),
    ("TODAY'S DEFECT, BACK: the outcomes keep a copy of the classes", QUERY,
     "    parks: dict[str, int] = dict.fromkeys(CLASSES, 0)",
     '    parks: dict[str, int] = dict.fromkeys(("transient", "credential", "environment",\n'
     '                                           "requirement", "code", "policy", "project",\n'
     '                                           "tree", "gate", "unknown"), 0)'),
    ("a store added from outside reaches the operator as a traceback", CLI,
     "    except Exception as exc:  # noqa: BLE001 — a store added from outside raises its own errors\n",
     "    except StoreUnreadable as exc:  # the core's own error only, as before\n",
     "tests/test_autonomy_is_read_from_the_record.py"),
]
