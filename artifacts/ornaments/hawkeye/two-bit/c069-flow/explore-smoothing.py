from pathlib import Path
import importlib.util, math
from shapely.geometry import LineString, Point
from shapely.prepared import prep
from shapely.ops import unary_union
ROOT=Path.cwd()
base=ROOT/'artifacts/ornaments/hawkeye/two-bit/c043-runtime'
c058=base/'c058-controller-efficient/01-detail-controller-efficient-450-120-review-only.nc'
src=base/'c057-fine-microsegments/optimize-fine-pass.py'
spec=importlib.util.spec_from_file_location('c057',src); mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod); gen=mod.load_generator()
paths=gen.emitted_paths_by_depth(c058.read_text(encoding='ascii'))
broad=paths[-1.625]; fine=paths[-0.04]
with gen.Image.open(gen.SOURCE) as im: size=im.size
settings=gen.settings_for(size); region,pixel=gen.raster_region(gen.SOURCE,settings)
work=region.difference(Point(*gen.HOLE_CENTER).buffer(gen.HOLE_KEEPOUT_RADIUS,quad_segs=256))
dia=settings.effective_diameter; radius=dia/2/math.cos(math.pi/128); allowed=prep(work)
def stats(paths):
 turns=0; segs=0; lengths=[]
 for path in paths:
  vec=[]
  for a,b in zip(path,path[1:]):
   dx=b[0]-a[0];dy=b[1]-a[1];n=math.hypot(dx,dy)
   if n>1e-9: segs+=1;lengths.append(n);vec.append((dx,dy,n))
  for a,b in zip(vec,vec[1:]):
   c=(a[0]*b[0]+a[1]*b[1])/(a[2]*b[2]); turns+=max(-1,min(1,c))
 angles=[]
 for path in paths:
  vec=[]
  for a,b in zip(path,path[1:]):
   dx=b[0]-a[0];dy=b[1]-a[1];n=math.hypot(dx,dy)
   if n>1e-9: vec.append((dx,dy,n))
  for a,b in zip(vec,vec[1:]):
   c=(a[0]*b[0]+a[1]*b[1])/(a[2]*b[2]);angles.append(math.degrees(math.acos(max(-1,min(1,c)))))
 return {'segments':segs,'median':sorted(lengths)[len(lengths)//2], 'right_or_more':sum(a>=89.999 for a in angles),'junctions':len(angles)}
def smooth(path,w):
 if len(path)<=2:return tuple(path)
 p=list(path);out=[p[0]]
 for i in range(1,len(p)-1):
  x,y=p[i]; ax,ay=p[i-1]; bx,by=p[i+1]
  out.append((x+w*((ax+bx)/2-x),y+w*((ay+by)/2-y)))
 out.append(p[-1]);return tuple(out)
def safe(path): return allowed.covers(LineString(path).buffer(radius,quad_segs=32))
print('source paths',len(broad),len(fine),'first boundary',len(broad[0]),'baseline stats',stats((*broad,*broad,*broad,*fine)))
for w in (.1,.2,.3,.4,.5):
 sm=[smooth(p,w) for p in broad]
 valid=[safe(p) for p in sm]
 first=sm[0]
 print('weight',w,'safe',sum(valid),'/',len(valid),'first safe',valid[0], 'first turns',stats([first])['right_or_more'],'first segment count',len(first)-1)
