"""#260: the suite a contributor runs neither writes their registry nor fails for a missing tool.

The first three rows take away the conftest's registry of its own — per test, before collection,
and both at once — and each must turn the registry guard red. The last puts back the defect the
installer file had: a test that runs install.sh without the skip that names its tools.
"""

TEST = "tests/test_the_suite_never_writes_the_registry_your_shell_names.py"
CONFTEST = "tests/conftest.py"
INSTALLER_TESTS = "tests/test_the_installer_builds_the_commands_it_says_it_does.py"

MUTATIONS = [
    ("a test no longer gets a registry of its own", CONFTEST,
     '    monkeypatch.setenv(REGISTRY_VARIABLE,\n'
     '                       str(tmp_path_factory.getbasetemp() / "registries" / own / "registry.yaml"))',
     "    assert own"),

    ("nothing names a registry before collection", CONFTEST,
     '    os.environ[REGISTRY_VARIABLE] = str(home / "registry.yaml")',
     "    assert home"),

    ("both halves name a variable the registry does not read", CONFTEST,
     'REGISTRY_VARIABLE = "OPENFACTORY_REGISTRY"',
     'REGISTRY_VARIABLE = "OPENFACTORY_REGISTRY_NOBODY_READS"'),

    ("the forced re-install runs the installer again without the skip that names its tools",
     INSTALLER_TESTS,
     "@needs_a_posix_shell\ndef test_a_forced_reinstall_states_the_runtime_too(tmp_path):",
     "def test_a_forced_reinstall_states_the_runtime_too(tmp_path):",
     INSTALLER_TESTS
     + "::test_every_test_that_drives_the_installer_skips_where_its_tools_are_missing"),
]
