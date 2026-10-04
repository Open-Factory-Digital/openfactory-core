"""A second answer to a staged proposal waits for the first one, and reads what it reads (#456)."""

TEST = "tests/test_a_second_answer_waits_for_the_first.py"
ROW = "openfactory/actions/catalog.py"

MUTATIONS = [
    ("a second start falls into the generic failure again", ROW,
     "    except WorkflowAlreadyStartedError:\n",
     "    except ImportError:\n"),
    ("the second answer waits on some other execution than the one that runs", ROW,
     "            raw = await client.get_workflow_handle(answering).result()\n",
     "            raw = await client.get_workflow_handle(answering + \"-again\").result()\n"),
    ("the second answer reads the first one's outcome past the mapping", ROW,
     "            raw = await client.get_workflow_handle(answering).result()\n",
     "            first = await client.get_workflow_handle(answering).result()\n"
     "            return done(str((first or {}).get(\"message\") or \"\"), project=proj.name)\n"),
    ("an unreadable first outcome is a FAILED, a 500, again", ROW,
     "                CONFLICT,\n"
     "                \"That proposal was already being answered when this answer arrived, so "
     "this one \"\n",
     "                FAILED,\n"
     "                \"That proposal was already being answered when this answer arrived, so "
     "this one \"\n"),
    ("the conflict says nothing was performed again", ROW,
     "                \"That proposal was already being answered when this answer arrived, so "
     "this one \"\n"
     "                \"was not performed a second time. The earlier answer's reply goes to "
     "whoever gave \"\n",
     "                \"I could not answer that just now, and nothing was performed. \"\n"
     "                \"The earlier answer's reply goes to whoever gave \"\n"),
    ("the conflict no longer says where the earlier answer's result is read", ROW,
     "                \"it, and `product_pending` stops listing the proposal once it is taken; "
     "one still \"\n"
     "                \"listed can be answered again.\", project=proj.name)\n",
     "                \"it.\", project=proj.name)\n"),
    ("the engine's diagnosis goes into the conflict's sentence", ROW,
     "                \"listed can be answered again.\", project=proj.name)\n",
     "                f\"listed can be answered again ({exc}).\", project=proj.name)\n"),
]
