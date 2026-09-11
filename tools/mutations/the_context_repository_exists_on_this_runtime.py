"""ADR-0049 slice 7 (follow-up), proven by breaking it — the context repository exists.

THREE CLAIMS:

  1. **It is made AND seeded** at registration on this runtime: an empty bare repository fails a
     checkout of its base branch exactly as a missing one does.
  2. **Both ends declare the pair** — the registry names the documentation repository and the
     source repository's manifest names it back.
  3. **Only here, and never at the cost of the registration.** A hosted row is left alone, because
     making a repository in somebody's organisation is an operator's decision; and a failure to
     seed is said out loud without losing the project that was already registered.

The guard under test is `tests/test_the_context_repository_exists_on_this_runtime.py`.
"""

TEST = "tests/test_the_context_repository_exists_on_this_runtime.py"

CLI = "openfactory/cli.py"

MUTATIONS = [
    ("nothing is created, so the module the platform switched on has nowhere to read", CLI,
     '        if kind == "local":\n            _seed_the_context_repository(name)\n', "", TEST),

    ("the repository is created and left EMPTY — a checkout of `main` fails as before", CLI,
     '            git("push", "-q", "origin", "HEAD:main")', "            pass", TEST),

    ("the seed says nothing about which product it is for", CLI,
     '            seed.write_text(f"product: {name}\\nsources:\\n  - {name}\\n"',
     '            seed.write_text(f"sources:\\n  - {name}\\n"', TEST),

    ("the source repository stops naming the context back, and the pair is half-declared", CLI,
     '                    scaffold += f"docs_repo: {name}-context\\n"',
     '                    scaffold += ""', TEST),

    ("a hosted project has a repository made in somebody's organisation without being asked", CLI,
     '        if kind == "local":\n            _seed_the_context_repository(name)',
     '        if True:\n            _seed_the_context_repository(name)', TEST),

    ("a failure to seed takes the registration down with it", CLI,
     '    except Exception as exc:  # noqa: BLE001 — the project is registered; this is the extra\n'
     '        log.warning("could not seed the context repository for %s (%s)", name, str(exc)[:200])',
     '    except ValueError as exc:\n'
     '        log.warning("could not seed the context repository for %s (%s)", name, str(exc)[:200])',
     TEST),

    ("the failure is silent, so the module is off and the reason is an hour away", CLI,
     '        typer.echo(f"\u00b7 the product role\'s context repository could not be created '
     '({exc}) \u2014 "',
     '        _ = (', TEST),
]
