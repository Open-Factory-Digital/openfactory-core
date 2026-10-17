"""The CLI image builds behind TLS interception and its pip trusts the extra root (#738), proven by
breaking it.

Run:  .venv/bin/python tools/mutate.py tools/mutations/the_cli_image_trusts_an_extra_root.py

Measured both ways on 2026-10-13: 5/5 red with a daemon, where the block runs in the base image,
and 5/5 red with `DOCKER_HOST` pointed at nothing, where those tests skip and the sandbox ones
alone catch every row.

The claims, each a row:
  1. with a certificate, the block runs in `python:3.12-slim` (TODAY'S RUN: it asked `certifi`);
  2. pip is pointed at the bundle that holds the extra root;
  3. with no certificate, nothing is written;
  4. the system roots stay in the bundle pip is pointed at.
"""

TEST = "tests/test_the_cli_image_trusts_an_extra_root.py"
CLI = "docker/cli.Dockerfile"

_APPEND = "      cat /usr/local/share/openfactory/extra-ca.crt >> /etc/ssl/certs/ca-certificates.crt; \\\n"
_PIP = "      printf '[global]\\ncert = %s\\n' /etc/ssl/certs/ca-certificates.crt > /etc/pip.conf; \\\n"

MUTATIONS = [
    ("TODAY'S RUN: the block asks the base image's Python for certifi, which it does not have", CLI,
     _APPEND + _PIP,
     "      cat /usr/local/share/openfactory/extra-ca.crt >> \\\n"
     "        \"$(python -c 'import certifi; print(certifi.where())')\"; \\\n"
     "      printf '[global]\\ncert = %s\\n' \\\n"
     "        \"$(python -c 'import certifi; print(certifi.where())')\" > /etc/pip.conf; \\\n"),
    ("pip is never pointed at the bundle, so it trusts its own and not the extra root", CLI,
     _PIP, ""),
    ("pip.conf is written with no certificate given, in every public build", CLI,
     _PIP + "    fi; \\\n",
     "    fi; \\\n" + _PIP),
    ("the extra root replaces the system bundle instead of joining it", CLI,
     "extra-ca.crt >> /etc/ssl/certs/ca-certificates.crt",
     "extra-ca.crt > /etc/ssl/certs/ca-certificates.crt"),
    ("pip is pointed at the extra root alone, so every site the proxy does not re-sign fails", CLI,
     _PIP,
     "      printf '[global]\\ncert = %s\\n' /usr/local/share/openfactory/extra-ca.crt > /etc/pip.conf; \\\n"),
]
