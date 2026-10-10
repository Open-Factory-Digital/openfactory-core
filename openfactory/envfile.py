"""An env file, read by one set of rules — `KEY=value` rows as the deployment writes them (#583).

THE CORE READ THIS FORMAT THREE WAYS. The preflight kept a parser of its own (`_env_file_rows`),
the preview assembler another (`_env_values`), and the CLI loads the same kind of file through
python-dotenv (`cli._load_environment`). Each was right for the lines its author tried: the
preflight read `export KEY=v` as the key `export KEY` and kept a trailing ` # comment` in the value,
so `OPENFACTORY_PANEL_PORT=8788  # moved` read `8788  # moved`, failed as a number, and the default
port was checked — the class #560 had just fixed, for a port moved by hand. `openfactory init`
writes plain rows, so the file as shipped was safe; a file edited by hand was not.

Now every reader asks `read`, built on `dotenv_values` — the parser the CLI already loads these
files with — for comments, quotes and `export`. A name with no `=` names nothing to read here and
is left out. Values are taken as written, never interpolated: nothing this reads expands `${…}`.

AN UNREADABLE FILE IS NOT AN ABSENT ONE. The installer runs the preflight as the person's own uid;
a `.env.compose` left root-owned at `0600` by a `sudo` run read as no file at all, and the line
after "the file is there" said no credential was set — sending the person to replace a token that
was in it. `EnvFile.unreadable` says why it could not be read, and a reader says THAT.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class EnvFile:
    """What an env file holds: its rows, whether it is there, and why it could not be read."""

    rows: dict[str, str] = field(default_factory=dict)
    exists: bool = False
    unreadable: str = ""


def parse(text: str) -> dict[str, str]:
    """The rows of an env file's text, by the one set of rules."""
    from dotenv import dotenv_values

    values = dotenv_values(stream=io.StringIO(text), interpolate=False)
    return {key: value for key, value in values.items() if key and value is not None}


def read(path: str | Path) -> EnvFile:
    """The file at `path`. Never raises: a missing file is `exists=False`, and one that is there
    and cannot be read is `exists=True` with `unreadable` saying why — never the same answer."""
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, NotADirectoryError):
        return EnvFile()
    except OSError as exc:  # there, and not to be read: permission denied, a directory, …
        return EnvFile(exists=True, unreadable=(exc.strerror or type(exc).__name__).lower())
    return EnvFile(rows=parse(text), exists=True)
