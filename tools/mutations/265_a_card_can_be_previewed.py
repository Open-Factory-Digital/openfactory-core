"""Mutation plan for #265 slice 0 — a preview is keyed, named and routed so agent-written code
never reaches the panel's credential (ADR-0050 D1, D7, D10; #271).

Each row takes away one rule the preview's safety rests on; every row must turn
`tests/test_a_card_can_be_previewed.py` red.
"""

TEST = "tests/test_a_card_can_be_previewed.py"
PREVIEW = "openfactory/preview/__init__.py"
APP = "openfactory/api/app.py"
PAGE = "openfactory/api/panel.html"
WORKTREE = "openfactory/adapters/sandbox/worktree.py"

MUTATIONS = [
    # ── the names ──
    ("any label under the domain is read as a preview host", PREVIEW,
     "    m = _HOST_RE.fullmatch(label)\n    if not m:\n        return None\n",
     "    m = _HOST_RE.match(label + '--x--1') if label else None\n    if not m:\n        return None\n"),
    ("a long project name cuts the unit off the end of the label", PREVIEW,
     "    return f\"{svc}--{proj}--{token}\"",
     "    return f\"{svc}--{slug(project) or 'project'}--{token}\"[:63]"),
    # ── the key ──
    ("a key's signature is not checked — a forged or tampered key opens the unit", PREVIEW,
     "    return hmac.compare_digest(parts[3], _mac(project, token, expires))",
     "    return True"),
    ("an expired key still opens", PREVIEW,
     "    if expires < (time.time() if now is None else now):\n        return False",
     "    if False:\n        return False"),
    ("the key is bound to the slug, so two projects whose slugs collide share it", PREVIEW,
     "    return hmac.new(_secret(), f\"v1|{project}|{token}|{expires}\".encode(),",
     "    return hmac.new(_secret(), f\"v1|{slug(project)}|{token}|{expires}\".encode(),"),
    # ── the record ──
    ("the unit is read back from any card's rows, so a card of the unit poses as the unit", PREVIEW,
     "            if str((r.get(\"extra\") or {}).get(\"unit\", \"\")) == str(token)]",
     "            if str((r.get(\"extra\") or {}).get(\"unit\", \"\")) == str(token)\n"
     "            or str(r.get(\"ticket\", \"\")) == str(token)]"),
    ("an expired preview still serves", PREVIEW,
     "        if p is None or not p.live or p.expired() or p.project != name:",
     "        if p is None or not p.live or p.project != name:"),
    ("two projects whose slugs collide both serve one host", PREVIEW,
     "    return found[0] if len(found) == 1 else None",
     "    return found[0] if found else None"),
    # ── the router ──
    ("a host under the preview domain that names no preview falls through to the panel", APP,
     "            return _preview_page(404, \"No such preview\", \"This address names no preview.\")",
     "            return await call_next(request)"),
    ("a preview is served without a key", APP,
     "    if not preview.admits(request.cookies.get(cookie, \"\"), project=record.project,",
     "    if False and not preview.admits(request.cookies.get(cookie, \"\"), project=record.project,"),
    ("the cookie keeps the link's minutes-long key instead of one as long as the preview", APP,
     "        kept = preview.mint(record.project, host.unit, expires=record.expires_at)",
     "        kept = request.query_params.get(\"t\", \"\")"),
    ("the preview's cookie is readable by the application's scripts", APP,
     "        response.set_cookie(cookie, kept, httponly=True, samesite=\"lax\", secure=secure, path=\"/\",",
     "        response.set_cookie(cookie, kept, httponly=False, samesite=\"lax\", secure=secure, path=\"/\","),
    ("the link's key lives as long as the preview", APP,
     "    expires = min(int(time.time()) + preview.LINK_TTL_SECONDS, found.expires_at)",
     "    expires = found.expires_at"),
    # re-pinned in slice 3: the order moved onto the record (`Preview.ordered`), so the card's
    # buttons and the enter door's chain read one definition of it
    ("the service the change touched is listed first", PREVIEW,
     "        return sorted(self.services, key=lambda s: (bool(self.from_change.get(s)), s))",
     "        return sorted(self.services, key=lambda s: (not self.from_change.get(s), s))"),
    ("a product-scoped person cannot open a preview", APP,
     "    if path in _UNSCOPED_ROUTES or path.startswith(_EVERY_AREA_PREFIXES):",
     "    if path in _UNSCOPED_ROUTES:"),
    ("the target is read from the record rather than derived from the name opened", APP,
     "    upstream_base = f\"http://{host.label}:{port}\"",
     "    upstream_base = f\"http://{record.project}:{port}\""),
    ("the browser's Host is replaced by the alias", APP,
     "                  \"trailer\", \"transfer-encoding\", \"upgrade\", \"content-length\"})",
     "                  \"trailer\", \"transfer-encoding\", \"upgrade\", \"content-length\", \"host\"})"),
    ("a redirect naming the alias reaches the browser as it is", APP,
     "        if low == \"location\" and v.startswith(upstream_base):",
     "        if False:"),
    ("another unit's preview cookie reaches the application", APP,
     "            or name.startswith(preview.COOKIE_PREFIX))",
     "            or name == preview.COOKIE_PREFIX)"),
    ("the Authorization header reaches the application", APP,
     "               and k.lower() not in (\"cookie\", \"authorization\")}",
     "               and k.lower() not in (\"cookie\",)}"),
    ("a Domain cookie from a preview passes when its name is its own", APP,
     "    return not _is_ours(name) and \"domain\" not in attrs",
     "    return not _is_ours(name)"),
    ("a preview may set any cookie at all", APP,
     "        if low == \"set-cookie\" and not _a_cookie_a_preview_may_set(v):",
     "        if False:"),
    ("a slow first page is reported as a dead one", APP,
     "        except httpx.TimeoutException:\n            return _preview_page(504,",
     "        except ValueError:\n            return _preview_page(504,"),
    ("the panel may be framed", APP,
     "    response.headers.setdefault(\"content-security-policy\", \"frame-ancestors 'none'\")\n",
     ""),
    # ── the credential (#271) ──
    ("a credential cookie that arrives twice is taken, last-wins", APP,
     "    return request.cookies.get(name, \"\") if seen == 1 else \"\"",
     "    return request.cookies.get(name, \"\")"),
    ("over TLS the plain, plantable name still counts", APP,
     "    return SECURE_TOKEN_COOKIE if _is_secure(request) else TOKEN_COOKIE",
     "    return TOKEN_COOKIE"),
    ("the login over TLS sets a cookie the browser does not require to be Secure", APP,
     "                        samesite=\"lax\", secure=secure, path=\"/\")",
     "                        samesite=\"lax\", secure=False, path=\"/\")"),
    ("the logout leaves the __Host- spelling behind", APP,
     "    response.delete_cookie(SECURE_TOKEN_COOKIE, path=\"/\", secure=True)",
     "    pass"),
    ("the page adopts the first credential cookie it finds", PAGE,
     "return all.length===1?decodeURIComponent(all[0].slice(TOKEN_COOKIE.length+1)):\"\"}",
     "return all.length>=1?decodeURIComponent(all[0].slice(TOKEN_COOKIE.length+1)):\"\"}"),
    ("a worktree workload keeps the key previews are signed with", WORKTREE,
     "    for var in _PANEL_SECRET_VARS:\n        env.pop(var, None)",
     "    for var in ():\n        env.pop(var, None)"),
]
