"""Compatibility entry point for the offline CAM workflow."""

from .cam.ladder import compare_raster_candidates, generate_raster_ladder, main


if __name__ == "__main__":
    raise SystemExit(main())
