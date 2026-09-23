"""Mutation plan for #265 — a card's preview before the merge (ADR-0050 and its amendment).

Each row takes away one rule the preview's safety or life cycle rests on; every row must turn
`tests/test_a_card_can_be_previewed.py` red.
"""

TEST = "tests/test_a_card_can_be_previewed.py"
PREVIEW = "openfactory/preview.py"
BOX = "openfactory/adapters/sandbox/container.py"
APP = "openfactory/api/app.py"
MACHINE = "openfactory/orchestrator/machine.py"

MUTATIONS = [
    # ── the host ──
    ("a host under the preview domain that names no preview falls through to the panel", APP,
     "                return _preview_page(404, \"No such preview\", \"This address names no "
     "preview.\")",
     "                return await call_next(request)"),
    ("any name under the domain is read as a preview label", PREVIEW,
     "    return label if _LABEL_RE.fullmatch(label) else \"\"",
     "    return label"),
    # ── the key ──
    ("a key's signature is not checked — a forged or tampered key opens the host", PREVIEW,
     "    return hmac.compare_digest(parts[3], _mac(label, expires))",
     "    return True"),
    ("an expired key still opens", PREVIEW,
     "    if expires < (time.time() if now is None else now):\n        return False",
     "    if False:\n        return False"),
    ("the preview's cookie is readable by the application's scripts", APP,
     "response.set_cookie(preview.COOKIE, token, httponly=True,",
     "response.set_cookie(preview.COOKIE, token, httponly=False,"),
    ("a preview is served without a key", APP,
     "    if not preview.admits(request.cookies.get(preview.COOKIE, \"\"), label=label):",
     "    if False:"),
    ("a product-scoped person cannot open a preview", APP,
     "    if path in _UNSCOPED_ROUTES or path.startswith(_EVERY_AREA_PREFIXES):",
     "    if path in _UNSCOPED_ROUTES:"),
    # ── what the application sees ──
    ("the panel's credential and the preview key reach the application", APP,
     "            if c.strip() and c.split(\"=\", 1)[0].strip() not in (preview.COOKIE, TOKEN_COOKIE)]",
     "            if c.strip()]"),
    ("the Authorization header reaches the application", APP,
     "               and k.lower() not in (\"cookie\", \"authorization\")}",
     "               and k.lower() not in (\"cookie\",)}"),
    # ── the box ──
    ("the factory's credentials survive into the frozen image", BOX,
     "        for var in dict.fromkeys((*_AUTH_ENV_VARS, *self.extra_env)):",
     "        for var in dict.fromkeys(()):"),
    ("the harnesses' state is frozen with the box", BOX,
     "[\"docker\", \"exec\", self._container, \"sh\", \"-c\", f\"rm -rf {scrub}\"]",
     "[\"docker\", \"exec\", self._container, \"sh\", \"-c\", \"true\"]"),
    ("the preview receives the build's secrets too", BOX,
     "        for var in dict.fromkeys(env_names):",
     "        for var in dict.fromkeys((*env_names, *self.extra_env, *_AUTH_ENV_VARS)):"),
    ("the preview wears the job box's name, which a repair of its card removes", PREVIEW,
     "    return f\"openfactory-preview-{safe}-{card}\"",
     "    return f\"openfactory-{safe}-{card}\""),
    ("the job's cleanup deletes the tree the preview serves", BOX,
     "        self._host_clone = None\n        preview.record_live(p)",
     "        preview.record_live(p)"),
    ("a preview name that is not a name reaches the daemon", BOX,
     "        if not re.fullmatch(r\"[a-zA-Z0-9][a-zA-Z0-9_.-]*\", network or \"\"):",
     "        if False:"),
    ("a worktree workload keeps the key previews are signed with", "openfactory/adapters/sandbox/worktree.py",
     "    for var in _PANEL_SECRET_VARS:\n        env.pop(var, None)",
     "    for var in ():\n        env.pop(var, None)"),
    # ── the end ──
    ("a checkout named by a label is deleted wherever it is", BOX,
     "    if _clone_is_ours(clone):",
     "    if clone:"),
    ("a pull request whose state could not be read counts as closed", BOX,
     "                status = \"open\"\n            if status in",
     "                status = \"closed\"\n            if status in"),
    ("a preview whose serve command stopped is advertised as live", BOX,
     "        elif state != \"running\":\n            why = \"its serve command stopped\"",
     "        elif False:\n            why = \"its serve command stopped\""),
    # ── the job ──
    ("the preview is never offered", MACHINE,
     "                self._offer_preview(ticket, pr)\n",
     ""),
    ("a preview that raises fails the job", MACHINE,
     "        except Exception as exc:  # noqa: BLE001 — the promise above: a preview never fails a job",
     "        except ValueError as exc:  # noqa: BLE001 — the promise above: a preview never fails a job"),
]
