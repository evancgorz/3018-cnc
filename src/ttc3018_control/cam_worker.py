"""Compatibility entry point for the offline CAM workflow."""

from .cam.worker import cancel, main, retry, status, submit, _job_path


if __name__ == "__main__":
    raise SystemExit(main())
