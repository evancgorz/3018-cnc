"""Compatibility entry point for the offline CAM workflow."""

from .cam.build import build, main, resolve_design_setup


if __name__ == "__main__":
    raise SystemExit(main())
