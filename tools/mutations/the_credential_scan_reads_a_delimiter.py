"""The floor's credential scan, and the nine ways it holds a client's pickup again.

THE DEFECT (#11), and it is the shape that makes this worth a mutation plan rather than a one-line
patch. A client vendoring `opencv.js` — 8.3 MB of minified WebAssembly on 47 lines, the binary
inline as base64 — had every card on the project held. Base64 of arbitrary bytes eventually spells
an uppercase/digit run satisfying `(AKIA|ASIA)[0-9A-Z]{16}`. Ten real repositories measured clean
when the pattern was written; the eleventh was a Django app that vendors a library.

The gate is `advisory: true`, so it cannot block a merge — and `box prove`'s validate station
demands rc==0 anyway, and `gate_reason` reads that proof before a card is taken. An advisory gate
with a decidedly non-advisory effect.

ROW 3 IS THE ONE THAT ALREADY HAPPENED, in the first attempt at this fix and not in some
hypothetical future. `=` is base64's padding, so it never precedes a run — and it is the commonest
separator in a `.env`, the file a real key is likeliest to be in. A symmetric character class
excluding `=` on both sides dropped `AWS_ACCESS_KEY_ID=AKIA…` along with the vendored blob: the
false-negative risk this whole direction was warned about, arriving on the first try. It was caught
by running the command, which is why these guards run it too.

ROWS 8-9 CUT THE OTHER WAY: the version that delimits everything "for consistency", and the version
that solves it with a path exclusion — predictable, and it silently stops scanning the places where
a credential could genuinely be committed.
"""

TEST = "tests/test_the_credential_scan_reads_a_delimiter.py"

_AWS = "(^|[^0-9A-Za-z+/])(AKIA|ASIA)[0-9A-Z]{16}([^0-9A-Za-z+/=]|$)"
_GOOGLE = "(^|[^0-9A-Za-z+/])AIza[0-9A-Za-z_-]{35}([^0-9A-Za-z+/=]|$)"

MUTATIONS = [
    # ── the defect, restored ────────────────────────────────────────────────────────────────────
    ("the AWS pattern loses its delimiter — #11 exactly as reported: a vendored base64 bundle "
     "fails the scan, `box prove` fails its validate station, and every card on the project is "
     "held on a file containing no credential",
     "openfactory/org_defaults/floor.yaml",
     _AWS,
     "(AKIA|ASIA)[0-9A-Z]{16}"),

    ("the Google pattern loses its delimiter — the same defect, the other pattern whose alphabet "
     "is drawn entirely from base64's own",
     "openfactory/org_defaults/floor.yaml",
     _GOOGLE,
     "AIza[0-9A-Za-z_-]{35}"),

    # ── the false negative this direction was warned about ──────────────────────────────────────
    ("`=` is excluded on the LEADING side too, which is symmetric and wrong: it is base64's "
     "padding so it never precedes a run, and it is the commonest separator in a `.env` — every "
     "`AWS_ACCESS_KEY_ID=AKIA…` is dropped along with the bundle. This is what the first attempt "
     "at the fix actually did",
     "openfactory/org_defaults/floor.yaml",
     "(^|[^0-9A-Za-z+/])(AKIA|ASIA)",
     "(^|[^0-9A-Za-z+/=])(AKIA|ASIA)"),

    ("the trailing class ALLOWS `=`, so a match followed by base64 padding counts — which is a "
     "blob ending on the collision, and the false positive returns for the commonest shape of it",
     "openfactory/org_defaults/floor.yaml",
     "[0-9A-Z]{16}([^0-9A-Za-z+/=]|$)",
     "[0-9A-Z]{16}([^0-9A-Za-z+/]|$)"),

    ("the leading alternative drops its `^` anchor, so a credential at the START of a line is "
     "never found — a `.env`'s first key, or a bare id on its own line",
     "openfactory/org_defaults/floor.yaml",
     "(^|[^0-9A-Za-z+/])(AKIA|ASIA)",
     "([^0-9A-Za-z+/])(AKIA|ASIA)"),

    ("the trailing alternative drops its `$`, so a credential at the END of a line is never found "
     "— which is where a value sits in every `KEY=value` file there is",
     "openfactory/org_defaults/floor.yaml",
     "[0-9A-Z]{16}([^0-9A-Za-z+/=]|$)",
     "[0-9A-Z]{16}([^0-9A-Za-z+/=])"),

    # ── what must not regress while the pattern is edited ───────────────────────────────────────
    ("a scan that could NOT run comes back clean: `git grep` exiting above 1 stops being an error "
     "and a repository nobody could read is indistinguishable from one with nothing in it",
     "openfactory/org_defaults/floor.yaml",
     "rc=$? ; if [ $rc -gt 1 ] ; then",
     "rc=$? ; if [ 0 -gt 1 ] ; then"),

    # ── THE OTHER DIRECTION ─────────────────────────────────────────────────────────────────────
    ("OVER-TIGHTENED — every pattern is delimited \"for consistency\", including the eight that "
     "contain a `_`, a `-` or a literal base64 cannot spell. It buys nothing, and each one is a "
     "fresh chance at the false negative that is the expensive error for this gate",
     "openfactory/org_defaults/floor.yaml",
     "|gh[pousr]_[0-9A-Za-z]{36}|",
     "|(^|[^0-9A-Za-z+/])gh[pousr]_[0-9A-Za-z]{36}([^0-9A-Za-z+/=]|$)|"),

    ("OVER-TIGHTENED — the fix becomes a path exclusion instead of a delimiter, which is "
     "predictable and silently stops scanning the places a credential could genuinely be "
     "committed. A repository with both a vendored bundle and a real key in it reports neither",
     "openfactory/org_defaults/floor.yaml",
     "      -- .) ; rc=$? ;",
     "      -- . ':(exclude)*/vendor/*' ':(exclude)*.min.js') ; rc=$? ;"),
]
