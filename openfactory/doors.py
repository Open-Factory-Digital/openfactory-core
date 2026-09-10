"""What a door writes when somebody registers a project — one answer for all three.

MOVED OUT OF `cli.py`, and the move is the point (ADR-0049 D2). Three doors register a project —
`openfactory project add`, `openfactory project init` and `POST /api/projects` — and only the two
in the CLI could reach these functions, because the API does not import the command line and
should not have to. So the panel's door asked no host at all, wrote `provider="github"` as a
model default and set `tracker=` alone, while the CLI beside it refused a GitLab URL by name and
wrote every axis. Two doors into one registry, disagreeing about what the same address means.

The functions below are the CLI's own, unchanged; `host_owner` and `kind_for` are what they were
always missing — the question "what kind is this address" asked once, in one place, instead of
being answered three times by whoever happened to be writing the door.
"""

from __future__ import annotations

import re as _re


def ado_coordinates(repo_path: str) -> tuple[str, str, str]:
    """`(organization, project, repository)` out of an Azure DevOps clone URL, or `("", "", "")`.

    Three shapes carry the coordinates, and they are the three ADO itself hands out:

        https://dev.azure.com/<org>/<project>/_git/<repo>       (Clone → HTTPS; may carry user@)
        git@ssh.dev.azure.com:v3/<org>/<project>/<repo>         (Clone → SSH)
        https://<org>.visualstudio.com/<project>/_git/<repo>    (legacy hosts, ± DefaultCollection)

    Segments are URL-decoded because an ADO project name may contain spaces — `%20` in the URL,
    a real space in every API route. Anything else answers empty triple, never a guess: a wrong
    coordinate aims a working credential at somebody else's project."""
    import urllib.parse

    raw = (repo_path or "").strip().rstrip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]
    unquote = urllib.parse.unquote
    if raw.startswith("git@ssh.dev.azure.com:v3/"):
        parts = [unquote(p) for p in raw.split(":v3/", 1)[1].split("/") if p]
        return (parts[0], parts[1], parts[2]) if len(parts) == 3 else ("", "", "")
    if "://" not in raw:
        return "", "", ""
    host, _, path = raw.split("://", 1)[1].partition("/")
    host = host.rsplit("@", 1)[-1].lower()  # a browser-copied URL carries <org>@ before the host
    parts = [unquote(p) for p in path.split("/") if p]
    if len(parts) >= 3 and parts[-2] == "_git":
        if host == "dev.azure.com" and len(parts) >= 4:
            return parts[0], parts[-3], parts[-1]
        if host.endswith(".visualstudio.com"):
            return host.split(".", 1)[0], parts[-3], parts[-1]
    return "", "", ""


def known_forges() -> list[str]:
    """Which forges this build actually implements — the registry's rows PLUS the installed
    add-ons, never listed here. `sorted(FORGES)` alone told an operator who had just installed
    `forge.gitea` that the platform did not support it (measured 2026-08-26)."""
    from openfactory import plugins
    from openfactory.adapters.forge.registry import FORGES

    return plugins.known("forge", FORGES)


def installed_forges() -> list[str]:
    """The forge kinds an add-on brought — the ones whose hosts this build cannot recognise."""
    from openfactory.adapters.forge.registry import FORGES

    return [k for k in known_forges() if k not in FORGES]


def shipped_hosts() -> dict[str, set[str]]:
    """Host names per SHIPPED forge kind — the hosts this build recognises without being told.

    GitHub's is the deployment's own (`GH_HOST`, honoured everywhere a URL is built) and github.com
    always; Azure DevOps's are the three shapes `ado_coordinates` reads. Keyed by the forge
    table's rows, and a guard holds the keys equal to that table: a shipped kind with no entry here
    would be refused as foreign on its own host."""
    import os

    github = {(os.environ.get("GH_HOST") or os.environ.get("GITHUB_HOST") or "github.com")
              .strip().lower(), "github.com"}
    # THE LOCAL ROW OWNS NO HOST, AND THAT IS ITS ANSWER — an empty set, not a missing key. Its
    # repositories are paths, so no URL can be "on its host": every URL handed to a local project
    # is foreign to it, which is exactly what the caller should be told (ADR-0049 D3).
    return {"local": set(),
            "github": github,
            "azure_devops": {"dev.azure.com", "ssh.dev.azure.com", "visualstudio.com"}}


def foreign_host(repo_path: str, *, provider: str = "") -> str:
    """The host in `repo_path` when it belongs to no forge this build implements, else `""`.

    A LOCAL PATH IS NOT FOREIGN: it names no host at all, and an operator registering a working
    copy is the ordinary local case this command was written for. Neither is an ssh remote whose
    host we know.

    AN INSTALLED ADD-ON CLAIMS ITS HOST THROUGH `provider`. The platform cannot know which hosts
    `forge.gitea` answers for — a self-hosted forge lives on whatever name the client gave it —
    so the operator names the kind (`--provider gitea`) and a kind an add-on brought is not
    foreign, whatever its host. A kind nobody implements is refused by name, listing what is
    installed; a host with no kind named keeps the refusal, because the alternative is the label
    that does not stay put (#162: a GitLab URL registered as GitHub).

    A SHIPPED KIND CLAIMS NOTHING. This build knows GitHub's and Azure DevOps's hosts, so
    `--provider github` on a GitLab URL is the #162 door reopened by flag — measured 2026-08-26:
    the first version of the flag let any KNOWN kind claim, and `gitlab.com` was written as a
    GitHub row again. With a shipped kind named, the host must be one that kind answers for: a
    foreign host keeps the refusal, and another shipped kind's host is refused by name too — a
    github.com URL under `--provider azure_devops` wrote an Azure row with `owner/name` for a
    repository and no organisation, which fails at pickup rather than here.
    """
    chosen = (provider or "").strip().lower()
    if chosen and chosen not in known_forges():
        raise ValueError(
            f"{chosen!r} is not a forge this build implements — known: "
            f"{', '.join(known_forges())}. An add-on's kind counts once its package is installed "
            f"where this command runs.")
    raw = (repo_path or "").strip()
    host = ""
    host = _host_in(raw)
    if not host:
        return ""
    if chosen and chosen in installed_forges():
        return ""  # an add-on's host is whatever the client named; the kind claims it

    # ONE READING FOR BOTH QUESTIONS. This walked `shipped_hosts()` itself until `kind_for` needed
    # the same walk; two copies of "whose host is this" is how a door and its refusal come to
    # disagree about one address.
    owner = host_owner(raw)
    if not chosen:
        return "" if owner else host
    if owner == chosen:
        return ""
    if owner:
        raise ValueError(
            f"{host} is not a host the {chosen!r} forge answers for — it is {owner!r}'s. Drop "
            f"--provider, or name {owner!r}.")
    return host  # foreign, and a shipped kind cannot claim it


def infer_repo(repo_path: str) -> str:
    """`owner/name` out of a clone URL, or "" — a local path carries no owner to infer."""
    raw = repo_path.strip().rstrip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]
    if "://" in raw:
        parts = raw.split("/")
        return "/".join(parts[-2:]) if len(parts) >= 2 else ""
    if raw.startswith("git@") and ":" in raw:
        return raw.split(":", 1)[1]
    return ""


def _host_in(repo_path: str) -> str:
    """The host an address names, lowercased, or `""` for a filesystem path — no judgement.

    A LOCAL PATH NAMES NO HOST, which is the sentence `foreign_host` opens with and the reason
    both readers below can share this: a path is not foreign, and it is not anybody's host either.
    """
    raw = (repo_path or "").strip()
    if "://" in raw:
        from openfactory.adapters.forge.base import host_of

        host = host_of(raw) or _re.sub(r"^[a-z+]+://", "", raw).split("/")[0].split("@")[-1]
    elif raw.startswith("git@") and ":" in raw:
        host = raw.split("@", 1)[1].split(":", 1)[0]
    else:
        return ""
    return host.strip().lower()


def host_owner(repo_path: str) -> str:
    """Which shipped forge kind answers for this address's host, or `""` — no judgement.

    `foreign_host` is the JUDGEMENT (is this address one this build can serve, given what the
    operator named); this is the READING under it, and `kind_for` needs the reading without the
    judgement: a URL on a host nobody owns must reach the door's refusal by name, not be silently
    typed as something."""
    host = _host_in(repo_path)
    if not host:
        return ""
    return next((kind for kind, owned in shipped_hosts().items()
                 if any(host == o or host.endswith("." + o) for o in owned)), "")


def kind_for(repo_path: str, *, repo: str = "", provider: str = "") -> str:
    """The kind a door writes on EVERY axis for this address (ADR-0049 D2).

    Four readings, in this order, and each one is a rule somebody can state:

    1. **The operator named a kind** — it is theirs, whatever the address looks like. Whether that
       kind may claim that host is `foreign_host`'s question, and every door asks it.
    2. **A URL** — the kind whose host it belongs to. A host nobody owns comes back `github` here
       and is refused by name at the door before anything is written; `foreign_host` is what makes
       that true, and a door that skipped it would write the #162 defect again.
    3. **A filesystem path** — `local`, UNLESS coordinates were given with it. A path plus
       `--repo owner/name` is a mounted checkout of a hosted repository, which is a shape that
       runs today (`docs/STATUS.md`) and must keep running; the coordinates are the operator
       saying so.

    AZURE DEVOPS IS NOT A READING OF ITS OWN, and the first version of this made it one. Reading
    the coordinates out of the URL to answer `azure_devops` is redundant with reading its host:
    all three shapes ADO hands out live on hosts `shipped_hosts` already names, so the extra line
    could not change a single answer — a mutation run proved it by deleting it and watching every
    test stay green. It bought one WRONG answer, though: an ADO address a person pasted without
    the `_git` segment reads as no coordinates at all, and fell through to `github`, so a project
    on their Azure organisation was registered as a GitHub row. By its host it is Azure DevOps,
    and the ADO door then refuses it by name for the coordinates it is missing.

    THE MODEL'S OWN DEFAULT IS NOT TOUCHED. `ProviderRef.kind` still reads `github`, for the 320
    tests that inherit it and the migration window the box declares. This is the door writing the
    kind explicitly on every axis, which is what makes the default unreachable in practice — the
    strict model is the follow-up card the contract itself names.
    """
    chosen = (provider or "").strip().lower()
    if chosen:
        return chosen
    raw = (repo_path or "").strip()
    if "://" in raw or raw.startswith("git@"):
        return host_owner(raw) or "github"
    return "github" if (repo or "").strip() else "local"
