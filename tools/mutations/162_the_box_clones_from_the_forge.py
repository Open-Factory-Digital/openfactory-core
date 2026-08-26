"""#162: the box clones from the forge it was told about.

The reverses are the two properties that were riding on the weld and could quietly be lost by
porting it: the origin remote must carry NO credential on every vendor, and the GitHub App token
the box holds must never reach dev.azure.com.
"""

TEST = "tests/test_the_box_clones_from_the_forge_it_was_told.py"
BOX = "openfactory/runtime/boxed_job.py"
LAUNCHER = "openfactory/runtime/fargate/launcher.py"
ACT = "openfactory/runtime/temporal/activities.py"
ENTRY = "tests/test_the_boxed_job_entrypoint.py"

MUTATIONS = [
    # ── the weld comes back ─────────────────────────────────────────────────────────────────────
    ("the URL is spelled here again — github.com whatever the forge", BOX,
     "    return clone_url_for(project, cfg.repo, token=token)",
     '    return f"https://x-access-token:{token}@github.com/{cfg.repo}.git"'),

    ("…and the tokenless half too", BOX,
     "        return build_forge(project).clone_url(cfg.repo, token=None)",
     '        return f"https://github.com/{cfg.repo}.git"'),

    # ── the two properties the port must keep ───────────────────────────────────────────────────
    ("the origin rewrite hands back the ADAPTER's credential — the agent can push", BOX,
     "        return build_forge(project).clone_url(cfg.repo, token=None)",
     "        return clone_url_for(project, cfg.repo, token=None)"),

    ("the caller's GitHub token is forced through, past the Azure row's refusal", BOX,
     "    return clone_url_for(project, cfg.repo, token=token)",
     "    return build_forge(project).clone_url(cfg.repo, token=token)"),

    # ── the coordinates ─────────────────────────────────────────────────────────────────────────
    ("the box stops reading the forge's coordinates", BOX,
     '        forge_options=_options(env.get("OPENFACTORY_FORGE_OPTIONS")),',
     "        forge_options={},"),

    ("the launcher stops sending them", LAUNCHER,
     '    if box.forge_options:\n'
     '        env["OPENFACTORY_FORGE_OPTIONS"] = json.dumps(box.forge_options, sort_keys=True)\n',
     ""),

    ("…and the reverse: an empty map becomes a variable saying nothing", LAUNCHER,
     "    if box.tracker_options:\n", "    if True:\n"),

    ("the worker builds a box with the kind and none of the coordinates", ACT,
     "        tracker_options=dict(project.tracker.options or {}),\n"
     "        forge_options=dict((project.forge.options if project.forge else None) or {}),\n"
     "        review=inp.review,", "        review=inp.review,"),

    ("the two axes share one map again — a Jira board on a GitHub forge", BOX,
     "        tracker=ProviderRef(kind=cfg.tracker_kind, repo=cfg.repo,\n"
     "                            options={**legacy, **cfg.tracker_options}),",
     "        tracker=ProviderRef(kind=cfg.tracker_kind, repo=cfg.repo,\n"
     "                            options={**legacy, **cfg.forge_options}),"),

    ("a box from an older worker loses its board", BOX,
     "options={**legacy, **cfg.tracker_options}),", "options=dict(cfg.tracker_options)),"),

    ("…and the reverse: a stale legacy pair overrides the map that contains it", BOX,
     "options={**legacy, **cfg.tracker_options}),",
     "options={**cfg.tracker_options, **legacy}),"),

    # ── the malformed map ───────────────────────────────────────────────────────────────────────
    ("a malformed options map loses the whole run", BOX,
     "    except ValueError:\n"
     '        print(f"OPENFACTORY_WARN: could not read provider options ({raw[:60]!r}) — '
     'continuing "\n              f"without them", flush=True)\n        return {}',
     "    except KeyError:\n        return {}"),

    ("…and the reverse: it is swallowed with nothing said", BOX,
     '        print(f"OPENFACTORY_WARN: could not read provider options ({raw[:60]!r}) — '
     'continuing "\n              f"without them", flush=True)\n', ""),

    # ── reachability ────────────────────────────────────────────────────────────────────────────
    ("`_clone` spells the URL by hand and the port is decoration", BOX,
     '["git", "clone", "--no-single-branch", clone_url(cfg, token=token), str(dest)],',
     '["git", "clone", "--no-single-branch",\n'
     '         f"https://x-access-token:{token}@github.com/{cfg.repo}.git", str(dest)],'),

    ("the origin reset is dropped — the agent keeps a credentialed remote", BOX,
     '            ["git", "-C", str(dest), "remote", "set-url", "origin", '
     'clone_url(cfg, token=None)],',
     '            ["git", "-C", str(dest), "remote", "-v"],', ENTRY),
]
