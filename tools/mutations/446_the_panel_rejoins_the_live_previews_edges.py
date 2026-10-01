"""A recreated panel is put back on every live preview's edge network, and a panel off one says so
instead of blaming the application (#446)."""

COMPOSE = "openfactory/adapters/preview/compose.py"
STEPS = "openfactory/preview/steps.py"
APP = "openfactory/api/app.py"
TEST = "tests/test_the_compose_row_runs_what_was_admitted.py"
WATCH = "tests/test_a_preview_is_started_on_demand.py"
PAGE = "tests/test_a_card_can_be_previewed.py"

MUTATIONS = [
    ("a look at a running unit never puts the panel back on its network", STEPS,
     "        _keep_the_panel_on(runtime, cp)\n        return RUNNING\n",
     "        return RUNNING\n", WATCH),
    ("the row joins nothing, as if the panel were always on the edge", COMPOSE,
     "        return self._connect_panel(edge_of(compose_project), _base_env(work_root()))\n",
     '        return ""\n'),
    ("a panel already on the edge is read as a failure", COMPOSE,
     '        if joined.rc and "already exists" not in f"{joined.out}{joined.err}":\n'
     '            return (f"the panel container `{self.panel_container}` could not join `{edge}`: "\n'
     '                    f"{joined.said}")\n'
     '        return ""\n\n    def join_panel',
     '        if joined.rc:\n'
     '            return (f"the panel container `{self.panel_container}` could not join `{edge}`: "\n'
     '                    f"{joined.said}")\n'
     '        return ""\n\n    def join_panel'),
    ("the loopback reach tries to join an edge it does not have", COMPOSE,
     '        if self.reach != "network" or not self.panel_container:\n            return ""\n'
     '        return self._connect_panel(',
     '        if not self.panel_container:\n            return ""\n'
     '        return self._connect_panel('),
    ("a join that failed is swallowed without a word", STEPS,
     '    if problem:\n        log.warning("OPENFACTORY_PREVIEW_PANEL_OFF_THE_EDGE %s — %s", '
     'compose_project, problem)\n',
     "    del problem\n", WATCH),
    ("the page blames the application for the panel's absence again", APP,
     "            if not await asyncio.to_thread(_resolves, upstream_base):\n",
     "            if False:\n", PAGE),
    ("any lookup error is read as a missing network", APP,
     "    except socket.gaierror:\n        return False\n    except OSError:\n        return True\n",
     "    except OSError:\n        return False\n", PAGE),
]
