"""#334: the suite's installer guard finds a driver written the way this repository writes one.

The first reader saw `subprocess.run` with the literal `"install.sh"` and nothing else: 0 of the
installer file's drivers, 1 in the tree. Each row takes back one thing the reader now follows — a
runner, a way of building an argv, a path constant, a helper, a fixture, a skip mark — and the
planted form, the real tree, or the two guards' agreement must go red. The last two rows take the
mark off a real driver that runs the script through `_a_forced_run_over`, which neither guard saw.
"""

TEST = "tests/test_the_installer_builds_the_commands_it_says_it_does.py"

FORMS = TEST + "::test_the_suite_guard_sees_a_driver_written_in_each_form_this_repository_uses"
NOT_DRIVERS = TEST + "::test_the_suite_guard_takes_nothing_but_a_started_script_for_a_driver"
MARKS = TEST + "::test_the_suite_guard_takes_a_skip_mark_in_each_form_it_is_written"
SUITE = TEST + "::test_every_direct_installer_driver_in_the_suite_names_missing_tools"
BOTH = TEST + "::test_both_guards_find_the_same_drivers_in_this_file"
LOCAL = TEST + "::test_every_test_that_drives_the_installer_skips_where_its_tools_are_missing"

MUTATIONS = [
    ("the reader knows `run` alone again, so check_output and Popen start nothing", TEST,
     '_STARTS_A_PROCESS = frozenset({"run", "call", "check_call", "check_output", "Popen"})',
     '_STARTS_A_PROCESS = frozenset({"run"})',
     FORMS),

    ("an argv built into a variable first is not followed", TEST,
     "    if isinstance(node, ast.Assign):\n"
     "        pairs = [(target, node.value) for target in node.targets]\n",
     "    if False:\n"
     "        pairs = []\n",
     FORMS),

    ("an argv grown with += is not followed", TEST,
     "    elif isinstance(node, ast.AugAssign):\n"
     "        pairs = [(node.target, node.value)]\n",
     "",
     FORMS),

    ("an argv grown with append is not followed", TEST,
     '            and node.func.attr in {"append", "extend", "insert"}):',
     "            and node.func.attr in set()):",
     FORMS),

    ("a path constant is not read as the path, and the tree's drivers fall to one", TEST,
     "            if name in paths:\n"
     "                found.add(_THE_SCRIPT)\n",
     "",
     SUITE),

    ("the shared module's path, read as an attribute, is not followed", TEST,
     "            if taken is None and attr in self.paths(home):\n"
     "                found.add(_THE_SCRIPT)\n",
     "",
     FORMS),

    ("a path imported by name is not followed", TEST,
     "                found.update(name for name, (home, attr) in self.bindings(module).items()\n"
     "                             if attr is not None and attr in self.paths(home))\n",
     "",
     FORMS),

    ("a helper that runs the script does not make its caller a driver", TEST,
     "                reached |= {_THE_SCRIPT} if runs else set()",
     "                reached |= set()",
     BOTH),

    ("a helper imported from another test module is not resolved", TEST,
     "            found = self.functions(home).get(attr) if attr else None\n",
     "            found = None\n",
     FORMS),

    ("a helper handed the script by position is not followed", TEST,
     "                        carried.append(arg)\n",
     "                        pass\n",
     FORMS),

    ("a helper handed the script by name is not followed", TEST,
     "                carried += [kw.value for kw in call.keywords if kw.arg in handed]",
     "                carried += []",
     FORMS),

    ("a fixture the test takes is not followed", TEST,
     '        if fn.name.startswith("test_") or _is_a_fixture(fn):\n'
     "            reached |= {_THE_SCRIPT for name in parameters",
     "        if False:\n"
     "            reached |= {_THE_SCRIPT for name in parameters",
     FORMS),

    ("a fixture from conftest is not looked up", TEST,
     '        for home in (module, "conftest"):',
     "        for home in (module,):",
     FORMS),

    ("a string that only ends like the script's name is taken for its path", TEST,
     '    return isinstance(value, str) and (value == "install.sh" or value.endswith("/install.sh"))',
     '    return isinstance(value, str) and value.endswith("install.sh")',
     NOT_DRIVERS),

    ("a helper that runs whatever it is handed is taken to run the installer", TEST,
     "                reached |= {_THE_SCRIPT} if runs else set()",
     "                reached |= {_THE_SCRIPT} if runs or handed else set()",
     NOT_DRIVERS),

    ("a skip mark bound to a name is no mark, so every driver in the installer file is unmarked",
     TEST,
     "            where = (module, mark.id) if mark.id in here else self.bindings(module).get(mark.id)",
     "            where = None",
     SUITE),

    ("a skip mark imported from another module is no mark", TEST,
     "            where = (module, mark.id) if mark.id in here else self.bindings(module).get(mark.id)",
     "            where = (module, mark.id) if mark.id in here else None",
     MARKS),

    ("a module's pytestmark is no mark on its tests", TEST,
     "                        for mark in (*fn.decorator_list, *module_marks))",
     "                        for mark in fn.decorator_list)",
     MARKS),

    ("any mark is taken for a skip", TEST,
     '            return getattr(mark.func, "attr", None) == "skipif"',
     "            return True",
     MARKS),

    ("the module guard lists its helpers again instead of following them", TEST,
     "               and _drives_the_installer(helper, followed) for helper in helpers)",
     '               and helper.__name__ == "_run_installer" for helper in helpers)',
     BOTH),

    ("a test that runs the script through `_a_forced_run_over` loses its skip (the suite guard)",
     TEST,
     "@needs_a_posix_shell\n"
     "def test_an_upgrade_moves_the_pin_to_the_release_it_installs(tmp_path):",
     "def test_an_upgrade_moves_the_pin_to_the_release_it_installs(tmp_path):",
     SUITE),

    ("a test that runs the script through `_a_forced_run_over` loses its skip (the module guard)",
     TEST,
     "@needs_a_posix_shell\n"
     "def test_a_kept_value_loses_only_its_surrounding_pair_of_quotes(tmp_path):",
     "def test_a_kept_value_loses_only_its_surrounding_pair_of_quotes(tmp_path):",
     LOCAL),
]
