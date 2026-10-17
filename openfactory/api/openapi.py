"""The API's description, as the repository commits it (#678): `docs/reference/openapi.json`.

A front end of one's own reads the shapes it builds on from this file, without running the core.
It is generated from the app, never edited by hand, and a test fails when the two are apart:

    python -m openfactory.api.openapi

writes it again. `info.version` is the package's version; `info.title` is the core's name and not
the one a deployment gives its panel (`OPENFACTORY_PLATFORM_NAME`), so every machine that
generates it writes the same file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

#: Where the description is committed, from the repository's root.
COMMITTED = Path("docs") / "reference" / "openapi.json"

#: What writes it again — said by the test that finds it stale.
COMMAND = "python -m openfactory.api.openapi"

TITLE = "OpenFactory"


def document() -> dict:
    """The description the app serves at `/openapi.json`, under the core's own title."""
    from openfactory.api.app import app

    served = app.openapi()
    return {**served, "info": {**served["info"], "title": TITLE}}


def render() -> str:
    """`document()` as the committed file holds it."""
    return json.dumps(document(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Write the description to the path given, or to `COMMITTED` under the current directory."""
    args = sys.argv[1:] if argv is None else argv
    target = Path(args[0]) if args else COMMITTED
    try:
        target.write_text(render(), encoding="utf-8")
    except OSError as exc:
        print(f"could not write {target}: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
