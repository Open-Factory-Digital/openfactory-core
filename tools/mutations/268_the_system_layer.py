"""The system layer (#268 slice 2, ADR-0052 D17): every guard it claims, cut one at a time.

WHAT THE ROWS BREAK, in the order the acceptance states it:

  ROWS 1-5    NO READ LEAVES THE TREE — a link read as a file, a path through a linked directory,
              a linked directory or file out of the tree not named, a NUL byte handed to the kernel.
  ROWS 6-11   NO SECRET VALUE REACHES THE MAP — a host that keeps the whole value, an environment
              that keeps values, Terraform reading a password, a `$ref`'s URL copied into a note,
              a server's user part kept, an env file said as nothing.
  ROWS 12-16  NOTHING IS RUN, AND A HOSTILE FILE COSTS ITSELF — Alembic's `downgrade()` applied,
              the per-file guard narrowed so one file's surprise stops the map, a manifest's number
              where a list belongs read as a list, SQL split inside a function body, a `.down.sql`
              applied.
  ROWS 17-33  THE MAP — the AsyncAPI 2 inversion, the owner rules, the join by name (a Service's
              selector, `svc.ns`, a source that could not be read), the kind of a link, a
              database's instance and its users, the order migrations apply, and each thing the
              fixture says it could not derive.
  ROWS 34-35  EVERY ENTRY CITED — the commit on every citation, the CLI's own commit.
  ROWS 36-43  PUBLISHED LIKE DERIVED KNOWLEDGE — the product's semaphore around the push, the
              convergence on a key that ignores commits, the publisher refusing a link in the
              context repository, `publish_bundle`'s bool, the refresh that runs it, the role
              told where the map is.
  ROWS 44-47  CHECKED OUT AS THE ROLE MOUNTS (after the rebase onto #268 slice 1) — partial and
              sparse, under keys of the layer's own, what the cone left out carried to the map,
              and the map of what the product declares rather than of the role's boundary.

NOT A ROW: LINEAR TIME. `test_pathological_text_is_read_in_linear_time` holds that no file makes
a reader quadratic, and a row cutting it either hangs (bodies unbounded: measured past 600 s on
that test's input, and this runner has no timeout) or lands within a few seconds of the test's
bound (line numbers recounted from the start: 11 s against 2 s), which is a coin toss rather than
a proof. The guard stands as a test; it is not claimed here.
"""

TEST = "tests/test_the_system_layer.py"
PUBLISHED = "tests/test_the_system_layer_is_published.py"

MUTATIONS = [
    # ── no read leaves the tree ────────────────────────────────────────────────────────────────
    # SURVIVED THE PLAN'S ONE RUN (2026-09-24), and the label it had then was wrong: it claimed the
    # recorder would see an `os.open` outside the source. It cannot — the real-path check and the
    # regular-file check behind this one still refuse a link, so what the cut changes is the REASON
    # a reader is given ("outside the tree", "not a regular file" for a link inside it). The tests
    # now hold the reason: `test_read_text_refuses_every_way_out` and the symlink test.
    ("a link is not refused as a link, and the reason a reader is given names something else",
     "openfactory/knowledge/system/tree.py",
     '    if stat.S_ISLNK(st.st_mode):\n'
     '        return Read(None, "is a link, and a link is never followed")\n',
     ""),

    ("a path through a linked directory is read — `inner/up/secret.txt` opens the file above",
     "openfactory/knowledge/system/tree.py",
     "    if not inside(real_root, os.path.realpath(full)):\n"
     "        return Read(None, \"is outside the repository's tree\")\n"
     "    if not stat.S_ISREG(st.st_mode):\n",
     "    if not stat.S_ISREG(st.st_mode):\n"),

    ("a linked directory out of the tree is skipped in silence instead of named as not followed",
     "openfactory/knowledge/system/tree.py",
     "            if os.path.islink(full):\n"
     "                if not inside(real_root, os.path.realpath(full)):\n"
     "                    out.links_out.append(rel(full))\n"
     "                continue\n"
     "            if name.lower() in PRUNED:\n",
     "            if os.path.islink(full):\n"
     "                continue\n"
     "            if name.lower() in PRUNED:\n"),

    ("a linked file out of the tree is skipped in silence instead of named as not followed",
     "openfactory/knowledge/system/tree.py",
     "            if stat.S_ISLNK(mode):\n"
     "                if not inside(real_root, os.path.realpath(full)):\n"
     "                    out.links_out.append(rel(full))\n"
     "                continue\n",
     "            if stat.S_ISLNK(mode):\n"
     "                continue\n"),

    ("a NUL byte in a path a document hands in reaches `os.lstat`, which raises",
     "openfactory/knowledge/system/tree.py",
     '    if "\\x00" in rel:\n'
     '        return Read(None, "is not a path (it holds a NUL byte)")\n',
     ""),

    # ── no secret value reaches the map ─────────────────────────────────────────────────────────
    ("an address keeps the whole value as its host — the password in a URL reaches a note",
     "openfactory/knowledge/system/deployments.py",
     "    return HostRef(name=name, scheme=scheme, host=host)",
     "    return HostRef(name=name, scheme=scheme, host=text.lower())"),

    ("a component's environment keeps each value beside its name",
     "openfactory/knowledge/system/deployments.py",
     "        target.env.append(name)",
     '        target.env.append(f"{name}={value}")'),

    # SURVIVED THE PLAN'S ONE RUN: the planted file wrote `identifier` before `password`, and the
    # reader takes the first matching LINE, so the cut never reached the password. The planted
    # file now writes the password first.
    ("Terraform's `password` is read as a resource's name",
     "openfactory/knowledge/system/deployments.py",
     '_TF_NAME_KEYS = ("name", "identifier",',
     '_TF_NAME_KEYS = ("password", "name", "identifier",'),

    ("a `$ref` to a URL copies the URL — and its user part — into the note",
     "openfactory/knowledge/system/interfaces.py",
     '                                        detail=f"{what} is described in a document outside '
     'this "',
     '                                        detail=f"{ref} — {what} is described in a document '
     'outside this "'),

    ("a server URL's user part is not dropped, so `svc:token@api` names `svc` and loses `api`",
     "openfactory/knowledge/system/interfaces.py",
     '    text = text.rsplit("@", 1)[-1]           # a userinfo part is dropped before anything '
     'is kept',
     "    text = text"),

    ("an env file is passed over in silence instead of said as not read",
     "openfactory/knowledge/system/deployments.py",
     "        if env_file:",
     "        if False:"),

    # ── nothing is run, and a hostile file costs itself ─────────────────────────────────────────
    ("Alembic's `downgrade()` is applied instead of its `upgrade()`",
     "openfactory/knowledge/system/schemas.py",
     '                    and n.name == "upgrade"), None)',
     '                    and n.name == "downgrade"), None)'),

    ("the per-file guard is narrowed, so one file a reader did not foresee stops the whole map",
     "openfactory/knowledge/system/derive.py",
     "        except Exception as exc:  # noqa: BLE001 — one file's surprise must not cost every "
     "source",
     "        except KeyboardInterrupt as exc:  # noqa: BLE001"),

    ("a manifest's number where a list belongs is iterated, and the file's workloads are lost",
     "openfactory/knowledge/system/deployments.py",
     "    return value if isinstance(value, list) else []",
     "    return value or []"),

    ("SQL is split inside a dollar-quoted body, so a function's `CREATE TABLE` becomes a table",
     "openfactory/knowledge/system/schemas.py",
     '        if ch == "$" and (m := _DOLLAR.match(text, i)):',
     '        if False and (m := _DOLLAR.match(text, i)):'),

    ("a golang-migrate `.down.sql` is applied, and the fixture's tables are dropped again",
     "openfactory/knowledge/system/schemas.py",
     '        if (m := _GOLANG_MIGRATE.match(name)) and m.group("dir").lower() == "down":',
     '        if (m := _GOLANG_MIGRATE.match(name)) and m.group("dir").lower() == "sideways":'),

    # ── the map ─────────────────────────────────────────────────────────────────────────────────
    ("AsyncAPI 2's `subscribe` is read as English — every event arrow drawn backwards",
     "openfactory/knowledge/system/interfaces.py",
     '        for key, action in (("subscribe", "send"), ("publish", "receive")):',
     '        for key, action in (("subscribe", "receive"), ("publish", "send")):'),

    ("the `servers` owner rule is gone — orders' API and a client copy land on the wrong owner",
     "openfactory/knowledge/system/derive.py",
     "        if len(targets) == 1:\n"
     '            return targets.pop(), "servers"\n',
     "        if False:\n"
     '            return targets.pop(), "servers"\n'),

    ("a description two components share is placed on the repository without a word",
     "openfactory/knowledge/system/derive.py",
     "        if shared:\n",
     "        if False:\n"),

    ("a Kubernetes Service selects no workload by its labels",
     "openfactory/knowledge/system/derive.py",
     "                        and all(c.labels.get(k) == v for k, v in svc.selector.items()))",
     "                        and False)"),

    ("`orders.shop` — a Service in its namespace — joins nothing",
     "openfactory/knowledge/system/derive.py",
     "        elif len(labels) == 2 and labels[0] in self.k8s_services:",
     "        elif False:"),

    ("a source that could not be read is not a source by name, so compose's build into it is "
     "reported as building from outside the product",
     "openfactory/knowledge/system/derive.py",
     '        self.leaves = {r.strip("/").rsplit("/", 1)[-1].lower(): r for r in missing}',
     "        self.leaves = {}",
     PUBLISHED),

    ("an address to a component that serves only gRPC is read as `network`",
     "openfactory/knowledge/system/derive.py",
     "        if serves_grpc and not serves_http:\n"
     '            return "grpc"\n',
     ""),

    ("a migration set is never joined to the instance its owner addresses",
     "openfactory/knowledge/system/derive.py",
     "        if len(instances) == 1:\n",
     "        if False:\n"),

    ("a component that connects to a database is not listed among its users",
     "openfactory/knowledge/system/derive.py",
     "            if link.from_ not in db.owners and link.from_ not in db.users:",
     "            if False:"),

    ("migrations are ordered as text — `V10__` before `V2__`",
     "openfactory/knowledge/system/schemas.py",
     '    return tuple(int(p) if p.isdigit() else p.lower() for p in re.split(r"(\\d+)", name))',
     "    return (name.lower(),)"),

    ("Alembic revisions are applied in file-name order instead of the chain",
     "openfactory/knowledge/system/derive.py",
     "        order, linear = schemas.alembic_order(parsed)",
     "        order, linear = sorted(parsed), True"),

    ("an event received and sent by nobody is not said",
     "openfactory/knowledge/system/derive.py",
     "        if event.consumers and not event.producers:",
     "        if False:"),

    ("a host no source declares is not said",
     "openfactory/knowledge/system/derive.py",
     '            elif "." not in ref.host and not re.fullmatch(r"[\\d.]+", ref.host):',
     "            elif False:"),

    ("an address taken from the environment at start (`${…}`, a bare name) is not said",
     "openfactory/knowledge/system/deployments.py",
     '        elif address_name(name) and (value is None or "$" in str(value)):',
     "        elif False:"),

    ("an address taken from a Kubernetes secret is not said",
     "openfactory/knowledge/system/deployments.py",
     '                            d.unresolved.append((vname, "secret"))',
     "                            pass"),

    ("a Helm chart is passed over in silence",
     "openfactory/knowledge/system/derive.py",
     "    for chart in sorted(charts):",
     "    for chart in sorted(charts)[:0]:"),

    ("a migration set's owner is never asked, so its schema joins no component and no instance",
     "openfactory/knowledge/system/derive.py",
     '        owner, _ = j.owner_of(cite.repo, cite.path, cite=cite)\n'
     '        migrated.append((owner, mset, schema, engine, cite))',
     '        owner, _ = "nobody", ""\n'
     '        migrated.append((owner, mset, schema, engine, cite))'),

    # ── every entry cited ───────────────────────────────────────────────────────────────────────
    ("every citation of a source loses its commit",
     "openfactory/knowledge/system/derive.py",
     "        return Cite(repo=repo, path=rel, commit=tree.commit, line=line)",
     '        return Cite(repo=repo, path=rel, commit="", line=line)'),

    ("the CLI cites no commit for a checkout that has one",
     "openfactory/cli.py",
     '        commit = _git_head(path) if (path / ".git").exists() else ""',
     '        commit = ""'),

    # ── published like derived knowledge ────────────────────────────────────────────────────────
    ("the push happens without the product's semaphore",
     "openfactory/knowledge/system/refresh.py",
     "            with semaphore.held(project, timeout=timeout):",
     "            with tempfile.TemporaryDirectory():",
     PUBLISHED),

    # RE-PINNED 2026-09-24 (#268 slice 3): the refresh publishes the flows beside the map, so the
    # comparison is kept as whether the map moved, and each publishes only what moved
    ("the published key is never compared, so every refresh commits a new clock",
     "openfactory/knowledge/system/refresh.py",
     '    moved = read_derived_key(ctx.docs_path, f"{system_subpath().as_posix()}/{SYSTEM_FILE}") '
     '!= key',
     "    moved = True",
     PUBLISHED),

    ("the derived key counts the commit, so a commit that changed nothing republishes the map",
     "openfactory/knowledge/system/render.py",
     '            return {k: ("" if k == "commit" else blank(v)) for k, v in node.items()}',
     '            return {k: ("" if k == "never" else blank(v)) for k, v in node.items()}'),

    ("the publisher writes through a link in the context repository",
     "openfactory/knowledge/pipeline.py",
     "    if not _within_clone(pub, subpath):",
     "    if False:",
     PUBLISHED),

    # SURVIVED THE PLAN'S ONE RUN: every test reached `publish_bundle` behind `write_bundle`'s own
    # no-change guard, so nothing asked it for its bool on an unchanged tree.
    # `test_publishing_the_map_the_branch_already_holds_answers_false_and_commits_nothing` does.
    ("`publish_bundle` answers True for a tree that already held the map",
     "openfactory/knowledge/pipeline.py",
     '                       what=f"module map @ {stamp}") == PUBLISHED',
     '                       what=f"module map @ {stamp}") != FAILED',
     "tests/test_knowledge_pipeline.py"),

    ("the knowledge refresh never runs the system layer",
     "openfactory/runtime/temporal/activities.py",
     '        if outcome in ("off", "no-context"):',
     "        if outcome:",
     PUBLISHED),

    ("the role is never told where the system map is",
     "openfactory/product/role.py",
     # re-pinned onto the rebase over #268 slice 1 and #267's briefing, where the facts section
     # takes whether the board is in the prompt
     "        parts += self._facts_section(board_in_prompt=board_in_prompt)\n"
     "        parts += self._system_section()\n",
     "        parts += self._facts_section(board_in_prompt=board_in_prompt)\n",
     PUBLISHED),

    ("`mounted` never reports the system map's door, even when it is on disk",
     "openfactory/product/module.py",
     "        if system.is_file():",
     "        if False:",
     PUBLISHED),

    # ── checked out as the role mounts: partial, sparse, its own keys (after the rebase) ─────────
    ("each source is cloned whole by the plain cache, not partially and sparsely",
     "openfactory/knowledge/system/refresh.py",
     "        cache = SparseRepoCache(root)\n",
     "        from openfactory.runtime.repo_cache import RepoCache\n"
     "        cache = RepoCache(root)\n"
     '        cache.failure, cache.left_out = "", []\n',
     PUBLISHED),

    ("the layer checks a source out under the role's own cache key",
     "openfactory/knowledge/system/refresh.py",
     '    return f"{project_name}-system--{flat}"',
     '    return f"{project_name}--source--{flat}"',
     PUBLISHED),

    ("what the cone left out is not carried to the map",
     "openfactory/knowledge/system/refresh.py",
     "                        left_out=got.left_out.get(repo, ()))",
     "                        left_out=())",
     PUBLISHED),

    ("the registry project's repository, left out of `sources:`, is published as a source that "
     "could not be read",
     "openfactory/knowledge/system/refresh.py",
     "    missing = {repo: why for repo, why in got.missing.items() if why != NOT_DECLARED}",
     "    missing = dict(got.missing)",
     PUBLISHED),
]
