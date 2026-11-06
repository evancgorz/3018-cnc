"""Independent offline checks for the single-bit review export (no machine I/O)."""
from pathlib import Path
import hashlib
import json
import math
import re

from ttc3018_control.gcode import load_gcode, validate_nonnegative_work_xy, validate_rapid_xy_clearance


if __name__ == '__main__':
    folder = Path(__file__).resolve().parent / 'single-bit'
    report = json.loads((folder / 'report.json').read_text(encoding='utf-8'))
    program = load_gcode(folder / 'review-draft.nc')
    validate_nonnegative_work_xy(program)
    validate_rapid_xy_clearance(program, 3)
    commands = '\n'.join(program.commands)
    assert not re.search(r'\bM(?:3|4|6)\b', commands)
    assert len(re.findall(r'\bM(?:2|30)\b', commands)) == 1
    assert program.commands[-1] == 'M2'
    assert program.bounds.minimum.z == -3.15
    assert max(len(c.encode('ascii')) + 1 for c in program.commands) <= 127
    hole, outer = [], []
    for index, segment in enumerate(program.segments):
        a, b = segment.start, segment.end
        assert all(math.isfinite(v) for p in (a,b) for v in (p.x,p.y,p.z))
        if segment.rapid or (a.x,a.y) == (b.x,b.y) or min(a.z,b.z) >= -.40001:
            continue
        radius = math.hypot((a.x+b.x)/2-55, (a.y+b.y)/2-55)
        hole_radius = math.hypot((a.x+b.x)/2-55, (a.y+b.y)/2-100)
        assert hole_radius < 3 or radius > 48, 'Unexpected deep cut in artwork'
        target = hole if hole_radius < 3 else outer
        target.append((index, min(a.z,b.z)))
        for p in (a,b):
            assert 1.5875 <= p.x <= 110-1.5875 and 1.5875 <= p.y <= 110-1.5875
    assert hole and outer and max(i for i,_ in hole) < min(i for i,_ in outer)
    levels = {}
    for name, group in [('hole',hole),('outer',outer)]:
        depths = sorted({round(-z,4) for _,z in group})
        assert depths[-1] == 3.15
        assert all(b-a <= .5001 for a,b in zip([0]+depths,depths))
        assert len(depths) >= 7
        levels[name] = depths
    hashes = {name:hashlib.sha256((folder/name).read_bytes()).hexdigest()
              for name in ['prepare.py','review-draft.nc','artwork-reference.svg','cutter-sweep-preview.svg']}
    for fact in report['artifacts'].values():
        name = Path(fact['path']).name
        if name in hashes:
            assert hashes[name] == fact['sha256'], f'Stale report hash for {name}'
    result = {'status':'offline_review_only', 'parse_and_clearance':'passed',
              'hole_complete_before_outer':True, 'maximum_profile_stepdown_mm':.5,
              'depth_levels_mm':levels, 'estimated_minutes_exact_program':program.estimated_seconds/60,
              'command_count':len(program.commands), 'sha256':hashes,
              'note':'No spindle start. Does not verify physical tooling, stock or fixturing.'}
    (folder/'independent-verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
