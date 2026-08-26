"""A stranger's add-on, installed the way `pip install` installs one — for the duration of a test.

THE CLAIM IS ABOUT PACKAGING, so the package is REAL: a directory on `sys.path` holding an
importable module (`acme_addons`) and a `*.dist-info` with an `entry_points.txt`, which is exactly
what `importlib.metadata.entry_points()` scans. Nothing of ours is patched — not the loader, not
the metadata reader — because a fixture that patched either would prove that our function returns
what we told it to, and the sentence being asserted is that a stranger who writes a pyproject and
installs it is heard by every registry.

ONE ADAPTER PER AXIS, each satisfying its port at runtime (`isinstance` against the Protocol) and
each honouring the rules the conformance suite charges for — so the same package proves that a
stranger's adapter builds, that the conformance CLI accepts it in its class AND factory forms, and
that the worker starts its listeners. `BUILT` records every builder the platform actually called,
which is the difference between "loaded" and "asked for".
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from openfactory import plugins

#: The stranger's kind on every axis but the remote box, which needs a name of its own because a
#: row is either local or remote and never both.
KIND = "acme"
REMOTE_KIND = "acme_cloud"
HOST = "git.acme.example"

SOURCE = '''
"""acme_addons — a third party's providers, registered through entry points only."""

from __future__ import annotations

from pathlib import Path

HOST = "git.acme.example"
#: (axis, kind) for every builder the platform CALLED. Loaded is not asked for.
BUILT: list[tuple[str, str]] = []
#: channel kinds whose listeners the worker started.
STARTED: list[str] = []


# ── forge ────────────────────────────────────────────────────────────────────────────────────────

class AcmeForge:
    def __init__(self, project=None, *, token=None, token_provider=None):
        self.project, self.token, self.token_provider = project, token, token_provider

    def push_remote(self):
        return None

    def clone_url(self, repo, *, token):
        return f"https://{HOST}/{repo}.git"

    def authenticated_url(self, url):
        from openfactory.adapters.forge.base import carries_credentials, host_of

        if not self.token or carries_credentials(url) or host_of(url) != HOST:
            return url
        return url.replace("https://", f"https://acme:{self.token}@", 1)

    def list_branches(self, repo="", *, prefix=""):
        return []

    def delete_branch(self, name, *, repo=""):
        return False

    def pr_for_head(self, head, *, repo=""):
        return None

    def open_pr(self, *, head, base, title, body, repo=""):
        return f"https://{HOST}/pr/1"

    def review_pr(self, *, pr, event, body):
        return None

    def request_reviewers(self, *, pr, reviewers):
        return None

    def merge_pr(self, *, pr, repo=""):
        return None

    def close_pr(self, *, pr, reason=""):
        return None

    def pr_merged(self, *, pr):
        return False

    def pr_status(self, *, pr, repo=""):
        return "open"

    def disable_auto_merge(self, *, pr):
        return None

    def pr_ci_status(self, *, pr):
        return "unknown"

    def failed_ci_logs(self, *, pr):
        return ""

    def pr_diff(self, *, pr, repo="", max_chars=60000):
        return None

    def pr_body(self, *, pr, repo=""):
        return None

    def set_pr_body(self, *, pr, body, repo=""):
        return False

    def pr_checks(self, *, pr):
        return []

    def merge_commit_sha(self, *, pr):
        return None

    def deploy_run_status(self, *, sha, workflow):
        return ("unknown", None)

    def dispatch_workflow(self, *, workflow, ref):
        return None

    def latest_run(self, *, workflow):
        return None

    def disabled_ci_paths(self, repo=""):
        return None

    def latest_tag(self):
        return None

    def create_tag(self, *, tag, ref):
        return None


def build_forge(project, *, token=None, token_provider=None):
    BUILT.append(("forge", "acme"))
    return AcmeForge(project, token=token, token_provider=token_provider)


def make_forge():
    return AcmeForge()


# ── tracker ──────────────────────────────────────────────────────────────────────────────────────

class AcmeTracker:
    def __init__(self, project=None, *, token=None, token_provider=None):
        self.project, self.token = project, token

    def budget(self):
        """The port's third answer: this vendor declares no readable quota (the forge cut of
        2026-08-26 put the question on the tracker port; a stranger answers it honestly)."""
        from openfactory.adapters.tracker.base import NOT_REPORTED

        return NOT_REPORTED

    def get_ticket(self, ref):
        from openfactory.contracts import Ticket

        return Ticket(id=ref, title="acme", objective="acme", repo="acme/repo")

    def set_state(self, ref, state, reason=None, *, needs_person=None):
        return None

    def comment(self, ref, body):
        return None

    def comments(self, ref, *, limit=0):
        return None  # could not read — never [] for a ticket it cannot have

    def list_tickets(self, *, state="all", updated_since="", limit=0):
        if state not in ("open", "closed", "all"):
            raise ValueError(f"unknown state filter {state!r}")
        return None

    def ticket_url(self, ref):
        return f"https://{HOST}/tickets/{ref}"

    def person(self, ref):
        return {}

    def assignees(self, ref):
        return []

    def set_assignees(self, ref, logins):
        return None

    def add_label(self, ref, label):
        return None

    def remove_label(self, ref, label):
        return None

    def create_ticket(self, *, title, body):
        return "ACME-1"

    def find_ticket(self, *, title):
        return None

    def update_body(self, ref, body):
        return None

    def close_ticket(self, ref, reason, *, delivered=True):
        return None

    def link_child(self, parent_ref, child_ref):
        return None

    def children_of(self, parent_ref):
        return []


def build_tracker(project, *, token=None, token_provider=None):
    BUILT.append(("tracker", "acme"))
    return AcmeTracker(project, token=token, token_provider=token_provider)


def make_tracker():
    return AcmeTracker()


# ── harness ──────────────────────────────────────────────────────────────────────────────────────

class AcmeHarness:
    def __init__(self, **kw):
        self.kw = kw

    def execute(self, *, sandbox, workspace, context):
        from openfactory.contracts import AgentRunResult

        sandbox.run(workspace=workspace, command="acme --implement", timeout=5)
        return AgentRunResult(ok=True, summary="acme did nothing", harness="acme")

    def repair(self, *, sandbox, workspace, context, failure_log):
        from openfactory.contracts import AgentRunResult

        return AgentRunResult(ok=True, summary="acme repaired nothing", harness="acme")


def build_harness(**kw):
    BUILT.append(("harness", "acme"))
    return AcmeHarness(**kw)


def make_harness():
    return AcmeHarness()


# ── channel ──────────────────────────────────────────────────────────────────────────────────────

class AcmeChannel:
    kind = "acme"

    def say(self, *, project, channel, text):
        return True

    def mention(self, person, **kw):
        return person

    def start_listeners(self):
        STARTED.append("acme")


def build_channel(**kw):
    BUILT.append(("channel", "acme"))
    return AcmeChannel()


#: What the channel's rows read, declared ON THE BUILDER (`plugins.environment`) — `openfactory
#: init` writes these as rows under the package's own comment, and spells none of them itself.
build_channel.environment = ("ACME_CHAT_TOKEN",)
build_channel.how_to = "Issued by the Acme workspace's admin console, one per deployment."


def make_channel():
    return AcmeChannel()


# ── board ────────────────────────────────────────────────────────────────────────────────────────

class AcmeBoard:
    """Jira-shaped: the project IS the board, no coordinates needed."""

    def __init__(self, project=None, *, options=None):
        self.project, self.options = project, dict(options or {})

    def url(self):
        return f"https://{HOST}/board"

    def columns(self):
        return {"todo": "To do", "done": "Done"}

    def column_names(self):
        return ["To do", "Done"]

    def pickup_column(self):
        return "To do"

    def items_in_status(self, status):
        return []

    def add_item(self, *, issue_url):
        return None

    def set_column(self, *, issue, issue_url, name):
        return False

    def set_status(self, *, issue, issue_url, state, needs_person=None):
        return False


def build_board(project, *, token=None, token_provider=None, options=None):
    BUILT.append(("board", "acme"))
    return AcmeBoard(project, options=options)


def make_board():
    return AcmeBoard()


# ── ci observer ──────────────────────────────────────────────────────────────────────────────────

class AcmeObserver:
    def __init__(self, project=None, *, token=None):
        self.project, self.token = project, token

    def ci_status(self, *, repo, ref):
        return []

    def deploy_status(self, *, env, ref):
        return "unknown"

    def health(self, *, url, timeout=10):
        return False


def build_observer(project, *, token=None):
    BUILT.append(("ci", "acme"))
    return AcmeObserver(project, token=token)


def make_observer():
    return AcmeObserver()


# ── box (local) and box (remote) with its runner ─────────────────────────────────────────────────

class AcmeBox:
    def __init__(self, **kw):
        self.kw = kw
        self.ran: list[str] = []

    def prepare(self, *, repo_path, base_branch, branch, checkout_existing=False, remote_url=None):
        from openfactory.adapters.sandbox.base import Workspace

        return Workspace(path=Path(repo_path), branch=branch, base_branch=base_branch)

    def harness_path(self, name):
        return name

    def run(self, *, workspace, command, timeout):
        self.ran.append(command)
        return 0, ""

    def tail(self):
        return None

    def export_home_dir(self, *, workspace, relative, dest):
        return False

    def import_home_dir(self, *, workspace, src, relative):
        return False

    def diff_paths(self, *, workspace):
        return []

    def publish_branch(self, *, workspace, remote_url=None):
        return None

    def rebase_onto_base(self, *, workspace, remote_url=None):
        return True

    def cleanup(self, *, workspace):
        return None


def _build_box(**kw):
    BUILT.append(("box", "acme"))
    return AcmeBox(**kw)


def box_row():
    from openfactory.adapters.sandbox.registry import BoxTraits

    return (BoxTraits("acme", remote=False, honours_image=True, idempotent=False, streams=False,
                      isolates_resources=True, transfers_state=False), _build_box)


def make_box():
    return AcmeBox()


class AcmeRunner:
    def launch(self, box, *, journal=None, variant="", extra_env=None, timeout=0, run_id=None):
        raise NotImplementedError("the test never launches")

    def stop(self, box):
        return 0

    def tail(self, project, issue):
        class _Tail:
            def fetch_new(self):
                return []

        return _Tail()


def build_runner(**kw):
    BUILT.append(("box_runner", "acme_cloud"))
    return AcmeRunner()


def remote_box_row():
    from openfactory.adapters.sandbox.registry import (
        BoxTraits,
        no_local_adapter,
        runner_from_addon,
    )

    return (BoxTraits("acme_cloud", remote=True, honours_image=False, idempotent=True,
                      streams=False, isolates_resources=True, transfers_state=False),
            no_local_adapter("acme_cloud"), runner_from_addon("acme_cloud"))


# ── observability ────────────────────────────────────────────────────────────────────────────────

class AcmeEvents:
    def __init__(self, **kw):
        self.kw, self.events = kw, []

    def emit(self, event):
        self.events.append(event)


def build_event_sink(**kw):
    BUILT.append(("event", "acme"))
    return AcmeEvents(**kw)


class AcmeMetrics:
    def __init__(self, **kw):
        self.kw = kw

    def record(self, rec):
        return True


def build_metrics_sink(**kw):
    BUILT.append(("metrics", "acme"))
    return AcmeMetrics(**kw)


# ── identity ─────────────────────────────────────────────────────────────────────────────────────

class AcmeIdentity:
    def identify(self, *, credential, via=""):
        from openfactory.identity.base import Subject

        if (credential or "").strip() == "acme-token":
            return Subject(id="acme-user", display="Acme User", via=via)
        return None


def build_identity():
    BUILT.append(("identity", "acme"))
    return AcmeIdentity()


# ── credential + board setup (the forge cut's two axes, 2026-08-26) ──────────────────────────────

def build_credential():
    """The stranger's forge names its OWN environment variable — the row is the declaration.
    A subclass, so the probe can tell the add-on's object from a row the core minted."""
    from openfactory.adapters.credential.registry import CredentialRow

    class AcmeCredentialRow(CredentialRow):
        pass

    BUILT.append(("credential", "acme"))
    return AcmeCredentialRow(env="ACME_FORGE_TOKEN")


class AcmeBoardCreator:
    """`BoardCreator` is a callable; an instance with `__call__` is one the probe can attribute."""

    def __call__(self, *, owner: str, title: str, token: str | None) -> tuple[str, str]:
        return "1", f"https://boards.acme.example/{owner}/{title}"


def build_board_setup():
    """The stranger's tracker creates its own board."""
    BUILT.append(("board_setup", "acme"))
    return AcmeBoardCreator()


def make_identity():
    return AcmeIdentity()


# ── notifier ─────────────────────────────────────────────────────────────────────────────────────

class AcmeNotifier:
    def __init__(self, project=None):
        self.project, self.sent = project, []

    def notify(self, *, message, level="info", about=""):
        self.sent.append((level, message, about))
        return None


def build_notifier(project):
    BUILT.append(("notifier", "acme"))
    return AcmeNotifier(project)


def make_notifier():
    return AcmeNotifier()


# ── role, session store, token pool ──────────────────────────────────────────────────────────────

def build_role():
    from openfactory.adapters.agent.roles import RoleSpec

    BUILT.append(("role", "acme"))
    return RoleSpec(name="acme", prompt="You are the acme role. Answer in one word.",
                    harness_env="ACME_ROLE_HARNESS", model_env="ACME_ROLE_MODEL",
                    human_facing=False)


class AcmeStore:
    def __init__(self, **kw):
        self.kw, self.blobs = kw, {}

    def put(self, *, key, blob):
        self.blobs[key] = blob
        return True

    def get(self, *, key):
        return self.blobs.get(key)


def build_session_store(**kw):
    BUILT.append(("session_store", "acme"))
    return AcmeStore(**kw)


def build_token_pool(**kw):
    BUILT.append(("token_pool", "acme"))
    return {"count": 0, "ids": [], "format": "unknown", "source": "acme"}


# ── half-implemented INSTANCES: what the conformance door judges and must never call ─────────────

def _half(name, *methods, callable_=False):
    """An instance carrying only `methods` of its port — never the whole surface — so the door
    has to refuse it by name. With `callable_` it also defines `__call__`, which RAISES: an
    instance is still an instance, and a door that calls it is caught in the act."""
    body = {m: (lambda self, *a, **k: None) for m in methods}
    if callable_:
        def __call__(self, *a, **k):
            raise AssertionError("the conformance door CALLED an instance")

        body["__call__"] = __call__
    return type(name, (), body)()


half_channel = _half("HalfChannel", "say")
half_callable_channel = _half("CallableHalfChannel", "say", callable_=True)
half_notifier = _half("HalfNotifier", "post")
half_identity = _half("HalfIdentity", "lookup")
half_board = _half("HalfBoard", "url")
half_tracker = _half("HalfTracker", "get_ticket")
half_forge = _half("HalfForge", "push_remote")
half_harness = _half("HalfHarness", "execute")
half_observer = _half("HalfObserver", "health")
half_box = _half("HalfBox", "run")
'''

#: `<axis>.<kind> = acme_addons:<attr>` — every axis in `plugins.AXES`, and the remote box twice
#: (its row and its runner) because that is how a remote box is declared.
ENTRY_POINTS = {
    "forge.acme": "build_forge",
    "tracker.acme": "build_tracker",
    "harness.acme": "build_harness",
    "channel.acme": "build_channel",
    "board.acme": "build_board",
    "ci.acme": "build_observer",
    "box.acme": "box_row",
    "box.acme_cloud": "remote_box_row",
    "box_runner.acme_cloud": "build_runner",
    "event.acme": "build_event_sink",
    "metrics.acme": "build_metrics_sink",
    "identity.acme": "build_identity",
    "notifier.acme": "build_notifier",
    "role.acme": "build_role",
    "session_store.acme": "build_session_store",
    "token_pool.acme": "build_token_pool",
    "credential.acme": "build_credential",
    "board_setup.acme": "build_board_setup",
}

#: kind → (the class a stranger names, the zero-arg factory FUNCTION they may name instead), for
#: every conformance kind. Both forms are what `openfactory conformance-adapter` documents.
CONFORMANCE_FORMS = {
    "channel": ("AcmeChannel", "make_channel"),
    "notifier": ("AcmeNotifier", "make_notifier"),
    "identity": ("AcmeIdentity", "make_identity"),
    "board": ("AcmeBoard", "make_board"),
    "tracker": ("AcmeTracker", "make_tracker"),
    "forge": ("AcmeForge", "make_forge"),
    "harness": ("AcmeHarness", "make_harness"),
    "ci": ("AcmeObserver", "make_observer"),
    "box": ("AcmeBox", "make_box"),
}

#: kind → (a half-implemented INSTANCE the stranger names, one method it lacks) — the form the
#: door lists first, and the one it used to CALL (`TypeError: 'HalfChannel' object is not
#: callable`, measured 2026-08-26). The refusal must name the method.
HALF_FORMS = {
    "channel": ("half_channel", "start_listeners"),
    "notifier": ("half_notifier", "notify"),
    "identity": ("half_identity", "identify"),
    "board": ("half_board", "columns"),
    "tracker": ("half_tracker", "set_state"),
    "forge": ("half_forge", "open_pr"),
    "harness": ("half_harness", "repair"),
    "ci": ("half_observer", "ci_status"),
    "box": ("half_box", "prepare"),
}


def points() -> list:
    """The stranger's rows as entry-point objects, for a test that serves them BESIDE the
    platform's own (`vendor_addons.install(monkeypatch, "channel.slack", extra=points())`):
    `install` patches the metadata reader, which would otherwise hide the real `dist-info`
    `installed()` wrote. The targets resolve because `installed()` registered `acme_addons` in
    `sys.modules`."""
    from vendor_addons import Point

    return [Point(name, f"acme_addons:{attr}") for name, attr in ENTRY_POINTS.items()]


def write_distribution(root: Path) -> Path:
    """The package and its metadata, on disk, under `root/site`. Returns the site directory."""
    site = root / "site"
    pkg = site / "acme_addons"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(SOURCE)
    dist = site / "acme_addons-0.1.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: acme-addons\nVersion: 0.1\n")
    lines = "\n".join(f"{name} = acme_addons:{attr}" for name, attr in ENTRY_POINTS.items())
    (dist / "entry_points.txt").write_text(f"[{plugins.GROUP}]\n{lines}\n")
    return site


def installed(tmp_path: Path, monkeypatch):
    """Install the stranger's distribution for one test and return its imported module.

    `monkeypatch.syspath_prepend` puts the site directory first and invalidates the import
    caches, which is what a `pip install` into the running interpreter's environment amounts to;
    the loader's cache is reset so the entry points are read afresh, and again on teardown so the
    rows leave with the test. The module is registered in `sys.modules` THROUGH monkeypatch, so
    the undo removes it — a second test's copy of the package must be its own, with an empty
    `BUILT`."""
    site = write_distribution(tmp_path)
    monkeypatch.syspath_prepend(str(site))
    sys.modules.pop("acme_addons", None)
    monkeypatch.setattr(plugins, "_cache", None)
    spec = importlib.util.spec_from_file_location("acme_addons", site / "acme_addons" / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    # registered while ABSENT, so the undo deletes it rather than restoring it
    monkeypatch.setitem(sys.modules, "acme_addons", module)
    spec.loader.exec_module(module)
    return module
