#!/usr/bin/env python3
"""Record what every decompile citation in docs/ck/ points at, and notice when it moves.

A citation like `Pug.Other:441234` is a claim in its own right, and it is wrong
unless that exact line carries what the sentence says it shows. Line numbers
move with every Core Keeper update, so after one, every citation in the
handbook is suspect and nothing says which. Answering that by hand cost four
parallel verifiers across 175 references on 2026-08-22, to find six errors.

This script answers it in seconds, by storing the *text* of each cited line
rather than trusting the number. It does not check whether a statement is true
— no script can — it checks whether the ground under it moved. A citation
whose line still reads the same is not thereby correct; it is merely unchanged.

Two modes: --capture writes the snapshot, the default compares against it.
Capture deliberately requires a flag, so a drift run can never silently record
the drift as the new truth.

What it does not resolve, and reports instead of guessing at:
citations naming something other than a decompiled assembly. Two exist today —
one into prefab YAML (`ControlMappingMenu.prefab:2456-2457`) and one naming the
dedicated-server *tree* rather than an assembly in it
(`DedicatedServer:263259-263262`), which is a documentation defect this surfaces
rather than papers over.

Usage:
    uv run utils/check_citation_drift.py [--capture] [--decompile PATH] [repo-root]
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Backtick-delimited, because that is how every real citation is written and it
# is what separates `Pug.Other:441234` from prose like "roughly 124940". The
# assembly part allows dots (Pug.ECS.Components) but not spaces or colons.
CITATION = re.compile(r"`([A-Za-z][A-Za-z0-9_.]*):(\d{3,})(?:-(\d{3,}))?`")


def extract(text):
    """Return (assembly, first_line, last_line) per citation, in document order."""
    return [
        (m.group(1), int(m.group(2)), int(m.group(3) or m.group(2)))
        for m in CITATION.finditer(text)
    ]


def resolve(assembly, first, last, decompile):
    """Return the stripped text of lines first..last, or None if unresolvable.

    Stripped, because leading whitespace is the one part of a decompiled line
    that changes for reasons having nothing to do with the code — a nesting
    level added around it moves every line inside without altering what any of
    them says. Comparing stripped text keeps the report about the statement.
    """
    source = Path(decompile) / f"{assembly}.decompiled.cs"
    if not source.is_file():
        return None
    lines = source.read_text(errors="replace").splitlines()
    return [line.strip() for line in lines[first - 1 : last]]
