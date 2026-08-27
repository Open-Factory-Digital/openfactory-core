# `docker/extra-ca/` — a root CA this deployment's network requires

**Empty on purpose.** Drop a PEM-encoded root certificate named `*.crt` in here and every image
this repository builds will trust it: the box, the worker, and the harness toolbox.

## When you need this

Your organisation terminates and re-signs outbound HTTPS (Zscaler, Netskope, a corporate
squid with a MITM certificate, most enterprise networks). The proxy presents a certificate
signed by a root that no public image ships, so a build dies like this:

```
pip install uv
  → SSLError(CERTIFICATE_VERIFY_FAILED): unable to get local issuer certificate
```

`apt` usually survives (Debian's own mirrors are plain HTTP), which is why the failure lands on
the *second* network instruction rather than the first and reads like a broken package rather
than a broken trust store.

## Using it

```bash
cp /path/to/your-corporate-root.crt docker/extra-ca/
docker compose --env-file .env.compose up -d --build
```

That is all. Each image copies whatever `.crt` files are here into the system trust store, runs
`update-ca-certificates`, and points `npm` and `pip` at the result. **With no `.crt` here the
images build exactly as they did before** — the block is a no-op, not a branch you opt out of.

`.gitignore` in this directory ignores `*.crt`, so a certificate dropped here is never committed
by accident. That is a convenience and not a secret: a root CA is public by construction — it is
the thing every client must already trust. Commit yours deliberately if your deployment prefers
it in the tree.

## What this does NOT cover

The **runtime** TLS of the worker's own calls (your tracker, your forge). Those go through
Python's `httpx`/`requests`, which read `certifi`'s bundle rather than the system store. Point
them at the system store from `.env.compose`, where every row reaches the worker as an
environment variable:

```
SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
```

That belongs in your deployment's environment rather than in an image, because it is a statement
about your network and not about how the image is built.
