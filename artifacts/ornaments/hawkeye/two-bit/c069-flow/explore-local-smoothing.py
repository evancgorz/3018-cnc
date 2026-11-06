from pathlib import Path
import importlib.util, math
from shapely.geometry import LineString, Point
from shapely.prepared import prep
from shapely.ops import unary_union
ROOT=Path.cwd(); base=ROOT/'artifacts/ornaments/hawkeye/two-bit/c043-runtime'; out=ROOT/'artifacts/ornaments/hawkeye/two-bit/c069-flow'
script=base/'c057-fine-microsegments/optimize-fine-pass.py'; spec=importlib.util.spec_from_file_location('c057',script); mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod); gen=mod.load_generator()
text=(base/'c058-controller-efficient/01-detail-controller-efficient-450-120-review-only.nc').read_text(encoding='ascii'); original=gen.emitted_paths_by_depth(text)
broad=original[-1.625]; fine=original[-0.04]
with gen.Image.open(gen.SOURCE) as im:size=im.size
settings=gen.settings_for(size); region,pixel=gen.raster_region(gen.SOURCE,settings); work=region.difference(Point(*gen.HOLE_CENTER).buffer(gen.HOLE_KEEPOUT_RADIUS,quad_segs=256)); dia=settings.effective_diameter; radius=dia/2/math.cos(math.pi/128); allowed=prep(work)
def edge_ok(a,b): return allowed.covers(LineString((a,b)).buffer(radius,quad_segs=32))
def smooth_local(path, weights):
 p=list(path); changed=0
 for i in range(1,len(p)-1):
  prev,cur,nxt=p[i-1],p[i],p[i+1]
  midpoint=((prev[0]+nxt[0])/2,(prev[1]+nxt[1])/2)
  for w in weights:
   cand=(cur[0]+w*(midpoint[0]-cur[0]),cur[1]+w*(midpoint[1]-cur[1]))
   if edge_ok(prev,cand) and edge_ok(cand,nxt):
    if math.dist(cand,cur)>1e-8: p[i]=cand;changed+=1
    break
 return tuple(p),changed
def stats(paths):
 lengths=[];angles=[]
 for path in paths:
  vectors=[]
  for a,b in zip(path,path[1:]):
   dx=b[0]-a[0];dy=b[1]-a[1];n=math.hypot(dx,dy)
   if n>1e-9:lengths.append(n);vectors.append((dx,dy,n))
  for a,b in zip(vectors,vectors[1:]):
   c=(a[0]*b[0]+a[1]*b[1])/(a[2]*b[2]);angles.append(math.degrees(math.acos(max(-1,min(1,c)))))
 lengths.sort()
 return {'segments':len(lengths),'median':lengths[len(lengths)//2] if lengths else 0,'right_or_more':sum(a>=89.999 for a in angles),'junctions':len(angles),'p95':lengths[int(.95*(len(lengths)-1))] if lengths else 0}
def evaluate(weights,label):
 sm=[]; changes=[]
 for p in broad:
  x,n=smooth_local(p,weights);sm.append(x);changes.append(n)
 assert all(edge_ok(a,b) for p in sm for a,b in zip(p,p[1:]))
 bs=stats((*broad,*broad,*broad,*fine));cs=stats((*sm,*sm,*sm,*fine))
 old=unary_union((gen.swept(broad,dia),gen.swept(fine,gen.settings_for(size,depth=gen.FINE_DEPTH,stepover=gen.FINE_STEPOVER,stepdown=gen.FINE_DEPTH).effective_diameter)))
 new=unary_union((gen.swept(sm,dia),gen.swept(fine,gen.settings_for(size,depth=gen.FINE_DEPTH,stepover=gen.FINE_STEPOVER,stepdown=gen.FINE_DEPTH).effective_diameter)))
 print(label, 'changed verts',sum(changes),'paths changed',sum(n>0 for n in changes),'first changed',changes[0], 'first boundary 90+',stats([sm[0]])['right_or_more'],'global',cs,'delta-vs-C058-omission',work.difference(new).area-work.difference(old).area,'symmetric-diff',new.symmetric_difference(old).area,flush=True)
for weights,label in [([.5],'half'),([.5,.25,.125,.0625],'adaptive')]: evaluate(weights,label)
