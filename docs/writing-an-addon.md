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
