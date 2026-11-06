"""Independently rebuild the preview height field from the review NC file."""
from pathlib import Path
import hashlib, importlib.util, json, sys
import numpy as np

HERE = Path(__file__).resolve().parent
NEW = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else HERE.parent / 'c095-lettering-rebuild'

def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

prep = module(HERE / 'prepare.py', 'c095_verify_prep')
reader = module(HERE / 'verify-and-illustrate.py', 'c095_verify_reader')
output = NEW / '01-c095-lettering-review-only.nc'
groups = reader.emitted_paths(output.read_text(encoding='ascii'))
assert set(groups) == {-.6, -1.2, -1.625, -.45, -.04}, sorted(groups)
result = np.zeros((round(110 / prep.GRID),) * 2, dtype=np.float32)
for z, paths in groups.items():
    prep.remove_surface(result, paths, -z)
saved = np.load(NEW / 'modeled-removal-depth-mm.npy')
difference = float(np.max(np.abs(saved - result)))
assert difference < 1e-5, difference
evidence = {'nc_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
            'depths': sorted(groups), 'grid_mm': prep.GRID,
            'max_preview_depth_difference_mm': difference,
            'paths_by_depth': {str(z): len(paths) for z, paths in groups.items()}}
(NEW / 'independent-height-verification.json').write_text(json.dumps(evidence, indent=2))
print(json.dumps(evidence, indent=2))
