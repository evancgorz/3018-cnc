"""Offline revision and analytic flat-tip V-bit surface render; no machine API."""
from pathlib import Path
from dataclasses import replace
import hashlib, importlib.util, json, math, sys
import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import Point, LineString, box
from shapely.affinity import scale
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT / 'src'))
from ttc3018_control.ornament_cam import OrnamentSettings, raster_region, plan_adaptive_region_engraving, _polygons
from ttc3018_control.gcode import parse_gcode, validate_nonnegative_work_xy, validate_rapid_xy_clearance
from ttc3018_control.job_analysis import analyze_program

SOURCE_DIR = HERE.parent / 'c091-approved-raised-plane'
DEPTH, TIP, ANGLE = 1.625, .1, 30.
GRID = .025

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def load(path):
    spec = importlib.util.spec_from_file_location('c095_helpers', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

def raster_geometry(geometry, size, extent=110):
    image = Image.new('L', (size, size), 0)
    draw = ImageDraw.Draw(image)
    for polygon in _polygons(geometry):
        draw.polygon([(x/extent*size, (extent-y)/extent*size) for x,y in polygon.exterior.coords], fill=255)
        for hole in polygon.interiors:
            draw.polygon([(x/extent*size, (extent-y)/extent*size) for x,y in hole.coords], fill=0)
    return image

def remove_surface(depth_map, paths, depth):
    """Analytic depth at grid centers from exact continuous rounded segments.

    Flat tip: d(r)=d at r<=.05; otherwise d-(r-.05)/tan15, clamped at0.
    The deepest removal across all traversals defines the final surface.
    """
    tangent = math.tan(math.radians(ANGLE/2))
    radius = TIP/2 + depth*tangent
    count = depth_map.shape[0]
    for path in paths:
        for (ax,ay),(bx,by) in zip(path,path[1:]):
            left = max(0, int(math.floor((min(ax,bx)-radius)/GRID)))
            right = min(count, int(math.ceil((max(ax,bx)+radius)/GRID))+1)
            bottom = max(0, int(math.floor((min(ay,by)-radius)/GRID)))
            top = min(count, int(math.ceil((max(ay,by)+radius)/GRID))+1)
            xx = (np.arange(left,right,dtype=np.float32)+.5)*GRID
            yy = (np.arange(bottom,top,dtype=np.float32)+.5)*GRID
            dx,dy = bx-ax,by-ay
            denominator = dx*dx+dy*dy
            if denominator:
                t = np.clip(((xx[None,:]-ax)*dx+(yy[:,None]-ay)*dy)/denominator,0,1)
                r = np.sqrt((xx[None,:]-ax-t*dx)**2+(yy[:,None]-ay-t*dy)**2)
            else:
                r = np.sqrt((xx[None,:]-ax)**2+(yy[:,None]-ay)**2)
            removal = np.maximum(0, depth-np.maximum(0,r-TIP/2)/tangent)
            target = depth_map[bottom:top,left:right]
            np.maximum(target, removal, out=target)

def render(depth_map, name, *, shaded):
    # Render depth in objective colors, with optional directional shape shading.
    fraction = np.clip(depth_map / DEPTH, 0, 1)
    light = np.array([236,208,160], dtype=np.float32)
    dark = np.array([104,57,31], dtype=np.float32)
    pixels = light[None,None,:] + fraction[:,:,None]*(dark-light)[None,None,:]
    if shaded:
        gy,gx = np.gradient(-depth_map, GRID)
        illumination = (.90 + .25*(-.45*gx+.55*gy+1) / np.sqrt(gx*gx+gy*gy+1))
        pixels *= np.clip(illumination,.62,1.15)[:,:,None]
    n = depth_map.shape[0]
    coord = (np.arange(n,dtype=np.float32)+.5)*GRID
    disc = (coord[None,:]-55)**2+(coord[:,None]-55)**2 <= 50**2
    hole = (coord[None,:]-55)**2+(coord[:,None]-100)**2 <= 2**2
    pixels[~disc | hole] = 255
    image = Image.fromarray(np.uint8(np.clip(pixels,0,255)[::-1]))
    image.resize((1500,1500), Image.Resampling.LANCZOS).save(HERE / name)

def main():
    HERE.mkdir(exist_ok=True)
    baseline = json.loads((SOURCE_DIR / 'report.json').read_text())
    cfg = OrnamentSettings(**baseline['settings'])
    original,_ = raster_region(SOURCE_DIR/'approved-depth-mask.png', cfg)
    keepout = Point(55,100).buffer(3,quad_segs=128)
    original = original.difference(keepout)
    # These two edit zones do not intersect the aircraft, lettering, palm or boat.
    inner = Point(55,55).buffer(32.0, quad_segs=256)
    # Protect the authentic raised aircraft components while removing every old
    # thin ray remnant in the sky, including those near the radar dome.
    raised_aircraft = unary_union([p for p in _polygons(inner.difference(original))
                                  if p.area > 15 and p.intersects(box(30,44,80,66))])
    sky_zone = inner.intersection(box(20,66,90,91)).difference(raised_aircraft.buffer(.15))
    water_zone = inner.intersection(box(22,24,88,41.5))
    rays=[]
    for angle in (30,45,60,75,90,105,120,135,150):
        a=math.radians(angle)
        start=(55+11*math.cos(a),62+11*math.sin(a))
        end=(55+27*math.cos(a),62+27*math.sin(a))
        rays.append(LineString((start,end)).buffer(.5,quad_segs=24))
    raised_rays=unary_union(rays).intersection(sky_zone).intersection(inner.buffer(-1.2))
    ripples=[]
    for x,y,length,height in ((47,39,22,1.25),(66,36.2,14,1.4),(42,33.4,17,1.35),
                              (61,30.5,18,1.3),(48,27.7,12,1.35)):
        ripples.append(scale(Point(x,y).buffer(1,quad_segs=64),xfact=length/2,yfact=height/2))
    raised_water=unary_union(ripples).intersection(water_zone)
    revised=original.union(sky_zone).difference(raised_rays).union(water_zone).difference(raised_water)
    assert revised.symmetric_difference(original).difference(sky_zone.union(water_zone)).area < 1e-8
    raster_geometry(revised,2200).point(lambda v:255-v).save(HERE/'revised-depth-mask.png')
    helpers=load(ROOT/'artifacts/ornaments/hawkeye/two-bit/c069-flow/prepare-c069-flow.py')
    # Rough upper levels need not repeat the close final floor finish.  The
    # 0.12 mm final-depth spacing limits the ideal parallel-lane cusp to
    # 0.0373 mm; upper passes use the established 0.27 mm roughing spacing.
    roughcfg=replace(cfg,stepover=.27)
    cfg=replace(cfg,stepover=.12)
    print('Planning concentric finish geometry',flush=True)
    raw,_,meta=plan_adaptive_region_engraving(revised,cfg)
    broad=helpers.simplify_paths(raw,.04,revised,cfg.effective_diameter)
    rough_raw,_,rough_meta=plan_adaptive_region_engraving(revised,roughcfg)
    rough=helpers.simplify_paths(rough_raw,.04,revised,roughcfg.effective_diameter)
    # Fine details remain at original shallow depth; their color is modeled as shallow.
    broad_sweep=unary_union([LineString(p).buffer(cfg.effective_diameter/2/math.cos(math.pi/128),quad_segs=32) for p in broad])
    residual=revised.difference(broad_sweep).buffer(.07).intersection(revised)
    finecfg=replace(cfg,engraving_depth=.04,max_stepdown=.04,stepover=.09)
    fine_raw,_,fine_meta=plan_adaptive_region_engraving(residual,finecfg)
    fine=helpers.simplify_paths(fine_raw,.04,revised,finecfg.effective_diameter)
    fine_sweep=unary_union([LineString(p).buffer(finecfg.effective_diameter/2/math.cos(math.pi/128),quad_segs=32) for p in fine])
    rough_sweep=unary_union([LineString(p).buffer(roughcfg.effective_diameter/2/math.cos(math.pi/128),quad_segs=32) for p in rough])
    if not revised.covers(broad_sweep) or not revised.covers(rough_sweep) or not revised.covers(fine_sweep):
        raise ValueError('Final rounded full-width cutter sweep exceeds revised dark region')
    print('Writing review program',flush=True)
    lines=['; C095 OFFLINE REVIEW ONLY; revised rays/water with cutter-faithful render',
           'G21 G17 G90 G94 G54','G0 Z3.0000','M3 S1000','G4 P2']
    for depth,paths in ((-.6,rough),(-1.2,rough),(-DEPTH,broad),(-.04,fine)):
        lines.append(f'; PASS Z{depth:.4f}')
        for p in paths: helpers.emit_path(lines,p,depth,3,.2)
    lines+=['G0 Z3.0000','M5','M2']
    text='\n'.join(lines)+'\n'; output=HERE/'01-c095-review-only.nc'
    output.write_text(text,encoding='ascii',newline='\n')
    program=parse_gcode(text,output)
    validate_nonnegative_work_xy(program);validate_rapid_xy_clearance(program,3)
    # Render every actual pass. Upper roughing and finishing paths differ, so
    # their material removal must be combined rather than assumed redundant.
    print('Rendering analytic V-bit height field',flush=True)
    removal=np.zeros((round(110/GRID),round(110/GRID)),dtype=np.float32)
    remove_surface(removal,rough,.6); remove_surface(removal,rough,1.2)
    remove_surface(removal,broad,DEPTH); remove_surface(removal,fine,.04)
    np.save(HERE/'modeled-removal-depth-mm.npy',removal)
    render(removal,'modeled-depth-preview.png',shaded=False)
    render(removal,'modeled-surface-preview.png',shaded=True)
    report={'status':'offline design review only; not loaded or released',
            'baseline_report_sha256':sha(SOURCE_DIR/'report.json'),'output_sha256':sha(output),
            'settings':cfg.__dict__,'fine_settings':finecfg.__dict__,'grid_mm':GRID,
            'strategy':meta,'rough_strategy':rough_meta,'fine_strategy':fine_meta,'motion':analyze_program(program),
            'edits':{'raised_ray_width_mm':1.,'raised_ray_count':9,'water_ripples':5,
                     'unchanged_outside_sky_water_zones':True,'plane_source_geometry_unchanged':True},
            'tool':{'angle_deg':ANGLE,'flat_tip_mm':TIP,'target_depth_mm':DEPTH,
                    'top_cut_width_mm':cfg.effective_diameter,'wall_horizontal_run_each_side_mm':DEPTH*math.tan(math.radians(15))},
            'ideal_parallel_lane_cusp_mm':{str(s):max(0,(s-TIP)/(2*math.tan(math.radians(15)))) for s in (.27,.15,.13,.12)},
            'model':'analytic continuous-segment nearest distance; removal=max(0,depth-max(0,r-tip/2)/tan15), maximum over paths',
            'limitations':['Height grid sampling .025mm; continuous cutter envelope checks separate.',
                           'Preview color is continuous depth color, not measured plywood ply color.',
                           'Ply-interface depth and layer colors have not been measured; second-ply contrast is not guaranteed.',
                           'Ideal lane cusp numbers do not bound corners, residual centers or irregular offset gaps; actual surface is rendered.',
                           'V-bit tapered walls round fine geometry and leave very shallow panel details pale rather than dark.',
                           'Smooth finish adds cutting distance; physical surface still depends on tool/runout/wood grain.']}
    (HERE/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'commands':len(program.commands),'nominal_minutes':program.estimated_seconds/60,'broad_paths':len(broad),'fine_paths':len(fine)}),flush=True)

if __name__=='__main__':main()
