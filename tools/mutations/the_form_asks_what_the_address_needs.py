"""ADR-0049 slice 4c, proven by breaking it — the panel's form asks only what the address needs.

FOUR CLAIMS:

  1. **The reading is the door's own.** `/api/address` answers `kind_for`/`foreign_host` and
     nothing else, so what the form shows is the row that lands.
  2. **Coordinates are a hosted idea.** They are hidden for an address that has no owner and no
     board, and one click away for the mounted checkout that does.
  3. **One claim, three doors.** The command line's refusal, the API's 422 and the form's line
     are all `doors.foreign_refusal`.
  4. **The door's sentence reaches the person.** Not "not registered (duplicate?)" over every
     refusal there is.

A READ THAT WRITES is the fifth row's subject, and it is the one shape a reading route must never
have: the form asks this on every keystroke.

The guards under test are `tests/test_the_form_asks_what_the_address_needs.py`; the doors-derive
suite and `tests/test_api.py` are the pins that must keep passing unedited.
"""

TEST = "tests/test_the_form_asks_what_the_address_needs.py"

API = "openfactory/api/app.py"
CLI = "openfactory/cli.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    # ── 1. the reading is the door's own ───────────────────────────────────────────────────────
    ("the reading stops asking the rule and answers the old model default instead", API,
     '    kind = doors.kind_for(repo_path, repo=repo, provider=provider)\n'
     '    # COORDINATES ARE A HOSTED IDEA.',
     '    kind = "github"\n'
     '    # COORDINATES ARE A HOSTED IDEA.', TEST),

    ("the form is told to ask for coordinates whatever the address is", API,
     '    return {"kind": kind, "coordinates": kind != "local", "refusal": ""}',
     '    return {"kind": kind, "coordinates": True, "refusal": ""}', TEST),

    ("a foreign host reads as an ordinary address, so the form asks the person to fill it in",
     API,
     '    if foreign:\n'
     '        return {"kind": "", "coordinates": False, "refusal": doors.foreign_refusal(foreign)}',
     '    if False:\n'
     '        return {"kind": "", "coordinates": False, "refusal": doors.foreign_refusal(foreign)}',
     TEST),

    ("a kind nobody implements 500s the modal instead of reading as a refusal", API,
     '    except ValueError as exc:\n'
     '        # A KIND NOBODY IMPLEMENTS, or a shipped kind claiming another\'s host.',
     '    except ValueError:\n'
     '        raise\n'
     '    if False:\n'
     '        # A KIND NOBODY IMPLEMENTS, or a shipped kind claiming another\'s host.', TEST),

    # THE ROW THAT SURVIVED, AND WHAT IT PROVED. It was the other way round — remove
    # `dependencies=_AUTH` from this route and require red — and every test passed, because
    # `_panel_gate` gates every read and answers first. The dependency was not protecting
    # anything; it was REFUSING something, a cookie credential the middleware had admitted. So
    # the cut is the dependency coming BACK, and the guard is the direction that can see it.
    ("the reading gets a second gate that reads headers alone, so a cookie the middleware "
     "admitted is refused", API,
     '@app.get("/api/address")',
     '@app.get("/api/address", dependencies=_AUTH)', TEST),

    # ── 2. a read that writes ──────────────────────────────────────────────────────────────────
    ("the reading registers what it was asked about — a door nobody knew was one", API,
     '    kind = doors.kind_for(repo_path, repo=repo, provider=provider)\n',
     '    try:\n'
     '        ProjectRegistry().add(Project(name="leaked", repo_path=repo_path))\n'
     '    except Exception:\n'
     '        pass\n'
     '    kind = doors.kind_for(repo_path, repo=repo, provider=provider)\n', TEST),

    # ── 3. one claim, three doors ──────────────────────────────────────────────────────────────
    ("the API door keeps its own copy of the refusal, which is how the two came to differ", API,
     '        raise HTTPException(status_code=422, detail=doors.foreign_refusal(foreign))',
     '        raise HTTPException(status_code=422, detail=f"{foreign} is not supported")', TEST),

    ("the command line keeps its own copy of the claim", CLI,
     '    return (f"✗ {doors.foreign_refusal(foreign)}\\n"',
     '    return (f"✗ {foreign} is not a forge this build implements.\\n"', TEST),

    # ── 4. the form ────────────────────────────────────────────────────────────────────────────
    ("the coordinates are visible under every address again, which is the whole defect", PANEL,
     '    <div id="np_coords" style="display:none">',
     '    <div id="np_coords">', TEST),

    ("the form stops asking the rule and guesses in the browser", PANEL,
     '    const r=await mfetch(`/api/address?${q}`);d=await r.json();',
     '    d={kind:address.includes("://")?"github":"local",coordinates:address.includes("://"),'
     'refusal:""};', TEST),

    ("what the person cannot see is submitted anyway", PANEL,
     '    repo:hosted?np_repo.value.trim():"",',
     '    repo:np_repo.value.trim(),', TEST),

    ("the mounted checkout loses its way back to the coordinates", PANEL,
     '<a href="#" onclick="return npHosted()">this checkout is of a hosted repository</a>', "",
     TEST),

    ("every refusal reads as a duplicate again", PANEL,
     '  else toast("Not registered",(d&&d.detail)||"the door refused it","err");',
     '  else toast("Error","not registered (duplicate?)","err");', TEST),
]
