"""Where a test hands the deployment a metrics sink of its own — one name, the door itself.

`observability.registry.deployment_metrics_sink` is the one door for everything that records, and
every caller in the package imports it INSIDE the function that uses it, so a patch on the
module's attribute reaches all of them: the attended half (`memory/transcript.py`,
`memory/messages.py`, `identity/people.py`, `techlead/conversation.py`, `product/role.py`) and the
worker's activities alike, because `activities._metrics_sink` asks this same door at call time.

THE FAKE USED TO BE INJECTED ONE MODULE OVER, at `runtime.temporal.activities._metrics_sink` — the
worker's private wrapper over this door — because that is where the attended half used to reach
for it (#178). `activities.py` imports `temporalio`, so those sites could not record anything on an
install made without the `runtime` extra, and `openfactory people invite` — the panel's own login
on a local-identity deployment — answered `No module named 'temporalio'`. The tests that patched
the wrapper were patching a name only reachable by paying for the engine's client, which is how
nine test files stayed green over that defect. They patch what the sites actually read now.

A helper module and not a fixture, because what is shared is a NAME: each test builds the fake it
needs (a list, a store, one that raises) and only the target was ever common.
"""

SINK_DOOR = "openfactory.observability.registry.deployment_metrics_sink"
