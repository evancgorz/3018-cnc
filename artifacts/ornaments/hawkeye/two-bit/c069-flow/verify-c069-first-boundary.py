from pathlib import Path
import hashlib, importlib.util, json
root=Path.cwd();folder=root/'artifacts/ornaments/hawkeye/two-bit/c069-flow';base=root/'artifacts/ornaments/hawkeye/two-bit/c043-runtime'
src=base/'c057-fine-microsegments/optimize-fine-pass.py';spec=importlib.util.spec_from_file_location('c057',src);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);gen=m.load_generator()
prior=base/'c058-controller-efficient/01-detail-controller-efficient-450-120-review-only.nc';candidate=folder/'01-detail-c069-first-boundary-675-120-review-only.nc'
p=gen.emitted_paths_by_depth(prior.read_text(encoding='ascii'));c=gen.emitted_paths_by_depth(candidate.read_text(encoding='ascii'))
checks={};changed={}
for depth in sorted(p):
 if depth not in c:raise SystemExit(f'missing depth {depth}')
 checks[str(depth)]={'pathCountSame':len(p[depth])==len(c[depth]),'onlyPath0Changed':len(p[depth])==len(c[depth]) and all(p[depth][i]==c[depth][i] for i in range(1,len(p[depth]))),'firstEndpointsPreserved':p[depth][0][0]==c[depth][0][0] and p[depth][0][-1]==c[depth][0][-1]}
 changed[str(depth)]=[i for i,(a,b) in enumerate(zip(p[depth],c[depth])) if a!=b]
 if not all(checks[str(depth)].values()):raise SystemExit(f'comparison failed at {depth}: {checks[str(depth)]}')
report={'result':'passed','priorC058Sha256':hashlib.sha256(prior.read_bytes()).hexdigest(),'candidateSha256':hashlib.sha256(candidate.read_bytes()).hexdigest(),'depths':checks,'changedPathIndexesByDepth':changed,'finePathUnchanged':c[-0.04]==p[-0.04],'allBroadLevelsChangeSameFirstPath':all(changed[str(d)]==[0] for d in (-0.6,-1.2,-1.625))}
if not report['finePathUnchanged'] or not report['allBroadLevelsChangeSameFirstPath']:raise SystemExit('operation order comparison failed')
(folder/'c069-first-boundary-comparison.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8',newline='\n');print(json.dumps(report,indent=2))
