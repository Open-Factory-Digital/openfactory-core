# Writing an add-on — a provider row, end to end

**Who this is for.** Anyone whose deployment needs a provider the core does not ship: another
forge, another tracker, another CI, a box that runs somewhere of your own, a chat channel, an
identity provider. You will not edit a file of this repository, and you do not need our
permission — the entry point is the whole contract.

[core/07-extensibility.md](core/07-extensibility.md) is the mechanism and the reasoning. This
page is the walkthrough: two files, four commands, and the traps that cost a real afternoon.

---

## 0. What you are building, in one picture

```
your-addon/                     ← a Python package. Contains no line of OpenFactory.
  pyproject.toml                ← declares `<axis>.<kind> = module:builder`
  your_addon/__init__.py        ← the builder, and what it builds

  ↓ pip install -e your-addon   ← writes `entry_points.txt` into the environment's metadata
  ↓
openfactory/plugins.py::_load() ← reads that metadata at lookup time
  ↓
the registry for that axis      ← your kind is now in its table
```

The bridge is the **Python environment**, not the code. The core never imports your package by
name; it asks `importlib.metadata.entry_points()` what is installed. That is why nothing here is
edited, and why a built-in row still wins a collision — see §6.

## 1. Pick the axis and the kind

`<axis>` must be one of `openfactory/plugins.py::AXES`. `<kind>` is yours to name: it is the
value a project (or the deployment's environment) will declare to select your row.

    forge.gitea          a forge the core does not ship
    ci.jenkins           a CI observer
    notifier.acme        this page's example

**A collision is not an override.** Declaring `forge.github` does not replace the shipped
GitHub row — the built-in answers and the collision is logged. An add-on able to change what
`github` means for every project on a deployment is a supply chain, not an extension point.

**The kind is a key; say what your row is CALLED.** A person never reads `jenkins` unless your
row gives the core nothing better. Declare `display_name` on the row and every surface that
names it asks (`openfactory/plugins.py::display_name`) — the core keeps no table of provider
names, so there is nothing of ours to edit:

```python
def build_observer(project, *, token=None): ...
build_observer.display_name = "Jenkins"      # the panel's heading: "CI checks (Jenkins)"
```

On the `ci` axis the row is the builder, so the name hangs off it, beside `environment` and
`how_to`; a forge says it on the adapter (`display_name = "Gitea"`, a class attribute), which is
what a repair brief calls it. Only a non-empty string counts. A row that declares nothing keeps
working and is shown honestly rather than prettily: by its kind in a heading, as "the forge" in
a sentence.

**And say what your vendor needs SAID.** A remedy is a vendor's own words — its variable, its
login, its console — and the core spells none: `openfactory doctor`, `product declare` and
`project init` ask the row (`openfactory/plugins.py::sentence`), by the name of the moment the
words are said. Every one is optional, a string, or a callable of the project when the words
depend on its options:

| on the row of | declare | said when |
|---|---|---|
| `credential.<kind>` (`CredentialRow`) | `when_missing`, `when_refused` | the doctor finds no forge credential; the forge refused the one it found |
| `board.<kind>` (the builder) | `coordinates(project)` | the doctor says WHICH board it could not read |
| | `when_unreadable` | what to do about that |
| | `setup` | `project init` has no board to create for this tracker |
| | `display_name` | the cockpit lists the boards this deployment can build |
| `forge.<kind>` (the builder) | `when_unreadable` | `product declare` recorded a repository nothing could read |

```python
def credential():
    return CredentialRow(env="ACME_TOKEN",
                         when_missing="run `acme login`, or set ACME_TOKEN",
                         when_refused="renew the token in the Acme console: they last thirty days")

def build_board(project, *, token, token_provider, options): ...

def which_board(project):
    return project.tracker.options["workspace"]

build_board.coordinates = which_board
```

A row that says nothing is never told another vendor's remedy: it gets a sentence that names no
vendor, built from what the row does declare — a credential row that names `ACME_TOKEN` and no
`when_missing` is still told to set `ACME_TOKEN`. A callable that raises is logged and read as
silence.

## 2. Write the two files

`pyproject.toml`:

```toml
[project]
name = "openfactory-acme"
version = "0.0.1"
requires-python = ">=3.12"
dependencies = []

[project.entry-points."openfactory.adapters"]
"notifier.acme" = "openfactory_acme:build_notifier"

[build-system]
requires = ["setuptools>=77"]
build-backend = "setuptools.build_meta"
```

**Do not put `openfactory` in `dependencies`.** The core is published to no index (see
`plugins.py::install_hint`), so `pip` would try to resolve a name that is not there and fail.
The core is installed *beside* your package, never pulled by it — `docker/install-addons.sh`
does exactly that, core first.

`openfactory_acme/__init__.py`:

```python
class AcmeNotifier:
    def notify(self, *, message: str, level: str = "info",
               about: str = "") -> str | None:
        ...                      # your provider
        return None              # or the provider's own handle for the message


def build_notifier(project=None, **_kw):
    return AcmeNotifier()
```

§3 is why the signature reads that way, and it is the part that bites.

## 3. THE BUILDER'S SIGNATURE IS NOT FREE, AND GETTING IT WRONG IS SILENT

Each axis calls its row with its own arguments. Derived from the call sites, and the one column
that matters:

| axis | how the core calls your builder | it returns |
|---|---|---|
| `tracker` | `builder(project, token=…, token_provider=…)` | a `TrackerAdapter` |
| `forge` | `builder(project, token=…, token_provider=…)` | a `ForgeAdapter` |
| `board` | `builder(project, token=…, token_provider=…, options=…)` | a `BoardAdapter` or `None` |
| `ci` | `builder(project, token=…)` | an `EnvironmentObserver` |
| `notifier` | `builder(project)` — **positional**, and `project` may be `None` | a `Notifier` |
| `channel` | `builder()` | a `ChannelAdapter` |
| `harness` | `builder(**kw)` | a `CodingAgentAdapter` |
| `box` | `builder()` | a `(BoxTraits, factory)` row |
| `box_runner` | `builder(**kw)` | a `RemoteBox` |
| `event`, `metrics` | `builder(**kw)` | a sink |
| `session_store`, `token_pool` | `builder(**kw)` | a store / a mapping |
| `identity` | `builder()` | an `IdentityProvider` |
| `credential` | `builder()` | a `CredentialRow` (a value, not a client) |
| `board_setup` | `builder()` | a `BoardCreator` |
| `role` | `builder()` | a `RoleSpec` (a value, not a client) |

The safe shape is **accept what your axis passes, then `**_kw`** — a keyword the core grows
later then arrives as ignorable instead of as a `TypeError` on a live path.

**Why "silent".** Written as `build_notifier(**_kw)`, the example above raises
`TypeError: takes 0 positional arguments but 1 was given` when the notifier axis calls it with
the project. The platform does not crash: `adapters/notify/registry.py::_row_answer` catches it,
records the row as one that "cannot post", and the deployment falls back to the panel. Your row
never runs, the notification is lost, and the only trace is a single WARNING line naming the
`TypeError`. Measured while writing this page, 2026-08-27.

The registries are built to degrade rather than take a scheduled round down. **That protects the
platform, not your afternoon** — so read the warning, and see §5 for the check that would have
caught it in one command.

**A harness's `repair` says nothing of its own about the words it is handed.** Six kinds of
words reach `repair(failure_log=…)` — a gate's output, a forge check's failing log, a person's
review comment, the reviewer's findings, a list of suppressions, an unfinished executor's last
summary — and only the orchestrator knows which. So the orchestrator writes the sentence that
says what the pass is and how it must end, and a harness that closes its prompt with one of its
own ("the validations above FAILED — do not change the tests") says it over a reviewer who asked
for a test to change. Declare the optional keyword, **by name**, to receive the two apart:

```python
def repair(self, *, sandbox, workspace, context, failure_log, instruction=""):
    # `instruction` is the platform's; `failure_log` is a stranger's — fence it as data
```

A `repair` that does not declare it keeps working: it is handed one text in `failure_log`, the
instruction first, as every harness was before the keyword existed. `**kwargs` is not a
declaration — a row that swallows the keyword would drop the instruction — so it is handed one
text too (`adapters/agent/base.py::takes_instruction`).

**The same keyword, on the two optional doors beside it.** If your harness has a `recover` or a
`continue_execute`, the question is asked of THAT method, by name — declaring it on `repair` says
nothing about the other two:

```python
def recover(self, *, sandbox, workspace, context, brief, instruction=""):
    # `instruction` is the platform's order for the pass. `brief` is ONLY what somebody else
    # said — today, the last words of the executor that stopped — so fence it:
    #   ticket_brief(context, failures=brief, this_pass="recovery")

def continue_execute(self, *, sandbox, workspace, context, handle, brief, instruction=""):
    # the session you resume already holds your role prompt and the card: send the instruction,
    # not a second brief. `brief` is empty unless words were handed; when they were, do not reuse
    # the first brief's fence — `handed_to_a_live_session(brief)` draws one for this message
```

Without the keyword `brief` is one text, the instruction first, as it always was. With it, never
render `brief` as an order, and say nothing of your own about why the run stopped — a turn cap,
an error, a caller's reason: only the caller knows (`RECOVER_INSTRUCTION` and
`CONTINUE_INSTRUCTION` in `adapters/agent/base.py` are what a row may say when nobody sent one).

## 4. Install it, and watch the core find it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e /path/to/openfactory      # the core
pip install -e /path/to/your-addon       # your package
```

Then ask a registry what this deployment can build:

```bash
python -c "
from openfactory.adapters.notify.registry import NOTIFIERS
from openfactory import plugins
print(plugins.known('notifier', NOTIFIERS))"
```

```
['acme', 'panel']
```

`NOTIFIERS` is the core's own built-in table; `plugins.known` is that table plus what is
installed. Seeing your kind in a list the **core** printed, with nothing of the core edited, is
the whole mechanism observable in one line.

**REINSTALL AFTER EVERY CHANGE TO `pyproject.toml`.** `entry_points.txt` is written once, at
install time. A row you add to the file is invisible to the running interpreter until the
package is reinstalled — an editable install does not help, because the metadata is not the
code. This one costs an hour if you do not know it.

## 5. Run the conformance suite before you trust it

```bash
openfactory conformance-adapter notifier openfactory_acme:build_notifier
```

```
CONFORMANT — notifier adapter holds every rule this platform has paid for
```

Every rule in it was learned from a live incident here; a green run means your provider does not
re-pay one. The target may be an instance, a class, or a zero-argument factory. The kinds it
accepts are the rows of `openfactory/conformance/adapters.py::CHECKS`, and `--help` lists them.

The suite exercises the **local** contract only — nothing remote is created or mutated — but
point a board adapter at a sandbox of yours anyway.

## 6. Getting it into a running deployment

**A local install** (the section above) is enough for the CLI and for tests.

**The compose stack** builds images, so the package has to reach the build context. The worker
and sandbox images run `docker/install-addons.sh`, which installs the core and then every
directory matching `addons/openfactory-*` in the context:

```dockerfile
COPY addon[s] ./addons
RUN sh docker/install-addons.sh '.[runtime]'     # the sandbox image passes `.` — same script
```

(`addon[s]` rather than `addons` is not a typo: a bracket makes the `COPY` optional, so a tree
without the directory builds instead of aborting on `"/addons": not found`.)

So, in your clone of this repository:

```
addons/openfactory-acme/          ← the name must start with `openfactory-`
```

then rebuild. **`addons/` is not in `.gitignore`** — if your clone has a remote you can push to,
your package is tracked by git and a push publishes it. Keep the package in its own repository
and place it here as a copy, a submodule, or a build-time step; decide that before the first
commit, not after.

If the directory is absent — which is what the public export looks like — the script installs
the core alone and exits 0. That is the shape working, not a failure.

## 6b. Running the core's own suite while your add-on is installed

If you run this repository's tests in the same environment your add-on is installed into, a
handful of them fail — and the failure is not yours:

```
tests/test_the_doctor_says_where_project_less_speech_goes.py
E   Left contains one more item: '<your kind>'
```

Those tests assert on the EXACT set of notifier rows a deployment has, through a fixture that
installs a real distribution and patches nothing — that is the point of it, and it is why it
also sees yours. Run the core's suite in an environment without your package (or uninstall it
for the run); your own package's tests are unaffected.

## 7. What the platform does when something is wrong

None of these is a crash, and each names the fix:

| situation | what happens |
|---|---|
| a kind nobody declares | refused **by name**, listing what IS installed — never a silent default |
| your package fails to import | logged, ignored, **every other axis unaffected** |
| an entry point not spelled `<axis>.<kind>` | logged and skipped, with the shape it needed |
| your builder raises | the axis degrades (a fallback, a refusal) and the error is reported as what the row lacked |
| your builder returns the wrong type | refused by name, listing the methods it lacks — it is never called |

## 8. When the answer is not an add-on

If what you need has **no axis** — a seam that does not exist anywhere — an add-on cannot help
and the change belongs here. Two things to know before opening it:

- **An axis is agnostic when it is born with two.** A port with one implementation is that
  implementation's shape wearing a general name. Bring the second, or the argument for it.
- **A port does not widen because a provider has a feature.** The question is never *does that
  provider support it* but *does the core call it*. A capability that grows because a provider
  has one is a leak with a Protocol on it.

[CONTRIBUTING.md](../CONTRIBUTING.md) §"Four ways to break a seam" has the other two, and each
has been proposed here at least once.

## 9. A chat add-on and the product role — what changed in #266 slice 6

The core stopped carrying a chat vendor's shape (ADR-0051 D14 and D16). A chat add-on written
against the earlier contract **breaks**, which is why the core ships this as a minor version.
What it must do now, and where:

| it used to | it does now | where |
|---|---|---|
| ask the core `is_product_channel(project, channel)` | decide which of its rooms is the product's from its own settings: `product.channel_options` (the room under `channel`, in its own terms) | the add-on |
| ask the core `conversation_key(event, channel)` | key the conversation itself — a bare message is its room's, a reply is its thread's — and hand the key over | the add-on → `handle(conversation=…, room=…)` |
| hand the core its user id and have it compared with `admins` | map its user to a **person of the platform** — the id the deployment's identity provider knows them by — by implementing the port | `openfactory/adapters/channel/base.py::PeopleOfAChannel.person_of`, passed as `handle(people=…)` and `confirm_by_click(people=…)` |
| be named `slack` by the core | say its own name | `handle(via=…)`, `confirm_by_click(via=…)` |
| have every message in the product's room answered | detect a **mention** its own way (its mention syntax), and say whether the conversation is a **direct** one | `handle(mentioned=…, direct=…)`; the reply rule is the core's |
| read a `channel_id` and be selected by it | be **declared** — `channel: <your kind>` — and read its room from `channel_options` | the operator's registry |
| read `<@user>` in what the core writes | read the person's plain id; render it as a mention of its own if it can map it back | the add-on |

The new call, in full:

```python
from openfactory.product import channel

reply = channel.handle(
    project,
    text=event_text,
    user=vendor_user_id,         # yours — turned into a person through `people`
    conversation=thread_or_room, # your key: a thread, or the room for a bare message
    room=room_id,                # the room that conversation lives in
    people=self,                 # anything with `person_of(user, *, project) -> str`
    via="your-kind",             # your own name, recorded as provenance
    mentioned=you_detected_a_mention,
    direct=it_is_a_direct_message,
    in_reply_to=parent_message_id,
    message_id=your_message_id,  # so a retry is one message
    notify=post_a_receipt,
    confirm=post_buttons,
)
```

**`person_of` answers `""` when it is not sure**, and that is safe: the user is spoken to as a
guest, told apart from every other guest, and may confirm nothing. A wrong person is not safe — it
would let one of your users confirm with somebody else's authority — so never guess. How you map
is yours: a verified email against the deployment's people, a table of your own, a directory
lookup.

**What the core decides, and you do not.** A message is addressed to the role when it is in a
direct conversation, when it mentions the role, or when it replies inside a conversation the role
takes part in (`openfactory/product/addressing.py`). Anything else is kept in the product's memory,
found by `product_recall`, and starts no turn: `handle` returns `None` for it, and the door's
acknowledgement is not sent to `notify` — nothing is posted into the room.

**The old registry keys keep loading until 0.5.0**, each named once in a deprecation warning
(`OPENFACTORY_DEPRECATED_KEY`): `slack_channel` and `channel_id` → `channel_options.channel` (the
project's and the product's), `slack_admins` → `admins`, `slack_bot_token_env` /
`slack_app_token_env` → `channel_options.bot_token_env` / `.app_token_env`. A project that carried
a coordinate without `channel:` talks through the panel now, and its warning says to add
`channel: <kind>`; `admins` that still hold your vendor's ids keep matching exactly as they did —
nothing is widened — but only for users your `person_of` names by those same ids.
