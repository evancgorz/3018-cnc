"""Check C095 analytic render inputs against emitted G-code; add profile figure."""
import importlib.util, json, math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('c095_prepare',HERE/'prepare.py')
prep=importlib.util.module_from_spec(spec);spec.loader.exec_module(prep)

def emitted_paths(text):
    """Recover every emitted continuous cut stroke, including repeated-point dots."""
    groups={}; path=None;depth=None
    def close():
        if path is not None and depth is not None:
            groups.setdefault(depth,[]).append(tuple(path))
    for line in text.splitlines():
        line=line.split(';',1)[0].strip()
        words=line.split()
        if not words:continue
        values={w[0]:float(w[1:]) for w in words[1:]}
        if words[0]=='G0' and 'Z' in values and values['Z']==3:
            close();path=None;depth=None
        elif words[0]=='G0' and 'X' in values and 'Y' in values:
            path=[(values['X'],values['Y'])]
        elif words[0]=='G1' and 'Z' in values:
            depth=values['Z']
        elif words[0]=='G1' and 'X' in values and 'Y' in values:
            assert path is not None
            path.append((values['X'],values['Y']))
    return groups

def main():
    output=HERE/'01-c095-review-only.nc'
    groups=emitted_paths(output.read_text())
    assert set(groups)=={-.6,-1.2,-1.625,-.04}
    assert all(len(p)>=2 for paths in groups.values() for p in paths)
    # All planned helpers emit exactly4decimal coordinates. Reconstruct renderer
    # from the emitted file, so image geometry is bound to actual output bytes.
    removal=np.zeros((round(110/prep.GRID),round(110/prep.GRID)),dtype=np.float32)
    for z in (-.6,-1.2,-1.625,-.04):
        prep.remove_surface(removal,groups[z],-z)
    prior=np.load(HERE/'modeled-removal-depth-mm.npy')
    maximum_difference=float(np.max(np.abs(prior-removal)))
    # Different roughing and finishing paths can leave rough-pass marks outside
    # the final-pass envelope. Report them and render the full exact program.
    prep.render(removal,'all-passes-depth-preview.png',shaded=False)
    prep.render(removal,'all-passes-surface-preview.png',shaded=True)
    # Unit check one segment against an independent point-to-line formula.
    test=np.zeros((120,120),dtype=np.float32)
    prep.remove_surface(test,[((.5,1.5),(2.5,1.5))],.6)
    coords=(np.arange(120)+.5)*prep.GRID
    dist=np.sqrt((coords[:,None]-1.5)**2+np.maximum(np.maximum(.5-coords[None,:],coords[None,:]-2.5),0)**2)
    expected=np.maximum(0,.6-np.maximum(0,dist-.05)/math.tan(math.radians(15)))
    formula_error=float(np.max(np.abs(test-expected)))
    assert formula_error<2e-6,formula_error
    report={'gcode_sha256':prep.sha(output),'render_vs_emitted_max_depth_difference_mm':maximum_difference,
            'independent_segment_formula_max_error_mm':formula_error,
            'rough_paths_per_upper_depth':len(groups[-.6]),'finish_paths':len(groups[-1.625]),'fine_paths':len(groups[-.04]),
            'depth_grid_mm':prep.GRID,'checks':'all emitted depth levels included; independent segment formula checked'}
    (HERE/'verification.json').write_text(json.dumps(report,indent=2))
    # Dependency-free explanatory profile. It is based on the same V-bit formula,
    # but is deliberately labeled ideal parallel lanes rather than a substitute
    # for the full surface simulation above.
    canvas=Image.new('RGB',(1600,900),'white'); draw=ImageDraw.Draw(canvas)
    font=ImageFont.load_default()
    draw.text((40,25),'30 degree V-bit / 0.1 mm flat tip / 1.625 mm commanded depth',fill='#222',font=font)
    draw.text((40,45),'Ideal parallel-lane floor profile (vertical scale exaggerated)',fill='#555',font=font)
    tangent=math.tan(math.radians(15))
    for index,spacing in enumerate((.27,.12)):
        top=120+index*380; left=100; right=1520; bottom=top+270
        draw.rectangle((left,top,right,bottom),outline='#bbb')
        for fraction in np.linspace(0,1,5):
            y=top+(bottom-top)*fraction
            draw.line((left,y,right,y),fill='#eee')
        samples=np.linspace(-spacing*2,spacing*2,2400)
        distance=np.min(np.abs(samples[:,None]-np.arange(-3,4)[None,:]*spacing),axis=1)
        removal=1.625-np.maximum(0,distance-.05)/tangent
        pts=[]
        for x,z in zip(samples,removal):
            px=left+(x-samples.min())/(samples.max()-samples.min())*(right-left)
            py=top+(1-z/1.625)*(bottom-top)
            pts.append((px,py))
        draw.line(pts,fill='#68391f',width=3)
        cusp=max(0,(spacing-.1)/(2*tangent))
        draw.text((left,top-24),f'{spacing:.2f} mm spacing: ideal cusp {cusp:.3f} mm',fill='#222',font=font)
        draw.text((left,bottom+8),'across neighboring paths',fill='#555',font=font)
    canvas.save(HERE/'floor-profile-comparison.png')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
