"""#163: a deployment-varying value has one home, read at call time, and absence is loud."""

TEST = "tests/test_the_second_deployment_is_not_the_first.py"
CONN = "openfactory/runtime/temporal/connection.py"
VIEW = "openfactory/runtime/temporal/view.py"
APP = "openfactory/api/app.py"
LAUNCHER = "openfactory/runtime/fargate/launcher.py"
DYNAMO = "openfactory/observability/dynamo.py"
ENV = "openfactory/environ.py"

BARRIER = "tests/test_the_suite_cannot_reach_a_live_engine.py"
FARGATE = "tests/test_fargate_launcher.py"
PANEL = "tests/test_the_panel_touches_no_cloud_locally.py"

MUTATIONS = [
    # ── the engine ───────────────────────────────────────────────────────────────────────────────
    ("the undeclared engine silently becomes a local one again", CONN,
     '    raise EngineNotDeclared(', '    return LOCAL_DEV_ADDRESS\n    raise EngineNotDeclared(',
     BARRIER),

    ("…and the panel re-derives the same question with its own default", VIEW,
     "    return connection.address(), connection.namespace()",
     '    import os as _os\n'
     '    return (_os.environ.get("TEMPORAL_ENDPOINT")\n'
     '            or _os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),\n'
     '            _os.environ.get("TEMPORAL_NAMESPACE", "default"))'),

    ("the newer Cloud endpoint form is unrecognised again", VIEW,
     '_CLOUD_HOSTS = ("tmprl.cloud", "api.temporal.io")',
     '_CLOUD_HOSTS = ("tmprl.cloud",)'),

    ("an undeclared engine 500s the route instead of answering 503", APP,
     "    try:\n        return _temporal()\n    except RuntimeError as exc:\n"
     "        raise HTTPException(status_code=503, detail=str(exc)[:300]) from exc",
     "    return _temporal()"),

    # ── the region ───────────────────────────────────────────────────────────────────────────────
    ("a cloud call falls back to the first deployment's region", ENV,
     '    if not required:\n        return ""',
     '    if True:\n        return "eu-west-2"'),

    ("the Fargate config stops requiring a region", LAUNCHER,
     '                    "AWS_DEFAULT_REGION")', '                    )', FARGATE),
    # the literal returning as a default is caught by the package-wide scan, not by the launcher's
    # own guard: with the `missing` check intact the fallback is unreachable code that still
    # carries somebody else's account.

    ("…and takes one back as a default", LAUNCHER,
     '        region=e["AWS_DEFAULT_REGION"],',
     '        region=e.get("AWS_DEFAULT_REGION", "eu-west-2"),'),

    ("the metrics store reads whatever region it likes", DYNAMO,
     "            region = self.region or environ.cloud_region(required=True)",
     '            region = self.region or "eu-west-2"'),

    ("the panel invents a console for a deployment with no cloud", APP,
     '    console = f"https://{region}.console.aws.amazon.com" if region else ""',
     '    console = f"https://{region or \'eu-west-2\'}.console.aws.amazon.com"'),

    # ── the parameter tree ───────────────────────────────────────────────────────────────────────
    ("the panel reads the first deployment's SSM tree again", APP,
     '        return token_pool_from_ssm(f"{prefix}/agent-tokens", region)',
     '        return token_pool_from_ssm("/openfactory/agent-tokens", region)'),

    ("…and asks SSM even when nobody said where the tree is", APP,
     "    if not _boxes_are_remote() or not prefix or not region:",
     "    if not _boxes_are_remote():", PANEL),

    ("the prefix var loses its trailing-slash discipline", ENV,
     '    return (os.environ.get(SSM_PREFIX_VAR) or "").strip().rstrip("/")',
     '    return os.environ.get(SSM_PREFIX_VAR) or ""'),
]
