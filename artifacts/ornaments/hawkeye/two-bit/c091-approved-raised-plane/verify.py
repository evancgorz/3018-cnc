"""Verify final C091 bytes independently of its generator's in-memory paths."""
from pathlib import Path
import sys, hashlib, json, math, importlib.util
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union
from shapely.prepared import prep
HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[4]
sys.path.insert(0,str(ROOT/'src'))
from ttc3018_control.gcode import parse_gcode, validate_nonnegative_work_xy, validate_rapid_xy_clearance
from ttc3018_control.ornament_cam import OrnamentSettings,raster_region

report=json.loads((HERE/'report.json').read_text()); path=HERE/'01-approved-raised-plane-full-detail-test.nc'
text=path.read_text(); p=parse_gcode(text,path)
assert hashlib.sha256(path.read_bytes()).hexdigest()==report['output_sha256']
validate_nonnegative_work_xy(p); validate_rapid_xy_clearance(p,3)
assert text.endswith('G0 Z3.0000\nM5\nM2\n')
assert text.count('M3 S1000')==1
assert sorted({s.end.z for s in p.segments if s.end.z<0})==[-1.625,-1.2,-.6,-.04]
cfg=OrnamentSettings(**report['settings']); allowed,_=raster_region(HERE/'approved-depth-mask.png',cfg)
allowed=allowed.difference(Point(55,100).buffer(3,quad_segs=256))
depth_sweeps={}
safe=prep(allowed)
for depth in (-.6,-1.2,-1.625,-.04):
    radius=(.1+2*abs(depth)*math.tan(math.radians(15)))/2/math.cos(math.pi/128)
    # Merge continuous centerlines first to bound GEOS union overhead.
    groups=[]; active=[]
    for s in p.segments:
        cutting=not s.rapid and s.start.z==depth and s.end.z==depth
        if cutting:
            if not active: active=[(s.start.x,s.start.y)]
            active.append((s.end.x,s.end.y))
        elif active:
            groups.append(active); active=[]
    if active: groups.append(active)
    excess=0.
    for coords in groups:
        sweep=LineString(coords).buffer(radius,quad_segs=32)
        if not safe.covers(sweep):
            excess+=sweep.difference(allowed).area
        assert box(0,0,110,110).covers(sweep)
    if excess>1e-7: raise AssertionError(f'Excess sweep at {depth}: {excess}')
    depth_sweeps[str(depth)]={'verified_continuous_paths':len(groups),'excess_mm2':excess}
result={'output_sha256':report['output_sha256'],'checks':'pass','commands':len(p.commands),'depth_sweeps':depth_sweeps}
(HERE/'verification.json').write_text(json.dumps(result,indent=2)); print(json.dumps(result,indent=2))
