"""#260: the suite a contributor runs neither writes their registry nor fails for a missing tool.

The first three rows take away the conftest's registry of its own — per test, before collection,
and both at once — and each must turn the registry guard red. The last puts back the defect the
installer file had: a test that runs install.sh without the skip that names its tools.
"""

TEST = "tests/test_the_suite_never_writes_the_registry_your_shell_names.py"
CONFTEST = "tests/conftest.py"
INSTALLER_TESTS = "tests/test_the_installer_builds_the_commands_it_says_it_does.py"
WORKDIR_TESTS = "tests/test_the_generated_environment_names_a_work_directory_that_needs_no_root.py"
E2E_TESTS = "tests/test_the_end_to_end_install_is_a_script_the_suite_can_run.py"

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

    ("the stubbed dry run borrows a host socket instead of one the test owns", INSTALLER_TESTS,
     '                 f"FAKE_SOCKET={socket_path}", "sh", str(INSTALLER), *args],',
     '                 "sh", str(INSTALLER), *args],',
     INSTALLER_TESTS + "::test_dry_run_writes_nothing_at_all"),

    ("a direct installer driver outside this module has no missing-tools skip", WORKDIR_TESTS,
     '@pytest.mark.skipif(any(shutil.which(tool) is None for tool in ("env", "sh", "stat", "id")),\n'
     '                    reason="the installer needs POSIX tools on this machine")\n',
     '',
     INSTALLER_TESTS + "::test_every_direct_installer_driver_in_the_suite_names_missing_tools"),

    ("Docker on PATH is mistaken for a daemon that answers", E2E_TESTS,
     '        return subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL,\n'
     '                              stderr=subprocess.DEVNULL, timeout=10, check=False).returncode == 0',
     '        return _HAS_DOCKER',
     E2E_TESTS + "::test_the_daemon_probe_checks_a_server_not_just_a_client"),
]
