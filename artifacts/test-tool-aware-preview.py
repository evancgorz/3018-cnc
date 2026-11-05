"""Verify the candidate preview; this does not establish physical machine safety."""

import hashlib
import importlib.util
import json
import math
import sys
import unittest
from pathlib import Path

import numpy as np
from scipy.ndimage import distance_transform_edt
import shapely
from shapely.geometry import LineString, Point
from shapely.ops import unary_union


HERE = Path(__file__).resolve().parent
original_args = sys.argv[:]
sys.argv = [str(HERE / 'build-tool-aware-preview.py'), '.', '.']
spec = importlib.util.spec_from_file_location('study', HERE / 'build-tool-aware-preview.py')
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)
sys.argv = original_args


class PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads((HERE / 'tool-aware-preview-only.json').read_text(encoding='utf-8'))
        cls.state = Path(sys.argv[1]).resolve()
        study.STATE = cls.state
        study.CHROME = Path(sys.argv[2])
        engraving, tab = study.rasterize()
        y, x = np.indices((study.SIZE, study.SIZE))
        part = ((x - 650) ** 2 + (y - 650) ** 2 <= 500 ** 2) | (tab[:, :, 3] > 127)
        cls.target = (engraving[:, :, 3] > 127) & (engraving[:, :, :3].max(axis=2) < 128) & part
        cls.clearance = distance_transform_edt(cls.target)

    def test_revision_and_tools(self):
        p = self.plan
        self.assertTrue(p['status'].startswith('PREVIEW ONLY'))
        self.assertEqual(p['study_script_sha256'], hashlib.sha256((HERE / 'build-tool-aware-preview.py').read_bytes()).hexdigest())
        self.assertEqual(p['artwork_rasterizer_sha256'], hashlib.sha256((HERE / 'tool-aware-raster.html').read_bytes()).hexdigest())
        for name, digest in p['source_sha256'].items():
            self.assertEqual(digest, hashlib.sha256((HERE / 'layers' / name).read_bytes()).hexdigest())
        self.assertEqual(p['stock_mm'], [152.4, 203.2, 3.25])
        self.assertAlmostEqual(p['v_width_at_depth_mm'], 0.1 + math.tan(math.radians(15)))
        self.assertEqual(p['through_depth_mm'], 3.35)
        flat_paths = p['flat_engraving_centerlines']
        self.assertAlmostEqual(p['flat_candidate_cutting_length_mm'], sum(math.dist(a, b) for a, b in flat_paths))
        self.assertEqual(p['flat_single_point_strokes'], sum(a == b for a, b in flat_paths))
        flat_routes = p['flat_connected_candidate_routes']
        self.assertEqual(p['flat_isolated_point_routes'], sum(
            len(route['stroke_indices']) == 1 and route['points'][0] == route['points'][-1]
            for route in flat_routes
        ))
        paths = p['v_engraving_centerlines_xyz_positive_depth']
        self.assertAlmostEqual(
            p['v_candidate_cutting_length_mm'],
            sum(math.dist(a[:2], b[:2]) for path in paths for a, b in zip(path, path[1:])),
        )
        self.assertEqual(p['v_single_point_strokes'], sum(len(path) == 1 for path in paths))
        self.assertEqual(p['v_isolated_point_routes'], sum(len(route['points']) == 1 for route in p['v_connected_candidate_routes']))

    def test_unverified_pass_study_caps_depth_and_work(self):
        study_plan = self.plan['unverified_pass_study']
        self.assertIn('UNVERIFIED', study_plan['status'])
        self.assertIsNone(study_plan['safe_z_mm'])
        profile = study_plan['flat_profile_and_hole_depths_mm']
        self.assertEqual(profile[-1], self.plan['through_depth_mm'])
        self.assertTrue(all(0 < b - a <= 0.75 + 1e-8 for a, b in zip([0] + profile[:-1], profile)))
        self.assertEqual(study_plan['flat_profile_tab_depth_cap_mm'], study.TAB_DEPTH)
        previous = 0
        expected_length = 0
        routes = self.plan['v_connected_candidate_routes']
        for item in study_plan['v_depth_passes']:
            cap = item['depth_cap_mm']
            self.assertTrue(0 < cap - previous <= 0.2 + 1e-8)
            active = [route['points'] for route in routes if max(point[2] for point in route['points']) > previous + 1e-8]
            self.assertEqual(item['route_count'], len(active))
            length = sum(math.dist(a[:2], b[:2]) for path in active for a, b in zip(path, path[1:]))
            self.assertAlmostEqual(item['cutting_length_mm'], length)
            expected_length += length
            previous = cap
        self.assertEqual(previous, self.plan['engraving_depth_mm'])
        self.assertAlmostEqual(study_plan['v_cutting_time_lower_bound_min_at_reference_feed'], expected_length / 50)

    def test_flat_paths_fit_target(self):
        for a, b in self.plan['flat_engraving_centerlines']:
            self.assertEqual(a[1], b[1])
            row, x1, x2 = round(a[1] * 10), round(a[0] * 10), round(b[0] * 10)
            samples = self.clearance[row, x1:x2 + 1]
            required = study.FLAT_R * 10 + math.sqrt(2) / 2
            self.assertTrue(np.all(samples > required))
            if len(samples) > 1:
                left, right = samples[:-1], samples[1:]
                crossing = np.clip((left - right + 1) / 2, 0, 1)
                self.assertTrue(np.all(np.maximum(left - crossing, right - (1 - crossing)) > required))

    def test_flat_route_links_and_coverage(self):
        paths = self.plan['flat_engraving_centerlines']
        routes = self.plan['flat_connected_candidate_routes']
        self.assertAlmostEqual(
            self.plan['flat_connected_candidate_length_mm'],
            sum(math.dist(a, b) for route in routes for a, b in zip(route['points'], route['points'][1:])),
        )
        visited = []
        for route in routes:
            indices, sides = route['stroke_indices'], route['stroke_entry_sides']
            self.assertEqual(len(indices), len(sides))
            expected = []
            for index, side in zip(indices, sides):
                self.assertIn(side, (0, 1))
                visited.append(index)
                expected.extend([paths[index][side], paths[index][1 - side]])
            self.assertEqual(route['points'], expected)
            for a, b in zip(expected[1::2], expected[2::2]):
                a, b = np.array(a) * 10, np.array(b) * 10
                radius = study.FLAT_R * 10
                lo = np.maximum(np.floor(np.minimum(a, b) - radius - 1).astype(int), 0)
                hi = np.minimum(np.ceil(np.maximum(a, b) + radius + 1).astype(int), study.SIZE - 1)
                rows, cols = np.where(~self.target[lo[1]:hi[1] + 1, lo[0]:hi[0] + 1])
                cells = shapely.box(cols + lo[0] - 0.5, rows + lo[1] - 0.5,
                                    cols + lo[0] + 0.5, rows + lo[1] + 0.5)
                if len(cells):
                    self.assertGreater(float(np.min(shapely.distance(cells, LineString((a, b))))), radius)
        self.assertEqual(sorted(visited), list(range(len(paths))))
        self.assertFalse(np.any(study.sampled_flat_sweep(routes) & ~self.target))

    def test_continuous_v_paths_fit_raster_target(self):
        levels = np.zeros(self.target.shape, dtype=np.int8)
        for path in self.plan['v_engraving_centerlines_xyz_positive_depth']:
            row = round(path[0][1] * 10)
            self.assertTrue(all(round(p[1] * 10) == row for p in path))
            xp = np.array([p[0] * 10 for p in path])
            depths = np.array([p[2] for p in path])
            xs = np.arange(round(xp[0]), round(xp[-1]) + 1)
            values = np.interp(xs, xp, depths)
            self.assertTrue(np.all((values >= 0.1) & (values <= 0.5)))
            self.assertTrue(np.allclose(values * 10, np.round(values * 10)))
            levels[row, xs] = np.round(values * 10).astype(np.int8)
            self.assertTrue(np.all(self.clearance[row, xs] > (study.V_TIP_R + values * study.V_SLOPE) * 10 + math.sqrt(2) / 2))
        rows, cols = np.nonzero((levels[:, :-1] > 0) & (levels[:, 1:] > 0))
        left, right = self.clearance[rows, cols], self.clearance[rows, cols + 1]
        r_left = (study.V_TIP_R + levels[rows, cols] * 0.1 * study.V_SLOPE) * 10
        r_right = (study.V_TIP_R + levels[rows, cols + 1] * 0.1 * study.V_SLOPE) * 10
        crossing = np.clip((left - right + 1) / 2, 0, 1)
        for t in (np.zeros_like(crossing), crossing, np.ones_like(crossing)):
            clearance_bound = np.maximum(left - t, right - (1 - t)) - math.sqrt(2) / 2
            radius = r_left + t * (r_right - r_left)
            self.assertTrue(np.all(clearance_bound > radius))
        coarse = levels.astype(float) / 10
        coarse[1::2] = 0
        paths = study.variable_depth_paths(coarse)
        comparison = self.plan['coarse_v_comparison_only']
        self.assertEqual(comparison['stroke_count'], len(paths))
        self.assertAlmostEqual(comparison['cutting_length_mm'], study.planar_path_length(paths))
        flat = np.where(study.sampled_flat_sweep(self.plan['flat_connected_candidate_routes']), study.ENGRAVE, 0)
        coarse_sweep = np.maximum(flat, study.sampled_v_depth(coarse))
        self.assertAlmostEqual(comparison['full_depth_area_mm2'], np.count_nonzero((coarse_sweep >= study.ENGRAVE - 0.01) & self.target) / 100)
        self.assertAlmostEqual(comparison['any_depth_area_mm2'], np.count_nonzero((coarse_sweep > 0) & self.target) / 100)

    def test_v_route_links_and_coverage(self):
        paths = self.plan['v_engraving_centerlines_xyz_positive_depth']
        routes = self.plan['v_connected_candidate_routes']
        self.assertAlmostEqual(
            self.plan['v_connected_candidate_length_mm'],
            sum(math.dist(a[:2], b[:2]) for route in routes for a, b in zip(route['points'], route['points'][1:])),
        )
        visited = []
        for route in routes:
            ids, sides = route['stroke_indices'], route['stroke_entry_sides']
            self.assertEqual(len(ids), len(sides))
            expected = []
            for index, side in zip(ids, sides):
                self.assertIn(side, (0, 1))
                visited.append(index)
                expected.extend(paths[index] if side == 0 else reversed(paths[index]))
            self.assertEqual(route['points'], expected)
            for left, side, right, right_side in zip(ids, sides, ids[1:], sides[1:]):
                a = paths[left][-1 if side == 0 else 0]
                b = paths[right][0 if right_side == 0 else -1]
                x1, y1 = round(a[0] * 10), round(a[1] * 10)
                x2, y2 = round(b[0] * 10), round(b[1] * 10)
                length = math.hypot(x2 - x1, y2 - y1)
                self.assertGreater(length, 0)
                d1, d2 = self.clearance[y1, x1], self.clearance[y2, x2]
                r1 = (study.V_TIP_R + a[2] * study.V_SLOPE) * 10
                r2 = (study.V_TIP_R + b[2] * study.V_SLOPE) * 10
                crossing = max(0, min(1, (d1 - d2 + length) / (2 * length)))
                for t in (0, crossing, 1):
                    bound = max(d1 - t * length, d2 - (1 - t) * length) - math.sqrt(2) / 2
                    self.assertGreater(bound, r1 + t * (r2 - r1))
        self.assertEqual(sorted(visited), list(range(len(paths))))
        self.assertFalse(np.any((study.sampled_v_links(routes, paths) > 0) & ~self.target))

    def test_profile_hole_and_holding_bridges(self):
        polygon, center, diameter = study.vector_part()
        self.assertAlmostEqual(polygon.bounds[2] - polygon.bounds[0], 100)
        self.assertTrue(polygon.covers(Point(center).buffer(diameter / 2)))
        self.assertEqual(diameter, 4)
        _, _, hole_error = study.hole_centers(center, diameter)
        self.assertLess(hole_error, 0.01)
        sections = self.plan['outer_profile_sections']
        deep = unary_union([LineString(s['points']) for s in sections if s['depth'] == study.THROUGH]).buffer(study.FLAT_R, quad_segs=128)
        self.assertLess(deep.intersection(polygon).area, 0.01)
        tabs = [LineString(s['points']) for s in sections if s['depth'] == study.TAB_DEPTH]
        self.assertEqual(len(tabs), 4)
        for tab in tabs:
            self.assertAlmostEqual(tab.difference(deep).length, 4, delta=0.02)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]])
