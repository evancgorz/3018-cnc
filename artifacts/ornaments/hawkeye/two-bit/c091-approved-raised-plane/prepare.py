"""Offline CAM derived from approved two-tone concept; never contacts Pine."""
from pathlib import Path
import sys, math, json, hashlib, importlib.util
from dataclasses import asdict, replace
from PIL import Image, ImageDraw
from shapely.geometry import Point, LineString, box
from shapely.ops import unary_union

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[4]
sys.path.insert(0,str(ROOT/'src'))
from ttc3018_control.ornament_cam import OrnamentSettings, raster_region, plan_adaptive_region_engraving, _polygons
from ttc3018_control.gcode import parse_gcode, validate_nonnegative_work_xy, validate_rapid_xy_clearance
from ttc3018_control.job_analysis import analyze_program

SOURCE=Path(r'C:\Users\Evan Gorczynski\.codex\generated_images\01a1973e-59f6-7913-babe-932570c6d115\exec-69faf806-9d1e-4686-8adf-dc7bd053efba.png')
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):
    spec=importlib.util.spec_from_file_location('c091_helpers',p); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
def sweep(paths,diam):
    return unary_union([LineString(p).buffer(diam/2/math.cos(math.pi/128),quad_segs=32) for p in paths])
def svgpath(geom):
    return ' '.join('M '+' L '.join(f'{x:.4f} {y:.4f}' for x,y in ring.coords)+' Z' for p in _polygons(geom) for ring in (p.exterior,*p.interiors))
def main():
    # Dark brown pixels are negative relief, light aircraft pixels remain raised.
    # Threshold is luminance only; it preserves real source contours rather than
    # inventing aircraft polygons. White 8 px padding ensures closed raster cells.
    rgb=Image.open(SOURCE).convert('RGB'); size=rgb.width
    mask=Image.new('L',(size+16,size+16),255)
    gray=rgb.convert('L'); binary=gray.point(lambda v: 0 if v<130 else 255)
    mask.paste(binary,(8,8)); MASK=HERE/'approved-depth-mask.png'; mask.save(MASK)
    cfg=OrnamentSettings(crop=(0,0,size+16,size+16),outer_diameter=100,art_diameter=99,
        stock_thickness=3.25,stock_margin=5,engraving_depth=1.625,v_angle=30,tip_diameter=.1,
        stepover=.27,max_stepdown=.6,safe_z=3,cut_feed=675,plunge_feed=120,spindle_rpm=1000,threshold=128,approach_z=.2)
    region,pixel=raster_region(MASK,cfg)
    # Keep at least 1 mm wood around the separately cut 4 mm hanger hole.
    keepout=Point(55,100).buffer(3,quad_segs=256)
    region=region.difference(keepout)
    helpers=load(ROOT/'artifacts/ornaments/hawkeye/two-bit/c069-flow/prepare-c069-flow.py')
    raw,_,broad_meta=plan_adaptive_region_engraving(region,cfg)
    broad=helpers.simplify_paths(raw,.08,region,cfg.effective_diameter)
    broad_sweep=sweep(broad,cfg.effective_diameter)
    residual=region.difference(broad_sweep).buffer(.07).intersection(region)
    finecfg=replace(cfg,engraving_depth=.04,max_stepdown=.04,stepover=.09)
    fine_raw,_,fine_meta=plan_adaptive_region_engraving(residual,finecfg)
    fine=helpers.simplify_paths(fine_raw,.04,region,finecfg.effective_diameter)
    fine_sweep=sweep(fine,finecfg.effective_diameter)
    if not region.covers(broad_sweep) or not region.covers(fine_sweep): raise ValueError('Cutter sweep leaves dark source artwork')
    lines=['; C091 approved raised-plane test; existing blank has irreversible prior cuts',
           'G21 G17 G90 G94 G54','G0 Z3.0000','M3 S1000','G4 P2.000']
    for depth,paths in [(-.6,broad),(-1.2,broad),(-1.625,broad),(-.04,fine)]:
        lines.append(f'; PASS Z{depth:.4f}')
        for p in paths: helpers.emit_path(lines,p,depth,3,.2)
    lines+=['G0 Z3.0000','M5','M2']; text='\n'.join(lines)+'\n'
    out=HERE/'01-approved-raised-plane-full-detail-test.nc'; out.write_text(text,encoding='ascii')
    program=parse_gcode(text,out); validate_nonnegative_work_xy(program); validate_rapid_xy_clearance(program,3)
    combined=broad_sweep.union(fine_sweep); omitted=region.difference(combined)
    svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="1100" viewBox="0 0 110 110"><rect width="110" height="110" fill="#fff"/><g transform="translate(0 110) scale(1 -1)"><circle cx="55" cy="55" r="50" fill="#ecd0a0"/><path d="{svgpath(broad_sweep)}" fill="#68391f" fill-rule="evenodd"/><path d="{svgpath(fine_sweep.difference(broad_sweep))}" fill="#b77838" fill-rule="evenodd"/><path d="{svgpath(omitted)}" fill="#de6a61" fill-rule="evenodd"/><circle cx="55" cy="100" r="2" fill="#fff"/></g></svg>'''
    (HERE/'exact-depth-preview.svg').write_text(svg,encoding='utf-8')
    report={'status':'offline candidate for primary verification','source':str(SOURCE),'source_sha256':sha(SOURCE),'mask_sha256':sha(MASK),'output_sha256':sha(out),'settings':asdict(cfg),'fine_settings':asdict(finecfg),'pixel_mm':pixel,'broad':broad_meta,'fine':fine_meta,'motion':analyze_program(program),'source_dark_area_mm2':region.area,'omitted_mm2':omitted.area,'omitted_fraction':omitted.area/region.area,'checks':{'parse':True,'safe_rapid':True,'full_cutter_containment':True},'limitations':['Approved generated image converted by threshold130; brown wood-grain/noise is thresholded too.','Original image fit to 99 mm artwork square with 8 px padding in shared 110 mm stock frame.','Deep V-bit passes produce scalloped floor; contrast not guaranteed by plywood thickness alone.','Existing test piece has irreversible prior cuts; concept appearance cannot be restored.','Fine residual=.04 mm; omitted cutter-inaccessible source area explicitly reported.']}
    (HERE/'report.json').write_text(json.dumps(report,indent=2)); print(json.dumps({k:report[k] for k in ('output_sha256','motion','omitted_fraction')},indent=2))
if __name__=='__main__': main()
