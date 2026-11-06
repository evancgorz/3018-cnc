from dataclasses import replace
import hashlib
import json

from PIL import Image, ImageDraw
import pytest
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from ttc3018_control.gcode import parse_gcode, validate_nonnegative_work_xy, validate_rapid_xy_clearance
from ttc3018_control.ornament_cam import (OrnamentSettings, generate_engraving, main,
                                          plan_adaptive_region_engraving, raster_region)


def settings(**changes):
    base = OrnamentSettings(crop=(0, 0, 100, 100), outer_diameter=100, art_diameter=90,
        stock_thickness=3, stock_margin=5, engraving_depth=0.3, v_angle=60,
        tip_diameter=0.05, stepover=0.2, max_stepdown=0.15, safe_z=3,
        cut_feed=300, plunge_feed=80, spindle_rpm=None, threshold=128)
    return replace(base, **changes)


def image_file(tmp_path):
    image = Image.new('RGB', (100, 100), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 39, 39), fill='black')
    draw.rectangle((25, 25, 34, 34), fill='white')
    draw.rectangle((60, 60, 75, 75), fill='black')
    path = tmp_path / 'source.png'
    image.save(path)
    return path


def test_generated_footprint_respects_white_counters_and_clearance(tmp_path):
    source = image_file(tmp_path)
    cfg = settings()
    gcode, report, svg = generate_engraving(source, cfg)
    program = parse_gcode(gcode)
    validate_nonnegative_work_xy(program)
    validate_rapid_xy_clearance(program, cfg.safe_z)
    region, _ = raster_region(source, cfg)
    cut_lines = [LineString([(s.start.x, s.start.y), (s.end.x, s.end.y)])
        for s in program.segments if not s.rapid and s.start.z < 0 and s.end.z < 0
        and (s.start.x, s.start.y) != (s.end.x, s.end.y)]
    swept = unary_union([line.buffer(cfg.effective_diameter/2) for line in cut_lines])
    assert region.buffer(1e-8).covers(swept)
    assert swept.area > region.area * 0.85
    assert report['passes'] == 2
    assert report['status'] == 'offline_uncommissioned_operator_review_required'
    assert report['inaccessible_black_area_mm2'] >= 0
    assert report['output_gcode_sha256'] == hashlib.sha256(gcode.encode('ascii')).hexdigest()
    assert len(report['settings_sha256']) == 64
    assert report['emitted_motion_metrics']['cut_distance_mm'] == pytest.approx(
        report['motion_metrics']['cutting_distance_mm'])
    assert report['emitted_motion_metrics']['rapid_xy_distance_mm'] == pytest.approx(
        report['motion_metrics']['rapid_xy_distance_mm'])
    assert 'M3' not in gcode and gcode.endswith('M5\nM2\n')
    assert '<polyline' in svg and 'scale(1 -1)' in svg
    assert min(s.end.z for s in program.segments) == -0.3


def test_raster_scale_y_flip_and_source_hash(tmp_path):
    source = image_file(tmp_path)
    cfg = settings()
    region, pixel = raster_region(source, cfg)
    # Top-left first square occupies x28..46 and y64..82; counter stays white.
    assert pixel == 0.9
    assert region.covers(Point(29, 81))
    assert not region.covers(Point(36, 74))
    _, report, _ = generate_engraving(source, cfg)
    assert len(report['source_sha256']) == 64


@pytest.mark.parametrize('changes', [
    {'engraving_depth': 3}, {'engraving_depth': float('nan')},
    {'cut_feed': 0}, {'safe_z': float('inf')}, {'v_angle': 180},
    {'tip_diameter': -0.1}, {'stepover': 2}, {'crop': (0, 0, 100, 90)},
    {'crop': (-1, 0, 99, 100)}, {'stock_margin': 0}, {'spindle_rpm': True},
    {'art_diameter': 100}, {'max_stepdown': 0.0001}, {'threshold': True},
    {'safe_z': 0.00001}, {'engraving_depth': 0.00001}, {'stock_margin': 1e308},
    {'max_stepdown': 1e-320}, {'stepover': 1e-320}, {'v_angle': 179.999999},
    {'engraving_depth': 0.00105}, {'safe_z': 0.01005}, {'max_stepdown': 0.00105},
])
def test_invalid_settings_rejected(changes):
    with pytest.raises(ValueError):
        settings(**changes).validate()


def test_artwork_rejects_crop_edge_outside_circle_and_too_narrow(tmp_path):
    path = tmp_path/'source.png'
    image = Image.new('L', (100,100), 255)
    ImageDraw.Draw(image).rectangle((0,20,20,30), fill=0)
    image.save(path)
    with pytest.raises(ValueError, match='crop edge'):
        generate_engraving(path, settings())
    image = Image.new('L', (100,100), 255)
    ImageDraw.Draw(image).rectangle((1,1,3,3), fill=0)
    image.save(path)
    with pytest.raises(ValueError, match='outside physical'):
        generate_engraving(path, settings())
    image = Image.new('L', (100,100), 255)
    ImageDraw.Draw(image).line((40,40,40,60), fill=0)
    image.save(path)
    with pytest.raises(ValueError, match='narrower'):
        generate_engraving(path, settings(engraving_depth=1, stepover=0.2))


def test_alpha_composited_on_white_and_explicit_spindle(tmp_path):
    image = Image.new('RGBA', (100,100), (0,0,0,0))
    ImageDraw.Draw(image).rectangle((30,30,50,50), fill=(0,0,0,255))
    path = tmp_path/'alpha.png'
    image.save(path)
    gcode, _, _ = generate_engraving(path, settings(spindle_rpm=9000))
    assert 'M3 S9000' in gcode


def test_cli_outputs_and_refuses_overwrite(tmp_path, capsys):
    source = image_file(tmp_path)
    cfg = settings()
    config = tmp_path/'settings.json'
    from dataclasses import asdict
    config.write_text(json.dumps(asdict(cfg)))
    output = tmp_path/'result'
    assert main([str(source), str(config), str(output)]) == 0
    assert {p.name for p in output.iterdir()} == {'engraving.nc', 'report.json', 'engraving-preview.svg'}
    saved = (output/'engraving.nc').read_bytes()
    with pytest.raises(SystemExit) as exc:
        main([str(source), str(config), str(output)])
    assert exc.value.code == 2
    assert (output/'engraving.nc').read_bytes() == saved


def test_omitted_narrow_components_are_reported(tmp_path):
    image = Image.new('L', (100, 100), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((20,20,40,40), fill=0)
    draw.line((60,60,60,70), fill=0)
    source = tmp_path/'detail.png'
    image.save(source)
    _, report, _ = generate_engraving(source, settings(engraving_depth=1, max_stepdown=0.5))
    assert report['fully_omitted_black_components'] == 1
    assert report['inaccessible_black_fraction'] > 0


def test_uneven_passes_do_not_exceed_stepdown(tmp_path):
    source = image_file(tmp_path)
    cfg = settings(engraving_depth=0.3001, max_stepdown=0.1001)
    gcode, _, _ = generate_engraving(source, cfg)
    program = parse_gcode(gcode)
    levels = sorted(set(-s.end.z for s in program.segments if s.end.z < 0))
    assert levels == [0.1001, 0.2002, 0.3001]
    previous = 0
    for level in levels:
        assert level-previous <= cfg.max_stepdown + 1e-12
        previous = level


def _program_footprint(gcode, diameter):
    program = parse_gcode(gcode)
    cuts = [LineString([(segment.start.x,segment.start.y), (segment.end.x,segment.end.y)])
            for segment in program.segments if not segment.rapid and segment.start.z < 0 and segment.end.z < 0
            and (segment.start.x,segment.start.y) != (segment.end.x,segment.end.y)]
    return unary_union([line.buffer(diameter/2) for line in cuts])


def test_optimization_preserves_counters_and_coverage_and_reduces_runtime(tmp_path):
    source = image_file(tmp_path)
    cfg = settings()
    baseline, before, _ = generate_engraving(source, replace(cfg, optimize_paths=False))
    optimized, after, _ = generate_engraving(source, cfg)
    region, _ = raster_region(source, cfg)
    base_sweep = _program_footprint(baseline, cfg.effective_diameter)
    opt_sweep = _program_footprint(optimized, cfg.effective_diameter)
    assert base_sweep.difference(opt_sweep).area < 1e-7
    assert region.buffer(1e-8).covers(opt_sweep)
    assert after['estimated_minutes'] < before['estimated_minutes'] * 0.5
    assert after['motion_metrics']['retract_count'] < before['motion_metrics']['retract_count']
    assert after['motion_metrics']['stay_down_link_count'] > 0
    assert after['motion_metrics']['reversed_primitive_paths'] > 0
    assert after['motion_metrics']['scheduled_order_changed']
    assert after['motion_metrics']['cut_segments_at_most_0_1mm'] >= 0
    assert after['motion_metrics']['cut_junctions_at_least_90_degrees'] > 0
    assert after['motion_metrics']['cutting_distance_mm'] >= before['motion_metrics']['cutting_distance_mm']
    assert after['motion_metrics']['estimated_minutes'] == pytest.approx(after['estimated_minutes'])
    assert after['optimization']['saved_minutes'] == pytest.approx(before['estimated_minutes'] - after['estimated_minutes'])
    assert after['fully_omitted_black_components'] == before['fully_omitted_black_components']
    assert after['inaccessible_black_area_mm2'] == before['inaccessible_black_area_mm2']
    assert generate_engraving(source, cfg)[0] == optimized


def test_staydown_link_must_be_cheaper_than_retract_cycle():
    from shapely.geometry import box
    from ttc3018_control.ornament_cam import optimize_engraving_paths
    paths = (((10.,10.), (11.,10.)), ((21.,10.), (22.,10.)))
    # A very small configured safe Z makes even an entirely in-black link slower.
    cfg = settings(safe_z=0.01)
    result = optimize_engraving_paths(paths, box(0,0,100,100), cfg)
    assert len(result) == 2


def test_adaptive_region_planner_keeps_components_local_and_safe(tmp_path):
    source = image_file(tmp_path)
    cfg = settings()
    region, _ = raster_region(source, cfg)
    paths, _, metrics = plan_adaptive_region_engraving(region, cfg)
    assert metrics['components'] == 2
    assert metrics['concentric_components'] >= 1
    assert paths
    sweep = unary_union([LineString(path).buffer(cfg.effective_diameter / 2) for path in paths])
    assert region.buffer(1e-8).covers(sweep)


def test_optimizer_rejects_non_boolean_setting():
    with pytest.raises(ValueError, match='boolean'):
        settings(optimize_paths=1).validate()


@pytest.mark.parametrize('value', [0, -1, 0.00001, 3.1, float('nan'), float('inf'), True, 0.01005])
def test_approach_clearance_rejects_invalid_values(value):
    with pytest.raises(ValueError, match='approach_z'):
        settings(approach_z=value).validate()


def test_vertical_approach_reduces_air_feed_without_lowering_xy_rapids(tmp_path):
    source = image_file(tmp_path)
    cfg = settings(optimize_paths=False)
    _, baseline, _ = generate_engraving(source, cfg)
    gcode, reduced, _ = generate_engraving(source, replace(cfg, approach_z=0.2))
    program = parse_gcode(gcode)
    validate_rapid_xy_clearance(program, cfg.safe_z)
    assert reduced['estimated_minutes'] < baseline['estimated_minutes']
    assert reduced['motion_metrics']['cutting_minutes'] == baseline['motion_metrics']['cutting_minutes']
    assert reduced['motion_metrics']['retract_count'] == baseline['motion_metrics']['retract_count']
    assert reduced['motion_metrics']['plunge_minutes'] < baseline['motion_metrics']['plunge_minutes']
    assert reduced['motion_metrics']['estimated_minutes'] == pytest.approx(reduced['estimated_minutes'])
    assert any(segment.rapid and segment.end.z == 0.2 for segment in program.segments)
    for segment in program.segments:
        if not segment.rapid and segment.start.z > 0 and segment.end.z < 0:
            assert segment.start.z == 0.2
    assert any('stock flatness' in warning for warning in reduced['warnings'])


def test_null_approach_retains_default_clearance(tmp_path):
    source = image_file(tmp_path)
    default, _, _ = generate_engraving(source, settings())
    explicit, _, _ = generate_engraving(source, settings(approach_z=3))
    assert default == explicit
