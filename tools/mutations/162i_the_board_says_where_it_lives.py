"""#162 (api/app.py:1769): the board says where it lives; the panel asks."""

TEST = "tests/test_the_board_says_where_it_lives.py"
VENDOR = "tests/test_a_local_deployment_names_no_vendor.py"
BASE = "openfactory/adapters/board/base.py"
GH = "openfactory/adapters/tracker/github_project.py"
ADO = "openfactory/adapters/board/azure_devops.py"
JIRA = "openfactory/adapters/board/jira.py"
APP = "openfactory/api/app.py"

MUTATIONS = [
    # ── the weld comes back ─────────────────────────────────────────────────────────────────────
    ("the panel spells a github.com board URL by hand again", APP,
     "        board = _board_url(proj) or None",
     '        opts = proj.tracker.options or {}\n'
     '        board = (f"https://github.com/orgs/{opts[\'board_owner\']}'
     "/projects/{opts['board_number']}\"\n"
     '                 if opts.get("board_owner") and opts.get("board_number") else None)', VENDOR),

    # ── each vendor's shape ─────────────────────────────────────────────────────────────────────
    ("a user-owned GitHub board links to /orgs/ — the 404 this line already shipped", GH,
     '        return f"https://{_gh_host()}/{_owner_kind(self.owner)}/{self.owner}'
     '/projects/{self.number}"',
     '        return f"https://{_gh_host()}/orgs/{self.owner}/projects/{self.number}"'),

    ("…and the reverse: an org board links to /users/", GH,
     "{_owner_kind(self.owner)}/", "users/"),

    ("a GitHub Enterprise board links to public github.com", GH,
     '    return (os.environ.get("GH_HOST") or os.environ.get("GITHUB_HOST") '
     'or "github.com").strip()', '    return "github.com"'),

    ("an Azure board with no team invents one", ADO,
     "        if not self._team:\n            return base",
     '        if not self._team:\n            return f"{base}/board/t/Default"'),

    ("…and the reverse: a declared team is ignored", ADO,
     "        if not self._team:\n            return base", "        return base"),

    ("a Jira board links somewhere its site does not serve", JIRA,
     '        return f"{site}/browse/{key}" if site and key else ""',
     '        return f"https://jira.atlassian.com/browse/{key}" if key else ""'),

    ("…and the reverse: a Jira project with a site says nothing", JIRA,
     '        return f"{site}/browse/{key}" if site and key else ""', '        return ""'),

    ("the contract stops declaring the question", BASE,
     "    def url(self) -> str:", "    def _url_removed(self) -> str:"),

    # ── the panel's own honesty ─────────────────────────────────────────────────────────────────
    ("a board that cannot say gets a button anyway", APP,
     "        return str(made.url() or \"\") if made is not None else \"\"",
     '        return str(made.url()) if made is not None else "https://github.com"', VENDOR),

    ("a board that RAISES takes the cockpit down", APP,
     '    except Exception as exc:  # noqa: BLE001 — a missing link never fails a page\n'
     '        log.warning("panel: could not resolve the board link for %s (%s)",\n'
     '                    getattr(project, "name", "?"), str(exc)[:120])\n        return ""',
     "    except ZeroDivisionError:\n        return \"\"", VENDOR),

    # ── the panel pays nothing for a string ─────────────────────────────────────────────────────
    ("the board link mints a credential no `url()` reads", APP,
     "        made = build_board(project)",
     "        from openfactory.credentials import deployment_tracker_token, tracker_token_for\n"
     "        made = build_board(project, token=tracker_token_for(project)\n"
     "                           or deployment_tracker_token(project))", VENDOR),

    # ── the ratchet ─────────────────────────────────────────────────────────────────────────────
    ("THE ROOT: the walk lists only `adapters/`, which it then skips entirely", TEST,
     "_PACKAGE = Path(inspect.getfile(BoardAdapter)).parent.parent.parent",
     "_PACKAGE = Path(inspect.getfile(BoardAdapter)).parent.parent"),

    ("the ratchet stops walking", TEST,
     '    for path in sorted(Path(root).rglob("*.py")):',
     '    for path in sorted(Path(root).rglob("nothing-*.py")):'),

    ("a tenant-subdomain host stops matching — Jira goes unguarded", TEST,
     "            if not host or not any(host.group(1).endswith(h) for h in VENDOR_HOSTS):",
     '            if not host or not any(f"https://{h}" in line for h in VENDOR_HOSTS):'),

    ("an exemption needs no reason after the colon", TEST,
     "        return bool(sep2) and bool(why.strip()) and not head.strip()",
     "        return bool(sep2)"),

    ("…and prose grants one, because the marker is read outside a comment", TEST,
     '        _, sep, rest = text.partition("#")\n        if not sep:\n            return False',
     "        rest = text\n        if False:\n            return False"),

    ("the exemption bleeds past the comment block above the statement", TEST,
     "        if not stripped.startswith(\"#\"):\n            return False",
     "        if False:\n            return False"),

    ("the stripper stops padding, so the two readings drift apart", "tests/conftest.py",
     '    return ("\\n".join(kept) + "\\n") if kept else ""',
     '    return "\\n".join(kept)'),

    # ── the conformance gate and the walk's own net ──────────────────────────────────────────────
    ("the board gate stops naming what is missing", "openfactory/conformance/adapters.py",
     '            "board.protocol", f"does not satisfy BoardAdapter (missing: {missing})",',
     '            "board.protocol", "does not satisfy BoardAdapter",'),

    ("the factory walk counts the Protocol as an implementation", TEST,
     '- {"BoardAdapter"}\n    assert len(classes) >= 3', "\n    assert len(classes) >= 3"),
]
