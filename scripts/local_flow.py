"""Run the OpenFactory pre-flight → split flow LOCALLY, offline, in under a second.

    python -m scripts.local_flow                 # intended: split once, children go to code
    python -m scripts.local_flow --always-split  # worst case: proves the cascade guard holds
    python -m scripts.local_flow --children 6    # how many children the sizer proposes

No Temporal, no Fargate, no GitHub — a scripted sizer drives the REAL _do_preflight/_do_split
against an in-memory board + a throwaway tiny repo. This is the fast feedback loop: a logic bug
like the split cascade shows up here instantly instead of after a 5-minute deploy + a 3-minute
poll on the heavy real project.
"""

from __future__ import annotations

import argparse

from openfactory.testing.local_flow import always_split, run_flow, split_once_then_fit


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--always-split", action="store_true",
                    help="sizer judges EVERY ticket too large (worst case for the cascade guard)")
    ap.add_argument("--children", type=int, default=4, help="children the sizer proposes")
    ap.add_argument("--title", default="Plan 92 — Guest-surface hardening + rate limits")
    args = ap.parse_args()

    sizer = always_split(args.children) if args.always_split else split_once_then_fit(args.children)
    run = run_flow(seed_title=args.title, sizer=sizer)
    run.print_trace()
    return 1 if run.cascaded else 0


if __name__ == "__main__":
    raise SystemExit(main())
