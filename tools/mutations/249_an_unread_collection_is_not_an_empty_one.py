"""Proven by breaking it — an Azure answer with no collection in it is not an empty collection.

`AzureDevOpsClient.values()` ended `return out if isinstance(out, list) else []`, and `call()`
returns `{}` for a 200 or 204 carrying no body. So an answer nobody could read arrived at every
Azure axis in this tree as "I looked and there is nothing there". On the one caller that gates a
merge it ran: `_evaluations` → `[]` → `"none"` ("no policy gates this merge") → `mergeable_state`
→ `"clean"` → the workflow's self-heal → `force_merge`, whose completion carries `bypassPolicy`.

FOUR CLAIMS:

  1. **A collection that is not there is refused by name**, at the seam every axis reads through,
     and the refusal says what was asked.
  2. **A collection that really is empty is still empty** — on Azure Repos that is the ordinary
     answer, not a rarity, and refusing it would hang every healthy deployment's merge watch.
  3. **An unread policy answer is never a clean pull request**: `unknown`, which the watch treats
     as "give CI time", never the one word `force_merge` acts on.
  4. **An unread ref list is still an unreadable repository** — the behaviour `list_branches`
     used to buy with a shape check of its own, now bought once for the whole file.

The guard is `tests/test_an_unread_collection_is_not_an_empty_one.py`.
"""

TEST = "tests/test_an_unread_collection_is_not_an_empty_one.py"

CLIENT = "openfactory/adapters/azure_devops.py"
FORGE = "openfactory/adapters/forge/azure_devops.py"

MUTATIONS = [
    # ── claim 1: the seam refuses, and says what it was asked ─────────────────────────────────
    ("THE DEFECT ITSELF: an answer with no collection in it is handed over as an empty one",
     CLIENT,
     "        if not isinstance(out, list):\n"
     "            raise AzureDevOpsError(\n",
     "        if False:\n"
     "            raise AzureDevOpsError(\n"),

    ("the refusal does not name the path that was asked, so an operator reading the log cannot "
     "tell which read failed", CLIENT,
     '                f"the answer to {path} carried no collection (`value` was "\n',
     '                f"the answer carried no collection (`value` was "\n'),

    # ── claim 2: an empty collection is an ANSWER, and the commonest one here ─────────────────
    ("every empty collection is refused too, so a project that simply has no branch policy — the "
     "default on Azure Repos — can never merge", CLIENT,
     "        if not isinstance(out, list):\n",
     "        if not out:\n"),

    # ── claim 3: an unread policy answer is not a clean pull request ──────────────────────────
    ("a policy read that failed reports the pull request as CLEAN, which is the one word "
     "`force_merge` acts on and it bypasses policy", FORGE,
     '            log.warning("could not read the policies for PR %s (%s)", pr, str(exc)[:160])\n'
     '            return "unknown"\n',
     '            log.warning("could not read the policies for PR %s (%s)", pr, str(exc)[:160])\n'
     '            return "clean"\n'),

    # ── claim 4: an unread ref list is an unreadable repository ───────────────────────────────
    ("a repository whose refs could not be read is reported as one with no branches, so a "
     "requirement number a live `req/*` branch already claims is minted again", FORGE,
     '            log.warning("could not list the branches of %s (%s)", target, str(exc)[:200])\n'
     "            return None\n",
     '            log.warning("could not list the branches of %s (%s)", target, str(exc)[:200])\n'
     "            return []\n"),
]
