#!/bin/sh
# THE PLATFORM'S INSTALL STEP, FOR BOTH IMAGES, AS ONE SCRIPT A GUARD CAN RUN.
#
#   sh docker/install-addons.sh '<core pip specifier>' [<packages directory>]
#
# It installs the core, then every add-on package the build context happens to carry, and it has
# to behave correctly in TWO trees:
#
#   · the PRIVATE repository, which has `addons/openfactory-aws` and `addons/openfactory-slack`:
#     both are installed, so the worker serves `channel: slack` and `OPENFACTORY_SANDBOX=fargate`;
#   · the PUBLIC export, where `addons/` is a row of docs/STATUS.md's excluded-paths table and the
#     directory is simply absent: the core alone is installed, exit 0, and the two rows above are
#     refused BY NAME with the package that carries them — the distribution's answer, not a break.
#
# WHY A SCRIPT AND NOT A `RUN` LINE. The `RUN` line this replaces was `for p in ./addons/…; do if
# [ -d "$p" ]; then pip install "$p"; fi; done`, and the guard on it asserted that SHAPE: that a
# glob was copied and that an existence test stood somewhere in the instruction. A reviewer
# replaced `[ -d "$p" ]` with `[ -f README.md ]` — README.md is COPYied into the same WORKDIR, so
# the test is always true — and all 23 guards stayed green while the public build went back to
# `pip install ./addons/openfactory-*`, i.e. exit 1 on the first command README.md gives a
# stranger (measured 2026-08-26). A shape cannot be judged; a behaviour can. This file is one
# command with one argument, so the guard runs the real instruction in a planted public tree and a
# planted private one and reads what was installed.
#
# EVERY FAILURE PROPAGATES. `set -e` plus the loop below means a pip that fails takes the layer
# down. The previous form's `|| exit 1` existed for that and nothing checked it: without it a
# failing install is swallowed by the next iteration and the image ships missing a package it was
# told to carry, green.
set -eu

core="${1:?usage: install-addons.sh '<core pip specifier>' [<packages directory>]}"
packages="${2:-./addons}"

pip install --no-cache-dir "$core"

# NOT AN ERROR, AND THAT IS THE WHOLE POINT: this is what the public export looks like.
if [ ! -d "$packages" ]; then
    echo "install-addons: no '$packages' directory in this build context — the core alone" >&2
    exit 0
fi

count=0
for package in "$packages"/openfactory-*; do
    # A glob that matched nothing leaves the pattern itself in "$package"; a README or a note
    # beside the packages is not one. Either way there is nothing to install here.
    [ -d "$package" ] || continue
    pip install --no-cache-dir "$package"
    count=$((count + 1))
done
echo "install-addons: installed $count add-on package(s) from '$packages'" >&2
