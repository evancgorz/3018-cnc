"""Compatibility entry point for the offline CAM workflow."""

from .cam.sequence import create, inspect, main


if __name__ == "__main__":
    raise SystemExit(main())
