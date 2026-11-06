"""Portable, offline library of stock, cutter, and fixture records."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping


_PROVENANCE = {"measured", "user-reported", "assumed", "unknown"}
_SETUP_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_FIELDS = {
    "stock": {"shape", "material", "dimensions_mm"},
    "tool": {"id", "kind", "diameter_mm", "tip_diameter_mm", "included_angle_deg"},
    "fixture": {"id", "name", "machine_profile_id", "wcs_slot", "datum"},
    "datum": {"xy_description", "z_description", "machine_x_mm", "machine_y_mm"},
    "process": {"safe_z_mm", "cut_feed_mm_min", "plunge_feed_mm_min", "spindle_rpm"},
}


@dataclass(frozen=True)
class SetupRecord:
    """Validated immutable record. Evidence values retain their units and origin."""

    id: str
    name: str
    description: str
    stock: Mapping[str, Any]
    tool: Mapping[str, Any]
    fixture: Mapping[str, Any]
    process: Mapping[str, Any]
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "stock": _thaw(self.stock),
            "tool": _thaw(self.tool),
            "fixture": _thaw(self.fixture),
            "process": _thaw(self.process),
        }


@dataclass(frozen=True)
class SetupSummary:
    id: str
    name: str
    material: str
    tool: str
    fixture: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "material": self.material,
            "tool": self.tool,
            "fixture": self.fixture,
        }


def _evidence(value: object, field: str, *, numeric: bool = False,
              positive: bool = False, integer: bool = False, unit: str | None = None) -> dict:
    if not isinstance(value, dict) or set(value) != {"value", "unit", "provenance"}:
        raise ValueError(f"{field} must have value, unit, and provenance")
    unit, source = value["unit"], value["provenance"]
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError(f"{field}.unit must be text")
    if unit is not None and unit != value["unit"]:
        raise ValueError(f"{field}.unit must be {unit}")
    if not isinstance(source, dict) or set(source) - {"kind", "note"} or "kind" not in source:
        raise ValueError(f"{field}.provenance requires kind and optional note")
    if not isinstance(source["kind"], str) or source["kind"] not in _PROVENANCE:
        raise ValueError(f"{field}.provenance.kind must be one of {sorted(_PROVENANCE)}")
    if "note" in source and not isinstance(source["note"], str):
        raise ValueError(f"{field}.provenance.note must be text")
    result = value["value"]
    if source["kind"] == "unknown":
        if result is not None:
            raise ValueError(f"{field} with unknown provenance must have null value")
    elif numeric:
        if isinstance(result, bool) or not isinstance(result, (int, float)) or not math.isfinite(result):
            raise ValueError(f"{field}.value must be a finite number")
        if positive and result <= 0:
            raise ValueError(f"{field}.value must be positive")
        if integer and (type(result) is not int or result < 0):
            raise ValueError(f"{field}.value must be a nonnegative integer")
    elif not isinstance(result, str) or not result.strip():
        raise ValueError(f"{field}.value must be nonempty text")
    return dict(value)


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _number(evidence: Mapping[str, Any]) -> int | float | None:
    if evidence["provenance"]["kind"] == "unknown":
        return None
    return evidence["value"]


def _add_default(defaults: dict, settings: Mapping[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    if key in settings:
        current = settings[key]
        if (isinstance(value, (int, float)) and not isinstance(value, bool)
                and isinstance(current, (int, float)) and not isinstance(current, bool)):
            agrees = math.isclose(float(value), float(current), rel_tol=1e-9, abs_tol=1e-6)
        else:
            agrees = current == value
        if not agrees:
            raise ValueError(f"Design {key} conflicts with selected setup ({value!r})")
    else:
        defaults[key] = value


def load_setup(path: Path) -> SetupRecord:
    """Load and strictly validate one standalone setup JSON file."""
    return parse_setup(json.loads(Path(path).read_text(encoding="utf-8-sig")))


def parse_setup(value: object) -> SetupRecord:
    """Validate an embedded portable setup snapshot without temporary files."""
    required = {"schema_version", "id", "name", "description", "stock", "tool", "fixture", "process"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("Setup record fields must match the v1 schema exactly")
    setup_id = value["id"]
    if not isinstance(setup_id, str) or not _SETUP_ID.fullmatch(setup_id):
        raise ValueError("Setup id must be a lowercase slug of letters, numbers, and hyphens")
    if value["schema_version"] != 1 or type(value["schema_version"]) is not int:
        raise ValueError("Only hardware setup schema version 1 is supported")
    for key in ("name", "description"):
        if not isinstance(value[key], str) or not value[key].strip():
            raise ValueError(f"Setup {key} must be nonempty text")

    stock, tool, fixture, process = (value[key] for key in ("stock", "tool", "fixture", "process"))
    if not isinstance(stock, dict) or set(stock) != _FIELDS["stock"]:
        raise ValueError("Stock fields must match the v1 schema exactly")
    if not isinstance(stock["shape"], str) or stock["shape"] not in {"rectangular", "square", "round"}:
        raise ValueError("Stock shape must be rectangular, square, or round")
    _evidence(stock["material"], "stock.material")
    dimensions = stock["dimensions_mm"]
    expected_dimensions = {"thickness"} | ({"diameter"} if stock["shape"] == "round" else {"width", "height"})
    if not isinstance(dimensions, dict) or set(dimensions) != expected_dimensions:
        raise ValueError(f"Stock dimensions must contain {sorted(expected_dimensions)}")
    for key, item in dimensions.items():
        _evidence(item, f"stock.dimensions_mm.{key}", numeric=True, positive=True, unit="mm")

    if not isinstance(tool, dict) or set(tool) != _FIELDS["tool"]:
        raise ValueError("Tool fields must match the v1 schema exactly")
    if not isinstance(tool["id"], str) or not tool["id"].strip():
        raise ValueError("Tool id must be nonempty text")
    if not isinstance(tool["kind"], str) or tool["kind"] not in {"v-bit", "flat-endmill", "ball-endmill", "other"}:
        raise ValueError("Unsupported tool kind")
    _evidence(tool["diameter_mm"], "tool.diameter_mm", numeric=True, positive=True, unit="mm")
    _evidence(tool["tip_diameter_mm"], "tool.tip_diameter_mm", numeric=True, positive=True, unit="mm")
    _evidence(tool["included_angle_deg"], "tool.included_angle_deg", numeric=True, positive=True, unit="degree")
    angle = _number(tool["included_angle_deg"])
    if angle is not None and angle >= 180:
        raise ValueError("Tool included angle must be below 180 degrees")

    if not isinstance(fixture, dict) or set(fixture) != _FIELDS["fixture"]:
        raise ValueError("Fixture fields must match the v1 schema exactly")
    if not isinstance(fixture["id"], str) or not _SETUP_ID.fullmatch(fixture["id"]):
        raise ValueError("Fixture id must be a lowercase slug")
    if not isinstance(fixture["name"], str) or not fixture["name"].strip():
        raise ValueError("Fixture name must be nonempty text")
    if fixture["machine_profile_id"] is not None and (
        not isinstance(fixture["machine_profile_id"], str) or not fixture["machine_profile_id"].strip()
    ):
        raise ValueError("Machine profile id must be null or nonempty text")
    if type(fixture["wcs_slot"]) is not int or fixture["wcs_slot"] not in range(1, 7):
        raise ValueError("Fixture WCS slot must be 1 through 6")
    datum = fixture["datum"]
    if not isinstance(datum, dict) or set(datum) != _FIELDS["datum"]:
        raise ValueError("Fixture datum fields must match the v1 schema exactly")
    for key in ("xy_description", "z_description"):
        _evidence(datum[key], f"fixture.datum.{key}")
    for key in ("machine_x_mm", "machine_y_mm"):
        _evidence(datum[key], f"fixture.datum.{key}", numeric=True, unit="mm")

    if not isinstance(process, dict) or set(process) != _FIELDS["process"]:
        raise ValueError("Process fields must match the v1 schema exactly")
    for key in ("safe_z_mm", "cut_feed_mm_min", "plunge_feed_mm_min"):
        _evidence(process[key], f"process.{key}", numeric=True, positive=True,
                  unit="mm" if key == "safe_z_mm" else "mm/min")
    _evidence(process["spindle_rpm"], "process.spindle_rpm", numeric=True, integer=True, unit="rpm")

    return SetupRecord(setup_id, value["name"], value["description"],
                       _freeze(stock), _freeze(tool), _freeze(fixture), _freeze(process))


def list_setups(directory: Path) -> list[SetupSummary]:
    """List valid setup JSON files in stable ID order."""
    summaries = []
    for path in sorted(Path(directory).glob("*.json"), key=lambda item: item.name.casefold()):
        record = load_setup(path)
        if record.id != path.stem:
            raise ValueError(f"Setup id in {path.name} does not match its filename")
        material = _number(record.stock["material"])
        tool_diameter = _number(record.tool["diameter_mm"])
        material_text = material if isinstance(material, str) else "material unknown"
        tool_text = record.tool["kind"]
        if tool_diameter is not None:
            tool_text += f" {tool_diameter:g} mm"
        summaries.append(SetupSummary(record.id, record.name, material_text, tool_text,
                                       record.fixture["name"]))
    return summaries


class SetupRegistry:
    """Read-only lookup over a portable directory of one-record-per-file JSON."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def list(self) -> list[SetupSummary]:
        return list_setups(self.directory)

    def load(self, setup_id: str) -> SetupRecord:
        if not isinstance(setup_id, str) or not _SETUP_ID.fullmatch(setup_id):
            raise ValueError("Invalid setup id")
        record = load_setup(self.directory / f"{setup_id}.json")
        if record.id != setup_id:
            raise ValueError(f"Setup id in {setup_id}.json does not match its filename")
        return record

    def describe(self, setup_id: str) -> dict[str, Any]:
        return self.load(setup_id).to_dict()

    def cam_defaults(self, setup_id: str, kind: str, settings: Mapping[str, Any]) -> dict[str, Any]:
        return resolve_cam_defaults(self.load(setup_id), kind, settings)


def resolve_cam_defaults(record: SetupRecord, kind: str,
                         settings: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve CAM values against one already loaded setup snapshot."""
    supported = {"plaque", "raster", "step-pocket", "step-profile"}
    if not isinstance(kind, str):
        raise ValueError(f"CAM kind must be one of {sorted(supported)}")
    if kind not in supported:
        raise ValueError(f"CAM kind must be one of {sorted(supported)}")
    if not isinstance(settings, Mapping):
        raise ValueError("CAM settings must be a mapping")

    defaults: dict[str, Any] = {}
    stock_dims = record.stock["dimensions_mm"]
    if record.fixture["wcs_slot"] != 1:
        raise ValueError("This CAM exporter writes G54, so the selected fixture must use WCS slot 1")
    if kind in {"plaque", "step-pocket", "step-profile"} and record.stock["shape"] == "round":
        raise ValueError(f"{kind} template requires square or rectangular stock")
    _add_default(defaults, settings, "stock_thickness", _number(stock_dims["thickness"]))
    for source, target in (("safe_z_mm", "safe_z"), ("cut_feed_mm_min", "cut_feed"),
                           ("plunge_feed_mm_min", "plunge_feed"), ("spindle_rpm", "spindle_rpm")):
        _add_default(defaults, settings, target, _number(record.process[source]))

    tool_kind = record.tool["kind"]
    if kind in {"plaque", "raster"}:
        if tool_kind != "v-bit":
            raise ValueError(f"{kind} needs a V-bit but setup selects {tool_kind}")
        _add_default(defaults, settings, "v_angle", _number(record.tool["included_angle_deg"]))
        _add_default(defaults, settings, "tip_diameter", _number(record.tool["tip_diameter_mm"]))
    elif kind in {"step-pocket", "step-profile"}:
        if tool_kind != "flat-endmill":
            raise ValueError(f"{kind} needs a flat endmill but setup selects {tool_kind}")
        _add_default(defaults, settings, "tool_diameter", _number(record.tool["diameter_mm"]))
        for axis in ("width", "height"):
            if axis in stock_dims:
                _add_default(defaults, settings, f"stock_{axis}", _number(stock_dims[axis]))
    if kind == "plaque":
        for axis in ("width", "height"):
            if axis in stock_dims:
                _add_default(defaults, settings, axis, _number(stock_dims[axis]))
    if kind == "raster" and {"width", "height"} <= stock_dims.keys():
        width, height = (_number(stock_dims[key]) for key in ("width", "height"))
        if width is not None and height is not None:
            if not {"outer_diameter", "stock_margin"} <= settings.keys():
                raise ValueError("Raster design must specify outer_diameter and stock_margin to check saved stock")
            margin, outer = settings["stock_margin"], settings["outer_diameter"]
            if (not math.isclose(width, height, abs_tol=1e-6) or
                    not math.isclose(width, outer + 2 * margin, abs_tol=1e-6)):
                raise ValueError("Raster outer diameter plus stock margin must match square stock")
    return defaults



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="list offline named setup records")
    listing.add_argument("directory", type=Path)
    inspect = commands.add_parser("inspect", help="print one complete setup record")
    inspect.add_argument("directory", type=Path)
    inspect.add_argument("setup_id")
    args = parser.parse_args(argv)
    try:
        registry = SetupRegistry(args.directory)
        result: Any = ([item.to_dict() for item in registry.list()] if args.command == "list"
                       else registry.describe(args.setup_id))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"Setup registry: {exc}\n")
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
