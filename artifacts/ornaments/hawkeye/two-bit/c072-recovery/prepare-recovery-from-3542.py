"""Build a conservative continuation after C-069 transport loss.

The observed stopped position matched the pass-1 stroke beginning at source
line 3531.  Re-entering at the stroke's safe-Z boundary deliberately re-cuts
the preceding portion of that one stroke instead of skipping unknown buffered
motion.  This script never edits the original program.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "artifacts" / "ornaments" / "hawkeye" / "two-bit" / "c069-flow" / "01-detail-c069-first-boundary-675-120-review-only.nc"
OUTPUT = Path(__file__).with_name("01-detail-c072-recovery-from-stroke-3531.nc")
MARKER = "G0 X36.6102 Y80.0535"

source = SOURCE.read_text(encoding="ascii").splitlines()
index = source.index(MARKER)
start = index - 1  # retain the source stroke's safe-Z boundary
assert source[start] == "G0 Z3.0000"
header = [
    "; C-072 conservative recovery continuation - generated, not hand edited",
    "; Restart from a safe-Z stroke boundary before last observed C-069 point.",
    "; Re-cuts an already-machined stroke prefix; does not skip uncertain buffered motion.",
    "G21 G17 G90 G94 G54",
    "G0 Z3.0000",
    "M3 S1000",
    "G4 P2.000",
]
OUTPUT.write_text("\n".join(header + source[start:]) + "\n", encoding="ascii", newline="\n")
print(OUTPUT)
print(sha256(OUTPUT.read_bytes()).hexdigest())
