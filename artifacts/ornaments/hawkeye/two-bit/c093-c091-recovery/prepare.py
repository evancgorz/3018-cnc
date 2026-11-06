"""Prepare an exact C091 suffix before the uncertain failure bookmark; offline only."""
from pathlib import Path
import hashlib
import json
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT / 'src'))
from ttc3018_control.gcode import parse_gcode, validate_nonnegative_work_xy, validate_rapid_xy_clearance

SOURCE = HERE.parent / 'c091-approved-raised-plane/01-approved-raised-plane-full-detail-test.nc'
OUTPUT = HERE / '01-c091-continuation-before-8603.nc'
EXPECTED_SHA = '2cba53849eeb5e7b255fdeb1d7fd332c71205d2b3c710882260f3fe9a85583e9'
ACCEPTED = 8603
REWIND = 32

def main():
    data = SOURCE.read_bytes()
    source_sha = hashlib.sha256(data).hexdigest()
    assert source_sha == EXPECTED_SHA
    original = parse_gcode(data.decode('ascii'), SOURCE)
    commands = original.commands
    # The accepted count includes queued motion, so restart a complete stroke
    # at least 32 commands earlier rather than treating it as an executed cursor.
    eligible = []
    for i in range(0, ACCEPTED - REWIND):
        if (commands[i] == 'G0 Z3.0000'
                and re.fullmatch(r'G0 X[0-9.]+ Y[0-9.]+', commands[i+1])
                and commands[i+2] == 'G0 Z0.2000'
                and re.fullmatch(r'G1 Z-[0-9.]+ F120.0000', commands[i+3])):
            eligible.append(i)
    start = max(eligible)
    prologue = ('G21 G17 G90 G94 G54', 'G0 Z3.0000', 'M3 S1000', 'G4 P2.000')
    text = ('; C093 conservative C091 continuation; source SHA ' + source_sha + '\n'
            + '; First included source executable command ' + str(start+1) + '\n'
            + '\n'.join((*prologue, *commands[start:])) + '\n')
    OUTPUT.write_text(text, encoding='ascii', newline='\n')
    candidate = parse_gcode(text, OUTPUT)
    assert candidate.commands[4:] == commands[start:]
    assert candidate.commands[-3:] == ('G0 Z3.0000', 'M5', 'M2')
    validate_nonnegative_work_xy(candidate)
    validate_rapid_xy_clearance(candidate, 3)
    assert candidate.bounds.maximum.x <= 110 and candidate.bounds.maximum.y <= 110
    depths = sorted({round(s.end.z, 4) for s in candidate.segments if s.end.z < 0})
    assert depths == [-1.625, -1.2, -0.04]
    report = dict(source=str(SOURCE), source_sha256=source_sha,
                  accepted_bookmark=ACCEPTED, sent_commands=8619,
                  rewind_commands_minimum=REWIND,
                  first_included_source_command=start+1,
                  boundary_commands=commands[start:start+4],
                  output=str(OUTPUT), output_sha256=hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
                  commands=len(candidate.commands), depths=depths,
                  nominal_minutes=candidate.estimated_seconds/60,
                  checks='pass: exact executable suffix, safe entry, parse, bounds, depths, safe rapids, final M5/M2',
                  note='Accepted count is not physical progress; re-cuts overlap before uncertain buffered region. Geometry inherits exact verified C091 suffix.')
    (HERE/'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
