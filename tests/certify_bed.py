"""A deployment for `openfactory certify` to read, with REAL-LOOKING names everywhere a pack must
not carry them (#356).

WHY REAL-LOOKING. A redaction guard fed `acme` and `demo` proves the redactor replaces `acme` and
`demo`. The names below are shaped like a customer's — a Brazilian payroll company's organisation,
two repositories, people with dotted logins, an enterprise forge host, a staging URL, a GitHub
token, a scanner token named after the customer, an App key — and every one of them is planted
where the platform really reads it: the registry, the manifests, the approver store, the
environment, the doctor's own words, the preflight's, the box proof's advisory output.

NOTHING HERE READS THIS MACHINE. The doctor and the preflight run on pinned probes, docker answers
a fixed digest, the foreign repository's checkout is a local directory, and the working directory
is a temporary one holding a `.env.compose` at mode 0600 outside any git repository.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ORG = "castello-tributos"
FOLHA = f"{ORG}/folha-pagamento"
PORTAL = f"{ORG}/portal-cliente"
WEB = f"{ORG}/folha-web"
SUPPORT = f"{ORG}/fabrica-suporte"
PROJECT = "castello-folha"
OTHER = "castello-portal"

#: Token-shaped values, each matching the floor's credential scan or named as a credential.
GH_TOKEN = "ghp_" + "Cx7q" * 9
SONAR = "squ_4f1c2b8e9d7a6c5b4a3f2e1d0c9b8a7f6e5d4c3b"
PANEL = "s3cret-castello-9f8e7d:mariana.souza:Mariana Souza"
APP_KEY = ("-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEAcastelloOnlyForTests0123456789\n"
           "-----END RSA PRIVATE KEY-----\n")
APP_INSTALLATION = "55512345"

PRACTITIONER = "Helena Prado"

#: Everything a pack must never carry, compared case-insensitively against every file. The
#: practitioner is NOT here: she is the one name a pack keeps.
FORBIDDEN = (
    "castello", "tributos", "folha-pagamento", "portal-cliente", "folha-web", "fabrica-suporte",
    "mariana", "souza", "joao.pereira", "rafaela", "beatriz", "U07CASTELLO", "ghe.", ".com.br",
    "https://", "mariana.souza@", GH_TOKEN, SONAR, "s3cret", "BEGIN RSA PRIVATE KEY",
    APP_INSTALLATION, "src/pagamentos", "Lucia Andrade",
)


def _manifest(**extra) -> str:
    data = {"version": 1, "merge_policy": "human", "review_mode": "advisory",
            "validate": {"test": "pytest -q"}}
    data.update(extra)
    return yaml.safe_dump(data, sort_keys=False)


def build(tmp_path: Path, monkeypatch) -> Path:
    """The deployment, wired; returns the directory certify runs in."""
    import openfactory.box_prove as bp
    from openfactory import approvals, doctor, preflight
    from tests.pinned_probes import a_fully_pinned_probe_set

    people = tmp_path / "mariana.souza" / "src"
    folha, portal, web = people / "folha-pagamento", people / "portal-cliente", people / "folha-web"
    (folha / ".openfactory").mkdir(parents=True)
    (folha / ".openfactory" / "project.yaml").write_text(_manifest(
        reviewers=["beatriz.costa"],
        components={"pagamentos": {"path": "src/pagamentos/**", "stack": "python",
                                   "risk": "high"}},
        post_merge_deploy={"workflow": "deploy.yml", "url": "https://staging.castello.com.br"},
        environments={"prod": {"health_url": "https://folha.castello.com.br/health",
                               "deploy_ref": "production"}},
        promote=["prod"], prod_approvers=["joao.pereira"]))
    (portal / ".openfactory").mkdir(parents=True)
    (portal / ".openfactory" / "project.yaml").write_text(_manifest())
    (web / ".openfactory").mkdir(parents=True)
    (web / ".openfactory" / "project.yaml").write_text(_manifest(merge_policy="auto"))

    registry = {"projects": {
        PROJECT: {
            "name": PROJECT, "repo_path": str(folha),
            "tracker": {"kind": "github", "repo": FOLHA,
                        "options": {"board_owner": ORG, "board_number": "3"}},
            "people": {"mariana.souza": "U07CASTELLO"},
            "admins": ["joao.pereira"],
            "box": {"env": ["CASTELLO_SONAR_TOKEN"]},
            "factory_board": {"tracker": {"kind": "github", "repo": SUPPORT},
                              "supervisor": "rafaela.lima"},
        },
        OTHER: {"name": OTHER, "repo_path": str(portal),
                "tracker": {"kind": "github", "repo": PORTAL}},
    }}
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(registry))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(path))

    for name, value in {"OPENFACTORY_BOT_TOKEN": GH_TOKEN, "OPENFACTORY_PANEL_TOKENS": PANEL,
                        "CASTELLO_SONAR_TOKEN": SONAR, "OPENFACTORY_BOT_NAME": "Castello Bot",
                        "OPENFACTORY_GH_APP_ID": "918273",
                        "OPENFACTORY_GH_APP_INSTALLATION_ID": APP_INSTALLATION,
                        "OPENFACTORY_GH_APP_KEY_CONTENT": APP_KEY}.items():
        monkeypatch.setenv(name, value)
    approvals.add_approver("joao.pereira", "a long enough password")

    # THE BOX PROOFS: the default repository's, with an advisory whose output quotes a path in
    # the customer's tree and a person, and a FOREIGN repository's, under its own key.
    proofs = tmp_path / "proofs"
    monkeypatch.setattr(bp, "PROOF_DIR", proofs)
    digest = "sha256:" + "a" * 64
    monkeypatch.setattr(bp, "_current_digest", lambda img: digest)
    monkeypatch.setattr(bp, "_toolchain_of", lambda img: "")

    import openfactory.factory as factory

    real_resolve = factory.resolve_repo_path

    def resolve(project, **kw):
        here = Path(str(getattr(project, "repo_path", "")))
        return here if here.is_dir() else (web if "folha-web" in str(here) else
                                           real_resolve(project, **kw))
    monkeypatch.setattr(factory, "resolve_repo_path", resolve)

    from openfactory.loader import load_manifest
    from openfactory.orchestrator.validation import gate_commands
    from openfactory.registry import ProjectRegistry

    def commands(project, root):
        m = load_manifest(project, repo_root=root)
        return bp._hash_commands(list(m.setup), gate_commands(m.validation),
                                 bp.component_gates(m))

    row = ProjectRegistry().get(PROJECT)
    bp.save(bp.Proof(project=PROJECT, image="registry.castello.com.br/castello-tributos/box:2",
                     ok=True, digest=digest, commands_hash=commands(row, folha),
                     toolchain="python=Python 3.12.5", at="2026-10-01T09:00:00Z",
                     findings=[bp.Finding("validate", False,
                                          "security: secret in src/pagamentos/folha.py:12 by "
                                          "mariana.souza", advisory=True)]), root=proofs)
    bp.save(bp.Proof(project=f"{PROJECT}--{ORG}--folha-web", image="openfactory-python:sandbox",
                     ok=True, digest="sha256:" + "b" * 64, commands_hash=commands(row, web),
                     at="2026-10-02T09:00:00Z", findings=[]), root=proofs)

    # THE DOCTOR AND THE PREFLIGHT, speaking the names the way a real failure would.
    said = (f"https://ghe.castello.com.br/api/v3/repos/{FOLHA} answered 401 to {GH_TOKEN} for "
            f"mariana.souza@castello.com.br (installation {APP_INSTALLATION})")
    monkeypatch.setattr(doctor, "probes_for", lambda project: a_fully_pinned_probe_set(
        forge_reachable=lambda: (False, said),
        forge_remedy=lambda what: f"ask joao.pereira to reinstall the App on {ORG}; "
                                  f"CASTELLO_SONAR_TOKEN is left as it is"))
    from tests.test_preflight_json_is_the_document_the_agent_lane_reads import _probes

    monkeypatch.setattr(preflight, "probes_for_this_machine", lambda: _probes(
        work_dir=lambda: "/home/mariana.souza/.local/share/openfactory/work",
        sandbox_image=lambda: f"registry.castello.com.br/{ORG}/box:2"))

    deploy = tmp_path / "deploy"
    deploy.mkdir()
    env_file = deploy / ".env.compose"
    env_file.write_text("OPENFACTORY_ENGINE_RETENTION_DAYS=30\n")
    env_file.chmod(0o600)
    monkeypatch.chdir(deploy)
    return deploy


def files_of(output: str) -> dict[str, str]:
    """The files a `--dry-run` printed, by name."""
    out: dict[str, str] = {}
    current = None
    for line in output.splitlines():
        if line.startswith("── ") and line.endswith(" ──"):
            current = line[3:-3]
            out[current] = ""
        elif line.startswith("— --dry-run"):
            current = None
        elif current is not None:
            out[current] += line + "\n"
    return out


def pack_json(files: dict[str, str]) -> dict:
    return json.loads(files["pack.json"])
