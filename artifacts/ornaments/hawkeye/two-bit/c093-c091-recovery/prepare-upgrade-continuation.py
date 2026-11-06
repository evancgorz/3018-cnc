"""Capture the confirmed pause and generate the exact conservative suffix."""
import json
import hashlib
from pathlib import Path
import subprocess
import os
from ttc3018_control.gcode import parse_gcode
from ttc3018_control.backend.auto_continuation import continuation

root = Path(__file__).resolve().parents[5]
here = Path(__file__).resolve().parent / 'backend-upgrade'
here.mkdir(exist_ok=True)
snapshot = json.loads(subprocess.check_output([str(root / '.venv/Scripts/pine-cli.exe'), '--root', str(root), 'status', '--json'], env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}))
bookmark = snapshot['job_recovery']['pause_bookmark']
assert bookmark['confirmed'] and bookmark['accepted_commands'] == 1437
source = root / snapshot['program']['path']
assert hashlib.sha256(source.read_bytes()).hexdigest() == bookmark['source_sha256']
program = parse_gcode(source.read_text(), source)
text, index, preamble = continuation(program, bookmark['accepted_commands'])
output = here / '01-upgrade-bookmark-continuation.nc'
output.write_text(text, encoding='ascii', newline='\n')
report = {'bookmark': bookmark, 'first_source_command': index + 1, 'preamble_commands': preamble,
          'output_sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'output': str(output)}
(here / 'bookmark-and-verification.json').write_text(json.dumps(report, indent=2))
assert parse_gcode(text).commands[preamble:] == program.commands[index:]
print(json.dumps(report, indent=2))
