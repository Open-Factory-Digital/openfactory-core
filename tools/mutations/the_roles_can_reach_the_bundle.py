"""The bundle reaches the PO and the tech-lead — and neither is told anything that is not true.

Two wirings, and the rows split along the line between them. The product role's context repository
is already mounted, so its half is about WHO decides that the bundle is really there (ROWS 1-4);
the tech-lead clones the source and has to fetch the bundle from the context repo, so its half is
about carrying it intact and about the difference between an absence and a failed read
(ROWS 5-15).

ROWS 1-2 ARE THE DEFECT THIS CHANGE WAS WRITTEN WITH AND THEN FOUND. `mounted`'s paths are
relative to the workspace root the AGENT stands in; the prompt is composed in the orchestrator's
process, which stands elsewhere. A `Path(docs) / ".okf"` check made where the prompt is built is
therefore answered by the worker's own cwd — False on every project that has a bundle — and the
section would have been dead everywhere while reading as fully wired. `module.py::mounted` is the
one place holding an absolute path, and it already makes exactly this promise about the source
code: what is mounted is what exists.

ROW 12 IS THE ONE THAT SEPARATES THIS FROM A CHEAPER DESIGN. `fetch_published_bundle` returned
`Path | None` and collapsed "nothing has ever been published" into "the context repository could
not be read". The first is every project before its first backfill and is worth no words to
anybody; the second is a failed read, and a tech-lead handed no `okf/` and told nothing resolves
it as "this codebase has no map" — a claim about the client's project produced by a clone that
never came back. That is the sentence `techlead/pack.py`'s manifest exists to prevent, one
artifact upstream of where it could still prevent it.
"""

TEST = "tests/test_the_roles_can_reach_the_bundle.py"

MUTATIONS = [
    ("the section is derived from the docs mount instead of the key that says the bundle is "
     "REALLY there, so every project is told to open an index that may not exist",
     "openfactory/product/role.py",
     '        where = self.mounted.get("okf") or ""',
     '        where = f"{self.mounted.get(\'docs\') or \'\'}/.okf"'),

    ("`mounted` announces the bundle whether or not the door is on disk — the promise that dict "
     "makes about the source code ('a prompt that describes what is mounted cannot lie'), broken "
     "one key along",
     "openfactory/product/module.py",
     "        if door.is_file():\n"
     '            out["okf"] = os.path.relpath(str(door.parent), root)',
     "        if True:\n"
     '            out["okf"] = os.path.relpath(str(door.parent), root)'),

    ("`mounted` never reports the bundle, so the section is dead on every project — the failure "
     "this codebase calls built-tested-reached-by-nothing, and the one the relative path would "
     "have produced in production while the suite stayed green",
     "openfactory/product/module.py",
     '        door = Path(root) / "docs" / OKF_DIRNAME / OKF_INDEX_FILE\n'
     "        if door.is_file():\n"
     '            out["okf"] = os.path.relpath(str(door.parent), root)\n',
     ""),

    ("the section is built and never joined to the prompt",
     "openfactory/product/role.py",
     "        parts += self._bundle_section()",
     "        parts += []"),

    ("the boundary goes unsaid — a concept becomes usable as an accepted requirement, which is "
     "how a bug gets frozen into a promise the factory then DEFENDS",
     "openfactory/product/role.py",
     '            "So: **never turn a concept into an accepted requirement**, and never tell '
     'anyone the "',
     '            "So: use the concepts freely when you write requirements. When a concept "',
     "tests/test_the_roles_can_reach_the_bundle.py"),

    ("the pack takes the index and leaves the concepts behind, handing the tech-lead an index "
     "whose every entry is a dead end — the index's links are relative",
     "openfactory/techlead/pack.py",
     '            shutil.copytree(Path(bundle), into / "okf", dirs_exist_ok=True)',
     '            (into / "okf").mkdir(parents=True, exist_ok=True)\n'
     '            shutil.copy2(Path(bundle) / "index.md", into / "okf" / "index.md")'),

    ("the bundle is copied in and not listed in the manifest — a fact the role never learns it "
     "has, which is the silence the manifest exists to end",
     "openfactory/techlead/pack.py",
     '            index = into / "okf" / "index.md"\n'
     '            written.append("okf/index.md" if index.is_file() else "okf/")',
     "            pass"),

    ("a bundle path that is not a directory takes the whole pack down with it, so a stale fetch "
     "costs the floor, the board and every verdict — and the prompt has already been shrunk",
     "openfactory/techlead/pack.py",
     "        if bundle is not None and Path(bundle).is_dir():",
     "        if bundle is not None:"),

    ("the fetched bundle never reaches `write_pack`, so the tech-lead is handed a pack that says "
     "nothing about the code it is being asked about",
     "openfactory/techlead/conversation.py",
     "                                bundle=bundle) if cloned else None",
     "                                bundle=None) if cloned else None"),

    ("the temp checkout the bundle arrived in is never discarded — one per question, on a path "
     "that runs once per chat message, until the worker's disk is full",
     "openfactory/techlead/conversation.py",
     "        discard_fetched_bundle(bundle)",
     "        pass"),

    ("a question with no checkout still pays for a clone of the context repository, for a file "
     "there is no pack to put it in",
     "openfactory/techlead/conversation.py",
     "    bundle, bundle_gaps = _bundle_for(project) if cloned else (None, [])",
     "    bundle, bundle_gaps = _bundle_for(project)"),

    ("the bundle's gap is collected and never rendered, so the manifest tells the model "
     "everything asked for was read",
     "openfactory/techlead/conversation.py",
     "                                diffs=_diff_files(jobs), gaps=_gaps(jobs) + bundle_gaps,",
     "                                diffs=_diff_files(jobs), gaps=_gaps(jobs),"),

    ("a read that FAILED is carried as an absence — the tech-lead is handed no bundle and told "
     "nothing, and answers that this codebase has no map",
     "openfactory/techlead/conversation.py",
     "    if got.unreadable:",
     "    if False:"),

    ("every empty fetch becomes a gap, so the warning appears on every project that has simply "
     "not been backfilled yet — and a warning on everything is one nobody reads",
     "openfactory/techlead/conversation.py",
     "    return got.path, []",
     "    return got.path, ([] if got.path is not None else [_BUNDLE_GAP])"),

    ("a project with no context repository still pays for the clone, on every question",
     "openfactory/techlead/conversation.py",
     "    if not docs_repo or not repo:",
     "    if not repo:"),

    ("the fetch asks for the `.okf/` ROOT rather than this source repository's own folder, so a "
     "multirepo product's tech-lead reads whichever bundle happens to be there (D-2)",
     "openfactory/techlead/conversation.py",
     "                           subpath=okf_subpath(repo))",
     '                           subpath=okf_subpath(""))'),

    ("the tokened URL a failed clone embeds is logged whole — truncation is not redaction, and "
     "the credential sits well inside the first 160 characters",
     "openfactory/techlead/conversation.py",
     '        log.warning("could not reach the knowledge bundle for %s: %s",\n'
     '                    getattr(project, "name", "?"),\n'
     '                    scrubbed(_URL_CREDENTIAL.sub(r"\\1***@", str(exc)), token))',
     '        log.warning("could not reach the knowledge bundle for %s: %s",\n'
     '                    getattr(project, "name", "?"),\n'
     '                    str(exc)[:160])'),

    ("a clone that never came back reports the same emptiness as a repository nobody has "
     "published to — the distinction cannot be recovered downstream, because by then the exit "
     "code is gone",
     "openfactory/knowledge/pipeline.py",
     '        return Fetched(None, "the context repository could not be read")',
     "        return Fetched(None)",
     "tests/test_knowledge_pipeline.py"),

    ("a subpath with nothing published in it is reported as unreadable, which puts a failed-read "
     "warning on every project until its first backfill",
     "openfactory/knowledge/pipeline.py",
     '        _log.info("knowledge: %s has no bundle yet — ignoring", subpath)\n'
     "        shutil.rmtree(tmp, ignore_errors=True)\n"
     "        return Fetched(None)",
     '        _log.info("knowledge: %s has no bundle yet — ignoring", subpath)\n'
     "        shutil.rmtree(tmp, ignore_errors=True)\n"
     '        return Fetched(None, "the context repository could not be read")',
     "tests/test_knowledge_pipeline.py"),
]
