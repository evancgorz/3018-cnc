from pathlib import Path
import importlib.util, math, json
from shapely.geometry import LineString, Point
from shapely.prepared import prep
ROOT=Path.cwd(); base=ROOT/'artifacts/ornaments/hawkeye/two-bit/c043-runtime'
src=base/'c057-fine-microsegments/optimize-fine-pass.py';sp=importlib.util.spec_from_file_location('c057',src);m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);gen=m.load_generator()
c058=(base/'c058-controller-efficient/01-detail-controller-efficient-450-120-review-only.nc').read_text(encoding='ascii'); emitted=gen.emitted_paths_by_depth(c058);broad=emitted[-1.625];fine=emitted[-.04]
with gen.Image.open(gen.SOURCE) as im:size=im.size
settings=gen.settings_for(size);region,pixel=gen.raster_region(gen.SOURCE,settings);work=region.difference(Point(*gen.HOLE_CENTER).buffer(gen.HOLE_KEEPOUT_RADIUS,quad_segs=256))
radius=settings.effective_diameter/2/math.cos(math.pi/128);allowed=prep(work)
def edge_ok(a,b):return allowed.covers(LineString((a,b)).buffer(radius,quad_segs=32))
def smooth_local(path):
 p=[(round(x,4),round(y,4)) for x,y in path]; changed=0
 for i in range(1,len(p)-1):
  a,b,c=p[i-1],p[i],p[i+1];mid=((a[0]+c[0])/2,(a[1]+c[1])/2)
  for w in (.5,.25,.125,.0625):
   cand=(round(b[0]+w*(mid[0]-b[0]),4),round(b[1]+w*(mid[1]-b[1]),4))
   if cand!=b and edge_ok(a,cand) and edge_ok(cand,c):p[i]=cand;changed+=1;break
 return tuple(p),changed
def dist(p,a,b):
 dx=b[0]-a[0];dy=b[1]-a[1];den=dx*dx+dy*dy
 if den==0:return math.dist(p,a)
 t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/den));return math.dist(p,(a[0]+t*dx,a[1]+t*dy))
def simp_open(p,tol):
 if len(p)<=2:return [p[0],p[-1]]
 d=[dist(q,p[0],p[-1]) for q in p[1:-1]];mx=max(d);idx=d.index(mx)+1
 if mx<=tol and edge_ok(p[0],p[-1]):return [p[0],p[-1]]
 if mx<1e-12:idx=len(p)//2
 a=simp_open(p[:idx+1],tol);b=simp_open(p[idx:],tol);return a[:-1]+b
def simplify_path(p,tol):
 if len(p)<=2:return tuple(p)
 if p[0]==p[-1]:
  idx=len(p)//2;a=simp_open(p[:idx+1],tol);b=simp_open(p[idx:],tol);q=a[:-1]+b
 else:q=simp_open(p,tol)
 out=[]
 for x,y in q:
  qpt=(round(x,4),round(y,4))
  if not out or qpt!=out[-1]:out.append(qpt)
 return tuple(out)
def stats(paths):
 lens=[];angs=[]
 for path in paths:
  v=[]
  for a,b in zip(path,path[1:]):
   dx=b[0]-a[0];dy=b[1]-a[1];n=math.hypot(dx,dy)
   if n>1e-9:lens.append(n);v.append((dx,dy,n))
  for a,b in zip(v,v[1:]):
   c=(a[0]*b[0]+a[1]*b[1])/(a[2]*b[2]);angs.append(math.degrees(math.acos(max(-1,min(1,c)))))
 lens.sort()
 return {'segments':len(lens),'medianMm':lens[len(lens)//2] if lens else 0,'junctions':len(angs),'junctionsAtLeast90Deg':sum(a>=89.999 for a in angs),'p95SegmentMm':lens[int(.95*(len(lens)-1))] if lens else 0}
smoothed=[];changed=0
for p in broad:
 q,n=smooth_local(p);smoothed.append(q);changed+=n
print('local smoothing changed',changed,'vertices across paths',len(broad),'first',stats([broad[0]]),stats([smoothed[0]]),flush=True)
reduced=[simplify_path(p,.02) for p in smoothed]
assert all(allowed.covers(LineString(p).buffer(radius,quad_segs=32)) for p in reduced)
old=stats((*broad,*broad,*broad,*fine));mid=stats((*smoothed,*smoothed,*smoothed,*fine));new=stats((*reduced,*reduced,*reduced,*fine))
print(json.dumps({'c058':old,'locallySmoothed':mid,'smoothedAndRdp0p02':new,'firstBoundaryAfterRdp':stats([reduced[0]]),'perPassSegments':[sum(len(p)-1 for p in broad),sum(len(p)-1 for p in reduced)],'firstBoundarySegments':[len(broad[0])-1,len(reduced[0])-1]},indent=2))
